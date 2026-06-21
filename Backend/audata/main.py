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

import json as _json
import queue
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

import requests
from fastapi import FastAPI, HTTPException, UploadFile, File, Header, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import settings, ingest, browserbase_fetch, storage, fulltext, llm, dataset_audit
from . import reference_integrity as refint
from . import methods_claims as mc

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
    use_open_access: bool = True   # Europe PMC / PMC / Unpaywall / arXiv ladder
    use_browserbase: bool = True   # headless-browser fallback for any URL
    session_id: Optional[str] = ""


class IngestUrlRequest(BaseModel):
    url: str
    session_id: Optional[str] = ""


def _pdf_for_viewer(doi: str, pmcid: str = "", arxiv: str = "") -> Optional[bytes]:
    """Best-effort free PDF (Unpaywall → PMC → arXiv) so the UI can show a PDF
    tab even when the full text came from structured XML."""
    try:
        if doi:
            b = ingest.fetch_unpaywall_pdf(doi)
            if b:
                return b
        if pmcid:
            b = fulltext.fetch_pmc_pdf_bytes(pmcid)
            if b:
                return b
        if arxiv:
            b = fulltext.fetch_arxiv_pdf_bytes(arxiv)
            if b:
                return b
    except Exception as e:
        print(f"[audata _pdf_for_viewer] {e}")
    return None


