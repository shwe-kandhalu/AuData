import os
import uuid
from typing import Any, Dict, List

import numpy as np
import redis
from dotenv import load_dotenv
from PIL import Image

load_dotenv("Backend/.env")

INDEX_NAME = "image_panel_index"
VECTOR_DIM = 512
KEY_PREFIX = "panel:"

_model = None


def get_model():
    global _model

    if _model is None:
        print("Loading CLIP model...")
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("clip-ViT-B-32")
        print("CLIP model loaded.")

    return _model


def get_redis_client(ssl_override=None, username_override="__USE_ENV__"):
    # Prefer the single REDIS_URL used by the rest of the app (storage/cache),
    # so one connection string drives both KV cache and vector search.
    url = os.getenv("REDIS_URL")
    if url:
        return redis.from_url(url, decode_responses=False, socket_connect_timeout=3, socket_timeout=3)

    ssl_value = os.getenv("REDIS_SSL", "false").lower() in {"1", "true", "yes"}
    if ssl_override is not None:
        ssl_value = ssl_override

    if username_override == "__USE_ENV__":
        username = os.getenv("REDIS_USERNAME", "default")
    else:
        username = username_override

    return redis.Redis(
        host=os.getenv("REDIS_HOST"),
        port=int(os.getenv("REDIS_PORT")),
        username=username if username else None,
        password=os.getenv("REDIS_PASSWORD"),
        ssl=ssl_value,
        socket_connect_timeout=3,
        socket_timeout=3,
        decode_responses=False,
    )



def test_connection():
    host = os.getenv("REDIS_HOST")
    port = os.getenv("REDIS_PORT")
    env_username = os.getenv("REDIS_USERNAME", "default")
    env_ssl = os.getenv("REDIS_SSL", "false")

    print(f"Redis host: {host}")
    print(f"Redis port: {port}")
    print(f"Redis username from env: {env_username}")
    print(f"Redis SSL from env: {env_ssl}")

    attempts = [
        {"name": "env settings", "ssl": None, "username": "__USE_ENV__"},
        {"name": "no username, ssl=false", "ssl": False, "username": None},
        {"name": "default username, ssl=false", "ssl": False, "username": "default"},
        {"name": "no username, ssl=true", "ssl": True, "username": None},
        {"name": "default username, ssl=true", "ssl": True, "username": "default"},
    ]

    last_error = None

    for attempt in attempts:
        print(f"Trying Redis connection: {attempt['name']}")
        try:
            r = get_redis_client(
                ssl_override=attempt["ssl"],
                username_override=attempt["username"],
            )
            result = r.ping()
            print(f"Redis PING returned using: {attempt['name']}")
            print(f"Use REDIS_SSL={str(r.connection_pool.connection_kwargs.get('ssl', False)).lower()}")
            if attempt["username"] is None:
                print("Use REDIS_USERNAME=")
            elif attempt["username"] == "default":
                print("Use REDIS_USERNAME=default")
            return result
        except Exception as e:
            last_error = e
            print(f"Failed: {type(e).__name__}: {e}")

    raise last_error


def create_index(overwrite: bool = False):
    r = get_redis_client()

    if overwrite:
        try:
            r.execute_command("FT.DROPINDEX", INDEX_NAME, "DD")
        except Exception:
            pass

    try:
        r.execute_command(
            "FT.CREATE",
            INDEX_NAME,
            "ON",
            "HASH",
            "PREFIX",
            "1",
            KEY_PREFIX,
            "SCHEMA",
            "paper_id",
            "TEXT",
            "panel_path",
            "TEXT",
            "page",
            "NUMERIC",
            "figure_id",
            "TEXT",
            "panel_id",
            "TEXT",
            "embedding",
            "VECTOR",
            "FLAT",
            "6",
            "TYPE",
            "FLOAT32",
            "DIM",
            VECTOR_DIM,
            "DISTANCE_METRIC",
            "COSINE",
        )
        print(f"Created Redis vector index: {INDEX_NAME}")

    except redis.ResponseError as e:
        if "Index already exists" in str(e):
            print(f"Redis index already exists: {INDEX_NAME}")
        else:
            raise


