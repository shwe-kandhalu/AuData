"""Reference-integrity detection for AuData.

Given a paper's cited references, this module:
  1. Resolves each reference against Crossref + OpenAlex (does it exist?).
  2. Checks retraction status (OpenAlex `is_retracted`, plus Crossref relations).
  3. Assesses citation-claim support: does the cited work actually back the
     in-text claim the citing paper attributes to it (via the LLM dispatcher)?

It reuses the existing literature integrations' providers (Crossref / OpenAlex)
and the provider-agnostic LLM dispatcher (`AIService`). Framing is
reviewer-assist: every result is a flag with a severity and reasoning, never an
automated verdict.
"""

from __future__ import annotations

import re
import difflib
from typing import Any, Dict, List, Optional

import requests

from config import Config
from utils import AIService

# ── HTTP config ─────────────────────────────────────────────────────────────
_MAILTO = Config.ENTREZ_EMAIL or "research@audata.local"
_HEADERS = {"User-Agent": f"AuData/0.1 (mailto:{_MAILTO})"}
_TIMEOUT = 15

CROSSREF_SEARCH = "https://api.crossref.org/works"
OPENALEX_WORKS = "https://api.openalex.org/works"

# A DOI: 10.<registrant>/<suffix>. Suffix is greedy but trimmed of trailing punctuation.
_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", re.I)

# Title-match thresholds when resolving a free-text citation string (no DOI).
_RESOLVE_SIM = 0.62   # >= this → treat the top search hit as the resolved match
_MISMATCH_SIM = 0.50  # a DOI resolved but its title barely matches the given text


# ── small helpers ─────────────────────────────────────────────────────────────

def extract_doi(text: str) -> Optional[str]:
    """Pull the first DOI out of a free-text string, normalized to lowercase."""
    if not text:
        return None
    m = _DOI_RE.search(text)
    if not m:
        return None
    return m.group(0).rstrip(".,;)].").lower()


def _strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def _title_sim(a: str, b: str) -> float:
    na, nb = _norm_title(a), _norm_title(b)
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


def _reconstruct_inverted(inv: Optional[Dict[str, List[int]]]) -> str:
    """Rebuild plain text from OpenAlex's abstract_inverted_index."""
    if not inv:
        return ""
    positions: List[tuple] = []
    for word, idxs in inv.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort(key=lambda x: x[0])
    return " ".join(w for _, w in positions)


def _authors_crossref(msg: Dict[str, Any]) -> str:
    out = []
    for a in (msg.get("author") or [])[:8]:
        name = " ".join(x for x in [a.get("given"), a.get("family")] if x)
        if name:
            out.append(name)
    return ", ".join(out)


def _authors_openalex(work: Dict[str, Any]) -> str:
    out = []
    for au in (work.get("authorships") or [])[:8]:
        name = (au.get("author") or {}).get("display_name")
        if name:
            out.append(name)
    return ", ".join(out)


# ── provider lookups ──────────────────────────────────────────────────────────

def fetch_crossref_by_doi(doi: str) -> Optional[Dict[str, Any]]:
    try:
        url = f"{CROSSREF_SEARCH}/{requests.utils.quote(doi, safe='/')}"
        r = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        if r.status_code != 200:
            return None
        msg = (r.json() or {}).get("message") or {}
    except Exception:
        return None
    title = ""
    if msg.get("title"):
        title = msg["title"][0] if isinstance(msg["title"], list) else str(msg["title"])
    year = None
    issued = (msg.get("issued") or {}).get("date-parts") or []
    if issued and issued[0]:
        year = issued[0][0]
    # Retraction signals on Crossref.
    retracted = False
    rtype = str(msg.get("type") or "").lower()
    if "retract" in rtype or "withdraw" in rtype:
        retracted = True
    if "retract" in (title or "").lower():
        retracted = True
    relation = msg.get("relation") or {}
    if any("retract" in str(k).lower() for k in relation.keys()):
        retracted = True
    return {
        "title": title,
        "doi": (msg.get("DOI") or doi).lower(),
        "year": year,
        "authors": _authors_crossref(msg),
        "abstract": _strip_tags(msg.get("abstract") or ""),
        "url": msg.get("URL") or f"https://doi.org/{doi}",
        "container": (msg.get("container-title") or [""])[0] if msg.get("container-title") else "",
        "retracted": retracted,
        "provider": "Crossref",
    }


