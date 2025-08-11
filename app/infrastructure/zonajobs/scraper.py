from __future__ import annotations
import re
import json
import time
import unicodedata
import urllib.parse as ul
from typing import Any, Dict, List, Optional

from playwright.sync_api import Browser, Page, TimeoutError as PWTimeoutError, Error as PWError

from app.infrastructure.utils import parse_fecha_publicacion
from app.infrastructure.common.logging_utils import get_logger
from app.scraper.application.scraper_control import ask_to_stop, push_result

try:
    from app.application.scraper_control import ask_to_stop, push_result  # type: ignore
except ModuleNotFoundError:
    try:
        from scraper_control import ask_to_stop, push_result  # type: ignore
    except ModuleNotFoundError:
        def ask_to_stop(job_id: str) -> bool:
            return False
        def push_result(job_id: str, item: dict) -> None:
            pass

from urllib.parse import urlparse, unquote

BAD_TITLE = re.compile(r"(?:^|\b)(descripci[oó]n del puesto|publicado|actualizado)\b", re.I)

def _slug_title_from_url(url: str) -> str:
    """Deriva un título legible a partir del slug de la URL de detalle."""
    try:
        path = urlparse(url).path.rstrip("/")
        last = path.split("/")[-1] if path else ""
        if not last:
            return ""
        last = last.split("?")[0].split("#")[0]
        last = re.sub(r"\.html?$", "", last, flags=re.I)    # quita .html
        last = re.sub(r"-\d+$", "", last)                  # quita -<id>
        title = unquote(last).replace("-", " ")
        title = re.sub(r"\s+", " ", title).strip()
        return title
    except ValueError:
        return ""

def _is_reasonable_title(s: str) -> bool:
    s = (s or "").strip()
    if not s or BAD_TITLE.search(s):
        return False
    if not re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]", s):
        return False
    return 3 <= len(s) <= 140

def _pick_title(texts: list[str]) -> str:
    seen, cleaned = set(), []
    for t in (t.strip() for t in texts if t):
        t = re.sub(r"\s+", " ", t)
        if t and t not in seen:
            seen.add(t)
            cleaned.append(t)
    for t in cleaned:
        if _is_reasonable_title(t):
            return t
    return max(cleaned, key=len, default="")

def _extract_title(dp: Page, url: str, detail_container: str = "#section-detalle") -> str:
    """Intenta varias estrategias para obtener el título; último recurso: URL."""
    selectors = [
        f"{detail_container} h1",
        f"{detail_container} h2",
        "main h1, article h1, header h1, h1",
        "main h2, article h2, header h2, h2",
    ]
    for sel in selectors:
        try:
            loc = dp.locator(sel)
            if not loc.count():
                continue
            try:
                texts = loc.all_inner_texts()
            except PWError:
                texts = []
            if not texts:
                try:
                    texts = dp.eval_on_selector_all(
                        sel, "els => els.map(e => (e.textContent || '').trim()).filter(Boolean)"
                    )
                except PWError:
                    texts = []
            chosen = _pick_title(texts)
            if chosen:
                return chosen
        except PWError:
            continue
    return _slug_title_from_url(url)
# ──────────────────────────────────────────────────────────────────────────────
# Constantes / Selectores
# ──────────────────────────────────────────────────────────────────────────────
BASE_URL = "https://www.zonajobs.com.ar/"

# En listados hemos visto anclas con clases utilitarias tipo .sc-....;
# además, los href de detalle tienen el patrón /empleos/<slug>-<id>.html
LISTING_SCOPE = "#listado-avisos"
LISTING_ANCHORS = f"{LISTING_SCOPE} a[href*='/empleos/']"

# Patrón URL de detalle (más estricto que un contains)
DETAIL_URL_RE = re.compile(r"/empleos/[^/]+-\d+\.html$", re.IGNORECASE)

# En detalle el portal suele renderizar un contenedor principal
DETAIL_CONTAINER = "#section-detalle"

# Paginación: botones y/o links con números; mantenemos 2 estrategias

