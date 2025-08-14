from playwright.sync_api import Browser, Page, TimeoutError
from app.scraper.application.scraper_control import ask_to_stop
import urllib.parse as ul
from typing import Any, Dict, List, Optional
from app.infrastructure.utils import parse_fecha_publicacion
from app.scraper.application.scraper_control import ask_to_stop, push_result
from app.infrastructure.common.logging_utils import get_logger

BASE_URL = "https://ar.computrabajo.com/"
TIMEOUT = 15_000
# Selectores para listados y detalle
LISTING_LINK = "article.box_offer h2 a.js-o-link"
DETAIL_PANEL = "main.detail_fs"
NEXT_BTN = "span.b_primary.w48.buildLink.cp[title='Siguiente']"
# Popups que deben cerrarse automáticamente
POPUP_SELECTORS = [
    "button[onclick*='webpush_subscribe']",
    "div.popup_webpush button.reject",
    "#js_close_box_alert",
    "[data-close-popup]",
    "button:has-text('Ahora no')",
    "button:has-text('Permitir')",
]

# ——— arriba del archivo, junto a tus otras constantes ———
LISTING_BLOCK = "article.box_offer, div#offers article, ul.offer_list li, div#p_ofertas article"
LISTING_LINK  = "article.box_offer h2 a.js-o-link, article.box_offer a.js-o-link, article a.js-o-link, a.js-o-link"
COOKIE_BTNS   = [
    "button#didomi-notice-agree-button",
    "button[aria-label*='Aceptar']",
    "button:has-text('Aceptar')",
    "button:has-text('Acepto')",
    "button:has-text('Aceptar todas')",
]

class ComputrabajoScraper:
    def __init__(
        self,
        browser: Browser,
        categoria: str,
        lugar: str,
        max_pages: Optional[int] = None,
        job_id: Optional[str] = None,
    ):
        self.browser = browser
        self.categoria = categoria.strip().lower().replace(' ', '-')
        self.lugar = lugar.strip().lower().replace(' ', '-')
        self.max_pages = max_pages
        self.job_id = job_id
        # Usar pantalla completa
        self.context = browser.new_context(viewport=None,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            ignore_https_errors=True
        )
        self.page: Page = self.context.new_page()
        self.results: List[Dict[str, Any]] = []
        # Manejar diálogos automáticamente
        self.page.on("dialog", lambda dialog: dialog.dismiss())

    def run(self) -> List[Dict[str, Any]]:
        self._open_search()
        page_num = 1

        while True:
            if self.job_id and ask_to_stop(self.job_id):
                get_logger().info("Scraping detenido por usuario")
                break

            links = self._scrape_listing()
            for url in links:
                if self.job_id and ask_to_stop(self.job_id):
                    break
                try:
                    data = self._scrape_detail(url)
                    self.results.append(data)
                    if self.job_id:
                                push_result(self.job_id, data)
                except Exception:
                            # Atrapa la excepción pero no hace nada,
                            # simplemente continúa con el siguiente URL.
                            pass

            if self.job_id and ask_to_stop(self.job_id):
                break
            if self.max_pages and page_num >= self.max_pages:
                break

            page_num += 1
            if not self._go_next():
                break

        self.context.close()
        return self.results

    def _open_search(self) -> None:
        slug = f"trabajo-de-{self.categoria}-en-{self.lugar}"
        url = ul.urljoin(BASE_URL, slug)
        self.page.goto(url, timeout=TIMEOUT)
        self.page.wait_for_selector(LISTING_LINK, timeout=TIMEOUT)
        self._handle_popups()

    def _scrape_listing(self) -> List[str]:
        self.page.wait_for_selector(LISTING_LINK, timeout=TIMEOUT)
        self._handle_popups()
        urls: List[str] = []
        for el in self.page.locator(LISTING_LINK).all():
            href = el.get_attribute("href") or ""
            full = ul.urljoin(self.page.url, href.split("#")[0])
            if '/ofertas-de-trabajo/' in full:
                urls.append(full)
        return sorted(set(urls))

    def _scrape_detail(self, url: str) -> Dict[str, Any]:
        self.page.goto(url, timeout=TIMEOUT)
        self.page.wait_for_selector(DETAIL_PANEL, timeout=TIMEOUT)
        self._handle_popups()
        panel = self.page.locator(DETAIL_PANEL).first

        data: Dict[str, Any] = {'url': url}
        # Título
        data['titulo'] = panel.locator("h1").first.inner_text().strip()
        # Empresa y Ubicación
        info = panel.locator("div.container p.fs16").first.inner_text().strip()
        if " - " in info:
            empresa, ubicacion = info.split(" - ", 1)
        else:
            empresa, ubicacion = info, ''
        data['empresa'] = empresa.strip()
        data['ubicacion'] = ubicacion.strip()

        # Salario, contrato, jornada y modalidad
        tags = panel.locator("div.mbB span.tag").all()
        tag_texts = [tag.inner_text().strip() for tag in tags]
        data['salario'] = tag_texts[0] if len(tag_texts) > 0 else ''
        data['contrato'] = tag_texts[1] if len(tag_texts) > 1 else ''
        data['jornada'] = tag_texts[2] if len(tag_texts) > 2 else ''
        data['modalidad'] = tag_texts[3] if len(tag_texts) > 3 else ''

        # Descripción
        data['descripcion'] = panel.locator("div[div-link=\"oferta\"] p.mbB").first.inner_text().strip()
        # Requerimientos
        reqs = panel.locator("ul.disc.mbB li")
        data['requerimientos'] = [li.inner_text().strip() for li in reqs.all()] if reqs.count() else []

        # Fecha de publicación
        pubs = panel.locator("div[div-link=\"oferta\"] p.fc_aux.fs13").all()
        if pubs:
            texto_pub = pubs[-1].inner_text().strip()
            data['publicado'] = texto_pub
            data['fecha_publicacion'] = parse_fecha_publicacion(texto_pub)
        else:
            data['publicado'] = ''
            data['fecha_publicacion'] = ''


        # Volver al listado
        self.page.go_back()
        self.page.wait_for_selector(LISTING_LINK, timeout=TIMEOUT)
        self._handle_popups()

        return data

    def _go_next(self) -> bool:
        try:
            btn = self.page.locator(NEXT_BTN).first
            if btn.count() and btn.is_visible():
                next_path = btn.get_attribute("data-path")
                # si data-path ya es URL absoluta, quita ul.urljoin
                next_url = ul.urljoin(BASE_URL, next_path)
                self.page.goto(next_url, timeout=TIMEOUT)
                self.page.wait_for_selector(LISTING_LINK, timeout=TIMEOUT)
                self._handle_popups()
                return True
        except TimeoutError:
            pass
        return False


    def _handle_popups(self) -> None:
        for sel in POPUP_SELECTORS:
            try:
                btn = self.page.locator(sel).first
                if btn.is_visible():
                    btn.click(timeout=3000)
            except:
                continue
