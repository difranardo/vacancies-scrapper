from __future__ import annotations
import os
import urllib.parse as ul
from typing import Any, Dict, List
from playwright.sync_api import Browser, Page, sync_playwright, TimeoutError as PWTimeoutError
from app.infrastructure.utils import parse_fecha_publicacion

from app.logging_utils import get_logger

try:
    from app.domain.scraper_control import ask_to_stop
except ImportError:
    def ask_to_stop(job_id: str) -> bool:
        return False

BASE_URL = "https://www.bumeran.com.ar/"
BUM_USER = os.getenv("BUMERAN_USER", "")
BUM_PASS = os.getenv("BUMERAN_PASS", "")
LISTING_SELECTOR = "#listado-avisos a.sc-gVZiCL"
DETAIL_CONTAINER = "#section-detalle"
TIMEOUT = 15_000
ZERO_JOBS_SEL = "span.sc-SxrYz.cBtoeQ:has-text('0')"
NEXT_BTN = "a.sc-dzVpKk.hFOZsP"

class BumeranScraper:
    def __init__(
        self,
        browser: Browser,
        query: str = "",
        location: str = "",
        max_pages: int | None = None,
        job_id: str | None = None,
    ) -> None:
        self.browser = browser
        self.query = query.strip()
        self.location = location.strip()
        self.max_pages = max_pages
        self.job_id = job_id or ""
        self.context = browser.new_context(viewport=None)
        self.list_page: Page = self.context.new_page()
        self.detail_page: Page = self.context.new_page()
        self.results: List[Dict[str, Any]] = []

    def run(self) -> List[Dict[str, Any]]:
        self._login_and_search()
        page_num = 1
        while True:
            if self.max_pages and page_num > self.max_pages:
                get_logger().info(
                    "Máximo de páginas (%s) alcanzado, deteniendo.", self.max_pages
                )
                break
            if self.job_id and ask_to_stop(self.job_id):
                get_logger().info("Scraping detenido por usuario.")
                break
            hrefs = self._get_listing_hrefs()
            if not hrefs:
                break
            for url in hrefs:
                if self.job_id and ask_to_stop(self.job_id):
                    break
                try:
                    self.results.append(self._scrape_detail(url))
                except Exception as exc:
                    get_logger().warning("%s: %s", url, exc)

            page_num += 1
            if not self._go_to_page(page_num):
                break
        self.context.close()
        return self.results

    def _login_and_search(self) -> None:
        p = self.list_page
        p.goto(BASE_URL, timeout=TIMEOUT)
        p.wait_for_selector("a[href*='/postulantes']", timeout=TIMEOUT)

        if self.query or self.location:
            #p.goto(BASE_URL, timeout=TIMEOUT)
            self._buscar_con_inputs()
        else:
            self.filtered_base_url = f"{BASE_URL}empleos.html?recientes=true"
            p.goto(f"{self.filtered_base_url}&page=1", timeout=TIMEOUT)
            p.wait_for_selector(LISTING_SELECTOR, timeout=TIMEOUT)


    def _buscar_con_inputs(self) -> None:
        p = self.list_page

        # 1. Click placeholder de puesto PARA DESPERTAR EL INPUT
        if self.query:
            get_logger().debug("Click placeholder puesto")
            p.wait_for_selector("div.select__placeholder:has-text('Buscar empleo por puesto o palabra clave')", timeout=TIMEOUT)
            ph_puesto = p.locator("div.select__placeholder:has-text('Buscar empleo por puesto o palabra clave')").first
            # Simula doble click para forzar apertura de input
            ph_puesto.click(force=True)
            p.wait_for_timeout(120)
            ph_puesto.click(force=True)
            p.wait_for_timeout(220)

            # Busca el input habilitado (puede ser react-select-4/5-input)
            for i in range(20):
                all_inputs = p.locator("input[id^='react-select'][type='text']")
                # Usa el primer input visible y no disabled
                for idx in range(all_inputs.count()):
                    inp = all_inputs.nth(idx)
                    if inp.is_visible() and not inp.is_disabled():
                        inp.fill(self.query)
                        p.keyboard.press("Enter")
                        p.wait_for_timeout(300)
                        break
                else:
                    p.wait_for_timeout(80)
                    continue
                break
            else:
                raise RuntimeError("No se pudo encontrar input de puesto habilitado/visible")

        p.wait_for_timeout(2000)
        # 2. Click placeholder de ubicación PARA DESPERTAR EL INPUT
        if self.location:
            get_logger().debug("Click placeholder ubicación")
            p.wait_for_selector("div.select__placeholder:has-text('Lugar de trabajo')", timeout=TIMEOUT)
            ph_ubic = p.locator("div.select__placeholder:has-text('Lugar de trabajo')").first
            ph_ubic.click(force=True)
            p.wait_for_timeout(120)
            ph_ubic.click(force=True)
            p.wait_for_timeout(220)

            for i in range(20):
                all_inputs = p.locator("input[id^='react-select'][type='text']")
                idx = all_inputs.count()-1 if all_inputs.count()>1 else 0
                inp = all_inputs.nth(idx)
                if inp.is_visible() and not inp.is_disabled():
                    inp.fill(self.location)
                    p.keyboard.press("Enter")
                    p.wait_for_timeout(350)
                    break
                p.wait_for_timeout(80)
            else:
                raise RuntimeError("No se pudo encontrar input de ubicación habilitado/visible")

        # 3. Click buscar
        get_logger().debug("Click en buscar trabajo")
        # ¡Usá el selector más específico!
        boton_buscar = p.locator("button.sc-btzYZH[type='link']").first
        boton_buscar.scroll_into_view_if_needed()
        p.wait_for_timeout(2000)
        boton_buscar.click(force=True)
        p.wait_for_timeout(600)


        # 4. Espera resultados
        if p.locator(ZERO_JOBS_SEL).count():
            self.filtered_base_url = None
            get_logger().debug("0 resultados, abortando búsqueda.")
            return

        p.wait_for_selector(LISTING_SELECTOR, timeout=TIMEOUT)
        self.filtered_base_url = p.url



    def _get_listing_hrefs(self) -> List[str]:
        p = self.list_page
        p.wait_for_selector(LISTING_SELECTOR, timeout=TIMEOUT)
        urls = p.locator(LISTING_SELECTOR).evaluate_all(
            "els => Array.from(new Set(els.map(e => e.href)))"
        )  # type: ignore
        return sorted(u for u in urls if u.endswith(".html"))

    def _scrape_detail(self, url: str) -> Dict[str, Any]:
        dp = self.detail_page
        dp.goto(url, timeout=TIMEOUT)
        dp.wait_for_selector(DETAIL_CONTAINER, timeout=TIMEOUT)

        data: Dict[str, Any] = {"url": url}

        # ─── Título ─────────────────────────────────────────────────────
        titulo = dp.locator(f"{DETAIL_CONTAINER} h1, {DETAIL_CONTAINER} h2").first
        data["titulo"] = titulo.inner_text().strip() if titulo.count() else ""

        # ─── Empresa ────────────────────────────────────────────────────
        empresa = dp.locator("text=Confidencial").first
        if not empresa.count():
            empresa = dp.locator(f"{DETAIL_CONTAINER} a[href*='/perfil/empresa']").first
        data["empresa"] = empresa.inner_text().strip() if empresa.count() else ""

        # ─── Fecha de publicación / actualización ──────────────────────
        pub_nodes = dp.locator(
            f"{DETAIL_CONTAINER} h2:has-text('Publicado'), "
            f"{DETAIL_CONTAINER} h2:has-text('Actualizado')"
        )
        texto_pub = pub_nodes.last.inner_text().strip() if pub_nodes.count() else ""
        data["publicado"]          = texto_pub
        data["fecha_publicacion"]  = parse_fecha_publicacion(texto_pub)

        # ─── Descripción ────────────────────────────────────────────────
        desc_nodes = dp.locator(f"{DETAIL_CONTAINER} p")
        data["descripcion"] = "\n\n".join(
            n.inner_text().strip() for n in desc_nodes.all() if n.inner_text().strip()
        )

        # ─── Campos adicionales (industria, ubicación, …) ──────────────
        def grab(sel: str) -> str:
            loc = dp.locator(sel).first
            return loc.inner_text().strip() if loc.count() else ""

        data["industria"]       = grab("p:has-text('Industria') + p")
        data["ubicacion"]       = grab("p:has-text('Ubicación') + p")
        data["tamano_empresa"]  = grab("p:has-text('Tamaño de la empresa') + span")

        data["beneficios"] = [
            b.strip()
            for b in dp.locator(f"{DETAIL_CONTAINER} ul li").all_inner_texts()
            if b.strip()
        ]
        data["tags"] = sorted({
            t.strip()
            for t in dp.locator("a[href*='/empleos-'], a[href*='/en-']").all_inner_texts()
            if t.strip()
        })

        return data


    def _go_to_page(self, num: int) -> bool:
        p = self.list_page
        try:
            next_btn = p.locator(NEXT_BTN).first
            if next_btn.count() and next_btn.is_visible():
                next_btn.click()
            else:
                url = f"{BASE_URL}empleos.html?recientes=true&palabra={ul.quote_plus(self.query)}&page={num}"
                p.goto(url, timeout=TIMEOUT)
            p.wait_for_selector(LISTING_SELECTOR, timeout=TIMEOUT)
            return True
        except PWTimeoutError:
            return False


