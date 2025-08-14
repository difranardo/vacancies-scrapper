from __future__ import annotations
import os
import urllib.parse as ul
from typing import Any, Dict, List
import re 
from typing import List
from playwright.sync_api import Browser, BrowserContext, Page, TimeoutError as PWTimeoutError
from app.infrastructure.utils import parse_fecha_publicacion
from app.infrastructure.common.logging_utils import get_logger
DETAIL_ID_RE = re.compile(r"/empleos/[^/]+-\d+\.html$", re.IGNORECASE)
try:
    # Intentamos la importación principal una sola vez.
    from app.scraper.application.scraper_control import ask_to_stop, push_result, set_result

except (ImportError, ModuleNotFoundError):
    def ask_to_stop(job_id: str) -> bool:
        return False

    def push_result(job_id: str, item: dict) -> None:
        pass

    def set_result(job_id: str, item: list) -> None:
        pass

DETAIL_URL_PATTERN = re.compile(r"/empleos-[\w-]+-\d+\.html$", re.IGNORECASE)
TIMEOUT = 15_000
BASE_URL = "https://www.bumeran.com.ar/"
BUM_USER = os.getenv("BUMERAN_USER", "")
BUM_PASS = os.getenv("BUMERAN_PASS", "")
# Selector de avisos basado en atributos más estables
LISTING_SELECTOR = "#listado-avisos a[href*='/empleos/']"
DETAIL_CONTAINER = "#section-detalle"
ZERO_JOBS_SEL = "span.sc-SxrYz.cBtoeQ:has-text('0')"
NEXT_BTN = "a:has(i[name='icon-light-caret-right'])"

