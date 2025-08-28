from __future__ import annotations
import re
import json
import time
import unicodedata
import urllib.parse as ul
from typing import Any, Dict, List, Optional
from playwright.sync_api import BrowserContext, Page, TimeoutError as PWTimeoutError
from app.infrastructure.utils import parse_fecha_publicacion
from app.infrastructure.common.logging_utils import get_logger

try:
    from app.scraper.application.scraper_control import ask_to_stop, push_result  # type: ignore
except Exception:
    try:
        from scraper_control import ask_to_stop, push_result  # type: ignore
    except Exception:
        def ask_to_stop(job_id: str) -> bool:
            return False
        def push_result(job_id: str, item: dict) -> None:
            pass

import re
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
    except Exception:
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
            except Exception:
                texts = []
            if not texts:
                try:
                    texts = dp.eval_on_selector_all(
                        sel, "els => els.map(e => (e.textContent || '').trim()).filter(Boolean)"
                    )
                except Exception:
                    texts = []
            chosen = _pick_title(texts)
            if chosen:
                return chosen
        except Exception:
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


def _build_search_url(query: str, location: str) -> str:
    """
    Construye la URL de búsqueda para ZonaJobs, con manejo especial
    para la estructura jerárquica de Capital Federal.
    """
    path_parts = []

    # Lógica de ubicación corregida
    if location == "Capital Federal":
        # 1. Caso especial: si la ubicación es "Capital Federal",
        #    se usa la ruta jerárquica correcta.
        path_parts.append("en-buenos-aires/capital-federal")
    elif location:
        # 2. Para cualquier otra ubicación, se mantiene la lógica original.
        slug_location = _slugify(location)
        path_parts.append(f"en-{slug_location}")

    # La lógica para la consulta (query) no necesita cambios
    if query:
        slug_query = _slugify(query)
        path_parts.append(f"empleos-busqueda-{slug_query}.html")
    else:
        path_parts.append("empleos.html")
    
    # Se unen las partes para formar la URL final
    search_path = "/".join(path_parts)
    return ul.urljoin(BASE_URL, search_path)

