from __future__ import annotations
from typing import Any, Dict, List, Optional
from playwright.sync_api import sync_playwright

from .scraper import ComputrabajoScraper


def scrape_computrabajo(
    *, categoria: str, lugar: str, job_id: Optional[str] = None, max_pages: Optional[int] = None
) -> List[Dict[str, Any]]:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=False, args=["--start-maximized"])
        try:
            scraper = ComputrabajoScraper(browser, categoria, lugar, max_pages, job_id)
            return scraper.run()
        finally:
            browser.close()