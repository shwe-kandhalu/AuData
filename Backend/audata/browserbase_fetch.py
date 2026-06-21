"""Browserbase-backed web fetch (AuData, self-contained).

Drives a remote Browserbase session via Playwright over CDP to fetch arbitrary /
paywalled / JS-rendered paper pages and cited PDFs. Runs in a dedicated thread
with a hard timeout; degrades gracefully when not configured.
"""

from __future__ import annotations

import base64
import threading
from typing import Any, Dict, Optional

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


def _playwright_fetch_file(page_url: str, file_url: str, timeout_ms: int,
                            browser_factory) -> Dict[str, Any]:
    """Shared Playwright logic: load page_url, open file_url in a new tab, return bytes.

    Filters out Cloudflare challenge pages (text/html status-200 responses) so
    expect_response only resolves once the real data file arrives.
    """
    from urllib.parse import urlparse
    from playwright.sync_api import sync_playwright

    out: Dict[str, Any] = {"status": "error", "reason": "unknown"}

    def _work():
        nonlocal out
        try:
            with sync_playwright() as p:
                browser = browser_factory(p)
                ctx = browser.contexts[0] if getattr(browser, "contexts", None) else None
                if ctx is None:
                    ctx = browser.new_context(
                        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                                   "Chrome/124.0.0.0 Safari/537.36",
                    )
                page = ctx.pages[0] if ctx.pages else ctx.new_page()

                # Load dataset page to establish session cookies in this browser context
                page.goto(page_url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(3000)

                path_suffix = urlparse(file_url).path

                # Open the file URL in a NEW tab so:
                # 1. The current page (with session) stays alive
                # 2. The new tab inherits context cookies
                # 3. If Cloudflare challenges the download URL the browser can solve it
                dl_page = ctx.new_page()

                # Only match the real data response — skip HTML (Cloudflare challenge pages)
                def _is_data_response(r):
                    ct = (r.headers.get("content-type") or "").lower()
                    return (path_suffix in r.url
                            and r.status == 200
                            and "text/html" not in ct)

                with dl_page.expect_response(_is_data_response, timeout=80000) as resp_info:
                    dl_page.goto(file_url, wait_until="commit", timeout=80000)

                resp = resp_info.value
                ct = (resp.headers.get("content-type") or "").lower()
                body = resp.body()
                out = {"status": "ok", "content": bytes(body), "content_type": ct, "size": len(body)}

                try:
                    browser.close()
                except Exception:
                    pass
        except Exception as e:
            out = {"status": "error", "reason": str(e)}

    t = threading.Thread(target=_work, daemon=True)
    t.start()
    t.join(timeout=(timeout_ms / 1000) + 90)
    if t.is_alive():
        return {"status": "error", "reason": "Browser file fetch timed out."}
    return out


def fetch_file_via_page(page_url: str, file_url: str, timeout_ms: int = 90000) -> Dict[str, Any]:
    """Load page_url in a browser (Browserbase first, local Chromium fallback), click the
    file download link, and return the raw bytes. Handles Cloudflare-protected repositories."""
    # --- Try Browserbase first ---
    if available():
        try:
            from browserbase import Browserbase
            bb = Browserbase(api_key=settings.BROWSERBASE_API_KEY)
            session = bb.sessions.create(project_id=settings.BROWSERBASE_PROJECT_ID)
            connect_url = session.connect_url

            def bb_factory(p):
                return p.chromium.connect_over_cdp(connect_url)

            result = _playwright_fetch_file(page_url, file_url, timeout_ms, bb_factory)
            if result["status"] == "ok":
                return result
            # On 402 / plan-limit the session creation would already have raised — fall through
            print(f"[browserbase_fetch] Browserbase attempt failed: {result.get('reason')} — trying local Chromium", flush=True)
        except Exception as bb_err:
            print(f"[browserbase_fetch] Browserbase session error: {bb_err} — trying local Chromium", flush=True)

    # --- Fallback: local headless Chromium ---
    try:
        from playwright.sync_api import sync_playwright as _spw  # noqa: F401

        def local_factory(p):
            # headless=False: real visible window passes Cloudflare JS challenges
            # that headless mode cannot solve
            return p.chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
            )

        print("[browserbase_fetch] Trying local headless Chromium for file download", flush=True)
        return _playwright_fetch_file(page_url, file_url, timeout_ms, local_factory)
    except Exception as e:
        return {"status": "error", "reason": f"Local Chromium also failed: {e}"}
