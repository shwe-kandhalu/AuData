# browserbase_input.py
## Retrieves research papers from journal websites, preprint servers, or DOI links, downloads the manuscript PDF, extracts basic metadata, and passes a standardized PDF file path to downstream auditing agents for analysis.

import os
import requests
from dotenv import load_dotenv
from browserbase import Browserbase
from playwright.sync_api import sync_playwright


load_dotenv()

def download_pdf_with_browserbase(url: str, output_path: str = "input_paper.pdf") -> str:
    """
    Opens a URL in Browserbase, finds a PDF link, downloads it locally,
    and returns the local PDF path.
    """

    ## Add your Browserbase API key
    api_key = os.getenv("BROWSERBASE_API_KEY")

    if not api_key:
        raise ValueError("BROWSERBASE_API_KEY not found")

    bb = Browserbase(api_key=api_key)

    session = bb.sessions.create()

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(session.connect_url)
        context = browser.contexts[0]
        page = context.pages[0]

        page.goto(url, wait_until="domcontentloaded", timeout=60000)

        # Simple first-pass logic: find first PDF link
        # PMC-specific handling
        if "pmc.ncbi.nlm.nih.gov/articles/" in url:
            pdf_url = url.rstrip("/") + "/pdf/"
        else:
            pdf_link = page.locator("a[href*='pdf']").first
            pdf_url = pdf_link.get_attribute("href")

        if not pdf_url:
            raise ValueError("No PDF link found on page.")

        if pdf_url.startswith("/"):
            base = page.url.split("/")[0] + "//" + page.url.split("/")[2]
            pdf_url = base + pdf_url

        r = requests.get(pdf_url, timeout=30)
        r.raise_for_status()

        with open(output_path, "wb") as f:
            f.write(r.content)

        browser.close()

    return output_path