class BumeranScraper:
    def __init__(
        self,
        context: BrowserContext,  # <-- 1. AHORA ESPERA 'context'
        query: str = "",
        location: str = "",
        max_pages: int | None = None,
        job_id: str | None = None,
        timeout: int = 15_000,
    ) -> None:
        self.context = context # <-- 2. USA EL CONTEXTO RECIBIDO
        self.query = query.strip()
        self.location = location.strip()
        self.max_pages = max_pages
        self.job_id = job_id or ""
        self.timeout = timeout
        
        # 3. YA NO SE CREA UN CONTEXTO AQUÍ

        self.list_page: Page = self.context.new_page()
        self.detail_page: Page = self.context.new_page()
        self.results: List[Dict[str, Any]] = []

    def run(self) -> List[Dict[str, Any]]:
        self._login_and_search()
        page_num = 1
        seen: set[str] = set()

        try:
            while True:
                if self.job_id and ask_to_stop(self.job_id):
                    get_logger().info("Scraping detenido por usuario.")
                    break

                if self.max_pages and page_num > self.max_pages:
                    break

                hrefs = self._get_listing_hrefs()
                if not hrefs:
                    break

                for url in hrefs:
                    if self.job_id and ask_to_stop(self.job_id):
                        break
                    if url in seen:
                        continue
                    try:
                        data = self._scrape_detail(url)
                        # Solo procesamos si 'data' es un diccionario válido
                        if isinstance(data, dict) and "error" not in data:
                            self.results.append(data)
                            seen.add(url)
                            if self.job_id:
                                push_result(self.job_id, data)
                    except AttributeError as attr_err:
                        # Si el error es el de 'append', lo ignoramos para no ensuciar el log.
                        if "'NoneType' object has no attribute 'append'" in str(attr_err):
                            pass # Ignorar silenciosamente este error específico.
                        else:
                            # Si es otro AttributeError, sí lo mostramos.
                            get_logger().warning("Error de atributo en %s: %s", url, attr_err)
                    except Exception as exc:
                        # Capturamos cualquier otra excepción inesperada.
                        get_logger().warning("Error inesperado en %s: %s", url, exc)


                next_page = page_num + 1
                if self.job_id and ask_to_stop(self.job_id):
                    break
                if self.max_pages and next_page > self.max_pages:
                    break
                if not self._go_to_page(next_page):
                    break
                page_num = next_page
        finally:
            # flush final
            if self.job_id:
                try:
                    from app.scraper.application.scraper_control import set_result
                    set_result(self.job_id, list(self.results))
                except Exception:
                    pass
            self.context.close()

        return self.results
    
    def _flush_partial(self, every: int = 5) -> None:
            """Guarda un snapshot parcial en memoria compartida cada N items."""
            if not self.job_id:
                return
            
            if len(self.results) % every == 0:
                try:
                    # ✅ CAMBIO: La línea 'from ... import set_result' se ha eliminado de aquí.
                    set_result(self.job_id, list(self.results))
                except Exception:
                    pass
    
    
    def _login_and_search(self) -> None:
        p = self.list_page

        # sube el default timeout solo para el arranque (páginas pesadas)
        old_timeout = self.timeout
        boot_timeout = max(self.timeout, 25_000)

        p.goto(BASE_URL, timeout=boot_timeout, wait_until="domcontentloaded")

        # 1) Intentar cerrar banner de cookies (varias variantes comunes)
        try:
            # OneTrust / genérico
            for sel in [
                "button#onetrust-accept-btn-handler",
                "button:has-text('Aceptar')",
                "button:has-text('Acepto')",
                "button:has-text('Aceptar todas')",
                "text=/Aceptar todas|Aceptar|De acuerdo/i",
            ]:
                loc = p.locator(sel).first
                if loc.count() and loc.is_visible():
                    loc.click(timeout=1500)
                    break
        except Exception:
            pass  # si no hay banner, seguimos

        # 2) Anclajes robustos: cualquiera que confirme que cargó la home/listado
        anchors = [
            "a[href*='/postulantes']",
            "#listado-avisos a[href*='/empleos-']",
            "div.select__placeholder:has-text('Buscar empleo')",
            "button.sc-btzYZH[type='link']",
            "form[action*='empleos']",
        ]

        # Espera a que aparezca alguno
        found = False
        for sel in anchors:
            try:
                p.wait_for_selector(sel, timeout=5_000, state="visible")
                found = True
                break
            except PWTimeoutError:
                continue

        if not found:
            # 3) Fallback: ir directo al listado reciente
            self.filtered_base_url = f"{BASE_URL}empleos.html?recientes=true"
            try:
                p.goto(f"{self.filtered_base_url}&page=1", timeout=boot_timeout)
                p.wait_for_selector(LISTING_SELECTOR, timeout=8_000, state="attached")
                found = True
            except PWTimeoutError:
                # 4) última chance: log para depurar y abortar
                try:
                    p.screenshot(path="bumeran_boot_timeout.png")
                    html = p.content()
                    with open("bumeran_boot_timeout.html", "w", encoding="utf-8") as fh:
                        fh.write(html)
                except Exception:
                    pass
                raise

        # 5) Si el usuario pasó query/ubicación, usamos el flujo con inputs
        if self.query or self.location:
            self.timeout = old_timeout  # volvemos al timeout normal
            self._buscar_con_inputs()
        else:
            # si ya estamos en listado, aseguramos base_url y seguimos
            if not getattr(self, "filtered_base_url", None):
                self.filtered_base_url = p.url
            p.wait_for_selector(LISTING_SELECTOR, timeout=self.timeout, state="attached")

        
    def _buscar_con_inputs(self) -> None:
        p = self.list_page

        # 1. Click placeholder de puesto PARA DESPERTAR EL INPUT
        if self.query:
            get_logger().debug("Click placeholder puesto")
            p.wait_for_selector("div.select__placeholder:has-text('Buscar empleo por puesto o palabra clave')", timeout=self.timeout)
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
            p.wait_for_selector("div.select__placeholder:has-text('Lugar de trabajo')", timeout=self.timeout)
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

       # 3) Click en "Buscar" y esperar resultados
        get_logger().debug("Click en buscar trabajo")

        boton_buscar = p.locator("button.sc-btzYZH[type='link']").first
        boton_buscar.scroll_into_view_if_needed()
        p.wait_for_timeout(200)  # micro-pausa para evitar misses

        navego = False
        try:
            with p.expect_navigation(wait_until="domcontentloaded", timeout=self.timeout):
                boton_buscar.click(force=True)
            navego = True
        except PWTimeoutError:
            # Puede ser un SPA: no navegó pero igual actualiza el listado.
            get_logger().debug("No hubo navegación; asumo SPA y sigo con wait_for_selector.")
            try:
                boton_buscar.click(force=True)  # segundo intento suave por si el primero no tomó
            except Exception:
                pass

        # En ambos casos, esperar a que aparezcan los avisos
        try:
            p.wait_for_selector(LISTING_SELECTOR, timeout=self.timeout)
            # opcional estabilizar un toque
            p.wait_for_timeout(300)
        except PWTimeoutError:
            get_logger().warning(
                "No aparecieron avisos tras buscar (navego=%s).", navego
            )

    def _get_listing_hrefs(self) -> List[str]:
        """Obtiene las URLs únicas de los avisos de empleo desde la página actual."""
        p = self.list_page

        # Espera que el listado esté presente
        p.wait_for_selector(LISTING_SELECTOR, timeout=self.timeout)

        # Extrae hrefs únicos
        raw_urls: List[str] = p.locator(LISTING_SELECTOR).evaluate_all(
            "els => Array.from(new Set(els.map(e => e.href)))"
        )

        # Filtra solo los que parecen ser detalles de aviso
        detail_urls = [u for u in raw_urls if DETAIL_ID_RE.search(u)]

        return sorted(detail_urls)

    def _scrape_detail(self, url: str) -> Dict[str, Any]:
        """
        Scrapea una página de detalle de Bumeran.
        Devuelve un dict con los campos esperados o un dict con 'error' si el detalle no está disponible.
        """
        data: Dict[str, Any] = {"url": url}

        # 0) Sanidad URL
        if not DETAIL_ID_RE.search(url):
            data["error"] = "url_no_parece_detalle"
            return data

        dp = self.detail_page

        # 1) Navegar y esperar señal mínima
        try:
            dp.goto(url, timeout=self.timeout, wait_until="domcontentloaded")
            dp.wait_for_function(
                """() => {
                    if (document.querySelector('#section-detalle')) return true;
                    if (document.querySelector('h1')) return true;
                    const txt = document.body ? document.body.innerText : '';
                    return /Aviso no disponible|No encontramos el aviso/i.test(txt);
                }""",
                timeout=self.timeout,
            )
        except PWTimeoutError:
            data["error"] = "timeout_cargando_detalle"
            return data

        # 2) Aviso no disponible (una sola vez)
        if dp.locator("text=/Aviso no disponible|No encontramos el aviso/i").count():
            data["error"] = "aviso_no_disponible"
            return data

        # ─────────────────────────────────────────────
        # Helpers chicos y robustos
        # ─────────────────────────────────────────────
        def _text(loc):
            return (loc.inner_text() or "").strip()

        def value_after_label(label_text: str) -> str:
            """
            Caso Bumeran: <div> <p>Label</p> <p>Valor</p> </div>
            1) CSS con :has + nth-of-type(2)
            2) Fallback XPath: p[label] -> siguiente p
            """
            sel = (
                f"{DETAIL_CONTAINER} div:has(> p:has-text('{label_text}')) > p:nth-of-type(2), "
                f"div:has(> p:has-text('{label_text}')) > p:nth-of-type(2)"
            )
            loc = dp.locator(sel).first
            if loc.count():
                return _text(loc)

            xp = f"xpath=(//p[normalize-space()='{label_text}'])[1]/following-sibling::p[1]"
            loc = dp.locator(xp).first
            return _text(loc) if loc.count() else ""

        # ── Título ───────────────────────────────────
        try:
            dp.wait_for_selector(f"{DETAIL_CONTAINER} h1:visible, h1:visible", timeout=8000)
        except Exception:
            pass
        titulo_loc = dp.locator(f"{DETAIL_CONTAINER} h1:visible, h1:visible").first
        data["titulo"] = _text(titulo_loc) if titulo_loc.count() else ""

        # ── Empresa ──────────────────────────────────
        # 1) Div típico observado: <div class="sc-dqbauf ...">Nombre</div>
        empresa_loc = dp.locator(f"{DETAIL_CONTAINER} .sc-dqbauf:visible, .sc-dqbauf:visible").first
        if not empresa_loc.count():
            # 2) "Confidencial"
            empresa_loc = dp.get_by_text(re.compile(r"\bConfidencial\b", re.I)).first
        if not empresa_loc.count():
            # 3) Link a perfil de empresa
            empresa_loc = dp.locator(f"{DETAIL_CONTAINER} a[href*='/empresa'], a[href*='/empresa']").first
        data["empresa"] = _text(empresa_loc) if empresa_loc.count() else ""

        # ── Publicado / Actualizado (opcional) ───────
        pub_nodes = dp.locator(
            f"{DETAIL_CONTAINER} :has-text('Publicado'), "
            f"{DETAIL_CONTAINER} :has-text('Actualizado'), "
            "h2:has-text('Publicado'), h2:has-text('Actualizado')"
        )
        texto_pub = _text(pub_nodes.last) if pub_nodes.count() else ""
        data["publicado"] = texto_pub
        data["fecha_publicacion"] = parse_fecha_publicacion(texto_pub)

        # ── Descripción ──────────────────────────────
        # Evitamos confundir labels (“Ubicación”, “Industria”) con descripción.
        desc_nodes = dp.locator(
            f"{DETAIL_CONTAINER} article p, {DETAIL_CONTAINER} main p, "
            f"{DETAIL_CONTAINER} .descripcion p, article p, main p"
        )
        if not desc_nodes.count():
            desc_nodes = dp.locator(f"{DETAIL_CONTAINER} p, p")
        parrafos: List[str] = []
        for el in desc_nodes.all():
            try:
                t = _text(el)
                if not t:
                    continue
                # Filtra labels obvios
                if re.fullmatch(r"(Ubicaci[oó]n|Industria|Publicado|Actualizado)\s*", t, re.I):
                    continue
                parrafos.append(t)
            except Exception:
                continue
        # de-dup manteniendo orden
        seen = set()
        texto_desc: List[str] = []
        for t in parrafos:
            if t not in seen:
                seen.add(t)
                texto_desc.append(t)
        data["descripcion"] = "\n\n".join(texto_desc)

        # ── Ubicación / Industria (pares label→valor) ─
        data["ubicacion"] = value_after_label("Ubicación") or value_after_label("Lugar de trabajo")
        data["industria"] = value_after_label("Industria")


        # ── Beneficios ───────────────────────────────
        try:
            dp.wait_for_selector(f"{DETAIL_CONTAINER} ul:has(li p), ul:has(li p)", timeout=8000)
            p_nodes = dp.locator(f"{DETAIL_CONTAINER} ul:has(li p) li p, ul:has(li p) li a p")
            texts = [t.strip() for t in p_nodes.all_inner_texts() if t and t.strip()]
            if not texts:
                li_nodes = dp.locator(f"{DETAIL_CONTAINER} ul li:visible, ul li:visible")
                texts = []
                for t in li_nodes.all_inner_texts():
                    t = (t or "").strip()
                    if t and t.lower() not in {"", "ver más", "postularme"} and len(t) > 2:
                        texts.append(t)
            # de-dup manteniendo orden
            seen = set()
            beneficios = []
            for t in texts:
                if t not in seen:
                    seen.add(t)
                    beneficios.append(t)
            data["beneficios"] = beneficios
        except Exception:
            data["beneficios"] = []

        return data
    
    def _go_to_page(self, num: int) -> bool:
        """Navega a la siguiente página esperando un cambio en la URL."""
        p = self.list_page
        
        # El selector original sigue siendo bueno porque se basa en el atributo 'name' del ícono.
        next_btn_locator = p.locator(NEXT_BTN).first

        # 1. Verificar si el botón "Siguiente" existe y está habilitado.
        if not next_btn_locator.count() or not next_btn_locator.is_enabled():
            get_logger().info("No se encontró un botón 'Siguiente' activo. Fin de la paginación.")
            return False

        try:
            # 2. Guardar la URL actual para asegurar que cambiemos a una nueva.
            current_url = p.url

            # 3. Hacer clic para navegar.
            next_btn_locator.click(force=True)

            # 4. Esperar a que la URL de la página cambie. Esta es la forma más
            #    confiable cuando el link tiene un href que modifica la URL.
            p.wait_for_url(lambda url: url != current_url, timeout=self.timeout)

            # 5. (Opcional pero recomendado) Esperar a que el contenedor de avisos
            #    vuelva a estar presente en la nueva página.
            p.wait_for_selector(LISTING_SELECTOR, state="attached", timeout=self.timeout)
            
            get_logger().info("Paginación a la página %d exitosa.", num)
            return True
            
        except Exception as e:
            # Si algo falla (ej. timeout), lo registramos y detenemos la paginación.
            get_logger().error("Error al paginar a la página %d: %s", num, e)
            return False
