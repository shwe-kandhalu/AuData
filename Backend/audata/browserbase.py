"""Browserbase integration for fetching full text from URLs via headless browser."""

from __future__ import annotations

from typing import Any, Dict, Optional
import requests

from . import settings

_BROWSERBASE_API = "https://api.browserbase.com/v1"


def available() -> bool:
    """Check if Browserbase is configured."""
    return bool(settings.BROWSERBASE_API_KEY and settings.BROWSERBASE_PROJECT_ID)


def fetch_url(url: str) -> Dict[str, Any]:
    """Fetch a URL via Browserbase headless browser."""
    if not available():
        return {"status": "not_configured", "text": "", "session_id": None, "final_url": url}

    try:
        headers = {
            "Authorization": f"Bearer {settings.BROWSERBASE_API_KEY}",
            "Content-Type": "application/json",
        }

        # Create a browserbase session
        session_res = requests.post(
            f"{_BROWSERBASE_API}/sessions",
            headers=headers,
            json={"project_id": settings.BROWSERBASE_PROJECT_ID},
            timeout=30,
        )
        if session_res.status_code != 201:
            return {"status": "failed", "text": "", "session_id": None, "final_url": url, "error": session_res.text}

        session_data = session_res.json()
        session_id = session_data.get("id")

        # Navigate to URL
        nav_res = requests.post(
            f"{_BROWSERBASE_API}/sessions/{session_id}/navigate",
            headers=headers,
            json={"url": url},
            timeout=60,
        )
        if nav_res.status_code != 200:
            return {"status": "failed", "text": "", "session_id": session_id, "final_url": url}

        # Get page content
        content_res = requests.get(
            f"{_BROWSERBASE_API}/sessions/{session_id}/content",
            headers=headers,
            timeout=30,
        )
        if content_res.status_code != 200:
            return {"status": "failed", "text": "", "session_id": session_id, "final_url": url}

        content_data = content_res.json()
        return {
            "status": "ok",
            "text": content_data.get("text", ""),
            "session_id": session_id,
            "final_url": content_data.get("url", url),
            "title": content_data.get("title", ""),
        }

    except Exception as e:
        return {"status": "error", "text": "", "session_id": None, "final_url": url, "error": str(e)}
