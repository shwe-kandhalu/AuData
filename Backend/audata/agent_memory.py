"""Redis Agent Memory Server integration (gated, no-op unless configured).

Gives the audit agents long-term memory: reviewer decisions (accept/dismiss),
confirmed/false findings, and notes are stored as memories and can be recalled
to calibrate future flags ("you've dismissed self-citation flags like this
before"). Backed by Redis's managed Agent Memory Server.

Active only when AGENT_MEMORY_BASE_URL is set (+ REDIS_AGENT_MEMORY_API_KEY for
the managed service). The client is async; we wrap calls for sync callers.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List

_client = None
_tried = False


def _get():
    global _client, _tried
    if _tried:
        return _client
    _tried = True
    base = os.getenv("AGENT_MEMORY_BASE_URL")
    if not base:
        return None
    try:
        from agent_memory_client import MemoryAPIClient, MemoryClientConfig
        cfg = MemoryClientConfig(base_url=base, default_namespace=os.getenv("AGENT_MEMORY_NAMESPACE", "audata"))
        _client = MemoryAPIClient(config=cfg)
        # The Redis managed Agent Memory gateway authenticates via X-Redis-Api-Key.
        key = os.getenv("REDIS_AGENT_MEMORY_API_KEY") or os.getenv("AGENT_MEMORY_API_KEY")
        if key and getattr(_client, "_client", None) is not None:
            try:
                _client._client.headers["X-Redis-Api-Key"] = key
            except Exception as e:
                print(f"[audata.agent_memory] header inject failed: {e}")
        print("[audata.agent_memory] enabled.")
    except Exception as e:
        print(f"[audata.agent_memory] init failed: {e}")
        _client = None
    return _client


def available() -> bool:
    return _get() is not None


def _run(make_coro):
    """Run an async call. `make_coro` is a 0-arg callable returning a fresh coroutine."""
    try:
        return asyncio.run(make_coro())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(make_coro())
        finally:
            loop.close()


def record(text: str, topics: List[str] | None = None, namespace: str | None = None) -> bool:
    """Store a long-term memory (e.g. a reviewer decision or confirmed finding)."""
    c = _get()
    if not c or not text:
        return False
    try:
        from agent_memory_client.models import ClientMemoryRecord
        rec = ClientMemoryRecord(text=text, topics=topics or [],
                                 namespace=namespace or os.getenv("AGENT_MEMORY_NAMESPACE", "audata"))
        _run(lambda: c.create_long_term_memory([rec]))
        return True
    except Exception as e:
        print(f"[audata.agent_memory] record failed: {e}")
        return False


def search(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Recall memories relevant to `query`."""
    c = _get()
    if not c or not query:
        return []
    try:
        res = _run(lambda: c.search_long_term_memory(text=query))
        mems = (getattr(res, "memories", None) or getattr(res, "data", None) or [])[:limit]
        out = []
        for m in mems:
            out.append({"text": getattr(m, "text", None) or (m.get("text") if isinstance(m, dict) else ""),
                        "topics": getattr(m, "topics", None) or (m.get("topics") if isinstance(m, dict) else [])})
        return out
    except Exception as e:
        print(f"[audata.agent_memory] search failed: {e}")
        return []