def fetch_openalex_by_doi(doi: str) -> Optional[Dict[str, Any]]:
    try:
        url = f"{OPENALEX_WORKS}/doi:{doi}"
        r = requests.get(url, headers=_HEADERS, params={"mailto": _MAILTO}, timeout=_TIMEOUT)
        if r.status_code != 200:
            return None
        w = r.json() or {}
    except Exception:
        return None
    if not w.get("id"):
        return None
    loc = w.get("primary_location") or {}
    return {
        "title": w.get("title") or w.get("display_name") or "",
        "doi": (w.get("doi") or "").replace("https://doi.org/", "").lower() or doi,
        "year": w.get("publication_year"),
        "authors": _authors_openalex(w),
        "abstract": _reconstruct_inverted(w.get("abstract_inverted_index")),
        "url": (loc.get("landing_page_url") or w.get("id") or ""),
        "container": ((loc.get("source") or {}) or {}).get("display_name") or "",
        "retracted": bool(w.get("is_retracted")),
        "provider": "OpenAlex",
    }


def search_crossref(raw: str, rows: int = 3) -> List[Dict[str, Any]]:
    try:
        r = requests.get(
            CROSSREF_SEARCH, headers=_HEADERS, timeout=_TIMEOUT,
            params={"query.bibliographic": raw, "rows": rows},
        )
        if r.status_code != 200:
            return []
        items = ((r.json() or {}).get("message") or {}).get("items") or []
    except Exception:
        return []
    out = []
    for it in items:
        title = (it.get("title") or [""])[0] if it.get("title") else ""
        out.append({"title": title, "doi": (it.get("DOI") or "").lower()})
    return out


# ── core checks ───────────────────────────────────────────────────────────────

def resolve_reference(doi: str, raw: str) -> Dict[str, Any]:
    """Resolve one reference to a real work; detect retraction + metadata mismatch."""
    doi = (doi or "").strip().lower() or (extract_doi(raw) or "")
    raw = (raw or "").strip()

    cr: Optional[Dict[str, Any]] = None
    oa: Optional[Dict[str, Any]] = None

    if doi:
        cr = fetch_crossref_by_doi(doi)
        oa = fetch_openalex_by_doi(doi)
    elif raw:
        # No DOI given — search by the citation string and accept the top hit
        # only if its title is close enough to the text we were handed.
        cands = search_crossref(raw, rows=3)
        best = cands[0] if cands else None
        if best and best.get("doi") and _title_sim(raw, best.get("title", "")) >= _RESOLVE_SIM:
            doi = best["doi"]
            cr = fetch_crossref_by_doi(doi)
            oa = fetch_openalex_by_doi(doi)

    resolved = bool(cr or oa)
    # Prefer Crossref metadata; fall back to / enrich with OpenAlex.
    meta = cr or oa or {}
    abstract = (meta.get("abstract") or "")
    if not abstract and oa:
        abstract = oa.get("abstract") or ""
    title = meta.get("title") or (oa.get("title") if oa else "") or ""
    retracted = bool((cr or {}).get("retracted")) or bool((oa or {}).get("retracted"))

    # If the user gave free text AND we resolved something, measure how well the
    # resolved title matches what they cited — a low score is a metadata mismatch.
    title_similarity: Optional[float] = None
    if resolved and raw and not _DOI_RE.search(raw):
        title_similarity = round(_title_sim(raw, title), 3)

    return {
        "resolved": resolved,
        "doi": (meta.get("doi") or doi or ""),
        "title": title,
        "year": meta.get("year"),
        "authors": meta.get("authors") or "",
        "container": meta.get("container") or "",
        "url": meta.get("url") or (f"https://doi.org/{doi}" if doi else ""),
        "abstract": abstract,
        "abstract_present": bool(abstract),
        "retracted": retracted,
        "providers": [p for p in [(cr or {}).get("provider"), (oa or {}).get("provider")] if p],
        "title_similarity": title_similarity,
    }


