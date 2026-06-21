"""Minimal provider-agnostic LLM dispatcher for AuData.

Self-contained (no Evidence Engine imports). Routes by model-name substring to
Claude / OpenAI / Gemini / Ollama via LangChain, reading keys from the env.
Returns None when the chosen provider has no key configured, so callers can
degrade gracefully (e.g. skip the LLM-dependent check).
"""

from __future__ import annotations

import os
import json
import re
from typing import Any, Optional


def default_model() -> str:
    return os.getenv("DEFAULT_MODEL") or "claude-sonnet-4-6"


def is_screening_model(name: str) -> bool:
    return "leads" in (name or "").lower()


def resolve_thinking(name: str) -> str:
    """Reasoning tasks (claim/methods analysis) must not use the screening-only
    LEADS model — route those to the capable default model instead."""
    if not name or is_screening_model(name):
        return os.getenv("MODEL_REASONING") or default_model()
    return name


# Task-aware model routing: heavy reasoning → Claude; cheap/structured work →
# local models; medical figures → a vision model; embeddings → a local embedder.
# Every model is env-overridable (e.g. MODEL_EXTRACTION=claude-sonnet-4-6).
TASK_REASONING = "reasoning"
TASK_EXTRACTION = "extraction"
TASK_LIGHT = "light"
TASK_VISION = "vision"      # image forensics (teammates)
TASK_EMBED = "embed"

_TASK_DEFAULTS = {
    TASK_EXTRACTION: "qwen2.5:7b",     # local; LEADS/other local models also fine
    TASK_LIGHT: "llama3.2:3b",          # trivial classification / cleanup
    TASK_VISION: "medgemma:27b",        # medical vision (multimodal variant / qwen3-vl)
    TASK_EMBED: "nomic-embed-text",     # feeds Redis vector search + semantic cache
}


def model_name_for(task: str, requested: str = "") -> str:
    """The model name chosen for a task (before instantiation)."""
    if task == TASK_REASONING:
        if requested and not is_screening_model(requested):
            return requested                       # honor an explicit capable choice
        return os.getenv("MODEL_REASONING") or default_model()
    env = os.getenv(f"MODEL_{task.upper()}")
    return env or _TASK_DEFAULTS.get(task) or default_model()


def get_model_for(task: str, requested: str = ""):
    """Resolve + instantiate the model for a task type."""
    return get_model(model_name_for(task, requested))


def get_model(model_name: Optional[str] = None):
    name = (model_name or default_model() or "").strip()
    low = name.lower()
    is_cloud = ("claude" in low) or ("gpt" in low) or low.startswith(("o1", "o3", "o4")) or ("gemini" in low)
    try:
        # Token Router (PaleBlueDot): when configured, route ALL cloud model calls
        # through its OpenAI-compatible gateway instead of the provider directly.
        tr_key = os.getenv("TOKENROUTER_API_KEY")
        if tr_key and is_cloud:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(model=name, api_key=tr_key,
                              base_url=os.getenv("TOKENROUTER_BASE_URL", "https://api.tokenrouter.io/v1"),
                              temperature=0, max_tokens=4096)
        if "claude" in low:
            key = os.getenv("ANTHROPIC_API_KEY")
            if not key:
                return None
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(model=name, api_key=key, temperature=0, max_tokens=4096)
        if "gpt" in low or low.startswith(("o1", "o3", "o4")):
            key = os.getenv("OPENAI_API_KEY")
            if not key:
                return None
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(model=name, api_key=key, temperature=0, max_tokens=4096)
        if "gemini" in low:
            key = os.getenv("GEMINI_API_KEY")
            if not key:
                return None
            from langchain_google_genai import ChatGoogleGenerativeAI
            return ChatGoogleGenerativeAI(model=name, google_api_key=key, temperature=0, max_output_tokens=4096)
        # Default → local Ollama (num_predict default is tiny — raise it).
        from langchain_ollama import ChatOllama
        return ChatOllama(model=name, temperature=0, num_predict=4096,
                          base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))
    except Exception as e:
        print(f"[audata.llm] get_model({name}) failed: {e}")
        return None


def invoke(model, prompt: str, cache: bool = True) -> str:
    """Run a single prompt and return the text content ('' on failure).

    Deterministic calls (temperature=0) are cached by (model, prompt) in Redis
    (in-memory fallback) so re-runs and repeated references/claims are free.
    """
    if model is None:
        return ""
    name = getattr(model, "model", None) or getattr(model, "model_name", "") or ""
    cache_prompt = f"{name}\n{prompt}"
    key = None
    if cache:
        import hashlib
        from . import storage, langcache
        # 1) semantic cache (Redis LangCache) — hits on similar prompts
        sem = langcache.search(cache_prompt)
        if sem is not None:
            return sem
        # 2) exact-match cache (Redis / in-memory)
        key = hashlib.sha256(cache_prompt.encode("utf-8")).hexdigest()
        hit = storage.cache_get(key)
        if hit is not None:
            return hit
    try:
        from langchain_core.messages import HumanMessage
        r = model.invoke([HumanMessage(content=prompt)])
        out = getattr(r, "content", "") or ""
    except Exception as e:
        print(f"[audata.llm] invoke failed: {e}")
        return ""
    if cache and out:
        try:
            from . import storage, langcache
            if key:
                storage.cache_set(key, out)
            langcache.store(cache_prompt, out)
        except Exception:
            pass
    return out


def extract_json(text: str) -> Optional[Any]:
    """Pull the first balanced JSON object/array out of an LLM response."""
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.I | re.M).strip()
    # Direct parse first.
    try:
        return json.loads(t)
    except Exception:
        pass
    # Otherwise scan for the outermost {...} or [...].
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = t.find(open_ch)
        if start < 0:
            continue
        depth = 0
        for i in range(start, len(t)):
            if t[i] == open_ch:
                depth += 1
            elif t[i] == close_ch:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(t[start:i + 1])
                    except Exception:
                        break
    return None
