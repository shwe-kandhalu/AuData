"""Redis LangCache — managed semantic cache for LLM calls (gated, no-op unless configured).

Unlike the exact-match cache in storage.py, LangCache returns a cached response
for *semantically similar* prompts (e.g. the same claim phrased slightly
differently, or the same reference cited across papers), cutting tokens/latency.

Active only when all three are set:
    REDIS_LANGCACHE_API_KEY   (the lc1_... key)
    LANGCACHE_SERVER_URL      (e.g. https://<region>.langcache.redis.io)
    LANGCACHE_CACHE_ID        (the cache id from the Redis console)
"""

from __future__ import annotations

import os

_client = None
_tried = False


def _get():
    global _client, _tried
    if _tried:
        return _client
    _tried = True
    url = os.getenv("LANGCACHE_SERVER_URL")
    cid = os.getenv("LANGCACHE_CACHE_ID")
    key = os.getenv("REDIS_LANGCACHE_API_KEY") or os.getenv("LANGCACHE_API_KEY")
    if not (url and cid and key):
        return None
    try:
        from langcache import LangCache
        _client = LangCache(server_url=url, api_key=key, cache_id=cid)
        print("[audata.langcache] semantic cache enabled.")
    except Exception as e:
        print(f"[audata.langcache] init failed: {e}")
        _client = None
    return _client


def available() -> bool:
    return _get() is not None


def search(prompt: str):
    """Return a semantically-cached response for `prompt`, or None."""
    c = _get()
    if not c:
        return None
    try:
        thr = float(os.getenv("LANGCACHE_THRESHOLD", "0.9"))
        r = c.search(prompt=prompt, similarity_threshold=thr, max_results=1)
        data = getattr(r, "data", None) or []
        if not data:
            return None
        top = data[0]
        return getattr(top, "response", None) if not isinstance(top, dict) else top.get("response")
    except Exception as e:
        print(f"[audata.langcache] search failed: {e}")
        return None


def store(prompt: str, response: str) -> None:
    c = _get()
    if not c or not response:
        return
    try:
        c.set(prompt=prompt, response=response)
    except Exception as e:
        print(f"[audata.langcache] set failed: {e}")
