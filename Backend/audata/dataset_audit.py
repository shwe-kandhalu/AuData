"""Dataset availability detection and raw-data verification for AuData.

Pipeline:
  1. Regex-scan paper text for known repository URLs and accession numbers.
  2. If links found, use Browserbase to visit each repository page and collect
     direct download URLs for CSV / TSV / XLSX files.
  3. Download small data files (≤ 5 MB) and compute column-level summary stats
     with pandas (N, mean, SD, min, max for numeric; top-value counts for
     categorical).
  4. Return a structured result the frontend can display and feed to Claude for
     comparison against paper-reported numbers.
"""

from __future__ import annotations

import io
import re
import statistics as _stats
from typing import Any, Dict, List, Optional

import requests

from . import browserbase_fetch

# ---------------------------------------------------------------------------
# Repository URL + accession patterns
# ---------------------------------------------------------------------------

_REPO_URL_PATTERNS: List[tuple[str, str]] = [
    (r"https?://osf\.io/[a-zA-Z0-9]+(?:/[^\s\"'<>\)]*)?", "OSF"),
    (r"https?://(?:www\.)?zenodo\.org/(?:record|deposit|doi|records)/[^\s\"'<>\)]+", "Zenodo"),
    (r"https?://doi\.org/10\.5281/zenodo\.\d+", "Zenodo"),
    (r"https?://figshare\.com/[^\s\"'<>\)]+", "Figshare"),
    (r"https?://(?:datadryad|dryad)\.org/[^\s\"'<>\)]+", "Dryad"),
    # Dryad datasets cited via doi.org resolver
    (r"https?://doi\.org/10\.5061/dryad\.[a-zA-Z0-9]+", "Dryad"),
    (r"https?://dataverse\.harvard\.edu/[^\s\"'<>\)]+", "Harvard Dataverse"),
    (r"https?://data\.mendeley\.com/[^\s\"'<>\)]+", "Mendeley Data"),
    (r"https?://(?:www\.)?github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[^\s\"'<>\)]*)?", "GitHub"),
    (r"https?://(?:www\.)?kaggle\.com/datasets/[^\s\"'<>\)]+", "Kaggle"),
    (r"https?://(?:www\.)?ncbi\.nlm\.nih\.gov/(?:geo|sra)/[^\s\"'<>\)]+", "NCBI"),
    (r"https?://(?:www\.)?ebi\.ac\.uk/[^\s\"'<>\)]+", "EBI"),
]

_ACCESSION_PATTERNS: List[tuple[str, str, str]] = [
    # (pattern, repo_name, url_template)
    # Bare Dryad DOIs (e.g. "10.5061/dryad.f7m0cfz53" or "doi:10.5061/dryad.xxx")
    (r"(?:doi:)?(10\.5061/dryad\.[a-zA-Z0-9]+)", "Dryad",
     "https://datadryad.org/dataset/doi:{acc}"),
    (r"(?:doi:)?10\.5281/zenodo\.(\d+)", "Zenodo", "https://zenodo.org/records/{acc}"),
    (r"\bGSE\d{4,}\b", "GEO", "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={acc}"),
    (r"\bPRJNA\d{4,}\b", "SRA/BioProject", "https://www.ncbi.nlm.nih.gov/sra/?term={acc}"),
    (r"\bPRJEB\d{4,}\b", "ENA", "https://www.ebi.ac.uk/ena/browser/view/{acc}"),
    (r"\bEGA[NS]\d{11}\b", "EGA", "https://ega-archive.org/datasets/{acc}"),
]

_AVAILABILITY_RE = re.compile(
    r"data\s+availab(?:ility|le)|availability\s+of\s+data|"
    r"data\s+access\s+statement|open\s+data|data\s+sharing\s+statement|"
    r"supplementary\s+(?:data|materials?)",
    re.IGNORECASE,
)

