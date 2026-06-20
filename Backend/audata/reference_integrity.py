"""Reference-integrity detection (AuData).

Grounded in the ingested article. For each cited reference it runs a battery of
checks and returns one calibrated, evidence-linked flag with a detailed
explanation:

  • existence       — resolves against Crossref + OpenAlex (else: may be fabricated)
  • retraction      — OpenAlex is_retracted + Crossref signals
  • metadata match  — resolved title vs. the cited text (free-text refs)
  • claim support   — does the cited work back the in-text sentence citing it? (LLM)
  • future-dated    — reference newer than the citing paper (temporal impossibility)
  • self-citation   — shares an author with the paper under audit
  • uncited         — listed in the bibliography but never cited in the body
  • duplicate       — same DOI listed more than once

Reviewer-assist — never an automated accusation.
"""

from __future__ import annotations

import difflib
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from . import ingest, llm

_RESOLVE_SIM = 0.62
_MISMATCH_SIM = 0.50
_COVERAGE_MIN = 0.60   # fraction of a candidate title's words that must appear in the citation
_SEV_RANK = {"none": 0, "info": 1, "low": 2, "medium": 3, "high": 4}
_FLAGGED = {"low", "medium", "high"}

_GREY_LIT = ("retrieved", "available at", "available from", "accessed", "http://",
             "https://", "www.", "[online]", "blog", "call for papers", "press release", "white paper")

_REF_MARKER = re.compile(r"(?m)^\s*\[?(\d{1,3})\]?[.)]\s+")
_CITE_GROUP = re.compile(r"\[([0-9,\s–\-]+)\]")


# ── helpers ───────────────────────────────────────────────────────────────────

def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def _title_sim(a: str, b: str) -> float:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


def _title_coverage(citation: str, title: str) -> float:
    """Fraction of the candidate title's significant words found in the citation.

    Robust to the citation carrying extra tokens (authors, year, journal) that a
    full-string similarity would penalise — the right signal for matching a
    free-text reference to a search hit.
    """
    cite_words = set(re.findall(r"[a-z0-9]+", (citation or "").lower()))
    title_words = [w for w in re.findall(r"[a-z0-9]+", (title or "").lower()) if len(w) > 3]
    if len(title_words) < 3:
        return 0.0
    return sum(1 for w in title_words if w in cite_words) / len(title_words)


def _is_grey_lit(text: str) -> bool:
    low = (text or "").lower()
    return any(k in low for k in _GREY_LIT)


def _surnames(authors: str) -> Set[str]:
    """Crude surname set from an 'First Last, First2 Last2' author string."""
    out: Set[str] = set()
    for name in (authors or "").split(","):
        toks = [t for t in re.split(r"\s+", name.strip()) if t]
        if toks:
            surname = re.sub(r"[^a-z]", "", toks[-1].lower())
            if len(surname) >= 3:
                out.add(surname)
    return out


def _shared_surnames(authors: str, paper_surnames: Set[str]) -> Set[str]:
    return _surnames(authors) & (paper_surnames or set())


def _parse_group(g: str) -> Set[int]:
    nums: Set[int] = set()
    for part in g.split(","):
        part = part.strip().replace("–", "-")
        if "-" in part:
            try:
                a, b = part.split("-", 1)
                a, b = int(a), int(b)
                if 0 < b - a < 200:
                    nums.update(range(a, b + 1))
            except Exception:
                pass
        elif part.isdigit():
            nums.add(int(part))
    return nums


def citation_map(body: str) -> Dict[int, int]:
    """How many times each numbered reference is cited in the body text."""
    counts: Dict[int, int] = {}
    for m in _CITE_GROUP.finditer(body or ""):
        for n in _parse_group(m.group(1)):
            counts[n] = counts.get(n, 0) + 1
    return counts


