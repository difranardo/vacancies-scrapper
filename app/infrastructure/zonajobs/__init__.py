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
    **_
) -> List[Dict[str, Any]]:
    env_pages = os.getenv("ZJ_PAGES")
    pages = (
        max_pages
        if max_pages is not None
        else int(env_pages) if env_pages and env_pages.isdigit() else None
    )
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, args=["--window-size=1920,1080"], slow_mo=150)
        try:
            return ZonaJobsScraper(
                browser=browser,
                query=query or os.getenv("ZJ_QUERY", ""),
                location=location or os.getenv("ZJ_LOCATION", ""),
                max_pages=pages,
                job_id=job_id,
            ).run()
        finally:
            browser.close()