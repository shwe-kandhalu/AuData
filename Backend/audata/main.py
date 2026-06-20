"""AuData FastAPI service — standalone, separate from Evidence Engine's api.py.

Endpoints:
  GET  /api/health                 — service + redis + db + browserbase status
  GET  /api/models/local           — local Ollama models (for the sidebar)
  POST /api/ingest/search          — Crossref search by name/title
  POST /api/ingest/fetch           — pull by DOI/title (+ Unpaywall, then Browserbase)
  POST /api/ingest/url             — fetch any URL via Browserbase
  POST /api/ingest/pdf             — parse an uploaded PDF
  GET  /api/session/{sid}/paper    — restore the paper under audit (Redis)
  GET  /api/audits                 — list persisted papers (SQLite)
Every ingest persists to SQLite (long-term) and, when a session id is given,
caches the paper under audit in Redis (short-term).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import requests
from fastapi import FastAPI, HTTPException, UploadFile, File, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import settings, ingest, browserbase_fetch, storage, fulltext

app = FastAPI(title="AuData API", version="0.1.0")

_origins = ["http://localhost:5173", "http://localhost:4173", "http://127.0.0.1:5173"] + settings.CORS_ORIGINS
app.add_middleware(
    CORSMiddleware, allow_origins=_origins, allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)


@app.on_event("startup")
def _startup():
    storage.init_db()


# ── status ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {
        "ok": True, "service": "audata",
        "redis": storage.redis_status(),
        "db": storage.db_status(),
        "browserbase": {"configured": browserbase_fetch.available()},
    }


@app.get("/api/models/local")
def models_local():
    try:
        r = requests.get(f"{settings.OLLAMA_BASE_URL}/api/tags", timeout=3)
        models = [m.get("name") for m in (r.json().get("models") or [])] if r.status_code == 200 else []
        return {"models": models, "running": True}
    except Exception:
        return {"models": [], "running": False}


# ── ingest ────────────────────────────────────────────────────────────────────

class IngestSearchRequest(BaseModel):
    query: str
    rows: int = 6


class IngestFetchRequest(BaseModel):
    doi: Optional[str] = ""
    title: Optional[str] = ""
    url: Optional[str] = ""
    use_browserbase: bool = True
    session_id: Optional[str] = ""


class IngestUrlRequest(BaseModel):
    url: str
    session_id: Optional[str] = ""


def _persist(paper: Dict[str, Any], session_id: Optional[str]) -> Dict[str, Any]:
    """Long-term to SQLite, short-term to Redis (if a session id was given)."""
    try:
        storage.save_paper(paper)
    except Exception as e:
        print(f"[audata] save_paper failed: {e}")
    if session_id:
        try:
            storage.session_set(session_id, "paper_under_audit", paper)
        except Exception as e:
            print(f"[audata] session_set failed: {e}")
    return paper


def _full_text_via_browserbase(url: str):
    bb = browserbase_fetch.fetch_url(url)
    if bb.get("status") != "ok":
        return "", "", bb
    pdf_url = bb.get("pdf_url") or ""
    if pdf_url:
        try:
            r = requests.get(pdf_url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200 and "pdf" in (r.headers.get("content-type") or "").lower():
                text = ingest.extract_text_from_pdf(r.content)
                if text and len(text) > 400:
                    return text, "Browserbase → PDF", bb
        except Exception as e:
            print(f"[audata browserbase pdf] {e}")
    txt = (bb.get("text") or "").strip()
    if len(txt) > 400:
        return txt, "Browserbase (page text)", bb
    return "", "", bb


@app.post("/api/ingest/search")
def ingest_search(req: IngestSearchRequest):
    return {"candidates": ingest.search_works(req.query, req.rows)}


@app.post("/api/ingest/fetch")
def ingest_fetch(req: IngestFetchRequest):
    doi = (req.doi or "").strip().lower()
    title = (req.title or "").strip()
    if not doi and not title and not req.url:
        raise HTTPException(status_code=400, detail="Provide a DOI, title, or URL.")
    if not doi and title:
        cands = ingest.search_works(title, rows=1)
        if cands:
            doi = cands[0].get("doi") or ""

    meta = ingest.resolve_doi(doi) if doi else {"resolved": False}
    url = (meta.get("url") if meta.get("resolved") else "") or (req.url or "") or (f"https://doi.org/{doi}" if doi else "")

    # Tier A — direct open-access APIs (Europe PMC XML, PMC PDF, Unpaywall, arXiv).
    full_text, ft_source = "", ""
    if doi or url:
        try:
            full_text, ft_source = fulltext.fetch_full_text(
                doi=doi, url=url, title=(meta.get("title") if meta.get("resolved") else "") or title)
        except Exception as e:
            print(f"[audata fulltext ladder] {e}")
    # Tier B — Browserbase fallback for anything the OA ladder can't reach.
    bb_info: Dict[str, Any] = {}
    if not full_text and req.use_browserbase and url and browserbase_fetch.available():
        full_text, ft_source, bb_info = _full_text_via_browserbase(url)

    paper = ingest._build_paper(
        source="doi" if doi else "url", ident=doi or url or title,
        title=(meta.get("title") if meta.get("resolved") else "") or title,
        authors=meta.get("authors", "") if meta.get("resolved") else "",
        year=meta.get("year") if meta.get("resolved") else None,
        doi=doi, container=meta.get("container", "") if meta.get("resolved") else "",
        url=url, abstract=meta.get("abstract", "") if meta.get("resolved") else "",
        full_text=full_text, full_text_source=ft_source,
        retracted=bool(meta.get("retracted")) if meta.get("resolved") else False,
        providers=meta.get("providers", []) if meta.get("resolved") else [],
    )
    _persist(paper, req.session_id)
    return {"paper": paper, "resolved": bool(meta.get("resolved")),
            "browserbase": {k: bb_info.get(k) for k in ("status", "session_id", "final_url") if k in bb_info}}


@app.post("/api/ingest/url")
def ingest_url(req: IngestUrlRequest):
    url = (req.url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="A URL is required.")
    if not browserbase_fetch.available():
        raise HTTPException(status_code=400, detail="Browserbase is not configured on the server.")
    full_text, ft_source, bb_info = _full_text_via_browserbase(url)
    if bb_info.get("status") != "ok":
        raise HTTPException(status_code=502, detail=f"Browserbase fetch failed: {bb_info.get('reason', 'unknown')}")
    doi = ingest.detect_doi(full_text[:4000]) or ingest.detect_doi(bb_info.get("final_url", ""))
    meta = ingest.resolve_doi(doi) if doi else {"resolved": False}
    # If the page yielded a DOI, the open-access ladder usually beats scraped
    # landing-page text (which is mostly cookie banner + nav). Prefer it.
    if doi:
        oa_text, oa_src = fulltext.fetch_full_text(doi=doi, url=bb_info.get("final_url", url))
        if oa_text and len(oa_text) > len(full_text):
            full_text, ft_source = oa_text, oa_src
    paper = ingest._build_paper(
        source="url", ident=doi or url,
        title=(meta.get("title") if meta.get("resolved") else "") or bb_info.get("title", "") or url,
        authors=meta.get("authors", "") if meta.get("resolved") else "",
        year=meta.get("year") if meta.get("resolved") else None,
        doi=doi, container=meta.get("container", "") if meta.get("resolved") else "",
        url=bb_info.get("final_url", url),
        abstract=meta.get("abstract", "") if meta.get("resolved") else "",
        full_text=full_text, full_text_source=ft_source,
        retracted=bool(meta.get("retracted")) if meta.get("resolved") else False,
        providers=meta.get("providers", []) if meta.get("resolved") else [],
    )
    _persist(paper, req.session_id)
    return {"paper": paper, "browserbase": {k: bb_info.get(k) for k in ("status", "session_id", "final_url")}}


@app.post("/api/ingest/pdf")
def ingest_pdf(file: UploadFile = File(...), x_session_id: Optional[str] = Header(default="")):
    data = file.file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file.")
    paper = ingest.parse_pdf_bytes(data, file.filename or "upload.pdf")
    if paper.get("doi"):
        meta = ingest.resolve_doi(paper["doi"])
        if meta.get("resolved"):
            paper["title"] = meta.get("title") or paper["title"]
            paper["authors"] = meta.get("authors") or paper["authors"]
            paper["year"] = meta.get("year") or paper["year"]
            paper["container"] = meta.get("container") or paper["container"]
            paper["abstract"] = meta.get("abstract") or paper["abstract"]
            paper["retracted"] = bool(meta.get("retracted"))
            paper["providers"] = meta.get("providers") or []
            paper["url"] = paper["url"] or meta.get("url") or ""
    _persist(paper, x_session_id)
    return {"paper": paper}


# ── storage access ────────────────────────────────────────────────────────────

@app.get("/api/session/{session_id}/paper")
def session_paper(session_id: str):
    return {"paper": storage.session_get(session_id, "paper_under_audit")}


@app.get("/api/audits")
def list_audits(limit: int = 50):
    return {"papers": storage.list_papers(limit)}