def assess_citation_claim(claim: str, title: str, abstract: str, model: Any) -> Dict[str, Any]:
    """Use the LLM to judge whether the resolved reference supports the claim."""
    claim = (claim or "").strip()
    if not claim:
        return {"verdict": "no_claim", "confidence": 0.0, "reasoning": "No in-text claim provided.", "quote": ""}
    if not (abstract or "").strip():
        return {
            "verdict": "unverifiable", "confidence": 0.0,
            "reasoning": "No abstract available for the resolved reference, so claim support cannot be verified from metadata.",
            "quote": "",
        }
    if model is None:
        return {"verdict": "skipped", "confidence": 0.0, "reasoning": "Claim checking disabled (no model).", "quote": ""}

    from langchain_core.messages import HumanMessage

    prompt = f"""You are assisting a human reviewer in checking research integrity. Decide whether a
CITED REFERENCE actually supports the CLAIM that a paper attributes to it. This is
reviewer-assist, not an accusation.

IN-TEXT CLAIM (what the citing paper asserts and attributes to this reference):
"{claim}"

CITED REFERENCE
Title: {title}
Abstract: {abstract[:3500]}

Output ONLY a JSON object:
{{
  "verdict": "supports" | "partial" | "unsupported" | "unrelated",
  "confidence": 0.0-1.0,
  "reasoning": "one or two sentences explaining the verdict",
  "quote": "a short snippet from the abstract that supports or contradicts the claim, or \\"\\" if none"
}}

Definitions:
- "supports": the reference clearly substantiates the claim.
- "partial": related and partially supports it, but the claim overstates or only tangentially follows.
- "unsupported": on-topic but the reference does NOT establish the claim.
- "unrelated": the reference is about something else entirely.
Be conservative: if the abstract is insufficient to judge, prefer "partial" with low confidence.
"""
    try:
        r = model.invoke([HumanMessage(content=prompt)])
        data = AIService._extract_json(getattr(r, "content", "") or "") or {}
    except Exception as e:  # network / model error → unverifiable, don't crash the batch
        return {"verdict": "error", "confidence": 0.0, "reasoning": f"Claim check failed: {e}", "quote": ""}

    verdict = str(data.get("verdict") or "").strip().lower()
    if verdict not in ("supports", "partial", "unsupported", "unrelated"):
        verdict = "partial"
    try:
        conf = float(data.get("confidence"))
        conf = max(0.0, min(1.0, conf))
    except (TypeError, ValueError):
        conf = 0.5
    return {
        "verdict": verdict,
        "confidence": round(conf, 3),
        "reasoning": str(data.get("reasoning") or "").strip(),
        "quote": str(data.get("quote") or "").strip(),
    }


# Severity ranking for combining multiple issues into one headline severity.
_SEV_RANK = {"none": 0, "info": 1, "low": 2, "medium": 3, "high": 4}


def check_reference(index: int, doi: str, raw: str, claim: str, model: Any,
                    check_claims: bool = True) -> Dict[str, Any]:
    """Full integrity check for one reference → a single flag object."""
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
        "matched": {
            "title": res["title"],
            "doi": res["doi"],
            "year": res["year"],
            "authors": res["authors"],
            "container": res["container"],
            "url": res["url"],
            "providers": res["providers"],
            "abstract_present": res["abstract_present"],
        },
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
        "by_severity": by_sev,
        "by_issue": by_code,
    }
