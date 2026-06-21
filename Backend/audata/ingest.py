"""Ingest — load the paper under audit (AuData, self-contained).

Produces one normalized "paper under audit" object from a PDF, a DOI, a title
search, or a URL. Full text via PyMuPDF (pypdf fallback); metadata via Crossref +
OpenAlex; open-access PDF via Unpaywall. No dependency on the Evidence Engine app.
"""

from __future__ import annotations

import io
import re
from typing import Any, Dict, List, Optional

import requests

from . import settings

_MAILTO = settings.ENTREZ_EMAIL or "research@audata.local"
_HEADERS = {"User-Agent": f"AuData/0.1 (mailto:{_MAILTO})"}
_TIMEOUT = 20
CROSSREF_SEARCH = "https://api.crossref.org/works"
OPENALEX_WORKS = "https://api.openalex.org/works"

_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", re.I)

_SECTION_WORDS = [
    "abstract", "introduction", "background", "related work",
    "methods", "materials and methods", "methodology", "experimental",
    "results", "results and discussion", "discussion", "limitations",
    "conclusion", "conclusions", "acknowledgments", "acknowledgements",
    "references", "bibliography", "supplementary", "appendix",
]
_HEADING_RE = re.compile(
    r"^\s*(?:\d{0,2}[.)]?\s*)?(" + "|".join(re.escape(w) for w in _SECTION_WORDS) + r")\s*:?\s*$",
    re.I,
)
_TABLE_RE = re.compile(r"\btable\s+(\d+)\b", re.I)
_FIGURE_RE = re.compile(r"\bfig(?:ure)?\.?\s+(\d+)\b", re.I)


# ── small helpers ─────────────────────────────────────────────────────────────

def detect_doi(text: str) -> str:
    if not text:
        return ""
    m = _DOI_RE.search(text)
    return m.group(0).rstrip(".,;)].").lower() if m else ""


def _authors(item: Dict[str, Any]) -> str:
    out = []
    for a in (item.get("author") or [])[:8]:
        name = " ".join(x for x in [a.get("given"), a.get("family")] if x)
        if name:
            out.append(name)
    return ", ".join(out)


def _reconstruct_inverted(inv) -> str:
    if not inv:
        return ""
    pos = []
    for word, idxs in inv.items():
        for i in idxs:
            pos.append((i, word))
    pos.sort(key=lambda x: x[0])
    return " ".join(w for _, w in pos)


def _split_sections(full_text: str) -> List[Dict[str, Any]]:
    if not full_text:
        return []
    sections: List[Dict[str, Any]] = []
    cur_title = "Preamble"
    cur_buf: List[str] = []

    def flush():
        body = "\n".join(cur_buf).strip()
        if body:
            sections.append({"title": cur_title, "char_count": len(body), "preview": body[:280]})

    for ln in full_text.split("\n"):
        m = _HEADING_RE.match(ln)
        if m:
            flush()
            cur_title = m.group(1).strip().title()
            cur_buf = []
        else:
            cur_buf.append(ln)
    flush()
    if len(sections) == 1 and sections[0]["title"] == "Preamble":
        return []
    return sections


def _count_references(full_text: str) -> int:
    idx = -1
    for kw in ("\nreferences\n", "\nbibliography\n"):
        j = full_text.lower().rfind(kw)
        if j > idx:
            idx = j
    tail = full_text[idx:] if idx >= 0 else full_text
    dois = len(set(_DOI_RE.findall(tail)))
    numbered = len(re.findall(r"(?m)^\s*\[?\d{1,3}\]?[.)]\s+\S", tail))
    return max(dois, numbered)


def _build_paper(
    *, source: str, ident: str, title: str = "", authors: str = "", year=None,
    doi: str = "", container: str = "", url: str = "", abstract: str = "",
    full_text: str = "", full_text_source: str = "", num_pages: Optional[int] = None,
    retracted: bool = False, providers: Optional[List[str]] = None,
) -> Dict[str, Any]:
    sections = _split_sections(full_text)
    tables = sorted({int(n) for n in _TABLE_RE.findall(full_text)}) if full_text else []
    figures = sorted({int(n) for n in _FIGURE_RE.findall(full_text)}) if full_text else []
    return {
        "id": ident, "source": source, "title": title or "", "authors": authors or "",
        "year": year, "doi": doi or "", "container": container or "", "url": url or "",
        "abstract": abstract or "", "full_text": full_text or "",
        "full_text_source": full_text_source or "", "has_full_text": bool((full_text or "").strip()),
        "num_pages": num_pages, "char_count": len(full_text or ""),
        "sections": sections, "tables_detected": len(tables), "table_numbers": tables[:50],
        "figures_detected": len(figures), "references_detected": _count_references(full_text) if full_text else 0,
        "retracted": bool(retracted), "providers": providers or [], "has_pdf": False,
    }