def intext_claims(body: str) -> Dict[int, str]:
    """Map each numbered reference to the sentence that first cites it."""
    out: Dict[int, str] = {}
    for sent in re.split(r"(?<=[.!?])\s+", body or ""):
        nums: Set[int] = set()
        for m in _CITE_GROUP.finditer(sent):
            nums.update(_parse_group(m.group(1)))
        if not nums:
            continue
        clean = " ".join(sent.split())
        if len(clean) < 20:
            continue
        for n in nums:
            out.setdefault(n, clean[:600])
    return out


def extract_references(full_text: str, limit: int = 120) -> Tuple[List[Dict[str, Any]], str]:
    """Split the bibliography into numbered entries; return (entries, body)."""
    if not full_text:
        return [], ""
    idx = -1
    for kw in ("\nreferences\n", "\nbibliography\n", "\nreferences ", "\nworks cited\n"):
        j = full_text.lower().rfind(kw)
        if j > idx:
            idx = j
    body = full_text[:idx] if idx >= 0 else full_text
    tail = full_text[idx:] if idx >= 0 else full_text

    entries: List[Dict[str, Any]] = []
    markers = list(_REF_MARKER.finditer(tail))
    if len(markers) >= 3:
        for i, m in enumerate(markers):
            number = int(m.group(1))
            start = m.end()
            end = markers[i + 1].start() if i + 1 < len(markers) else len(tail)
            entry = " ".join(tail[start:end].split())
            if len(entry) < 15:
                continue
            d = ingest.detect_doi(entry)
            entries.append({"number": number, "doi": d, "raw": "" if d else entry[:400]})
            if len(entries) >= limit:
                break
        if entries:
            return entries, body

    # Fallback: no numbering — collect unique DOIs (no in-text linking possible).
    seen: Set[str] = set()
    for m in ingest._DOI_RE.findall(tail):
        d = m.rstrip(".,;)].").lower()
        if d not in seen:
            seen.add(d)
            entries.append({"number": None, "doi": d, "raw": ""})
            if len(entries) >= limit:
                break
    return entries, body


# Backwards-compatible: simple list for the "edit references" populate.
def extract_references_from_text(full_text: str, limit: int = 120) -> List[Dict[str, str]]:
    entries, _ = extract_references(full_text, limit)
    return [{"doi": e.get("doi", ""), "raw": e.get("raw", ""), "claim": ""} for e in entries]


# ── resolution + claim ────────────────────────────────────────────────────────

