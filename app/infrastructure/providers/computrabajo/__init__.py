from __future__ import annotations
import os
from typing import Any, Dict, List, Optional
from playwright.sync_api import sync_playwright

from .scraper import ComputrabajoScraper


def scrape_computrabajo(
    *,
    categoria: str = "",
    lugar: str = "",
    job_id: Optional[str] = None,
    max_pages: Optional[int] = None,
    headless: bool = True,  
) -> List[Dict[str, Any]]:
    env_pages = os.getenv("CT_PAGES")
    pages = (
        max_pages
        if max_pages is not None
        else int(env_pages) if env_pages and env_pages.isdigit() else None
    )

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,  
            args=["--window-size=1920,1080"],
            slow_mo=150,    
        )
        try:
            return ComputrabajoScraper(
                browser=browser,
                categoria=categoria or os.getenv("CT_CATEGORIA", ""),
                lugar=lugar or os.getenv("CT_LUGAR", ""),
                max_pages=pages,
                job_id=job_id,
            ).run()
        finally:
            browser.close()