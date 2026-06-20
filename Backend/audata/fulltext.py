"""Open-access full-text ladder (AuData, self-contained).

Direct API access to open-access sources for clean, structured full text —
ported from Evidence Engine's fetch ladder and decoupled from its app:

  1. Europe PMC JATS fullTextXML  (best — structured body text)
  2. PMC PDF                       (parsed)
  3. Unpaywall OA PDF             (any OA source)
  4. arXiv PDF                    (preprints)

Tried BEFORE Browserbase so OA papers yield real article text instead of a
publisher landing page's cookie banner + nav chrome.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

import requests
from bs4 import BeautifulSoup

from . import settings, ingest

_HEADERS = {"User-Agent": f"AuData/0.1 (mailto:{settings.ENTREZ_EMAIL})"}
_EPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_EPMC_REST = "https://www.ebi.ac.uk/europepmc/webservices/rest"

_ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/([\w./-]+?)(?:v\d+)?(?:\.pdf)?(?:[/?#]|$)", re.I)


def _extract_pdf(pdf_bytes: bytes) -> str:
    text = ingest.extract_text_from_pdf(pdf_bytes) if pdf_bytes else ""
    return text if text and len(text) > 200 else ""


def extract_arxiv_id(url: str) -> Optional[str]:
    m = _ARXIV_RE.search(url or "")
    return m.group(1) if m else None


def lookup_ids(doi: str = "", pmid: str = "") -> Dict[str, Optional[str]]:
    """Resolve a DOI or PMID to Europe PMC ids (pmcid / pmid / id / source)."""
    q = None
    if pmid and str(pmid).strip().isdigit():
        q = f"EXT_ID:{pmid} AND SRC:MED"
    elif doi:
        q = f'DOI:"{doi}"'
    if not q:
        return {}
    try:
        r = requests.get(_EPMC_SEARCH, headers=_HEADERS, timeout=15, params={
            "query": q, "format": "json", "resultType": "lite", "pageSize": 1,
        })
        if r.status_code != 200:
            return {}
        items = (r.json().get("resultList") or {}).get("result") or []
        if not items:
            return {}
        it = items[0] or {}
        return {"pmcid": it.get("pmcid"), "pmid": it.get("pmid"),
                "id": it.get("id"), "source": it.get("source"), "doi": it.get("doi")}
    except Exception as e:
        print(f"[fulltext.lookup_ids] {e}")
        return {}


def _epmc_xml_text(cid: str) -> str:
    if not cid:
        return ""
    try:
        r = requests.get(f"{_EPMC_REST}/{cid}/fullTextXML", headers=_HEADERS, timeout=20)
        if r.status_code != 200 or not r.content:
            return ""
        soup = BeautifulSoup(r.content, "lxml-xml")
        body = soup.find("body") or soup
        text = body.get_text(separator="\n", strip=True)
        return text if text and len(text) > 200 else ""
    except Exception as e:
        print(f"[fulltext._epmc_xml_text] {cid}: {e}")
        return ""


def _fetch_pmc_pdf(pmcid: str) -> Optional[bytes]:
    if not pmcid:
        return None
    pmcid = pmcid.upper()
    if not pmcid.startswith("PMC"):
        pmcid = f"PMC{pmcid}"
    for url in (f"https://europepmc.org/articles/{pmcid}/pdf",
                f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/"):
        try:
            r = requests.get(url, headers=_HEADERS, timeout=30, allow_redirects=True)
            ct = (r.headers.get("content-type") or "").lower()
            if r.status_code == 200 and ("pdf" in ct or r.content[:4] == b"%PDF"):
                return r.content
        except Exception as e:
            print(f"[fulltext._fetch_pmc_pdf] {url}: {e}")
    return None


def _fetch_arxiv_pdf(arxiv_id: str) -> Optional[bytes]:
    if not arxiv_id:
        return None
    try:
        r = requests.get(f"https://arxiv.org/pdf/{arxiv_id}.pdf", headers=_HEADERS,
                         timeout=30, allow_redirects=True)
        ct = (r.headers.get("content-type") or "").lower()
        if r.status_code == 200 and ("pdf" in ct or r.content[:4] == b"%PDF"):
            return r.content
    except Exception as e:
        print(f"[fulltext._fetch_arxiv_pdf] {e}")
    return None


def fetch_full_text(doi: str = "", url: str = "", title: str = "", source: str = "",
                    pmid: str = "") -> Tuple[str, str]:
    """Try the open-access ladder. Returns (text, source_label) or ("", "")."""
    ids = lookup_ids(doi=doi, pmid=pmid)
    pmcid = ids.get("pmcid")
    epmc_id, epmc_src = ids.get("id"), ids.get("source")

    # Tier 1 — Europe PMC structured XML.
    candidates = [pmcid]
    if epmc_src and epmc_id:
        candidates.append(f"{epmc_src}/{epmc_id}")
    for cid in [c for c in candidates if c]:
        text = _epmc_xml_text(cid)
        if text:
            return text, "Europe PMC (XML)"

    # Tier 2 — PMC PDF.
    if pmcid:
        t = _extract_pdf(_fetch_pmc_pdf(pmcid) or b"")
        if t:
            return t, f"PMC PDF ({pmcid})"

    # Tier 3 — Unpaywall OA PDF by DOI.
    if doi:
        t = _extract_pdf(ingest.fetch_unpaywall_pdf(doi) or b"")
        if t:
            return t, "Unpaywall PDF"

    # Tier 4 — arXiv PDF.
    aid = extract_arxiv_id(url)
    if aid or (source or "").lower() == "arxiv" or "arxiv.org" in (url or "").lower():
        t = _extract_pdf(_fetch_arxiv_pdf(aid) or b"") if aid else ""
        if t:
            return t, f"arXiv PDF ({aid})"

    return "", ""
