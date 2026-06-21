"""AuData storage layer.

Two tiers, both separate from Evidence Engine's Supabase:
  • Redis  — short-term session state / cache (current paper under audit, etc.),
             with a TTL. Falls back to an in-process dict if Redis is unreachable
             so the app still runs.
  • SQLite — long-term persistence (ingested papers, sessions, and a flags table
             for the detection agents). A single file, behind small functions so
             it can be swapped for Postgres later without touching callers.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

from . import settings

# ── Redis (short-term) ────────────────────────────────────────────────────────

_redis = None
_redis_tried = False
_mem: Dict[str, Any] = {}  # fallback: key -> (json_str, expiry_ts)


def _get_redis():
    global _redis, _redis_tried
    if _redis_tried:
        return _redis
    _redis_tried = True
    if not settings.REDIS_URL:
        print("[audata.storage] REDIS_URL not set — using in-memory session store.")
        return None
    try:
        import redis
        r = redis.from_url(settings.REDIS_URL, decode_responses=True, socket_connect_timeout=5)
        r.ping()
        _redis = r
        print("[audata.storage] Redis connected.")
    except Exception as e:
        print(f"[audata.storage] Redis unavailable ({e}); using in-memory session store.")
        _redis = None
    return _redis


def cache_get(key: str) -> Any:
    """LLM response cache (Redis when available, in-memory otherwise)."""
    full = f"audata:llmcache:{key}"
    r = _get_redis()
    if r:
        try:
            return r.get(full)
        except Exception:
            pass
    tup = _mem.get(full)
    if tup:
        val, exp = tup
        if exp > time.time():
            return val
        _mem.pop(full, None)
    return None


def cache_set(key: str, value: str, ttl: int = 604800) -> None:  # 7 days
    full = f"audata:llmcache:{key}"
    r = _get_redis()
    if r:
        try:
            r.set(full, value, ex=ttl)
            return
        except Exception:
            pass
    _mem[full] = (value, time.time() + ttl)


def redis_status() -> Dict[str, Any]:
    r = _get_redis()
    if r is None:
        return {"connected": False, "backend": "in-memory", "url_set": bool(settings.REDIS_URL)}
    try:
        r.ping()
        return {"connected": True, "backend": "redis"}
    except Exception as e:
        return {"connected": False, "backend": "in-memory", "error": str(e)}


def _skey(session_id: str, key: str) -> str:
    return f"audata:sess:{session_id}:{key}"


def session_set(session_id: str, key: str, value: Any, ttl: Optional[int] = None) -> None:
    ttl = ttl or settings.SESSION_TTL_SECONDS
    full = _skey(session_id, key)
    payload = json.dumps(value)
    r = _get_redis()
    if r:
        r.set(full, payload, ex=ttl)
    else:
        _mem[full] = (payload, time.time() + ttl)


def session_get(session_id: str, key: str) -> Any:
    full = _skey(session_id, key)
    r = _get_redis()
    if r:
        v = r.get(full)
    else:
        tup = _mem.get(full)
        v = None
        if tup:
            val, exp = tup
            if exp > time.time():
                v = val
            else:
                _mem.pop(full, None)
    return json.loads(v) if v else None


# ── SQLite (long-term) ────────────────────────────────────────────────────────

_db_lock = threading.Lock()


def _conn():
    c = sqlite3.connect(settings.AUDATA_DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _db_lock, _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS papers (
            id TEXT PRIMARY KEY, doi TEXT, title TEXT, source TEXT,
            data TEXT NOT NULL, created_at REAL, updated_at REAL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY, data TEXT, updated_at REAL)""")
        # Forward-looking: detection agents will write calibrated flags here.
        c.execute("""CREATE TABLE IF NOT EXISTS flags (
            id INTEGER PRIMARY KEY AUTOINCREMENT, paper_id TEXT, agent TEXT,
            severity TEXT, data TEXT, created_at REAL)""")
        # Raw PDF bytes for the paper under audit, so the UI can render it.
        c.execute("""CREATE TABLE IF NOT EXISTS pdfs (
            paper_id TEXT PRIMARY KEY, bytes BLOB, created_at REAL)""")
        # Per-paper detection results, keyed by (paper, stage).
        c.execute("""CREATE TABLE IF NOT EXISTS paper_audits (
            paper_id TEXT, stage TEXT, data TEXT, updated_at REAL, PRIMARY KEY(paper_id, stage))""")


def save_paper(paper: Dict[str, Any]) -> str:
    pid = paper.get("id") or paper.get("doi") or paper.get("title") or "unknown"
    now = time.time()
    with _db_lock, _conn() as c:
        c.execute(
            """INSERT INTO papers (id, doi, title, source, data, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET doi=excluded.doi, title=excluded.title,
                 source=excluded.source, data=excluded.data, updated_at=excluded.updated_at""",
            (pid, paper.get("doi", ""), paper.get("title", ""), paper.get("source", ""),
             json.dumps(paper), now, now),
        )
    return pid