def resolve_reference(doi: str, raw: str) -> Dict[str, Any]:
    doi = (doi or "").strip().lower() or ingest.detect_doi(raw or "")
    raw = (raw or "").strip()
    meta: Dict[str, Any] = {"resolved": False}
    match_cov: Optional[float] = None
    if doi:
        meta = ingest.resolve_doi(doi)
    elif raw:
        # Pick the search hit whose title is best covered by the citation text
        # (robust to authors/year/journal noise that full-string similarity hurts on).
        best, best_cov = None, 0.0
        for c in ingest.search_works(raw, rows=5):
            cov = _title_coverage(raw, c.get("title", ""))
            if cov > best_cov:
                best_cov, best = cov, c
        if best and best.get("doi") and best_cov >= _COVERAGE_MIN:
            doi = best["doi"]
            meta = ingest.resolve_doi(doi)
            match_cov = best_cov
    resolved = bool(meta.get("resolved"))
    title = meta.get("title", "") if resolved else ""
    title_similarity: Optional[float] = round(match_cov, 3) if (resolved and match_cov is not None) else None
    return {
        "resolved": resolved, "doi": meta.get("doi", doi) if resolved else doi, "title": title,
        "year": meta.get("year") if resolved else None, "authors": meta.get("authors", "") if resolved else "",
        "container": meta.get("container", "") if resolved else "", "url": meta.get("url", "") if resolved else (f"https://doi.org/{doi}" if doi else ""),
        "abstract": meta.get("abstract", "") if resolved else "", "abstract_present": bool(meta.get("abstract")) if resolved else False,
        "retracted": bool(meta.get("retracted")) if resolved else False, "providers": meta.get("providers", []) if resolved else [],
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
CITED REFERENCE supports the CLAIM the paper makes where it cites it. Reviewer-assist,
not an accusation.

IN-TEXT SENTENCE (the citing paper's text around this citation):
"{claim}"

CITED REFERENCE
Title: {title}
Abstract: {abstract[:3500]}

Output ONLY JSON:
{{"verdict":"supports"|"partial"|"unsupported"|"unrelated","confidence":0.0-1.0,
  "reasoning":"one or two sentences","quote":"short snippet from the abstract or \\"\\""}}
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


# ── per-reference check ───────────────────────────────────────────────────────

def check_reference(index: int, doi: str, raw: str, claim: str, model: Any,
                    check_claims: bool = True, ctx: Optional[Dict[str, Any]] = None,
                    number: Optional[int] = None) -> Dict[str, Any]:
    ctx = ctx or {}
    res = resolve_reference(doi, raw)
    issues: List[Dict[str, str]] = []

    def add(code: str, label: str, sev: str, detail: str):
        issues.append({"code": code, "label": label, "severity": sev, "detail": detail})

    if not res["resolved"]:
        if _is_grey_lit(raw) and not (doi or ingest.detect_doi(raw or "")):
            add("unindexed", "Non-indexed source (couldn't auto-verify)", "low",
                "This looks like a website, report, press release, or other grey-literature source that isn't "
                "indexed in Crossref or OpenAlex, so it can't be auto-verified. Check the link/source manually — "
                "this is common for legitimate citations and isn't itself a red flag.")
        else:
            kind = "DOI" if (doi or ingest.detect_doi(raw or "")) else "citation"
            add("unresolved", "Could not be resolved", "high",
                f"No matching record was found in Crossref or OpenAlex for this {kind}. The reference may be "
                f"fabricated, contain a typo, or be too obscure to be indexed — verify it by hand before relying on it.")
    if res["retracted"]:
        add("retracted", "Cited work is retracted", "high",
            "OpenAlex/Crossref marks this work as retracted. Any conclusion that rests on it should be "
            "re-examined; if the paper discusses it, it should cite the retraction notice, not the original.")
    if res["resolved"] and res.get("title_similarity") is not None and res["title_similarity"] < _MISMATCH_SIM:
        add("metadata_mismatch", "Resolved title doesn't match the citation", "medium",
            f'The closest record found is titled "{res["title"][:120]}", which differs substantially from the '
            f'cited text (title match {int(res["title_similarity"] * 100)}%). The citation may point to a different work.')

    claim_result: Dict[str, Any] = {"verdict": "skipped", "confidence": 0.0, "reasoning": "", "quote": ""}
    if check_claims and (claim or "").strip():
        claim_result = assess_citation_claim(claim, res["title"], res["abstract"], model if res["resolved"] else None)
        v, reason = claim_result["verdict"], claim_result.get("reasoning", "")
        if v == "unsupported":
            add("claim_unsupported", "Doesn't support the in-text claim", "high",
                reason or "The reference is on-topic but its abstract does not establish the specific claim it is cited for.")
        elif v == "unrelated":
            add("claim_unrelated", "Unrelated to the in-text claim", "high",
                reason or "The reference appears to be about a different topic than the sentence that cites it.")
        elif v == "partial":
            add("claim_partial", "Only partially supports the claim", "medium",
                reason or "The reference is related but the claim overstates it or only loosely follows from it.")
        elif v == "unverifiable":
            add("claim_unverifiable", "No abstract to verify the claim", "low",
                "No abstract was available for the resolved reference, so claim support could not be checked from metadata.")

    # Context-dependent checks (need the paper under audit).
    paper_year = ctx.get("paper_year")
    if res["resolved"] and res["year"] and paper_year and res["year"] > paper_year + 1:
        add("future_dated", "Dated after the citing paper", "high",
            f"This reference is dated {res['year']}, but the paper under audit is from {paper_year}. Citing work "
            f"published after the paper is chronologically impossible — usually a metadata error or a fabricated citation.")
    surnames = ctx.get("paper_surnames")
    if res["resolved"] and surnames and res["authors"]:
        shared = _shared_surnames(res["authors"], surnames)
        if shared:
            add("self_citation", "Self-citation", "info",
                f"Shares author(s) ({', '.join(sorted(shared))}) with the paper under audit. Self-citation is normal "
                f"in moderation, but a high rate across the bibliography can artificially inflate citation metrics.")
    cited_count = ctx.get("cited_count")
    if cited_count == 0 and number is not None:
        add("uncited", "Listed but not cited in the text", "low",
            f"Reference [{number}] appears in the bibliography but its citation marker was not found in the body text. "
            f"It may be an uncited (padded) reference, or the body uses a citation style this check didn't detect.")
    if ctx.get("duplicate"):
        add("duplicate", "Duplicate of an earlier reference", "low",
            "The same DOI is listed earlier in the reference list — a duplicate entry, which can pad the reference count.")

    severity = "none"
    for it in issues:
        if _SEV_RANK.get(it["severity"], 0) > _SEV_RANK.get(severity, 0):
            severity = it["severity"]
    flagged = any(it["severity"] in _FLAGGED for it in issues)

    return {
        "index": index, "number": number,
        "input": {"doi": doi or "", "raw": raw or "", "claim": claim or ""},
        "resolved": res["resolved"],
        "matched": {"title": res["title"], "doi": res["doi"], "year": res["year"], "authors": res["authors"],
                    "container": res["container"], "url": res["url"], "providers": res["providers"],
                    "abstract_present": res["abstract_present"]},
        "title_similarity": res.get("title_similarity"),
        "retracted": res["retracted"], "cited_count": cited_count,
        "claim": claim_result, "issues": issues,
        "severity": severity, "status": "flagged" if flagged else "ok",
    }


# ── paper-level orchestration ─────────────────────────────────────────────────

def prepare_paper_references(paper: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract refs from a paper and attach in-text claims + per-ref context."""
    full_text = paper.get("full_text", "") or ""
    entries, body = extract_references(full_text)
    cmap = citation_map(body)
    claims = intext_claims(body)
    paper_year = paper.get("year")
    surnames = _surnames(paper.get("authors", ""))
    seen_doi: Set[str] = set()
    prepared: List[Dict[str, Any]] = []
    for e in entries:
        num = e.get("number")
        doi = (e.get("doi") or "").lower()
        raw = e.get("raw", "")
        dup = bool(doi and doi in seen_doi)
        if doi:
            seen_doi.add(doi)
        prepared.append({
            "number": num, "doi": doi, "raw": raw,
            "claim": claims.get(num, "") if num is not None else "",
            "ctx": {"paper_year": paper_year, "paper_surnames": surnames,
                    "cited_count": (cmap.get(num, 0) if num is not None else None), "duplicate": dup},
        })
    return prepared


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


def paper_metrics(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(results) or 1
    years = sorted([r["matched"].get("year") for r in results if r["resolved"] and r["matched"].get("year")])
    self_cit = sum(1 for r in results if any(i["code"] == "self_citation" for i in r["issues"]))
    return {
        "self_citations": self_cit,
        "self_citation_rate": round(self_cit / total, 3),
        "uncited_count": sum(1 for r in results if any(i["code"] == "uncited" for i in r["issues"])),
        "duplicate_count": sum(1 for r in results if any(i["code"] == "duplicate" for i in r["issues"])),
        "future_dated_count": sum(1 for r in results if any(i["code"] == "future_dated" for i in r["issues"])),
        "oldest_year": years[0] if years else None,
        "newest_year": years[-1] if years else None,
        "median_year": years[len(years) // 2] if years else None,
        "most_cited": max((r.get("cited_count") or 0 for r in results), default=0),
    }