def _persist(paper: Dict[str, Any], session_id: Optional[str], pdf_bytes: Optional[bytes] = None) -> Dict[str, Any]:
    """Long-term to SQLite, short-term to Redis (if a session id was given)."""
    if pdf_bytes:
        try:
            storage.save_pdf(paper["id"], pdf_bytes)
            paper["has_pdf"] = True
        except Exception as e:
            print(f"[audata] save_pdf failed: {e}")
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
    """Returns (text, source_label, bb_info, pdf_bytes|None)."""
    bb = browserbase_fetch.fetch_url(url)
    if bb.get("status") != "ok":
        return "", "", bb, None
    pdf_url = bb.get("pdf_url") or ""
    if pdf_url:
        try:
            r = requests.get(pdf_url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200 and "pdf" in (r.headers.get("content-type") or "").lower():
                text = ingest.extract_text_from_pdf(r.content)
                if text and len(text) > 400:
                    return text, "Browserbase → PDF", bb, r.content
        except Exception as e:
            print(f"[audata browserbase pdf] {e}")
    txt = (bb.get("text") or "").strip()
    if len(txt) > 400:
        return txt, "Browserbase (page text)", bb, None
    return "", "", bb, None


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
    if req.use_open_access and (doi or url):
        try:
            full_text, ft_source = fulltext.fetch_full_text(
                doi=doi, url=url, title=(meta.get("title") if meta.get("resolved") else "") or title)
        except Exception as e:
            print(f"[audata fulltext ladder] {e}")
    # Tier B — Browserbase fallback for anything the OA ladder can't reach.
    bb_info: Dict[str, Any] = {}
    pdf_bytes: Optional[bytes] = None
    if not full_text and req.use_browserbase and url and browserbase_fetch.available():
        full_text, ft_source, bb_info, pdf_bytes = _full_text_via_browserbase(url)

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
    if pdf_bytes is None and doi:
        pdf_bytes = _pdf_for_viewer(doi)
    _persist(paper, req.session_id, pdf_bytes)
    return {"paper": paper, "resolved": bool(meta.get("resolved")),
            "browserbase": {k: bb_info.get(k) for k in ("status", "session_id", "final_url") if k in bb_info}}


@app.post("/api/ingest/url")
def ingest_url(req: IngestUrlRequest):
    url = (req.url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="A URL is required.")

    # Tier A — if the URL carries an OA identifier (PMC / DOI / arXiv / PMID),
    # use the open-access API ladder. This avoids NCBI/publisher bot-walls
    # (e.g. PMC serves a reCAPTCHA to headless browsers).
    ids = fulltext.ids_from_url(url)
    look = fulltext.lookup_ids(doi=ids["doi"], pmid=ids["pmid"], pmcid=ids["pmcid"]) if (ids["doi"] or ids["pmid"] or ids["pmcid"]) else {}
    doi = ids["doi"] or (look.get("doi") or "")
    pmcid = ids["pmcid"] or (look.get("pmcid") or "")
    full_text, ft_source, pdf_bytes = "", "", None
    bb_info: Dict[str, Any] = {}

    if doi or pmcid or ids["arxiv"]:
        full_text, ft_source = fulltext.fetch_full_text(
            doi=doi, pmcid=pmcid, pmid=(look.get("pmid") or ids["pmid"] or ""), url=url, source="arxiv" if ids["arxiv"] else "")
        if pmcid:
            pdf_bytes = fulltext.fetch_pmc_pdf_bytes(pmcid)  # for the in-app PDF viewer

    # Tier B — Browserbase. For NCBI/PMC origins (which serve a reCAPTCHA to
    # headless browsers) point it at the Europe PMC article page instead, which
    # renders the full text and isn't bot-walled.
    if not full_text and browserbase_fetch.available():
        browse_url = url
        host = (url.split("/", 3)[2].lower() if "://" in url else "")
        if pmcid and ("ncbi.nlm.nih.gov" in host or "pubmed" in host):
            browse_url = f"https://europepmc.org/articles/{pmcid}"
        elif (look.get("pmid") or ids["pmid"]) and ("ncbi.nlm.nih.gov" in host or "pubmed" in host):
            browse_url = f"https://europepmc.org/article/MED/{look.get('pmid') or ids['pmid']}"
        bt, bs, bb_info, bpdf = _full_text_via_browserbase(browse_url)
        low = (bt or "")[:300].lower()
        if bt and "recaptcha" not in low and "checking your browser" not in low:
            full_text, ft_source, pdf_bytes = bt, bs, (pdf_bytes or bpdf)
        doi = doi or ingest.detect_doi((bt or "")[:4000]) or ingest.detect_doi(bb_info.get("final_url", ""))
    elif not full_text and not (doi or pmcid):
        raise HTTPException(status_code=400, detail="Browserbase is not configured, and no open-access source was found for this URL.")

    meta = ingest.resolve_doi(doi) if doi else {"resolved": False}
    if not meta.get("resolved") and ids["arxiv"]:
        am = fulltext.fetch_arxiv_meta(ids["arxiv"])
        if am.get("title"):
            meta = {"resolved": True, "title": am["title"], "authors": am.get("authors", ""),
                    "year": am.get("year"), "container": "arXiv", "abstract": am.get("abstract", ""),
                    "url": am.get("url", ""), "retracted": False, "providers": ["arXiv"]}
    if not full_text and bb_info and bb_info.get("status") != "ok" and not meta.get("resolved"):
        raise HTTPException(status_code=502, detail="Could not retrieve this URL (no open-access source and the page was blocked or empty).")

    paper = ingest._build_paper(
        source="url", ident=doi or pmcid or url,
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
    if pdf_bytes is None and (doi or pmcid or ids["arxiv"]):
        pdf_bytes = _pdf_for_viewer(doi, pmcid, ids["arxiv"])
    _persist(paper, req.session_id, pdf_bytes)
    return {"paper": paper, "full_text_source": ft_source,
            "browserbase": {k: bb_info.get(k) for k in ("status", "session_id", "final_url") if k in bb_info}}


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
    _persist(paper, x_session_id, data)  # keep the uploaded PDF for the viewer
    return {"paper": paper}


@app.get("/api/ingest/pdf-file")
def ingest_pdf_file(id: str):
    """Serve a stored PDF same-origin so the browser can render it inline."""
    data = storage.get_pdf(id)
    if not data:
        raise HTTPException(status_code=404, detail="No PDF stored for this paper.")
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="paper.pdf"'})


# ── dataset audit ────────────────────────────────────────────────────────────

class DatasetAuditRequest(BaseModel):
    full_text: str
    doi: Optional[str] = ""
    title: Optional[str] = ""


@app.post("/api/audit/dataset")
def audit_dataset_endpoint(req: DatasetAuditRequest):
    if not req.full_text.strip():
        raise HTTPException(status_code=400, detail="full_text is required.")
    return dataset_audit.audit_dataset(req.full_text)


# ── storage access ────────────────────────────────────────────────────────────

@app.get("/api/session/{session_id}/paper")
def session_paper(session_id: str):
    return {"paper": storage.session_get(session_id, "paper_under_audit")}


class SessionDataRequest(BaseModel):
    value: Any = None


@app.put("/api/session/{session_id}/data/{key}")
def session_data_set(session_id: str, key: str, req: SessionDataRequest):
    """Stash arbitrary per-session data in Redis (short-term, with TTL)."""
    storage.session_set(session_id, key, req.value)
    return {"ok": True}


@app.get("/api/session/{session_id}/data/{key}")
def session_data_get(session_id: str, key: str):
    return {"value": storage.session_get(session_id, key)}


_AUDIT_LIGHT_FIELDS = ("id", "title", "authors", "year", "source", "container", "url",
                       "doi", "has_pdf", "has_full_text", "char_count", "retracted",
                       "references_detected", "tables_detected", "figures_detected")


@app.get("/api/audits")
def list_audits(limit: int = 100):
    """Lightweight list of ingested papers (no full text) for the Audits view."""
    out = []
    for p in storage.list_papers(limit):
        out.append({k: p.get(k) for k in _AUDIT_LIGHT_FIELDS})
    return {"papers": out}


@app.get("/api/paper")
def get_one_paper(id: str):
    """Full paper record (with full text) — used to reopen an audit."""
    p = storage.get_paper(id)
    if not p:
        raise HTTPException(status_code=404, detail="Paper not found.")
    return {"paper": p}


# ── sessions (SQLite, keyed by a per-browser owner id; no auth needed) ─────────

class SessionSaveRequest(BaseModel):
    title: Optional[str] = "Untitled session"
    owner: Optional[str] = ""
    data: Any = None


@app.get("/api/sessions")
def sessions_list(owner: str = ""):
    return {"sessions": storage.list_sessions(owner)}


@app.get("/api/sessions/{session_id}")
def session_load(session_id: str):
    sess = storage.get_session(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found.")
    return {"session": sess}


@app.put("/api/sessions/{session_id}")
def session_save(session_id: str, req: SessionSaveRequest):
    meta = storage.save_session(session_id, req.owner or "", req.title or "Untitled session", req.data)
    return {"session": meta}


@app.delete("/api/sessions/{session_id}")
def session_delete(session_id: str):
    storage.delete_session(session_id)
    return {"ok": True}


class RenameRequest(BaseModel):
    title: str


@app.patch("/api/sessions/{session_id}/title")
def session_rename(session_id: str, req: RenameRequest):
    ok = storage.rename_session(session_id, req.title)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found.")
    return {"ok": True}


# ── per-paper detection audits (Redis + SQLite, keyed by paper id) ─────────────

class PaperAuditSave(BaseModel):
    paper_id: str
    stage: str
    data: Any = None


@app.put("/api/paper-audit")
def paper_audit_save(req: PaperAuditSave):
    storage.save_paper_audit(req.paper_id, req.stage, req.data)
    return {"ok": True}


@app.get("/api/paper-audits")
def paper_audits_get(paper_id: str):
    return {"audits": storage.get_paper_audits(paper_id)}


# ── Reference Integrity (Detect) ──────────────────────────────────────────────

class RefItem(BaseModel):
    doi: Optional[str] = ""
    raw: Optional[str] = ""
    claim: Optional[str] = ""


class ReferenceIntegrityRequest(BaseModel):
    references: List[RefItem]
    model: Optional[str] = None
    check_claims: bool = True


def _ri_model(req: "ReferenceIntegrityRequest"):
    return llm.get_model_for(llm.TASK_REASONING, req.model or "") if req.check_claims else None


def _ri_check_all(refs: List["RefItem"], model, check_claims: bool) -> List[Dict[str, Any]]:
    results: List[Optional[Dict[str, Any]]] = [None] * len(refs)
    workers = min(8, max(1, len(refs)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(refint.check_reference, i, r.doi or "", r.raw or "", r.claim or "", model, check_claims): i
                for i, r in enumerate(refs)}
        for fut in as_completed(futs):
            i = futs[fut]
            try:
                results[i] = fut.result()
            except Exception as e:
                results[i] = {"index": i, "input": {"doi": refs[i].doi or "", "raw": refs[i].raw or "", "claim": refs[i].claim or ""},
                              "resolved": False, "matched": {}, "retracted": False,
                              "claim": {"verdict": "error", "confidence": 0.0, "reasoning": str(e), "quote": ""},
                              "issues": [{"code": "error", "label": f"Check failed: {e}", "severity": "medium"}],
                              "severity": "medium", "status": "flagged"}
    return [r for r in results if r is not None]


@app.post("/api/reference-integrity/check")
def reference_integrity_check(req: ReferenceIntegrityRequest):
    model = _ri_model(req)
    results = _ri_check_all(req.references or [], model, req.check_claims)
    return {"results": results, "summary": refint.summarize(results)}


@app.post("/api/reference-integrity/check/stream")
def reference_integrity_stream(req: ReferenceIntegrityRequest):
    refs = req.references or []
    model = _ri_model(req)
    event_queue: "queue.Queue[tuple]" = queue.Queue()

    def _run():
        results: List[Dict[str, Any]] = []
        try:
            workers = min(8, max(1, len(refs)))
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = {ex.submit(refint.check_reference, i, r.doi or "", r.raw or "", r.claim or "", model, req.check_claims): i
                        for i, r in enumerate(refs)}
                for fut in as_completed(futs):
                    i = futs[fut]
                    try:
                        res = fut.result()
                    except Exception as e:
                        res = {"index": i, "input": {"doi": refs[i].doi or "", "raw": refs[i].raw or "", "claim": refs[i].claim or ""},
                               "resolved": False, "matched": {}, "retracted": False,
                               "claim": {"verdict": "error", "confidence": 0.0, "reasoning": str(e), "quote": ""},
                               "issues": [{"code": "error", "label": f"Check failed: {e}", "severity": "medium"}],
                               "severity": "medium", "status": "flagged"}
                    results.append(res)
                    event_queue.put(("result", res))
            event_queue.put(("done", {"summary": refint.summarize(results)}))
        except Exception as e:
            event_queue.put(("error", {"message": str(e)}))

    threading.Thread(target=_run, daemon=True).start()

    def _gen():
        while True:
            try:
                event_type, data = event_queue.get(timeout=600)
            except queue.Empty:
                yield f"event: error\ndata: {_json.dumps({'message': 'timeout'})}\n\n"
                return
            yield f"event: {event_type}\ndata: {_json.dumps(data)}\n\n"
            if event_type in ("done", "error"):
                return

    return StreamingResponse(_gen(), media_type="text/event-stream")


class MethodsClaimsRequest(BaseModel):
    paper_id: str
    model: Optional[str] = None


@app.post("/api/methods-claims/check-paper/stream")
def methods_claims_stream(req: MethodsClaimsRequest):
    """Extract the paper's claims, then assess each against its methods/results."""
    paper = storage.get_paper(req.paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found. Ingest it first.")
    # Extraction → local model (cheap); assessment → reasoning model (Claude).
    assess_model = llm.get_model_for(llm.TASK_REASONING, req.model or "")
    extract_model = llm.get_model_for(llm.TASK_EXTRACTION) or assess_model
    event_queue: "queue.Queue[tuple]" = queue.Queue()

    def _run():
        results: List[Dict[str, Any]] = []
        try:
            if assess_model is None:
                event_queue.put(("error", {"message": "No reasoning model is configured. Set a model key (e.g. ANTHROPIC_API_KEY) in Backend/.env."}))
                return
            claims = mc.extract_claims(paper, extract_model)
            if not claims and extract_model is not assess_model:
                claims = mc.extract_claims(paper, assess_model)  # fall back to the reasoning model
            if not claims:
                event_queue.put(("done", {"summary": mc.summarize([]), "note": "No claims could be extracted from this paper."}))
                return
            evidence = mc._evidence_context(paper)
            with ThreadPoolExecutor(max_workers=min(10, len(claims))) as ex:
                futs = {ex.submit(mc.check_claim, i, c["claim"], c.get("quote", ""), evidence, assess_model): i
                        for i, c in enumerate(claims)}
                for fut in as_completed(futs):
                    i = futs[fut]
                    try:
                        res = fut.result()
                    except Exception as e:
                        res = {"index": i, "claim": claims[i]["claim"], "quote": claims[i].get("quote", ""),
                               "verdict": "error", "severity": "medium", "issue_type": "Check failed",
                               "confidence": 0.0, "reasoning": str(e), "evidence": "", "suggestion": "", "status": "flagged"}
                    results.append(res)
                    event_queue.put(("result", res))
            event_queue.put(("done", {"summary": mc.summarize(results)}))
        except Exception as e:
            event_queue.put(("error", {"message": str(e)}))

    threading.Thread(target=_run, daemon=True).start()

    def _gen():
        while True:
            try:
                event_type, data = event_queue.get(timeout=600)
            except queue.Empty:
                yield f"event: error\ndata: {_json.dumps({'message': 'timeout'})}\n\n"
                return
            yield f"event: {event_type}\ndata: {_json.dumps(data)}\n\n"
            if event_type in ("done", "error"):
                return

    return StreamingResponse(_gen(), media_type="text/event-stream")


@app.get("/api/reference-integrity/from-paper")
def reference_integrity_from_paper(paper_id: str):
    """Extract candidate references (DOIs / citations) from a stored paper."""
    paper = storage.get_paper(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found. Ingest it first.")
    refs = refint.extract_references_from_text(paper.get("full_text", ""))
    return {"references": refs, "count": len(refs)}


class CheckPaperRequest(BaseModel):
    paper_id: str
    model: Optional[str] = None
    check_claims: bool = True


@app.post("/api/reference-integrity/check-paper/stream")
def reference_integrity_check_paper_stream(req: CheckPaperRequest):
    """Full reference-integrity audit of a stored paper, streamed.

    Extracts the bibliography, links each reference to the in-text sentence that
    cites it, and runs the whole battery (existence, retraction, mismatch, claim
    support, future-dated, self-citation, uncited, duplicate). Ends with summary
    + paper-level metrics.
    """
    paper = storage.get_paper(req.paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found. Ingest it first.")
    prepared = refint.prepare_paper_references(paper)
    model = llm.get_model_for(llm.TASK_REASONING, req.model or "") if req.check_claims else None
    event_queue: "queue.Queue[tuple]" = queue.Queue()

    def _run():
        results: List[Dict[str, Any]] = []
        try:
            if not prepared:
                event_queue.put(("done", {"summary": refint.summarize([]), "metrics": refint.paper_metrics([]),
                                          "note": "No references could be parsed from this paper's reference list."}))
                return
            workers = min(8, max(1, len(prepared)))
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = {ex.submit(refint.check_reference, i, p["doi"], p["raw"], p["claim"],
                                  model, req.check_claims, p["ctx"], p["number"]): i
                        for i, p in enumerate(prepared)}
                for fut in as_completed(futs):
                    i = futs[fut]
                    try:
                        res = fut.result()
                    except Exception as e:
                        res = {"index": i, "number": prepared[i].get("number"),
                               "input": {"doi": prepared[i].get("doi", ""), "raw": prepared[i].get("raw", ""), "claim": prepared[i].get("claim", "")},
                               "resolved": False, "matched": {}, "retracted": False, "cited_count": None,
                               "claim": {"verdict": "error", "confidence": 0.0, "reasoning": str(e), "quote": ""},
                               "issues": [{"code": "error", "label": f"Check failed: {e}", "severity": "medium", "detail": str(e)}],
                               "severity": "medium", "status": "flagged"}
                    results.append(res)
                    event_queue.put(("result", res))
            event_queue.put(("done", {"summary": refint.summarize(results), "metrics": refint.paper_metrics(results)}))
        except Exception as e:
            event_queue.put(("error", {"message": str(e)}))

    threading.Thread(target=_run, daemon=True).start()

    def _gen():
        while True:
            try:
                event_type, data = event_queue.get(timeout=600)
            except queue.Empty:
                yield f"event: error\ndata: {_json.dumps({'message': 'timeout'})}\n\n"
                return
            yield f"event: {event_type}\ndata: {_json.dumps(data)}\n\n"
            if event_type in ("done", "error"):
                return

    return StreamingResponse(_gen(), media_type="text/event-stream")