def list_papers(limit: int = 50) -> List[Dict[str, Any]]:
    with _db_lock, _conn() as c:
        rows = c.execute("SELECT data FROM papers ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
    return [json.loads(r["data"]) for r in rows]


def get_paper(pid: str) -> Optional[Dict[str, Any]]:
    with _db_lock, _conn() as c:
        row = c.execute("SELECT data FROM papers WHERE id=?", (pid,)).fetchone()
    return json.loads(row["data"]) if row else None


def save_session(session_id: str, owner: str, title: str, data: Any) -> Dict[str, Any]:
    now = time.time()
    blob = json.dumps({"owner": owner or "", "title": title or "Untitled session", "data": data})
    with _db_lock, _conn() as c:
        # Preserve created_at on update.
        row = c.execute("SELECT data FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        created = now
        if row:
            try:
                created = json.loads(row["data"]).get("created_at", now)
            except Exception:
                created = now
        rec = json.loads(blob)
        rec["created_at"] = created
        c.execute(
            """INSERT INTO sessions (session_id, data, updated_at) VALUES (?,?,?)
               ON CONFLICT(session_id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at""",
            (session_id, json.dumps(rec), now),
        )
    return {"id": session_id, "title": rec["title"], "updated_at": now, "created_at": created}


def list_sessions(owner: str) -> List[Dict[str, Any]]:
    with _db_lock, _conn() as c:
        rows = c.execute("SELECT session_id, data, updated_at FROM sessions ORDER BY updated_at DESC").fetchall()
    out = []
    for r in rows:
        try:
            rec = json.loads(r["data"])
        except Exception:
            continue
        if owner and rec.get("owner") and rec.get("owner") != owner:
            continue
        out.append({"id": r["session_id"], "title": rec.get("title", "Untitled session"),
                    "updated_at": r["updated_at"], "created_at": rec.get("created_at", r["updated_at"])})
    return out


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    with _db_lock, _conn() as c:
        row = c.execute("SELECT session_id, data FROM sessions WHERE session_id=?", (session_id,)).fetchone()
    if not row:
        return None
    try:
        rec = json.loads(row["data"])
    except Exception:
        return None
    return {"id": row["session_id"], "title": rec.get("title", "Untitled session"), "data": rec.get("data")}


def delete_session(session_id: str) -> None:
    with _db_lock, _conn() as c:
        c.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))


def rename_session(session_id: str, title: str) -> bool:
    """Update only a session's title, preserving its data/timestamps."""
    with _db_lock, _conn() as c:
        row = c.execute("SELECT data FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        if not row:
            return False
        try:
            rec = json.loads(row["data"])
        except Exception:
            rec = {}
        rec["title"] = title or "Untitled session"
        c.execute("UPDATE sessions SET data=?, updated_at=? WHERE session_id=?",
                  (json.dumps(rec), time.time(), session_id))
    return True


# ── per-paper detection audits (stored in Redis + SQLite, keyed by paper) ──────

_AUDIT_STAGES = ("references", "methods", "numerical", "recompute", "imaging")


def save_paper_audit(paper_id: str, stage: str, data: Any) -> None:
    if not paper_id or not stage:
        return
    blob = json.dumps(data)
    now = time.time()
    with _db_lock, _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS paper_audits (
            paper_id TEXT, stage TEXT, data TEXT, updated_at REAL, PRIMARY KEY(paper_id, stage))""")
        c.execute("""INSERT INTO paper_audits (paper_id, stage, data, updated_at) VALUES (?,?,?,?)
                     ON CONFLICT(paper_id, stage) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at""",
                  (paper_id, stage, blob, now))
    r = _get_redis()
    if r:
        try:
            r.set(f"audata:audit:{paper_id}:{stage}", blob)  # persistent (no TTL)
        except Exception as e:
            print(f"[audata.storage] redis save_paper_audit: {e}")


def get_paper_audits(paper_id: str) -> Dict[str, Any]:
    """All detection-stage results for a paper — Redis first, SQLite fallback."""
    out: Dict[str, Any] = {}
    r = _get_redis()
    if r:
        try:
            for st in _AUDIT_STAGES:
                v = r.get(f"audata:audit:{paper_id}:{st}")
                if v:
                    out[st] = json.loads(v)
            if out:
                return out
        except Exception as e:
            print(f"[audata.storage] redis get_paper_audits: {e}")
    with _db_lock, _conn() as c:
        try:
            rows = c.execute("SELECT stage, data FROM paper_audits WHERE paper_id=?", (paper_id,)).fetchall()
        except sqlite3.OperationalError:
            return out
    for row in rows:
        try:
            out[row["stage"]] = json.loads(row["data"])
        except Exception:
            pass
    return out


def save_pdf(paper_id: str, data: bytes) -> None:
    if not paper_id or not data:
        return
    now = time.time()
    with _db_lock, _conn() as c:
        c.execute(
            """INSERT INTO pdfs (paper_id, bytes, created_at) VALUES (?,?,?)
               ON CONFLICT(paper_id) DO UPDATE SET bytes=excluded.bytes, created_at=excluded.created_at""",
            (paper_id, sqlite3.Binary(data), now),
        )


def get_pdf(paper_id: str) -> Optional[bytes]:
    with _db_lock, _conn() as c:
        row = c.execute("SELECT bytes FROM pdfs WHERE paper_id=?", (paper_id,)).fetchone()
    return bytes(row["bytes"]) if row else None


def has_pdf(paper_id: str) -> bool:
    with _db_lock, _conn() as c:
        row = c.execute("SELECT 1 FROM pdfs WHERE paper_id=?", (paper_id,)).fetchone()
    return bool(row)


def db_status() -> Dict[str, Any]:
    try:
        with _db_lock, _conn() as c:
            n = c.execute("SELECT COUNT(*) AS n FROM papers").fetchone()["n"]
        return {"connected": True, "backend": "sqlite", "path": settings.AUDATA_DB_PATH, "papers": n}
    except Exception as e:
        return {"connected": False, "error": str(e)}
