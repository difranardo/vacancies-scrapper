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
) -> List[Dict[str, Any]]:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless, args=["--start-maximized"])
        try:
            scraper = BumeranScraper(
                browser, query=query, location=location, max_pages=max_pages, job_id=job_id
            )
            return scraper.run()
        finally:
            browser.close()