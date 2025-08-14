from __future__ import annotations
from typing import Any, Dict, List, Optional
from playwright.sync_api import sync_playwright

from .scraper import BumeranScraper


def scrap_jobs_bumeran(
    *,
    query: str = "",
    location: str = "",
    max_pages: Optional[int] = None,
    job_id: Optional[str] = None,
    headless: bool = True,
    timeout: int = 15_000,
) -> List[Dict[str, Any]]:
    """
    Initializes a Playwright instance to scrape job postings from Bumeran.
    """
    with sync_playwright() as pw:
        # 1. Launch the browser process with only browser-level arguments
        browser = pw.chromium.launch(headless=headless)

        # 2. Create a browser context with all session-specific settings
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            ignore_https_errors=True,
            viewport=None,  # This disables the default 800x600 viewport
        )
        try:
            # 3. Pass the configured 'context' to your scraper class
            # The 'timeout' value is correctly passed here to be used for page actions.
            scraper = BumeranScraper(
                context=context,
                query=query,
                location=location,
                max_pages=max_pages,
                job_id=job_id,
                timeout=timeout,
            )
            return scraper.run()
        finally:
            # 4. Ensure both the context and browser are closed
            context.close()
            browser.close()

