from __future__ import annotations
import os
from typing import Any, Dict, List, Optional
from playwright.sync_api import sync_playwright

from .scraper import ZonaJobsScraper


def scrape_zonajobs(
    *,
    job_id: Optional[str] = None,
    query: str = "",
    location: str = "",
    max_pages: Optional[int] = None,
    headless: bool = True,
    **_
) -> List[Dict[str, Any]]:
    """
    Initializes a Playwright instance to scrape job postings from ZonaJobs.

    This function configures and launches a Chromium browser instance, creates a
    browser context with specific settings (like user agent and viewport), and
    then passes this context to the ZonaJobsScraper class to perform the
    scraping logic.
    """
    env_pages = os.getenv("ZJ_PAGES")
    pages = (
        max_pages
        if max_pages is not None
        else int(env_pages) if env_pages and env_pages.isdigit() else None
    )
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            ignore_https_errors=True,
            viewport=None,  # Disables the default 800x600 viewport
        )
        try:
            # Note: ZonaJobsScraper must be updated to accept 'context'
            scraper = ZonaJobsScraper(
                context=context,
                query=query or os.getenv("ZJ_QUERY", ""),
                location=location or os.getenv("ZJ_LOCATION", ""),
                max_pages=pages,
                job_id=job_id,
            )
            return scraper.run()
        finally:
            context.close()
            browser.close()