# ──────────────────────────────────────────────────────────────────────────────
# Scraper
# ──────────────────────────────────────────────────────────────────────────────
class ZonaJobsScraper:
    def __init__(
        self,
        context: BrowserContext, 
        query: str = "",
        location: str = "",
        max_pages: Optional[int] = None,
        job_id: Optional[str] = None,
    ) -> None:
        self.context = context 
        self.query = (query or "").strip()
        self.location = (location or "").strip()
        self.max_pages = max_pages
        self.job_id = job_id or ""
        

        self.page: Page = self.context.new_page()
        self.results: List[Dict[str, Any]] = []
        self.base_url: Optional[str] = None
        self.page.on("dialog", lambda d: d.dismiss())
        
    def _go_next(self) -> bool:
            """
            Busca el botón 'Siguiente', hace clic en él y espera a que la página cargue.
            Devuelve True si tuvo éxito, False en caso contrario.
            """
            # Selector robusto para el botón 'Siguiente' basado en el ícono que contiene.
            # Esto es más estable que usar las clases autogeneradas como 'sc-hBcjXN'.
            next_button_selector = "a:has(i[name='icon-light-caret-right'])"
            
            try:
                next_btn = self.page.locator(next_button_selector).first
                
                # Comprueba si el botón existe y no está deshabilitado.
                if next_btn.count() and next_btn.is_enabled():
                    get_logger().info("Pasando a la página siguiente...")
                    
                    # Hacemos clic y esperamos a que la URL cambie.
                    # Esto confirma que la navegación se ha iniciado.
                    current_url = self.page.url
                    next_btn.click()
                    
                    # Espera a que la URL sea diferente a la actual.
                    self.page.wait_for_url(lambda url: url != current_url, timeout=15000)
                    
                    # Pequeña espera adicional para que el contenido se asiente.
                    self.page.wait_for_load_state("domcontentloaded")
                    
                    return True
                else:
                    # Si no hay botón de 'Siguiente' o está deshabilitado, es la última página.
                    get_logger().info("No se encontró un botón 'Siguiente' activo. Fin de la paginación.")
                    return False
                    
            except Exception as e:
                get_logger().error("Error al intentar pasar a la página siguiente: %s", e)
                return False    

    # ── Flujo principal ───────────────────────────────────────────────────────
    def run(self) -> List[Dict[str, Any]]:
        self._open_listing()
        page_num = 1
        STEP_TIMEOUT = min(self.page.timeout, 8_000) if hasattr(self.page, "timeout") else 8_000

        while True:
            if self.job_id and ask_to_stop(self.job_id):
                get_logger().info("Scraping detenido por usuario (antes de listar).")
                break

            links = self._get_listing_hrefs(page_num)
            for url in links:
                if self.job_id and ask_to_stop(self.job_id):
                    get_logger().info("Cancelado durante el bucle de avisos.")
                    break
                try:
                    data = self._scrape_detail(url, step_timeout=STEP_TIMEOUT)
                    # Solo procesamos si 'data' es un diccionario válido y no tiene errores.
                    if isinstance(data, dict) and "error" not in data:
                        self.results.append(data)
                        if self.job_id:
                            push_result(self.job_id, data)
                except Exception as e:
                    # Se captura el error inesperado, pero solo se registra a nivel DEBUG
                    # para no llenar la consola con warnings. El scraping continúa.
                    get_logger().debug("Detalle %s falló con error no crítico: %s", url, e)

            if self.job_id and ask_to_stop(self.job_id):
                break
            if self.max_pages and page_num >= self.max_pages:
                break

            page_num += 1
            try:
                if not self._go_next():
                    break
            except Exception:
                break

        # flush final (por si quedaron items sin snapshot)
        if self.job_id:
            try:
                from app.scraper.application.scraper_control import set_result
                set_result(self.job_id, list(self.results))
            except Exception:
                pass

        self.context.close()
        return self.results
    # ── Helpers de control ────────────────────────────────────────────────────
    def _should_stop(self) -> bool:
        return bool(self.job_id and ask_to_stop(self.job_id))
    
    def _flush_partial(self, every: int = 5) -> None:
        """Guarda un snapshot parcial en memoria compartida cada N items."""
        if not self.job_id:
            return
        # cada N resultados, publicamos un snapshot completo
        if len(self.results) % every == 0:
            try:
                from app.scraper.application.scraper_control import set_result  # import local para evitar ciclos
                set_result(self.job_id, list(self.results))  # copia por seguridad
            except Exception:
                pass

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
            except Exception:
                pass

    # ── Arranque / listado ────────────────────────────────────────────────────
    def _open_listing(self) -> None:
        # Si pasan query o location usamos URL parametrizada; si no, recientes
        if self.query or self.location:
            url = _build_search_url(self.query, self.location)
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

    def _scrape_detail(self, url: str, step_timeout: int = 6000) -> Dict[str, Any]:
        """Scrapea un aviso de ZonaJobs (detalle) con cancelación cooperativa."""
        data: Dict[str, Any] = {"url": url}

        if not DETAIL_URL_RE.search(url):
            data["error"] = "url_no_parece_detalle"
            return data

        if self.job_id and ask_to_stop(self.job_id):
            data["error"] = "cancelado"
            return data

        dp = self.context.new_page()
        try:
            dp.set_default_timeout(step_timeout)

            # Navegación con tolerancia
            try:
                dp.goto(url, timeout=step_timeout, wait_until="domcontentloaded")
            except PWTimeoutError:
                pass  # seguimos intentando leer algo útil

            if self.job_id and ask_to_stop(self.job_id):
                data["error"] = "cancelado"
                return data

            # Espera mínima: contenedor o algún H1/H2 visible
            try:
                dp.wait_for_selector(DETAIL_CONTAINER, timeout=step_timeout, state="attached")
            except PWTimeoutError:
                try:
                    dp.wait_for_selector("h1, h2", timeout=step_timeout, state="visible")
                except PWTimeoutError:
                    data["error"] = "timeout_detalle"
                    return data

            # ─────────────────────────────────────────────
            # TÍTULO (prioriza h1.sc-ggcyCb; luego h1; luego heurística)
            # ─────────────────────────────────────────────
            try:
                dp.wait_for_selector(
                    "#section-detalle h1.sc-ggcyCb:visible, h1.sc-ggcyCb:visible, "
                    "#section-detalle h1:visible, h1:visible",
                    timeout=min(8000, step_timeout),
                    state="visible",
                )
            except Exception:
                pass

            title_loc = dp.locator(
                "#section-detalle h1.sc-ggcyCb, h1.sc-ggcyCb, "
                "#section-detalle h1, h1"
            ).first

            titulo_txt = (title_loc.inner_text().strip() if title_loc.count() else "")
            if not titulo_txt:
                # fallback a tu heurística existente
                titulo_txt = _extract_title(dp, url) or _slug_title_from_url(url)
            data["titulo"] = titulo_txt

            if self.job_id and ask_to_stop(self.job_id):
                data["error"] = "cancelado"
                return data


            # ─────────────────────────────────────────────
            # EMPRESA (ZonaJobs: data-url + .sc-glwGys → slug → variantes → JSON-LD)
            # ─────────────────────────────────────────────
            empresa_txt: Optional[str] = None
            try:
                dp.wait_for_function("""
                () => {
                    const selA = document.querySelector("span[data-url^='/perfiles/empresa_'] .sc-glwGys");
                    const selB = document.querySelector("p.sc-ktJJTZ, p.sc-gCeyOJ, p.sc-hyMgjL");
                    return (selA && selA.textContent && selA.textContent.trim().length > 0) ||
                        (selB && selB.textContent && selB.textContent.trim().length > 0);
                }
                """, timeout=7000)
            except Exception:
                pass

            empresa = None

            # 1) JSON-LD primero (si no dice confidencial)
            if not empresa:
                try:
                    org = dp.evaluate("""
                    () => {
                        for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
                        try {
                            const j = JSON.parse(s.textContent||'{}');
                            const n = j?.hiringOrganization?.name || j?.organization?.name || j?.publisher?.name;
                            if (n && typeof n === 'string') return n.trim();
                        } catch(e) {}
                        }
                        return null;
                    }
                    """)
                    if org and "confidencial" not in org.lower():
                        empresa = org
                except Exception:
                    pass

            # 2) XPaths en cascada
            def get_xpath(xp):
                try:
                    h = dp.locator(f"xpath={xp}").first
                    if h.count():
                        t = (h.inner_text() or h.text_content() or "").strip()
                        return t or None
                except Exception:
                    return None
                return None

            if not empresa:
                empresa = ( get_xpath("(//span[starts-with(@data-url,'/perfiles/empresa_')]//*[contains(@class,'sc-glwGys')])[1]")
                        or get_xpath("(//p[contains(@class,'sc-ktJJTZ') or contains(@class,'sc-gCeyOJ') or contains(@class,'sc-hyMgjL')])[1]")
                        or get_xpath("(//p[.//div[contains(@class,'company-verified')]])[1]")
                        or get_xpath("(//*[contains(normalize-space(.),'Seguir empresa')]/ancestor::*[self::div or self::section or self::header][1]/preceding::p[1])[1]") )

            # 3) Slug del perfil (último recurso)
            if not empresa:
                href = dp.eval_on_selector(
                    "xpath=(//*[@data-url and starts-with(@data-url,'/perfiles/empresa_')][1])",
                    "n => n.getAttribute('data-url')"
                ) or dp.eval_on_selector(
                    "xpath=(//a[starts-with(@href,'/perfiles/empresa_')][1])",
                    "n => n.getAttribute('href')"
                )
                if href:
                    import re
                    from urllib.parse import unquote
                    m = re.search(r"/perfiles/empresa_([a-z0-9\\-_]+)", href, re.I)
                    if m:
                        slug = unquote(m.group(1)).replace("-", " ").replace("_", " ").strip().title()
                        slug = re.sub(r"\\bS\\.?\\s*A\\.?\\b", "SA", slug, flags=re.I)
                        slug = re.sub(r"\\bS\\.?\\s*R\\.?\\s*L\\.?\\b", "SRL", slug, flags=re.I)
                        empresa = slug

            # 4) Confidencial
            if not empresa:
                c = get_xpath("(//*[contains(translate(.,'CONFIDENCIAL','confidencial'),'confidencial')])[1]")
                empresa = "Confidencial" if c else ""

            data["empresa"] = empresa or ""


            if self.job_id and ask_to_stop(self.job_id):
                data["error"] = "cancelado"
                return data

            # ─────────────────────────────────────────────
            # PUBLICADO / ACTUALIZADO (y parseo de fecha)
            # ─────────────────────────────────────────────
            pub_loc = dp.locator(
                "#section-detalle h2.sc-iKcCTQ, "
                "#section-detalle :has-text('Publicado'), "
                "#section-detalle :has-text('Actualizado')"
            ).first
            txt_pub = pub_loc.inner_text().strip() if pub_loc.count() else ""
            data["publicado"] = txt_pub
            data["fecha_publicacion"] = parse_fecha_publicacion(txt_pub)

            # ─────────────────────────────────────────────
            # UBICACIÓN (dos variantes comunes)
            # ─────────────────────────────────────────────
            try:
                ubi_loc = dp.locator(
                    "#section-detalle a:has(i[name='icon-light-location-pin']) h2, "
                    "#section-detalle p.sc-sJJJd"
                ).first
                data["ubicacion"] = ubi_loc.inner_text().strip() if ubi_loc.count() else ""
            except Exception:
                data["ubicacion"] = ""

            try:
                        # 1. Buscamos el encabezado "Descripción del puesto" como un ancla fiable.
                        description_header = dp.locator('h3:has-text("Descripción del puesto")').first
                        
                        descripcion_html = "" # Variable para guardar el resultado

                        # 2. Si encontramos el encabezado, procedemos a buscar el contenido
                        if description_header.count():
                            # El contenido real de la descripción suele estar en el elemento que le sigue.
                            # Usamos XPath para seleccionar el primer "hermano" que sigue al encabezado.
                            description_container = description_header.locator("xpath=./following-sibling::*[1]")
                            
                            if description_container.count():
                                # 3. Extraemos el HTML interno para preservar la estructura (<ul>, <p>, etc.).
                                raw_html = description_container.inner_html()
                                
                                # 4. Limpiamos el HTML de clases y estilos que no aportan información.
                                clean_html = re.sub(r'\s(class|style)="[^"]*"', '', raw_html)
                                descripcion_html = clean_html.strip()

                        # Fallback: Si no se encontró la descripción con el método anterior, usamos una versión más simple.
                        if not descripcion_html:
                            get_logger().debug("Fallback para descripción: buscando párrafos genéricos.")
                            container = dp.locator("#section-detalle").first
                            parrafos = [p.strip() for p in container.locator("p").all_inner_texts() if len(p.strip()) > 20]
                            
                            # Usamos tu lógica de de-duplicación original
                            seen: set[str] = set()
                            limpio: List[str] = []
                            for t in parrafos:
                                if t not in seen:
                                    seen.add(t)
                                    limpio.append(t)
                            descripcion_html = "\n\n".join(limpio)
                            
                        data["descripcion"] = descripcion_html

            except Exception as e:
                        get_logger().warning("No se pudo extraer la descripción: %s", e)
                        data["descripcion"] = ""

            return data

        except PWTimeoutError:
            data["error"] = "timeout_detalle"
            return data
        finally:
            try:
                dp.close()
            except Exception:
                pass