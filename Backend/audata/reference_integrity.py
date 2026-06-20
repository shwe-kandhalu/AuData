"""Reference-integrity detection (AuData).

For each cited reference: resolve it (Crossref + OpenAlex, via the ingest layer),
check retraction status, and assess whether it supports the in-text claim
attributed to it (via the LLM dispatcher). Each result is one calibrated,
evidence-linked flag. Reviewer-assist — never an automated accusation.
"""

from __future__ import annotations

import difflib
import re
from typing import Any, Dict, List, Optional

from . import ingest, llm

_RESOLVE_SIM = 0.62    # accept a free-text citation's top hit at/above this title match
_MISMATCH_SIM = 0.50   # a resolved record whose title barely matches the cited text
_SEV_RANK = {"none": 0, "info": 1, "low": 2, "medium": 3, "high": 4}


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def _title_sim(a: str, b: str) -> float:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


def resolve_reference(doi: str, raw: str) -> Dict[str, Any]:
    """Resolve one reference (by DOI or free-text), with retraction + mismatch."""
    doi = (doi or "").strip().lower() or ingest.detect_doi(raw or "")
    raw = (raw or "").strip()
    meta: Dict[str, Any] = {"resolved": False}

    if doi:
        meta = ingest.resolve_doi(doi)
    elif raw:
        cands = ingest.search_works(raw, rows=3)
        if cands and cands[0].get("doi") and _title_sim(raw, cands[0].get("title", "")) >= _RESOLVE_SIM:
            doi = cands[0]["doi"]
            meta = ingest.resolve_doi(doi)

    resolved = bool(meta.get("resolved"))
    title = meta.get("title", "") if resolved else ""
    title_similarity: Optional[float] = None
    if resolved and raw and not ingest._DOI_RE.search(raw):
        title_similarity = round(_title_sim(raw, title), 3)

    return {
        "resolved": resolved,
        "doi": meta.get("doi", doi) if resolved else doi,
        "title": title,
        "year": meta.get("year") if resolved else None,
        "authors": meta.get("authors", "") if resolved else "",
        "container": meta.get("container", "") if resolved else "",
        "url": meta.get("url", "") if resolved else (f"https://doi.org/{doi}" if doi else ""),
        "abstract": meta.get("abstract", "") if resolved else "",
        "abstract_present": bool(meta.get("abstract")) if resolved else False,
        "retracted": bool(meta.get("retracted")) if resolved else False,
        "providers": meta.get("providers", []) if resolved else [],
        "title_similarity": title_similarity,
    }


def assess_citation_claim(claim: str, title: str, abstract: str, model: Any) -> Dict[str, Any]:
    claim = (claim or "").strip()
    if not claim:
        return {"verdict": "no_claim", "confidence": 0.0, "reasoning": "No in-text claim provided.", "quote": ""}
    if not (abstract or "").strip():
        return {"verdict": "unverifiable", "confidence": 0.0,
                "reasoning": "No abstract available for the resolved reference; claim support can't be verified.", "quote": ""}
    if model is None:
        return {"verdict": "skipped", "confidence": 0.0, "reasoning": "No model configured for claim checking.", "quote": ""}

    prompt = f"""You are assisting a human reviewer with research-integrity checks. Decide whether a
CITED REFERENCE actually supports the CLAIM a paper attributes to it. Reviewer-assist,
not an accusation.

IN-TEXT CLAIM (what the citing paper asserts and attributes to this reference):
"{claim}"

CITED REFERENCE
Title: {title}
Abstract: {abstract[:3500]}

Output ONLY a JSON object:
{{"verdict": "supports" | "partial" | "unsupported" | "unrelated",
  "confidence": 0.0-1.0,
  "reasoning": "one or two sentences",
  "quote": "a short snippet from the abstract that supports/contradicts the claim, or \\"\\""}}

- supports: clearly substantiates the claim.
- partial: related and partially supports it, but overstated or only tangential.
- unsupported: on-topic but does NOT establish the claim.
- unrelated: about something else entirely.
Be conservative: if the abstract is insufficient, prefer "partial" with low confidence."""

    data = llm.extract_json(llm.invoke(model, prompt)) or {}
    verdict = str(data.get("verdict") or "").strip().lower()
    if verdict not in ("supports", "partial", "unsupported", "unrelated"):
        verdict = "partial"
    try:
        conf = max(0.0, min(1.0, float(data.get("confidence"))))
    except (TypeError, ValueError):
        conf = 0.5
    return {"verdict": verdict, "confidence": round(conf, 3),
            "reasoning": str(data.get("reasoning") or "").strip(), "quote": str(data.get("quote") or "").strip()}


