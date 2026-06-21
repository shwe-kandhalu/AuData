"""Agent long-term memory, backed natively by Redis (RediSearch vector search).

Gives the audit agents long-term memory: reviewer decisions (accept/dismiss),
confirmed/false findings, and notes are stored as memories and can be recalled
semantically to calibrate future flags ("you've dismissed self-citation flags
like this before").

This is implemented directly on our Redis Cloud instance (the same REDIS_URL the
rest of the app uses) via a RediSearch KNN vector index, with a local
sentence-transformers embedder. We run it natively rather than against the
managed Agent Memory gateway so it works offline and is fully under our control.

Active whenever REDIS_URL is set and the embedder can load.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any, Dict, List

import numpy as np

INDEX_NAME = "audata_memory_idx"
KEY_PREFIX = "memory:"
EMBED_MODEL = os.getenv("AGENT_MEMORY_EMBED_MODEL", "all-MiniLM-L6-v2")
VECTOR_DIM = 384  # all-MiniLM-L6-v2

_model = None
_index_ready = False
_disabled = False


def _embedder():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(EMBED_MODEL)
    return _model


def _embed(text: str) -> np.ndarray:
    vec = np.asarray(_embedder().encode(text), dtype=np.float32)
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


def _redis():
    # Reuse the app's single REDIS_URL connection logic (raw bytes for vectors).
    from .image_vector_store import get_redis_client
    return get_redis_client()


def _ensure_index():
    global _index_ready
    if _index_ready:
        return
    r = _redis()
    try:
        r.execute_command(
            "FT.CREATE", INDEX_NAME, "ON", "HASH", "PREFIX", "1", KEY_PREFIX,
            "SCHEMA",
            "text", "TEXT",
            "topics", "TAG", "SEPARATOR", ",",
            "namespace", "TAG",
            "created", "NUMERIC",
            "embedding", "VECTOR", "FLAT", "6",
            "TYPE", "FLOAT32", "DIM", VECTOR_DIM, "DISTANCE_METRIC", "COSINE",
        )
    except Exception as e:
        if "Index already exists" not in str(e):
            raise
    _index_ready = True


def available() -> bool:
    """Native memory is usable when Redis is configured (embedder loads lazily)."""
    return bool(os.getenv("REDIS_URL")) and not _disabled


def record(text: str, topics: List[str] | None = None, namespace: str | None = None) -> bool:
    """Store a long-term memory (e.g. a reviewer decision or confirmed finding)."""
    global _disabled
    if not text or not available():
        return False
    try:
        _ensure_index()
        vec = _embed(text)
        ns = namespace or os.getenv("AGENT_MEMORY_NAMESPACE", "audata")
        key = f"{KEY_PREFIX}{uuid.uuid4()}"
        _redis().hset(key, mapping={
            "text": text,
            "topics": ",".join(topics or []),
            "namespace": ns,
            "created": int(time.time()),
            "embedding": vec.tobytes(),
        })
        return True
    except Exception as e:
        print(f"[audata.agent_memory] record failed: {e}")
        return False


def _dec(x):
    return x.decode() if isinstance(x, (bytes, bytearray)) else x


def _dget(d, *keys):
    for k in keys:
        if k in d:
            return d[k]
        kb = k.encode() if isinstance(k, str) else k
        if kb in d:
            return d[kb]
    return None


def search(query: str, limit: int = 5, namespace: str | None = None) -> List[Dict[str, Any]]:
    """Recall memories semantically relevant to `query` (KNN over embeddings)."""
    if not query or not available():
        return []
    try:
        _ensure_index()
        vec = _embed(query)
        ns = namespace or os.getenv("AGENT_MEMORY_NAMESPACE", "audata")
        # Filter by namespace, then KNN by vector similarity.
        q = f"(@namespace:{{{ns}}})=>[KNN {int(limit)} @embedding $vec AS score]"
        result = _redis().execute_command(
            "FT.SEARCH", INDEX_NAME, q,
            "PARAMS", 2, "vec", vec.tobytes(),
            "RETURN", 4, "text", "topics", "created", "score",
            "SORTBY", "score", "DIALECT", 2,
        )
        rows: List[Dict[str, Any]] = []
        if isinstance(result, dict):
            for d in (_dget(result, "results", "Results") or []):
                attrs = _dget(d, "extra_attributes", "attributes", "fields") or {}
                if isinstance(attrs, list):
                    attrs = {_dec(attrs[j]): _dec(attrs[j + 1]) for j in range(0, len(attrs) - 1, 2)}
                else:
                    attrs = {_dec(k): _dec(v) for k, v in attrs.items()}
                rows.append(attrs)
        elif isinstance(result, (list, tuple)):
            for i in range(2, len(result), 2):
                fields = result[i]
                rows.append({_dec(fields[j]): _dec(fields[j + 1]) for j in range(0, len(fields) - 1, 2)})
        out = []
        for data in rows:
            topics = data.get("topics") or ""
            out.append({
                "text": data.get("text", ""),
                "topics": [t for t in topics.split(",") if t],
                "similarity": round(1 - float(data.get("score", 1.0)), 3),
            })
        return out
    except Exception as e:
        print(f"[audata.agent_memory] search failed: {e}")
        return []