PAGER_CONTAINER = ".sc-kJdAmE"        # contenedor del paginador (ajústalo si difiere)
PAGER_LINKS     = f"{PAGER_CONTAINER} a"
NEXT_BTN_SELECTOR = "a[aria-label='Siguiente'], a[rel='next'], a.sc-dzVpKk.hFOZsP"

# Timeout base (ms)
TIMEOUT = 25_000


# ──────────────────────────────────────────────────────────────────────────────
# Utilidades mínimas
# ──────────────────────────────────────────────────────────────────────────────
def _slugify(text: str) -> str:
    norm = unicodedata.normalize("NFKD", text)
    ascii_ = norm.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-")


def _build_search_url(query: str, location: str, page: int = 1) -> str:
    # ZonaJobs acepta estructuras tipo:
    #   /empleos.html?recientes=true&palabra=<q>&zona=<loc>&page=<n>
    # Donde ‘palabra’ y ‘zona’ suelen tolerar valores vacíos.
    params = []
    if query:
        params.append(("palabra", query))
    if location:
        params.append(("zona", location))
    params.append(("recientes", "true"))
    params.append(("page", str(page)))
    return ul.urljoin(BASE_URL, f"empleos.html?{ul.urlencode(params)}")


# ──────────────────────────────────────────────────────────────────────────────
# Scraper
# ──────────────────────────────────────────────────────────────────────────────
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
        self.query = (query or "").strip()
        self.location = (location or "").strip()
        self.max_pages = max_pages
        self.job_id = job_id or ""

        # Contexto de ventana completa + UA común para evitar variantes raras
        self.context = browser.new_context(
            viewport=None,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        )
        self.page: Page = self.context.new_page()

        self.results: List[Dict[str, Any]] = []
        self.base_url: Optional[str] = None

        # Descartar cualquier diálogo
        self.page.on("dialog", lambda d: d.dismiss())

    # ── Flujo principal ───────────────────────────────────────────────────────
    def run(self) -> List[Dict[str, Any]]:
        """Itera sobre el listado de avisos y acumula los datos extraídos."""
        self._open_listing()
        page_num = 1
        total_pages = self._get_total_pages_safe()
        get_logger().info("Total de páginas detectado: %s", total_pages)

        # respetar max_pages si lo pasan
        if self.max_pages:
            total_pages = min(total_pages, self.max_pages)

        while page_num <= total_pages:
            if self._should_stop():
                break

            get_logger().debug("Scrapeando página %s/%s", page_num, total_pages)
            hrefs = self._get_listing_hrefs(page_num)

            if not hrefs:
                # Reintento suave (pantallas con loaders)
                self.page.reload(wait_until="domcontentloaded")
                self.page.wait_for_timeout(1200)
                hrefs = self._get_listing_hrefs(page_num)

            for url in hrefs:
                if self._should_stop():
                    break
                try:
                    data = self._scrape_detail(url)
                    if data:
                        self.results.append(data)
                        if self.job_id:
                            push_result(self.job_id, data)
                except (PWError, RuntimeError, ValueError) as exc:
                    get_logger().warning("Detalle %s falló: %s", url, exc)

            if self._should_stop():
                break

            page_num += 1
            if page_num <= total_pages:
                if not self._go_to_page(page_num):
                    # Si la paginación falla, intentamos construir URL directa
                    fallback = _build_search_url(self.query, self.location, page=page_num)
                    try:
                        self.page.goto(fallback, timeout=TIMEOUT, wait_until="domcontentloaded")
                    except PWTimeoutError:
                        get_logger().warning("Timeout al ir a %s. Cortando.", fallback)
                        break

        self.context.close()
        return self.results

    # ── Helpers de control ────────────────────────────────────────────────────
    def _should_stop(self) -> bool:
        return bool(self.job_id and ask_to_stop(self.job_id))

    def _close_cookie_banner(self) -> None:
        # Intento genérico de cierre de cookies (varias variantes típicas)
        for sel in [
            "button#onetrust-accept-btn-handler",
            "button:has-text('Aceptar todas')",
            "button:has-text('Aceptar')",
            "text=/Acepto|De acuerdo|OK/i",
        ]:
            try:
                btn = self.page.locator(sel).first
                if btn.count() and btn.is_visible():
                    btn.click(timeout=1000)
                    break
            except PWError:
                pass

    # ── Arranque / listado ────────────────────────────────────────────────────
    def _open_listing(self) -> None:
        # Si pasan query o location usamos URL parametrizada; si no, recientes
        if self.query or self.location:
            url = _build_search_url(self.query, self.location, page=1)
        else:
            url = ul.urljoin(BASE_URL, "empleos.html?recientes=true&page=1")

        get_logger().debug("Abriendo listado: %s", url)
        self.page.goto(url, timeout=TIMEOUT, wait_until="domcontentloaded")
        self._close_cookie_banner()

        # Ancla robusta: contenedor de avisos o cualquier <a> con /empleos/
        try:
            self.page.wait_for_selector(
                f"{LISTING_SCOPE}, {LISTING_ANCHORS}",
                timeout=TIMEOUT,
                state="attached",
            )
        except PWTimeoutError:
            # fallback: intentar de nuevo con recientes
            fallback = ul.urljoin(BASE_URL, "empleos.html?recientes=true&page=1")
            get_logger().warning("Fallback a %s", fallback)
            self.page.goto(fallback, timeout=TIMEOUT, wait_until="domcontentloaded")
            self.page.wait_for_selector(LISTING_ANCHORS, timeout=TIMEOUT)

        self.base_url = self.page.url

    def _get_total_pages_safe(self) -> int:
        try:
            return self._get_total_pages()
        except PWError:
            return 1

    def _get_total_pages(self) -> int:
        # 1) Esperá que aparezca el paginador (si existe); si no, 1
        try:
            self.page.wait_for_selector(PAGER_CONTAINER, timeout=5_000, state="attached")
        except PWError:
            return 1

        pager = self.page.locator(PAGER_CONTAINER)
        if not pager.count():
            return 1

        nums = []

        # 2) Recorre TODOS los <a> del paginador
        for a in self.page.locator(PAGER_LINKS).all():
            try:
                # a) número visible (por si viene en <span> dentro del <a>)
                txt = (a.inner_text() or "").strip()
                # puede venir "1", "2", "Siguiente", etc.
                for m in re.findall(r"\b\d+\b", txt):
                    nums.append(int(m))

                # b) número en el href (?page=74, &page=3, etc.)
                href = a.get_attribute("href") or ""
                m = re.search(r"[?&]page=(\d+)\b", href)
                if m:
                    nums.append(int(m.group(1)))
            except PWError:
                continue

        # 3) Filtra basura: ignorá anchors deshabilitados con href="#"
        nums = [n for n in nums if n > 0]

        return max(nums) if nums else 1

    # ── Scrape de listado ─────────────────────────────────────────────────────
    def _get_listing_hrefs(self, page_index: int) -> List[str]:
        """Devuelve URLs únicas de detalle confiables para la página actual."""
        # Esperar algo de contenido en el listado
        try:
            self.page.wait_for_selector(LISTING_ANCHORS, timeout=8_000)
        except PWTimeoutError:
            # Puede estar cargando; intentamos un ciclo corto de espera incremental
            waited = 0.0
            urls: List[str] = []
            while waited < 6.0:
                anchors = self.page.locator(LISTING_ANCHORS)
                if anchors.count():
                    urls = anchors.evaluate_all("els => Array.from(new Set(els.map(e => e.href)))")
                    urls = [u for u in urls if DETAIL_URL_RE.search(u or "")]
                    if urls:
                        break
                time.sleep(0.5)
                waited += 0.5
            return sorted(urls)

        anchors = self.page.locator(LISTING_ANCHORS)
        raw = anchors.evaluate_all("els => Array.from(new Set(els.map(e => e.href)))")
        urls = [u for u in raw if u and DETAIL_URL_RE.search(u)]
        return sorted(urls)

    # ── Helpers de detalle ────────────────────────────────────────────────────
    def _parse_company(self, dp: Page) -> str:
        """Obtiene el nombre de la empresa si está disponible."""
        try:
            org_name = dp.evaluate(
                """
                    () => {
                    const blocks = Array.from(document.querySelectorAll('script[type="application/ld+json"]'));
                    for (const b of blocks) {
                        try {
                        const j = JSON.parse(b.textContent || '{}');
                        const n = j?.hiringOrganization?.name || j?.organization?.name || j?.publisher?.name;
                        if (n && typeof n === 'string') return n.trim();
                        } catch(e) {}
                    }
                    return null;
                    }
                """
            )
        except PWError:
            org_name = None

        empresa_txt = None
        candidatos = [
            "a[href*='/perfiles/empresa']",
            ".sc-gDrLyk",
            "[data-testid*='company']",
            "header .company, .company-name",
        ]
        for sel in candidatos:
            try:
                loc = dp.locator(sel).first
                if loc.count():
                    loc.wait_for(state="visible", timeout=3000)
                    t = (loc.inner_text() or "").strip()
                    if t and t.lower() not in {"", "ver más", "postularme"}:
                        empresa_txt = t
                        break
            except (PWError, PWTimeoutError):
                continue

        if not empresa_txt:
            try:
                loc_conf = dp.get_by_text(re.compile(r"\bConfidencial\b", re.I)).first
                if loc_conf.count():
                    empresa_txt = (loc_conf.inner_text() or "").strip()
            except PWError:
                pass

        return org_name or empresa_txt or ""

    def _parse_publication_date(self, dp: Page) -> tuple[str, Optional[str]]:
        """Extrae el texto de publicación y su fecha parseada."""
        pub_loc = dp.locator("#section-detalle *").filter(
            has_text=re.compile(r"(Publicado|Actualizado)", re.I)
        ).last
        txt_pub = ""
        if pub_loc.count():
            try:
                txt_pub = pub_loc.inner_text().strip()
            except PWError:
                pass
        return txt_pub, parse_fecha_publicacion(txt_pub)

    def _parse_location(self, dp: Page) -> str:
        """Obtiene la ubicación del aviso."""
        ubi_loc = dp.locator(
            "#section-detalle a[href*='/empleos'] h2, "
            "#section-detalle a[href*='/en-'] h2, "
            "#section-detalle i[name='icon-light-location-pin'] ~ * h2",
        ).first
        if not ubi_loc.count():
            return ""
        try:
            return ubi_loc.inner_text().strip()
        except PWError:
            return ""

    def _parse_description(self, dp: Page) -> str:
        """Compila los párrafos de la descripción del puesto."""
        p_nodes = dp.locator(
            "#section-detalle .sc-boLwTQ p, "
            "#section-detalle p.sc-boLwTQ p, "
            "#section-detalle .sc-bGXeph ~ p, "
            "#section-detalle article p, "
            "#section-detalle main p",
        )

        parrafos: List[str] = []
        for el in p_nodes.all():
            try:
                t = el.inner_text().strip()
                if not t:
                    continue
                if re.fullmatch(r"(Descripción del puesto|Postulación rápida)\s*", t, re.I):
                    continue
                parrafos.append(t)
            except PWError:
                continue

        seen: set[str] = set()
        limpio: List[str] = []
        for t in parrafos:
            if t not in seen:
                seen.add(t)
                limpio.append(t)
        return "\n\n".join(limpio)

    def _parse_benefits(self, dp: Page) -> List[str]:
        """Obtiene la lista de beneficios si está presente."""
        try:
            chip_ps = dp.locator(f"{DETAIL_CONTAINER} ul.sc-didJYH li p")
            texts = [t.strip() for t in chip_ps.all_inner_texts() if t and t.strip()]
            if not texts:
                chip_links = dp.locator(f"{DETAIL_CONTAINER} ul.sc-didJYH li a")
                texts = [t.strip() for t in chip_links.all_inner_texts() if t and t.strip()]
            return texts
        except PWError:
            return []

    def _parse_tags(self, dp: Page) -> List[str]:
        """Recupera los tags asociados al aviso."""
        try:
            tags_txt = dp.locator(
                "#section-detalle a[href*='/empleos-'], "
                "#section-detalle a[href*='/empleos/'], "
                "#section-detalle a[href*='/en-']",
            ).all_inner_texts()
            return sorted({t.strip() for t in tags_txt if t and t.strip()})
        except PWError:
            return []

    def _scrape_detail(self, url: str) -> Dict[str, Any]:
        """Scrapea un aviso de ZonaJobs (detalle)."""
        data: Dict[str, Any] = {"url": url}

        # Validación rápida de URL de detalle
        if not DETAIL_URL_RE.search(url):
            data["error"] = "url_no_parece_detalle"
            return data

        # Stop cooperativo
        try:
            if hasattr(self, "_should_stop") and self._should_stop():
                raise RuntimeError("Scraping detenido por usuario")
            if self.job_id and ask_to_stop(self.job_id):
                raise RuntimeError("Scraping detenido por usuario")
        except RuntimeError as e:
            data["error"] = str(e)
            return data

        dp = self.context.new_page()
        try:
            # Carga inicial
            dp.goto(url, timeout=TIMEOUT, wait_until="domcontentloaded")

            # Espera robusta: contenedor o al menos un h1/h2 visible
            try:
                dp.wait_for_selector(DETAIL_CONTAINER, timeout=TIMEOUT, state="attached")
            except PWTimeoutError:
                # Fallback a cabecera mínima
                dp.wait_for_selector("h1, h2", timeout=TIMEOUT, state="visible")

            # Espera a que haya al menos un H1 visible en la página
            try:
                dp.wait_for_selector("h1", timeout=12_000, state="visible")
            except PWTimeoutError:
                # Fallback a role (por si el sitio arma el H1 de otra forma)
                try:
                    dp.get_by_role("heading", level=1).first.wait_for(state="visible", timeout=6_000)
                except PWTimeoutError:
                    pass

            # Selector robusto: primero H1 visible; si no, role heading nivel 1; último recurso, cualquier H1
            title_loc = (
                dp.locator("h1:visible").first
                if dp.locator("h1:visible").count()
                else dp.get_by_role("heading", level=1).first
                if dp.get_by_role("heading", level=1).count()
                else dp.locator("h1").first
            )

            titulo_txt = ""
            if title_loc and title_loc.count():
                # text_content es menos propenso a forzar layout que inner_text y suele alcanzar
                titulo_txt = (title_loc.text_content() or "").strip()

            data["titulo"] = titulo_txt or _slug_title_from_url(url)

            data["empresa"] = self._parse_company(dp)
            pub_txt, pub_date = self._parse_publication_date(dp)
            data["publicado"] = pub_txt
            data["fecha_publicacion"] = pub_date
            data["ubicacion"] = self._parse_location(dp)
            data["descripcion"] = self._parse_description(dp)
            data["beneficios"] = self._parse_benefits(dp)
            data["tags"] = self._parse_tags(dp)

            return data

        except PWTimeoutError:
            data["error"] = "timeout_detalle"
            return data
        finally:
            try:
                dp.close()
            except PWError:
                pass
    # ── Paginación ────────────────────────────────────────────────────────────
    def _go_to_page(self, page_number: int) -> bool:
        """Intenta navegar a la página N usando el propio paginador; si no hay, devuelve False."""
        try:
            # 1) Intento click en botón/liga 'Siguiente' si el número siguiente es consecutivo.
            #    Si no, intentamos click directo en el número de página.
            pager = self.page.locator(PAGER_CONTAINER)
            if not pager.count():
                return False

            # Click directo al número de página
            num_link = self.page.locator(
                f"{PAGER_LINKS}:has-text('{page_number}')"
            ).first
            if num_link.count() and num_link.is_enabled():
                num_link.click()
            else:
                # fallback: Siguiente
                next_btn = self.page.locator(NEXT_BTN_SELECTOR).first
                if next_btn.count() and next_btn.is_enabled():
                    next_btn.click()
                else:
                    return False

            # Espera a que cambie el contenido del listado
            self.page.wait_for_selector(LISTING_ANCHORS, timeout=TIMEOUT)
            return True
        except PWTimeoutError:
            return False
