import os
from datetime import datetime, timedelta
import time
import re
import unicodedata
import urllib.parse as ul
from typing import Any, Dict, List, Optional
from playwright.sync_api import Browser, Page
from playwright.sync_api import sync_playwright
from playwright.sync_api import Page, TimeoutError
import time, pathlib


try:
    from app.domain.scraper_control import ask_to_stop  # type: ignore
except ImportError:
    def ask_to_stop(job_id: str) -> bool:
        return False

BASE_URL = "https://www.zonajobs.com.ar/"
LISTING_SELECTOR = "div#listado-avisos a.sc-ddcOto"
DETAIL_CONTAINER = "#section-detalle"
TIMEOUT = TIMEOUT = 30_000         
NEXT_BTN_SELECTOR = "a.sc-dzVpKk.hFOZsP:not([disabled])"

def slugify(text: str) -> str:
    norm = unicodedata.normalize("NFKD", text)
    ascii_ = norm.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-")

def parse_fecha_publicacion(texto: str) -> str:
    """Convierte fechas relativas en texto a fecha absoluta dd/mm/yyyy"""
    if not texto:
        return ""
    hoy = datetime.now()

    # Hace X días/horas/minutos
    match = re.search(r"hace (\d+) (minuto|minutos|hora|horas|día|días)", texto, re.IGNORECASE)
    if match:
        valor, unidad = int(match.group(1)), match.group(2)
        if "minuto" in unidad:
            fecha = hoy - timedelta(minutes=valor)
        elif "hora" in unidad:
            fecha = hoy - timedelta(hours=valor)
        elif "día" in unidad:
            fecha = hoy - timedelta(days=valor)
        else:
            fecha = hoy
        return fecha.strftime("%d/%m/%Y")

    # Hace más de X días
    match = re.search(r"hace más de (\d+) días", texto, re.IGNORECASE)
    if match:
        valor = int(match.group(1))
        fecha = hoy - timedelta(days=valor)
        return fecha.strftime("%d/%m/%Y")

    # Ayer
    if "ayer" in texto.lower():
        fecha = hoy - timedelta(days=1)
        return fecha.strftime("%d/%m/%Y")

    # Solo "actualizada" (sin otra info) → dejar vacío, o podés poner la fecha de hoy
    if "actualizada" in texto.lower():
        return ""  # o return hoy.strftime("%d/%m/%Y") si preferís

    return hoy.strftime("%d/%m/%Y")  # fallback por si hay algo nuevo


