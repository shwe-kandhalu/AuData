"""Browserbase-backed web fetch (AuData, self-contained).

Drives a remote Browserbase session via Playwright over CDP to fetch arbitrary /
paywalled / JS-rendered paper pages and cited PDFs. Runs in a dedicated thread
with a hard timeout; degrades gracefully when not configured.
"""

from __future__ import annotations

import threading
from typing import Any, Dict

from . import settings


def available() -> bool:
    return bool(settings.BROWSERBASE_API_KEY and settings.BROWSERBASE_PROJECT_ID)


def fetch_url(url: str, timeout_ms: int = 45000) -> Dict[str, Any]:
    if not available():
        return {"status": "unavailable", "reason": "Browserbase is not configured (set BROWSERBASE_API_KEY / BROWSERBASE_PROJECT_ID)."}
    try:
        from browserbase import Browserbase
        from playwright.sync_api import sync_playwright
    except Exception as e:  # pragma: no cover
        return {"status": "error", "reason": f"Browserbase/Playwright not installed: {e}"}

    out: Dict[str, Any] = {"status": "error", "reason": "unknown"}

    def _work():
        nonlocal out
        try:
            bb = Browserbase(api_key=settings.BROWSERBASE_API_KEY)
            session = bb.sessions.create(project_id=settings.BROWSERBASE_PROJECT_ID)
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(session.connect_url)
                ctx = browser.contexts[0] if browser.contexts else browser.new_context()
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                try:
                    page.wait_for_timeout(1500)
                except Exception:
                    pass
                final_url = page.url
                try:
                    title = page.title()
                except Exception:
                    title = ""
                try:
                    text = page.inner_text("body")
                except Exception:
                    text = ""
                pdf_url = ""
                try:
                    pdf_url = page.eval_on_selector("meta[name='citation_pdf_url']", "el => el.content") or ""
                except Exception:
                    pdf_url = ""
                if not pdf_url:
                    try:
                        hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
                        for h in hrefs or []:
                            if h and ".pdf" in h.lower():
                                pdf_url = h
                                break
                    except Exception:
                        pass
                try:
                    browser.close()
                except Exception:
                    pass
                out = {
                    "status": "ok", "text": text or "", "title": title or "",
                    "final_url": final_url or url, "pdf_url": pdf_url or "",
                    "session_id": getattr(session, "id", ""),
                }
        except Exception as e:
            out = {"status": "error", "reason": str(e)}

    t = threading.Thread(target=_work, daemon=True)
    t.start()
    t.join(timeout=(timeout_ms / 1000) + 30)
    if t.is_alive():
        return {"status": "error", "reason": "Browserbase fetch timed out."}
    return out