_DOWNLOAD_EXTS = re.compile(
    r"https?://[^\s\"'<>]+" r"\.(?:csv|tsv|txt|xlsx|xls|sav|dta)(?:\?[^\s\"'<>]*)?",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Step 1 — extract links from paper text
# ---------------------------------------------------------------------------

def extract_dataset_links(text: str) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    seen: set[str] = set()

    for pattern, repo in _REPO_URL_PATTERNS:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            url = m.group(0).rstrip(".,;)")
            if url not in seen:
                seen.add(url)
                results.append({"url": url, "repository": repo, "type": "url"})

    for pattern, repo, url_tmpl in _ACCESSION_PATTERNS:
        for m in re.finditer(pattern, text):
            # Use capture group 1 if present (strips optional prefix like "doi:")
            acc = m.group(1) if m.lastindex else m.group(0)
            if acc not in seen:
                seen.add(acc)
                url = url_tmpl.format(acc=acc)
                results.append({"url": url, "repository": repo, "type": "accession", "accession": acc})

    return results


# ---------------------------------------------------------------------------
# Step 2 — visit repository page via Browserbase (with API shortcuts)
# ---------------------------------------------------------------------------

_DRYAD_DOI_RE = re.compile(
    r"10\.5061/dryad\.[a-zA-Z0-9]+",
    re.IGNORECASE,
)

_DATA_MIMES = {"text/csv", "text/tab-separated-values", "application/vnd.ms-excel",
               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
_DATA_EXTS  = {".csv", ".tsv", ".txt", ".xlsx", ".xls"}

def _fetch_dryad_via_api(url: str) -> Optional[Dict[str, Any]]:
    """Use the Dryad REST API to list files — avoids JS-rendered download buttons."""
    m = _DRYAD_DOI_RE.search(url)
    if not m:
        return None
    doi = m.group(0)
    try:
        encoded_doi = "doi%3A" + doi.replace("/", "%2F")
        base = "https://datadryad.org"

        # 1. Get dataset → follow stash:version link
        r = requests.get(f"{base}/api/v2/datasets/{encoded_doi}", timeout=20,
                         headers={"Accept": "application/json"})
        if r.status_code != 200:
            return None
        version_href = ((r.json().get("_links") or {}).get("stash:version") or {}).get("href", "")
        if not version_href:
            return None

        # 2. Get version → follow stash:files link
        rv = requests.get(f"{base}{version_href}", timeout=20,
                          headers={"Accept": "application/json"})
        if rv.status_code != 200:
            return None
        files_href = ((rv.json().get("_links") or {}).get("stash:files") or {}).get("href", "")
        if not files_href:
            return None

        # 3. List files, collect download URLs for data files only
        rf = requests.get(f"{base}{files_href}", timeout=20,
                          headers={"Accept": "application/json"})
        if rf.status_code != 200:
            return None
        files_list = (rf.json().get("_embedded") or {}).get("stash:files") or []

        # Dryad file downloads via /downloads/file_stream/{id} are blocked by Cloudflare.
        # The API endpoint /api/v2/files/{id}/download requires bearer auth.
        # Neither is directly downloadable without a browser session.
        # Report file metadata but mark downloads as unavailable.
        file_info = []
        for f in files_list:
            path = f.get("path", "")
            mime = f.get("mimeType", "")
            ext  = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
            if mime in _DATA_MIMES or ext in _DATA_EXTS:
                file_info.append(path)

        dataset_page = f"{base}/dataset/doi:{doi}"
        return {
            "ok": True,
            "final_url": dataset_page,
            "page_url": dataset_page,
            "page_summary": (
                f"Dryad dataset: {len(files_list)} file(s) found via API. "
                f"Data files: {', '.join(file_info) or 'none'}. "
                "Note: Dryad file downloads require authentication — direct download unavailable."
            ),
            "download_urls": [],  # Dryad blocks direct download; files listed in page_summary
            "dryad_files": file_info,
        }
    except Exception:
        return None


_ZENODO_ID_RE = re.compile(r"zenodo\.org/(?:record|records|doi)/(?:10\.\d+/zenodo\.)?(\d+)", re.I)

def _fetch_zenodo_via_api(url: str) -> Optional[Dict[str, Any]]:
    """Use the Zenodo REST API to get direct file download URLs."""
    m = _ZENODO_ID_RE.search(url)
    if not m:
        # Try DOI form: 10.5281/zenodo.12345
        doi_m = re.search(r"10\.5281/zenodo\.(\d+)", url)
        if doi_m:
            record_id = doi_m.group(1)
        else:
            return None
    else:
        record_id = m.group(1)
    try:
        r = requests.get(f"https://zenodo.org/api/records/{record_id}", timeout=20,
                         headers={"Accept": "application/json"})
        if r.status_code != 200:
            return None
        data = r.json()
        files = data.get("files") or []
        download_urls = []
        for f in files:
            fname = f.get("key", "")
            ext = "." + fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
            links = f.get("links") or {}
            dl = links.get("self", "") or links.get("download", "")
            if (ext in _DATA_EXTS) and dl:
                download_urls.append(dl)
        record_url = f"https://zenodo.org/records/{record_id}"
        return {
            "ok": True,
            "final_url": record_url,
            "page_url": record_url,
            "page_summary": f"Zenodo record {record_id}: {len(files)} file(s), {len(download_urls)} data file(s).",
            "download_urls": download_urls[:5],
        }
    except Exception:
        return None


def fetch_repository_page(url: str) -> Dict[str, Any]:
    # Dryad: REST API shortcut (but downloads are auth-gated)
    if "dryad" in url.lower() or "10.5061" in url:
        result = _fetch_dryad_via_api(url)
        if result:
            return result

    # Zenodo: REST API gives direct download URLs
    if "zenodo" in url.lower() or "10.5281/zenodo" in url:
        result = _fetch_zenodo_via_api(url)
        if result:
            return result

    # Generic: try Browserbase if available, otherwise regex-scan for download links
    if browserbase_fetch.available():
        bb = browserbase_fetch.fetch_url(url, timeout_ms=35000)
        if bb.get("status") == "ok":
            page_text = bb.get("text", "")
            final_url = bb.get("final_url", url)
            download_urls: List[str] = []
            for m in _DOWNLOAD_EXTS.finditer(page_text):
                u = m.group(0).rstrip(".,;)")
                if u not in download_urls:
                    download_urls.append(u)
            return {"ok": True, "final_url": final_url, "page_summary": page_text[:2000],
                    "download_urls": download_urls[:10]}

    return {"ok": False, "reason": "Repository page fetch unavailable (no Browserbase).", "download_urls": []}


# ---------------------------------------------------------------------------
# Step 3 — download and summarize a data file
# ---------------------------------------------------------------------------

_MAX_BYTES = 5_000_000  # 5 MB


def _col_stats(values: list) -> Dict[str, Any]:
    nums = []
    for v in values:
        try:
            if v is not None and str(v).strip():
                nums.append(float(str(v).strip()))
        except (ValueError, TypeError):
            pass

    if len(nums) >= max(2, len(values) * 0.5):
        mean = sum(nums) / len(nums)
        return {
            "type": "numeric",
            "n": len(nums),
            "mean": round(mean, 4),
            "sd": round(_stats.stdev(nums), 4) if len(nums) > 1 else 0.0,
            "min": round(min(nums), 4),
            "max": round(max(nums), 4),
        }

    str_vals = [str(v).strip() if v is not None else "" for v in values]
    counts: Dict[str, int] = {}
    for v in str_vals:
        counts[v] = counts.get(v, 0) + 1
    top = sorted(counts.items(), key=lambda x: -x[1])[:10]
    return {"type": "categorical", "n_unique": len(counts), "top_values": top}


def _summarize_csv(data: bytes, delimiter: str = ",") -> Dict[str, Any]:
    import csv as _csv

    try:
        text = data.decode("utf-8", errors="replace")
        reader = _csv.DictReader(io.StringIO(text), delimiter=delimiter)
        rows = list(reader)
        if not rows:
            return {"ok": False, "reason": "Empty file"}
        columns = list(rows[0].keys())[:60]
        col_stats = {col: _col_stats([r.get(col) for r in rows]) for col in columns}
        return {"ok": True, "format": "csv", "rows": len(rows), "columns": columns, "stats": col_stats}
    except Exception as e:
        return {"ok": False, "reason": str(e)}


def _summarize_excel(data: bytes) -> Dict[str, Any]:
    try:
        import openpyxl  # type: ignore
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        sheet = wb.active
        all_rows = list(sheet.iter_rows(values_only=True))
        if len(all_rows) < 2:
            return {"ok": False, "reason": "Empty or header-only sheet"}
        headers = [str(h) if h is not None else f"col_{i}" for i, h in enumerate(all_rows[0])][:60]
        data_rows = all_rows[1:]
        col_stats = {
            col: _col_stats([r[i] if i < len(r) else None for r in data_rows])
            for i, col in enumerate(headers)
        }
        return {"ok": True, "format": "xlsx", "rows": len(data_rows), "columns": headers, "stats": col_stats}
    except Exception as e:
        return {"ok": False, "reason": str(e)}


def download_and_summarize(file_url: str, page_url: str = "") -> Dict[str, Any]:
    try:
        r = requests.get(
            file_url, timeout=30,
            headers={"User-Agent": "Mozilla/5.0 (compatible; AuData/1.0)"},
            stream=True,
        )
        if r.status_code != 200:
            return {"ok": False, "reason": f"HTTP {r.status_code}"}
        ct = (r.headers.get("content-type") or "").lower()
        if "text/html" in ct:
            return {"ok": False, "reason": "Server returned HTML (access restricted or bot-blocked)"}
        chunks: List[bytes] = []
        total = 0
        for chunk in r.iter_content(chunk_size=65536):
            chunks.append(chunk)
            total += len(chunk)
            if total > _MAX_BYTES:
                return {"ok": False, "reason": "File exceeds 5 MB limit"}
        raw = b"".join(chunks)
    except Exception as e:
        return {"ok": False, "reason": str(e)}

    fname = file_url.split("?")[0].split("/")[-1].lower()
    if fname.endswith(".xlsx") or fname.endswith(".xls") or "spreadsheet" in ct:
        return _summarize_excel(raw)
    elif fname.endswith(".tsv") or "\t" in raw[:500].decode("utf-8", errors="replace"):
        return _summarize_csv(raw, "\t")
    else:
        return _summarize_csv(raw, ",")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def audit_dataset(full_text: str) -> Dict[str, Any]:
    has_availability = bool(_AVAILABILITY_RE.search(full_text))
    links = extract_dataset_links(full_text)

    if not links:
        return {
            "has_dataset": False,
            "has_availability_statement": has_availability,
            "flag": "no_public_dataset",
            "message": (
                "No public dataset repository link or accession number found in the paper text. "
                "The paper does not appear to have shared raw data publicly."
                if not has_availability
                else "A data availability statement was found but no repository URL or accession number could be extracted."
            ),
            "links": [],
            "datasets": [],
        }

    if not browserbase_fetch.available():
        return {
            "has_dataset": True,
            "has_availability_statement": has_availability,
            "flag": "browserbase_unavailable",
            "message": "Dataset links found but Browserbase is not configured — cannot fetch the repository page.",
            "links": links,
            "datasets": [],
        }

    # Deduplicate: if multiple links resolve to the same repository page, process each page once
    seen_pages: set[str] = set()
    datasets = []
    for link in links[:3]:
        url = link.get("url", "")
        if not url:
            continue
        # Dedup: collapse multiple links pointing to the same dataset record
        dedup_key = url
        dryad_m = _DRYAD_DOI_RE.search(url)
        zenodo_m = re.search(r"(?:zenodo[./]|/records?/)(\d{5,})", url)  # matches zenodo.6834569 or /records/6834569
        if dryad_m:
            dedup_key = dryad_m.group(0).lower()
        elif zenodo_m:
            dedup_key = f"zenodo.{zenodo_m.group(1)}"
        if dedup_key in seen_pages:
            continue
        seen_pages.add(dedup_key)
        page = fetch_repository_page(url)
        page_url = page.get("page_url") or page.get("final_url") or url
        files = []
        for dl_url in (page.get("download_urls") or [])[:3]:
            summary = download_and_summarize(dl_url, page_url=page_url)
            if summary.get("ok"):
                files.append({"url": dl_url, **summary})
        datasets.append({
            "link": link,
            "page_ok": page.get("ok", False),
            "final_url": page.get("final_url", url),
            "page_summary": page.get("page_summary", ""),
            "download_urls": page.get("download_urls", []),
            "files": files,
        })

    any_files = any(d["files"] for d in datasets)
    return {
        "has_dataset": True,
        "has_availability_statement": has_availability,
        "flag": None if any_files else "no_data_files_found",
        "message": (
            None if any_files
            else "Dataset repository found but no downloadable data files (CSV/TSV/XLSX) were detected on the page."
        ),
        "links": links,
        "datasets": datasets,
    }
