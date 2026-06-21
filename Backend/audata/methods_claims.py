"""Methods ↔ Claims detection (AuData).

Checks whether a paper's main claims/conclusions are actually supported by its
own methods and results. Flags over-claiming, causal language from non-causal
designs, over-generalization beyond the sample, claims not backed by the
reported data, and mismatched statistical methods. LLM-driven; reviewer-assist.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from . import llm

# Canonical section → heading keywords.
_SEC_KEYS = {
    "abstract": ["abstract", "summary"],
    "introduction": ["introduction", "background"],
    "methods": ["methods", "materials and methods", "methodology", "method",
                "experimental", "study design", "data and methods", "patients and methods"],
    "results": ["results", "results and discussion", "findings"],
    "discussion": ["discussion", "limitations"],
    "conclusion": ["conclusion", "conclusions", "concluding remarks"],
}
_HEADING_RE = re.compile(
    r"^\s*(?:\d{0,2}[.)]?\s*)?(" +
    "|".join(re.escape(w) for ws in _SEC_KEYS.values() for w in ws) + r")\s*:?\s*$",
    re.I,
)
_CANON = {w: canon for canon, ws in _SEC_KEYS.items() for w in ws}

_SEV_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3}
_VERDICTS = ("supported", "overreach", "causal_overreach", "overgeneralization", "unsupported", "methods_mismatch")


def _sections(full_text: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not full_text:
        return out
    cur = None
    buf: List[str] = []

    def flush():
        if cur and buf:
            body = "\n".join(buf).strip()
            if body and len(body) > len(out.get(cur, "")):
                out[cur] = body

    for ln in full_text.split("\n"):
        m = _HEADING_RE.match(ln)
        if m:
            flush()
            cur = _CANON.get(m.group(1).strip().lower())
            buf = []
        elif cur:
            buf.append(ln)
    flush()
    return out


def _evidence_context(paper: Dict[str, Any]) -> str:
    secs = _sections(paper.get("full_text", "") or "")
    abstract = paper.get("abstract", "") or secs.get("abstract", "")
    parts = []
    if abstract:
        parts.append(f"ABSTRACT:\n{abstract[:2500]}")
    if secs.get("methods"):
        parts.append(f"METHODS:\n{secs['methods'][:4000]}")
    if secs.get("results"):
        parts.append(f"RESULTS:\n{secs['results'][:4000]}")
    if not parts:  # no sections detected — fall back to the body
        return (paper.get("full_text", "") or abstract)[:9000]
    return "\n\n".join(parts)


def _claims_context(paper: Dict[str, Any]) -> str:
    secs = _sections(paper.get("full_text", "") or "")
    abstract = paper.get("abstract", "") or secs.get("abstract", "")
    parts = []
    if abstract:
        parts.append(f"ABSTRACT:\n{abstract[:2500]}")
    for k in ("conclusion", "discussion"):
        if secs.get(k):
            parts.append(f"{k.upper()}:\n{secs[k][:3500]}")
    if not parts:
        return (paper.get("full_text", "") or abstract)[:6000]
    return "\n\n".join(parts)


def extract_claims(paper: Dict[str, Any], model: Any, limit: int = 10) -> List[str]:
    if model is None:
        return []
    ctx = _claims_context(paper)
    if not ctx.strip():
        return []
    prompt = f"""You are auditing a research paper. From the text below (its abstract and
conclusions/discussion), list the paper's MAIN claims and conclusions — the substantive
assertions the authors make about what they found and what it means. Capture claims about
effects, causation, performance, superiority, and generalisable implications.

Output ONLY JSON: {{"claims": ["concise claim 1", "concise claim 2", ...]}}
- {limit} items max, each a single clear sentence (verbatim phrasing where possible).
- Skip background facts and citations of others' work — only THIS paper's own claims.

