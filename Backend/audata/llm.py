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
        return default_model()
    return name


def get_model(model_name: Optional[str] = None):
    name = (model_name or default_model() or "").strip()
    low = name.lower()
    try:
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


def invoke(model, prompt: str) -> str:
    """Run a single prompt and return the text content ('' on failure)."""
    if model is None:
        return ""
    try:
        from langchain_core.messages import HumanMessage
        r = model.invoke([HumanMessage(content=prompt)])
        return getattr(r, "content", "") or ""
    except Exception as e:
        print(f"[audata.llm] invoke failed: {e}")
        return ""


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