def embed_image(image_path: str) -> np.ndarray:
    model = get_model()

    image = Image.open(image_path).convert("RGB")
    vector = model.encode(image)
    vector = np.asarray(vector, dtype=np.float32)

    norm = np.linalg.norm(vector)
    if norm > 0:
        vector = vector / norm

    return vector


def store_panel_embedding(
    paper_id: str,
    panel_path: str,
    page: int = 0,
    figure_id: str = "",
    panel_id: str = "",
) -> str:
    r = get_redis_client()

    vector = embed_image(panel_path)
    redis_id = str(uuid.uuid4())
    key = f"{KEY_PREFIX}{redis_id}"

    r.hset(
        key,
        mapping={
            "paper_id": paper_id,
            "panel_path": panel_path,
            "page": int(page),
            "figure_id": figure_id,
            "panel_id": panel_id,
            "embedding": vector.tobytes(),
        },
    )

    return key


def search_similar_panels(
    paper_id: str,
    panel_path: str,
    top_k: int = 5,
    similarity_threshold: float = 0.85,
) -> List[Dict[str, Any]]:
    r = get_redis_client()
    vector = embed_image(panel_path)

    query = f"*=>[KNN {top_k} @embedding $vec AS score]"

    result = r.execute_command(
        "FT.SEARCH",
        INDEX_NAME,
        query,
        "PARAMS",
        2,
        "vec",
        vector.tobytes(),
        "RETURN",
        6,
        "paper_id",
        "panel_path",
        "page",
        "figure_id",
        "panel_id",
        "score",
        "SORTBY",
        "score",
        "DIALECT",
        2,
    )

    # Normalize FT.SEARCH reply to a list of field dicts. redis-py 8 (RESP3)
    # returns a dict {"results": [{"extra_attributes": {...}}, ...]}; older RESP2
    # returns a flat list [total, key, [f,v,...], key, [f,v,...], ...].
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

    matches = []
    for data in rows:
        matched_paper_id = data.get("paper_id")

        if matched_paper_id == paper_id:
            continue

        distance = float(data.get("score", 1.0))
        similarity = round(1 - distance, 3)

        if similarity >= similarity_threshold:
            matches.append(
                {
                    "flag_type": "cross_paper_possible_reuse",
                    "query_panel": panel_path,
                    "matched_panel": data.get("panel_path"),
                    "matched_paper_id": matched_paper_id,
                    "matched_page": data.get("page"),
                    "matched_figure_id": data.get("figure_id"),
                    "matched_panel_id": data.get("panel_id"),
                    "similarity_score": similarity,
                    "severity": "high" if similarity >= 0.92 else "moderate",
                }
            )

    return matches


def store_many_panels(paper_id: str, panels: List[Dict[str, Any]]) -> List[str]:
    keys = []

    for idx, panel in enumerate(panels):
        key = store_panel_embedding(
            paper_id=paper_id,
            panel_path=panel["panel_path"],
            page=panel.get("page", 0),
            figure_id=panel.get("source_figure", ""),
            panel_id=panel.get("panel_id", f"panel_{idx + 1}"),
        )
        keys.append(key)

    return keys


def search_many_panels(
    paper_id: str,
    panels: List[Dict[str, Any]],
    top_k: int = 5,
    similarity_threshold: float = 0.85,
) -> List[Dict[str, Any]]:
    all_matches = []

    for panel in panels:
        matches = search_similar_panels(
            paper_id=paper_id,
            panel_path=panel["panel_path"],
            top_k=top_k,
            similarity_threshold=similarity_threshold,
        )
        all_matches.extend(matches)

    return all_matches


if __name__ == "__main__":
    print("Starting Redis vector store test...")
    print("Redis connected:", test_connection())
    create_index(overwrite=False)
    print("Done.")