# ── PDF parsing ───────────────────────────────────────────────────────────────

def extract_text_from_pdf(data: bytes) -> str:
    return _extract_pdf_text(data).get("text") or ""


def _extract_pdf_text(data: bytes) -> Dict[str, Any]:
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=data, filetype="pdf")
        pages = [doc[i].get_text("text") for i in range(doc.page_count)]
        meta = doc.metadata or {}
        meta_title = meta.get("title") or ""
        # DOI sometimes embedded in PDF metadata subject/keywords fields
        meta_doi = detect_doi(meta.get("subject") or "") or detect_doi(meta.get("keywords") or "")
        n = doc.page_count
        doc.close()
        return {"text": "\n".join(pages), "num_pages": n, "meta_title": meta_title, "meta_doi": meta_doi}
    except Exception:
        pass
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        pages = [(pg.extract_text() or "") for pg in reader.pages]
        try:
            meta_title = (reader.metadata or {}).get("/Title") or ""
        except Exception:
            meta_title = ""
        return {"text": "\n".join(pages), "num_pages": len(reader.pages), "meta_title": meta_title}
    except Exception as e:
        return {"text": "", "num_pages": None, "meta_title": "", "error": str(e)}


def _guess_title(full_text: str, meta_title: str, filename: str) -> str:
    mt = (meta_title or "").strip()
    if mt and len(mt) > 8 and "untitled" not in mt.lower():
        return mt
    for ln in (full_text or "").split("\n"):
        s = ln.strip()
        if 12 <= len(s) <= 220 and not s.lower().startswith(("doi", "http", "www")):
            return s
    return (filename or "Uploaded PDF").rsplit(".", 1)[0]


def parse_pdf_bytes(data: bytes, filename: str) -> Dict[str, Any]:
    info = _extract_pdf_text(data)
    full_text = info.get("text") or ""
    # Only look for the paper's own DOI in: PDF metadata → first 2000 chars (title page).
    # Never scan the full text — references contain many foreign DOIs.
    doi = (info.get("meta_doi") or "") or detect_doi(full_text[:2000])
    title = _guess_title(full_text, info.get("meta_title") or "", filename)
    return _build_paper(
        source="pdf_upload", ident=doi or filename, title=title, doi=doi,
        url=(f"https://doi.org/{doi}" if doi else ""), full_text=full_text,
        full_text_source=f"Uploaded PDF ({filename})", num_pages=info.get("num_pages"),
    )


# ── metadata resolution + search ──────────────────────────────────────────────

def search_openalex(query: str, rows: int = 5) -> List[Dict[str, Any]]:
    """Search OpenAlex by free text — a fallback when Crossref misses."""
    query = (query or "").strip()
    if not query:
        return []
    try:
        r = requests.get(OPENALEX_WORKS, headers=_HEADERS, timeout=_TIMEOUT, params={
            "search": query[:350], "per_page": max(1, min(rows, 10)), "mailto": _MAILTO,
        })
        if r.status_code != 200:
            return []
        results = (r.json() or {}).get("results") or []
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for w in results:
        loc = w.get("primary_location") or {}
        out.append({
            "title": w.get("title") or w.get("display_name") or "",
            "doi": (w.get("doi") or "").replace("https://doi.org/", "").lower(),
            "year": w.get("publication_year"),
            "authors": ", ".join((au.get("author") or {}).get("display_name", "")
                                  for au in (w.get("authorships") or [])[:8]).strip(", "),
            "container": ((loc.get("source") or {}) or {}).get("display_name") or "",
            "url": loc.get("landing_page_url") or w.get("id") or "",
            "abstract": _reconstruct_inverted(w.get("abstract_inverted_index")),
            "retracted": bool(w.get("is_retracted")),
        })
    return out