TEXT:
{ctx}"""
    parsed = llm.extract_json(llm.invoke(model, prompt))
    # Flatten whatever shape the model returned ({"claims":[...]}, a bare list,
    # [{"claims":[...]}], [{"claim":"..."}], etc.) down to plain strings.
    flat: List[str] = []

    def _collect(x):
        if isinstance(x, str):
            flat.append(x)
        elif isinstance(x, dict):
            if isinstance(x.get("claims"), list):
                _collect(x["claims"])
            else:
                for k in ("claim", "text", "statement", "conclusion"):
                    if x.get(k):
                        flat.append(str(x[k]))
                        break
        elif isinstance(x, list):
            for y in x:
                _collect(y)

    _collect(parsed)
    out = []
    for c in flat:
        s = " ".join(str(c).split()).strip()
        if len(s) > 8:
            out.append(s[:400])
        if len(out) >= limit:
            break
    return out


def assess_claim(claim: str, evidence_ctx: str, model: Any) -> Dict[str, Any]:
    if model is None:
        return {"verdict": "skipped", "severity": "none", "issue_type": "", "confidence": 0.0,
                "reasoning": "No model configured.", "evidence": "", "suggestion": ""}
    prompt = f"""You are a research-integrity reviewer. Decide whether a paper's CLAIM is
supported by its own METHODS and RESULTS. Reviewer-assist, not an accusation.

CLAIM:
"{claim}"

PAPER METHODS & RESULTS (with abstract):
{evidence_ctx[:9000]}

Judge support, watching specifically for:
- over-claiming (overstating strength, certainty, or clinical importance),
- causal language from a non-causal design (observational / correlational / cross-sectional),
- over-generalisation beyond the sample, setting, or population actually studied,
- claims not backed by the reported data or statistics,
- mismatched or inappropriate statistical methods for the claim.

Output ONLY JSON:
{{"verdict": "supported|overreach|causal_overreach|overgeneralization|unsupported|methods_mismatch",
  "severity": "none|low|medium|high",
  "issue_type": "short label (e.g. 'Causal claim from observational data')",
  "confidence": 0.0-1.0,
  "reasoning": "1-3 sentences grounding the verdict in the methods/results",
  "evidence": "the relevant methods/results detail (quote or paraphrase), or what is missing",
  "suggestion": "a more defensible rewording of the claim, or \\"\\" if supported"}}

- "supported": the methods/results adequately back the claim → severity "none".
Be conservative: if the evidence is insufficient to judge, prefer "overreach"/"low"."""
    parsed = llm.extract_json(llm.invoke(model, prompt))
    data = parsed if isinstance(parsed, dict) else {}
    verdict = str(data.get("verdict") or "").strip().lower()
    if verdict not in _VERDICTS:
        verdict = "overreach" if data else "skipped"
    severity = str(data.get("severity") or "").strip().lower()
    if severity not in _SEV_RANK:
        severity = "none" if verdict == "supported" else "medium"
    if verdict == "supported":
        severity = "none"
    try:
        conf = max(0.0, min(1.0, float(data.get("confidence"))))
    except (TypeError, ValueError):
        conf = 0.5
    return {
        "verdict": verdict, "severity": severity,
        "issue_type": str(data.get("issue_type") or "").strip(),
        "confidence": round(conf, 3),
        "reasoning": str(data.get("reasoning") or "").strip(),
        "evidence": str(data.get("evidence") or "").strip(),
        "suggestion": str(data.get("suggestion") or "").strip(),
    }


def check_claim(index: int, claim: str, evidence_ctx: str, model: Any) -> Dict[str, Any]:
    a = assess_claim(claim, evidence_ctx, model)
    flagged = a["verdict"] not in ("supported", "skipped") and _SEV_RANK.get(a["severity"], 0) > 0
    return {"index": index, "claim": claim, **a, "status": "flagged" if flagged else "ok"}


def summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_verdict: Dict[str, int] = {}
    by_sev: Dict[str, int] = {}
    for r in results:
        by_verdict[r["verdict"]] = by_verdict.get(r["verdict"], 0) + 1
        by_sev[r["severity"]] = by_sev.get(r["severity"], 0) + 1
    return {
        "total": len(results),
        "flagged": sum(1 for r in results if r["status"] == "flagged"),
        "supported": sum(1 for r in results if r["verdict"] == "supported"),
        "by_verdict": by_verdict, "by_severity": by_sev,
    }