class ZonaJobsScraper:
    def __init__(
        self,
        browser: Browser,
        query: str = "",
        location: str = "",
        max_pages: Optional[int] = None,
        job_id: Optional[str] = None,
    ) -> None:
        self.browser = browser
        self.query = query.strip()
        self.location = location.strip()
        self.max_pages = max_pages
        self.job_id = job_id or ""
        self.context = browser.new_context(viewport=None,
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
        self.page = self.context.new_page()

        self.filtered_base_url: Optional[str] = None
        self.results: List[Dict[str, Any]] = []
        
    def _get_total_pages(self) -> int:
        paginador = self.page.locator("div.sc-jrOYZv")
        if not paginador.count():
            return 1
        paginas = paginador.locator("a.sc-fQfKYo.ddMBgL, a.sc-fQfKYo.cLGqfc")
        nums = []
        for el in paginas.all():
            txt = el.inner_text().strip()
            if txt.isdigit():
                nums.append(int(txt))
        return max(nums) if nums else 1
        

    def run(self) -> List[Dict[str, Any]]:
        self._login()
        page_num = 1
        total_pages = self._get_total_pages()
        print(f"[INFO] Total de páginas detectado: {total_pages}")
        limit_pages = min(self.max_pages if self.max_pages else total_pages, total_pages)
        while page_num <= limit_pages:
            print(f"[DEBUG] Scrapeando página {page_num}")
            hrefs = self._get_listing_hrefs(page_num)

            # Si no hay avisos, reintentar una vez (por si fue loader/lentitud)
            if not hrefs:
                print(f"[WARN] Página {page_num} sin avisos, reintentando 1 vez...")
                self.page.reload()
                self.page.wait_for_timeout(2000)  # Espera un poco por las dudas
                hrefs = self._get_listing_hrefs(page_num)
                if not hrefs:
                    print(f"[INFO] No hay avisos en la página {page_num}, deteniendo.")
                    break

            for url in hrefs:
                if self.job_id and ask_to_stop(self.job_id):
                    break
                try:
                    self.results.append(self._scrape_detail(url))
                except Exception as e:
                    print(f"[WARN] Error scrapeando {url}: {e}")
                    continue

            page_num += 1

        self.context.close()
        return self.results

    def _login(self) -> None:
        p = self.page
        p.goto(BASE_URL, wait_until="domcontentloaded", timeout=TIMEOUT)

        # Ancla multifunción: placeholder *o* botón «Buscar»
        home_ready_sel = (
            "div.select__placeholder:has-text('Buscar'), "
            "input[id^='react-select'][type='text'], "
            "button#buscarTrabajo, button[data-tag='searchBtn']"
        )
        # Aceptamos cookies si siguen ahí
        if p.locator("button:has-text('Aceptar')").count():
            p.click("button:has-text('Aceptar')")

        if self.query or self.location:
            self._buscar_con_inputs()
        else:
            # Feed general orden "recientes"
            self.filtered_base_url = f"{BASE_URL}empleos.html?recientes=true"
            p.goto(f"{self.filtered_base_url}&page=1",
                wait_until="domcontentloaded", timeout=TIMEOUT)


    def _buscar_con_inputs(self) -> None:
        p = self.page
        if self.query:
            p.wait_for_selector("#react-select-6-input", timeout=TIMEOUT)
            p.fill("#react-select-6-input", self.query)
            p.wait_for_timeout(800)
        if self.location:
            ctl = "#lugar-de-trabajo .select__control:not(.select__control--is-disabled)"
            p.wait_for_selector(ctl, timeout=TIMEOUT)
            p.click(ctl)
            p.wait_for_selector("#react-select-7-input", timeout=TIMEOUT)
            p.fill("#react-select-7-input", self.location)
            p.wait_for_timeout(400)
            p.keyboard.press("Enter")
        elif self.query:
            p.click("#buscarTrabajo")
            p.wait_for_timeout(400)
        p.wait_for_timeout(2000)
        p.wait_for_selector("#listado-avisos", timeout=TIMEOUT)
        avisos = p.locator(LISTING_SELECTOR)
        n_avisos = avisos.count()
        print(f"[DEBUG] Avisos encontrados: {n_avisos}")
        if n_avisos == 0:
            self.filtered_base_url = None
            print("[INFO] No hay avisos en el listado, abortando búsqueda")
            return
        self.filtered_base_url = p.url

    def _click_next_page(self) -> bool:
        # Busca el botón "siguiente" que NO está deshabilitado
        next_btn = self.page.locator("a.sc-dzVpKk:not([disabled])").first
        if next_btn.count():
            next_btn.scroll_into_view_if_needed()
            next_btn.click()
            self.page.wait_for_load_state("networkidle", timeout=TIMEOUT)
            return True
        else:
            print("[INFO] No hay más páginas (botón next está deshabilitado)")
            return False

    def _page_url(self, page: int) -> str:
        if self.query or self.location:
            loc = f"{slugify(self.location)}/" if self.location else ""
            base = f"{BASE_URL}{loc}empleos.html"
            params = [f"page={page}"]
            if self.query:
                params.insert(0, f"palabra={ul.quote_plus(self.query)}")
            return f"{base}?{'&'.join(params)}"
        return f"{BASE_URL}empleos.html?recientes=true&page={page}"


    def _get_listing_hrefs(self, page: int) -> List[str]:
        if self.job_id and ask_to_stop(self.job_id):
            return []
        # Cambio de página
        if page > 1 and self.filtered_base_url:
            if not self._click_next_page():
                print(f"[INFO] Ya no hay más páginas tras la {page-1}")
                return []
        elif page > 1:
            self.page.goto(self._page_url(page), timeout=TIMEOUT)
            self.page.wait_for_selector("#listado-avisos", timeout=TIMEOUT)

        # Esperar avisos REALES (no solo el contenedor) - hasta 10s, en 0.5s steps
        max_wait = 10
        waited = 0
        urls = []
        while waited < max_wait:
            avisos = self.page.locator("div#listado-avisos a[href*='/empleos/']")
            urls = avisos.evaluate_all("els => [...new Set(els.map(e => e.href))]")
            urls = [u for u in urls if re.search(r"/empleos/[^.]+-\d+\.html$", u)]
            if urls:
                break

            # Además, verificar si sigue el spinner/Buscando ofertas
            loading = self.page.locator("h1").first.inner_text().lower()
            if "buscando ofertas" in loading:
                time.sleep(0.5)
                waited += 0.5
            else:
                # Si el loading desapareció pero no hay avisos, salir igual
                break

        print(f"[DEBUG] Avisos REALES encontrados en página {page}: {len(urls)}")

        if not urls:
            html_debug = self.page.inner_html("#listado-avisos")
            print(f"[DEBUG] HTML en página {page} (primeros 1000):\n{html_debug[:1000]}")
            avisos_alt = self.page.locator("#listado-avisos a")
            urls_alt = avisos_alt.evaluate_all("els => [...new Set(els.map(e => e.href))]")
            urls_alt = [u for u in urls_alt if re.search(r"/empleos/[^.]+-\d+\.html$", u)]
            print(f"[DEBUG] Selector alternativo encontró: {len(urls_alt)} avisos reales")
            if urls_alt:
                return sorted(urls_alt)
            return []
        return sorted(urls)


    def _scrape_detail(self, url: str) -> Dict[str, Any]:
        if self.job_id and ask_to_stop(self.job_id):
            raise Exception("Parado por usuario")
        page_detail = self.context.new_page()
        page_detail.goto(url, timeout=TIMEOUT)
        page_detail.wait_for_selector(DETAIL_CONTAINER, timeout=TIMEOUT)
        data: Dict[str, Any] = {"url": url}
        data["titulo"] = page_detail.locator(
            f"h1, {DETAIL_CONTAINER} h1, {DETAIL_CONTAINER} h2"
        ).first.inner_text().strip()
        comp = page_detail.locator("text=Confidencial").first
        if comp.count():
            data["empresa"] = comp.inner_text().strip()
        else:
            comp_div = page_detail.locator("div.sc-kZuyWR").first
            if comp_div.count():
                data["empresa"] = comp_div.inner_text().strip()
            else:
                comp_link = page_detail.locator("a[href*='/perfiles/empresa']").first
                data["empresa"] = comp_link.inner_text().strip() if comp_link.count() else ""
        pub = page_detail.locator(
            f"{DETAIL_CONTAINER} h2:has-text('Publicado'),"
            f"{DETAIL_CONTAINER} h2:has-text('Actualizado')"
        ).first
        texto_pub = pub.inner_text().strip() if pub.count() else ""
        data["publicado"] = texto_pub
        data["fecha_publicacion"] = parse_fecha_publicacion(texto_pub)
        desc_nodes = page_detail.locator(f"{DETAIL_CONTAINER} p").all()
        data["descripcion"] = "\n\n".join(
            n.inner_text().strip() for n in desc_nodes if n.inner_text().strip()
        )
        def grab(sel: str) -> str:
            elem = page_detail.locator(sel).first
            return elem.inner_text().strip() if elem.count() else ""
        data["industria"] = grab("p:has-text('Industria') + p")
        data["ubicacion"] = grab("p:has-text('Ubicación') + p")
        data["tamano_empresa"] = grab("p:has-text('Tamaño de la empresa') + span")
        data["modalidad"] = grab(f"{DETAIL_CONTAINER} li a[href*='modalidad-'] p")
        data["beneficios"] = [
            b.inner_text().strip()
            for b in page_detail.locator(f"{DETAIL_CONTAINER} ul li").all()
            if b.inner_text().strip()
        ]
        data["tags"] = sorted({
            t.inner_text().strip()
            for t in page_detail.locator(f"{DETAIL_CONTAINER} li p").all()
            if t.inner_text().strip()
        })
        page_detail.close()
        return data

def scrape_zonajobs(
    *, job_id: Optional[str] = None,
    query: str = "", location: str = "",
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
        browser = pw.chromium.launch(headless=False, args=["--window-size=1920,1080"],slow_mo=150)

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