def resolve_doi(doi: str) -> Dict[str, Any]:
    doi = (doi or "").strip().lower()
    if not doi:
        return {"resolved": False}
    cr = oa = None
    try:
        r = requests.get(f"{CROSSREF_SEARCH}/{requests.utils.quote(doi, safe='/')}",
                         headers=_HEADERS, timeout=_TIMEOUT)
        if r.status_code == 200:
            m = (r.json() or {}).get("message") or {}
            title = (m.get("title") or [""])[0] if m.get("title") else ""
            dp = (m.get("issued") or {}).get("date-parts") or []
            rtype = str(m.get("type") or "").lower()
            retr = "retract" in rtype or "retract" in (title or "").lower() or any(
                "retract" in str(k).lower() for k in (m.get("relation") or {}).keys())
            cr = {
                "title": title, "authors": _authors(m),
                "year": (dp[0][0] if dp and dp[0] else None),
                "container": (m.get("container-title") or [""])[0] if m.get("container-title") else "",
                "abstract": re.sub(r"<[^>]+>", "", m.get("abstract") or "").strip(),
                "url": m.get("URL") or f"https://doi.org/{doi}", "retracted": retr,
            }
    except Exception:
        cr = None
    try:
        r = requests.get(f"{OPENALEX_WORKS}/doi:{doi}", headers=_HEADERS,
                         params={"mailto": _MAILTO}, timeout=_TIMEOUT)
        if r.status_code == 200:
            w = r.json() or {}
            if w.get("id"):
                loc = w.get("primary_location") or {}
                oa = {
                    "title": w.get("title") or "",
                    "authors": ", ".join((au.get("author") or {}).get("display_name", "")
                                         for au in (w.get("authorships") or [])[:8]).strip(", "),
                    "year": w.get("publication_year"),
                    "container": ((loc.get("source") or {}) or {}).get("display_name") or "",
                    "abstract": _reconstruct_inverted(w.get("abstract_inverted_index")),
                    "url": loc.get("landing_page_url") or w.get("id") or "",
                    "retracted": bool(w.get("is_retracted")),
                }
    except Exception:
        oa = None
    if not (cr or oa):
        return {"resolved": False, "doi": doi}
    base = cr or oa or {}
    return {
        "resolved": True, "doi": doi,
        "title": base.get("title") or (oa or {}).get("title") or "",
        "authors": base.get("authors") or (oa or {}).get("authors") or "",
        "year": base.get("year") or (oa or {}).get("year"),
        "container": base.get("container") or "",
        "abstract": base.get("abstract") or (oa or {}).get("abstract") or "",
        "url": base.get("url") or "",
        "retracted": bool((cr or {}).get("retracted")) or bool((oa or {}).get("retracted")),
        "providers": [p for p in [("Crossref" if cr else None), ("OpenAlex" if oa else None)] if p],
    }


def search_works(query: str, rows: int = 6) -> List[Dict[str, Any]]:
    query = (query or "").strip()
    if not query:
        return []
    params = {
        "query.bibliographic": query, "rows": max(1, min(rows, 15)),
        "select": "DOI,title,author,issued,container-title,abstract,type",
    }
    try:
        r = requests.get(CROSSREF_SEARCH, headers=_HEADERS, params=params, timeout=_TIMEOUT)
        if r.status_code != 200:
            return []
        items = ((r.json() or {}).get("message") or {}).get("items") or []
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for it in items:
        title = (it.get("title") or [""])[0] if it.get("title") else ""
        if not title:
            continue
        dp = (it.get("issued") or {}).get("date-parts") or []
        out.append({
            "title": title, "doi": (it.get("DOI") or "").lower(),
            "year": (dp[0][0] if dp and dp[0] else None), "authors": _authors(it),
            "container": (it.get("container-title") or [""])[0] if it.get("container-title") else "",
            "type": it.get("type") or "", "abstract_present": bool(it.get("abstract")),
        })
    return out


# ── Unpaywall open-access PDF ─────────────────────────────────────────────────

def fetch_unpaywall_pdf(doi: str) -> Optional[bytes]:
    """Resolve a DOI to an open-access PDF via Unpaywall and download it."""
    doi = (doi or "").strip().lower()
    if not doi:
        return None
    try:
        r = requests.get(f"https://api.unpaywall.org/v2/{doi}",
                         params={"email": _MAILTO}, timeout=_TIMEOUT)
        if r.status_code != 200:
            return None
        data = r.json() or {}
    except Exception:
        return None
    urls: List[str] = []
    best = data.get("best_oa_location") or {}
    if best.get("url_for_pdf"):
        urls.append(best["url_for_pdf"])
    for loc in (data.get("oa_locations") or []):
        if loc.get("url_for_pdf"):
            urls.append(loc["url_for_pdf"])
    for u in urls:
        try:
            pr = requests.get(u, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            if pr.status_code == 200 and "pdf" in (pr.headers.get("content-type") or "").lower():
                return pr.content
        except Exception:
            continue
    return None