def check_reference(index: int, doi: str, raw: str, claim: str, model: Any, check_claims: bool = True) -> Dict[str, Any]:
    res = resolve_reference(doi, raw)
    issues: List[Dict[str, str]] = []

    if not res["resolved"]:
        issues.append({"code": "unresolved", "label": "Reference could not be resolved (may not exist)", "severity": "high"})
    if res["retracted"]:
        issues.append({"code": "retracted", "label": "Cited work is retracted", "severity": "high"})
    if res["resolved"] and res.get("title_similarity") is not None and res["title_similarity"] < _MISMATCH_SIM:
        issues.append({"code": "metadata_mismatch", "label": "Resolved record's title does not match the cited text", "severity": "medium"})

    claim_result: Dict[str, Any] = {"verdict": "skipped", "confidence": 0.0, "reasoning": "", "quote": ""}
    if check_claims and (claim or "").strip():
        claim_result = assess_citation_claim(claim, res["title"], res["abstract"], model if res["resolved"] else None)
        v = claim_result["verdict"]
        if v == "unsupported":
            issues.append({"code": "claim_unsupported", "label": "Reference does not support the in-text claim", "severity": "high"})
        elif v == "unrelated":
            issues.append({"code": "claim_unrelated", "label": "Reference is unrelated to the in-text claim", "severity": "high"})
        elif v == "partial":
            issues.append({"code": "claim_partial", "label": "Reference only partially supports the claim", "severity": "medium"})
        elif v == "unverifiable":
            issues.append({"code": "claim_unverifiable", "label": "No abstract available to verify the claim", "severity": "low"})

    severity = "none"
    for it in issues:
        if _SEV_RANK.get(it["severity"], 0) > _SEV_RANK.get(severity, 0):
            severity = it["severity"]

    return {
        "index": index,
        "input": {"doi": doi or "", "raw": raw or "", "claim": claim or ""},
        "resolved": res["resolved"],
        "matched": {"title": res["title"], "doi": res["doi"], "year": res["year"], "authors": res["authors"],
                    "container": res["container"], "url": res["url"], "providers": res["providers"],
                    "abstract_present": res["abstract_present"]},
        "title_similarity": res.get("title_similarity"),
        "retracted": res["retracted"],
        "claim": claim_result,
        "issues": issues,
        "severity": severity,
        "status": "flagged" if issues else "ok",
    }


def summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_sev: Dict[str, int] = {}
    by_code: Dict[str, int] = {}
    for r in results:
        by_sev[r["severity"]] = by_sev.get(r["severity"], 0) + 1
        for it in r["issues"]:
            by_code[it["code"]] = by_code.get(it["code"], 0) + 1
    return {
        "total": len(results),
        "flagged": sum(1 for r in results if r["status"] == "flagged"),
        "retracted": sum(1 for r in results if r["retracted"]),
        "unresolved": sum(1 for r in results if not r["resolved"]),
        "by_severity": by_sev, "by_issue": by_code,
    }


def extract_references_from_text(full_text: str, limit: int = 60) -> List[Dict[str, str]]:
    """Pull DOIs out of a paper's reference section so they can be auto-checked."""
    if not full_text:
        return []
    idx = -1
    for kw in ("\nreferences\n", "\nbibliography\n"):
        j = full_text.lower().rfind(kw)
        if j > idx:
            idx = j
    tail = full_text[idx:] if idx >= 0 else full_text
    seen, out = set(), []
    for m in ingest._DOI_RE.findall(tail):
        d = m.rstrip(".,;)].").lower()
        if d not in seen:
            seen.add(d)
            out.append({"doi": d, "raw": "", "claim": ""})
            if len(out) >= limit:
                break
    return out
