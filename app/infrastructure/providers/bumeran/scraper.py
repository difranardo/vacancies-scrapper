from __future__ import annotations
import os
import urllib.parse as ul
from typing import Any, Dict, List
import re 
from typing import List
from playwright.sync_api import Browser, BrowserContext, Page, TimeoutError as PWTimeoutError
from app.infrastructure.utils import parse_fecha_publicacion
from app.infrastructure.common.logging_utils import get_logger
from playwright.sync_api import Page
from typing import Optional
from playwright.sync_api import Page
from typing import Optional
import re
from urllib.parse import unquote

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

DETAIL_ID_RE = re.compile(r"/empleos/[^/]+-\d+\.html$", re.IGNORECASE)
BASE_URL = "https://www.bumeran.com.ar/"
BUM_USER = os.getenv("BUMERAN_USER", "")
BUM_PASS = os.getenv("BUMERAN_PASS", "")
LISTING_SELECTOR = "#listado-avisos a[href*='/empleos/']"
DETAIL_CONTAINER = "#section-detalle"
NEXT_BTN = "a:has(i[name='icon-light-caret-right'])"
# --- helpers de normalización -------------------------------------------------

# --- helpers de normalización -------------------------------------------------

ACRONYMS = {
    "SA","SRL","SAS","SAU","SCA","SGR","SGSA","SAIC","SACI","SACIF","SACIFIA","SAICYF",
    "ID","RRHH","SVA","CRM","CX","IT","UX","QA","HR"
}
SMALL_WORDS = {"de","del","la","las","los","y","e","en","para","por","con","a","da","do","dos","das"}

# Si querés mostrar nombre "corto", poné True (quita sufijos societarios largos al final)
TRIM_LONG_LEGAL_SUFFIX = True
LEGAL_SUFFIX_RE = re.compile(r"\b(SGSA|SAIC|SACI|SACIFIA|SACIF|SAICYF)\b\.?$", re.I)

# Tildes opcionales en palabras comunes
FIX_DIACRITICS = True
_DIACRITICS_MAP = {
    r"\bVinculos\b": "Vínculos",
    r"\bTecnologia\b": "Tecnología",
    r"\bTecnologias\b": "Tecnologías",
    r"\bQuimica\b": "Química",
    r"\bQuimicas\b": "Químicas",
    r"\bMecanica\b": "Mecánica",
    r"\bMecanicas\b": "Mecánicas",
    r"\bElectronica\b": "Electrónica",
    r"\bElectronicas\b": "Electrónicas",
    r"\bLogistica\b": "Logística",
    r"\bLogisticas\b": "Logísticas",
    r"\bTrafico\b": "Tráfico",
}

def _fix_diacritics(text: str) -> str:
    if not FIX_DIACRITICS or not text:
        return text
    out = text
    for pat, rep in _DIACRITICS_MAP.items():
        out = re.sub(pat, rep, out, flags=re.I)
    return out

def _smart_title(s: str) -> str:
    if not s:
        return ""
    tokens = s.split()
    out = []
    for i, tok in enumerate(tokens):
        parts = tok.split("'")  # respeta D'Amelio
        new_parts = []
        for p in parts:
            if not p:
                new_parts.append(p); continue
            up = p.upper().replace(".", "")
            low = p.lower()
            if up in ACRONYMS:
                new_parts.append(up)
            elif 0 < i < len(tokens)-1 and low in SMALL_WORDS:
                new_parts.append(low)
            else:
                new_parts.append(p[:1].upper() + p[1:].lower())
        out.append("'".join(new_parts))
    return " ".join(out)

def _normalize_company(raw: Optional[str]) -> str:
    if not raw:
        return ""
    t = raw.strip()

    # quita .html e ID final si vinieron del slug
    t = re.sub(r"\.html?$", "", t, flags=re.I)
    t = re.sub(r"[-_/]?\b\d{5,}\b$", "", t).strip()

    # espacios múltiples
    t = re.sub(r"\s{2,}", " ", t)

    # normaliza abreviaturas comunes
    t = re.sub(r"\bS\.?\s*A\.?\b", "SA", t, flags=re.I)
    t = re.sub(r"\bS\.?\s*R\.?\s*L\.?\b", "SRL", t, flags=re.I)
    t = re.sub(r"\bS\.?\s*A\.?\s*S\.?\b", "SAS", t, flags=re.I)
    t = re.sub(r"\bS\.?\s*A\.?\s*U\.?\b", "SAU", t, flags=re.I)

    # capitaliza con reglas + tildes opcionales
    t = _smart_title(t)
    t = _fix_diacritics(t)

    # forzado final de acrónimos cortos
    def up_if_acronym(m):
        w = m.group(0)
        return w.upper() if w.upper() in ACRONYMS else w
    t = re.sub(r"\b[A-Za-z]{2,5}\b", up_if_acronym, t)

    # (opcional) recortar sufijo societario largo al final
    if TRIM_LONG_LEGAL_SUFFIX:
        t = LEGAL_SUFFIX_RE.sub("", t).strip()

    return t


# ------------------------------------------------------------
# Extractor robusto de empresa (Bumeran)
# ------------------------------------------------------------
def _extract_company_bumeran(dp: Page, step_timeout: int = 10000) -> str:
    """
    Orden: JSON-LD (incluye @graph) → variantes DOM/atributos → slug del link → título → 'Confidencial'
    Siempre normaliza el texto final.
    """
    timeout = step_timeout if step_timeout and step_timeout > 0 else 10000

    # 0) Espera a TEXTO real o presencia de JSON-LD
    try:
        dp.wait_for_function("""
          () => {
            const hasTxt = el => el && el.textContent && el.textContent.trim().length > 0;
            const cand = document.querySelector(
              ".sc-dqbauf, p:has(i[name*='verified']), a[href*='/empresa'], [data-company-name]"
            );
            return (cand && hasTxt(cand)) || !!document.querySelector("script[type='application/ld+json']");
          }
        """, timeout=timeout)
    except Exception:
        pass

    # 1) JSON-LD (directo o dentro de @graph)
    conf_jsonld = False
    try:
        org = dp.evaluate("""
          () => {
            const pick = (o) => {
              if (!o || typeof o !== 'object') return null;
              const g = n => (n && typeof n === 'string') ? n.trim() : null;
              const direct = g(o?.hiringOrganization?.name) || g(o?.organization?.name) || g(o?.publisher?.name);
              if (direct) return direct;
              const arr = Array.isArray(o) ? o : (Array.isArray(o?.["@graph"]) ? o["@graph"] : null);
              if (arr) {
                for (const it of arr) {
                  const t = (it && (it["@type"] || it.type)) || "";
                  if (t && /Organization/i.test(String(t)) && typeof it.name === "string") return it.name.trim();
                  const nested = g(it?.hiringOrganization?.name) || g(it?.organization?.name) || g(it?.publisher?.name);
                  if (nested) return nested;
                }
              }
              return null;
            };
            for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
              try {
                const j = JSON.parse(s.textContent || '{}');
                const n = pick(j);
                if (n) return n;
              } catch {}
            }
            return null;
          }
        """)
        if isinstance(org, str) and org.strip():
            if "confidencial" in org.lower():
                conf_jsonld = True
            else:
                return _normalize_company(org)
    except Exception:
        pass

    # 2) Variantes de DOM (texto o atributos)
    try:
        loc = dp.locator(
            ".sc-dqbauf:visible, "
            "p:has(i[name*='verified']):visible, "
            "a[href*='/empresa']:visible, "
            "[data-company-name]:visible, "
            "[data-qa='company-name']:visible, "
            "[data-cy='companyName']:visible"
        ).first
        if loc.count():
            txt = (loc.inner_text() or "").strip()

            if not txt:
                # a veces el nombre está como atributo
                for attr in ("data-company-name", "aria-label", "title"):
                    try:
                        val = (loc.get_attribute(attr) or "").strip()
                        if val:
                            txt = val
                            break
                    except Exception:
                        pass

                # si el nodo visible es <a> sin texto, probá su padre o hermano
                if not txt:
                    try:
                        parent = loc.locator("xpath=..").first
                        sib = loc.locator("xpath=following-sibling::*[1]").first
                        for cand in (parent, sib):
                            if cand and cand.count():
                                t2 = (cand.inner_text() or "").strip()
                                if t2:
                                    txt = t2
                                    break
                    except Exception:
                        pass

            if txt:
                return _normalize_company(txt)
    except Exception:
        pass

    # 3) Slug del link (sin ID ni .html)
    href = None
    try:
        href = dp.eval_on_selector(
            "xpath=(//a[contains(@href,'/empresa')][1])",
            "n => n.getAttribute('href')"
        )
    except Exception:
        pass
    if href:
        m = re.search(r"/empresa[-/_]([a-z0-9._-]+?)(?:[-_]\d+)?(?:\.html)?$", href, re.I)
        if m:
            slug = unquote(m.group(1)).replace("-", " ").replace("_", " ").strip()
            if slug:
                return _normalize_company(slug)
        # 3.b) Inferencia desde la URL del AVISO (cuando no hay perfil de empresa)
    try:
        detail_url = dp.url or ""
    except Exception:
        detail_url = ""
    m = re.search(r"/empleos/([a-z0-9._-]+)-\d+\.html$", detail_url, re.I)
    if m:
        raw_slug = unquote(m.group(1))
        # tokens del slug
        tokens = [t for t in re.split(r"[-_]+", raw_slug) if t]
        low = [t.lower() for t in tokens]

        # palabras que NO pertenecen al nombre de empresa (roles/áreas/conectores)
        STOP = {
            "analista","jr","sr","ssr","semi","semi","semi-senior","semisenior",
            "de","del","la","las","los","el","en","y","para","por","con",
            "calidad","comercial","comex","contable","contabilidad",
            "cobranzas","costos","datos","crm","cx","impuestos","logistica",
            "logístico","logística","microbiologia","microbiología","negocio",
            "trafico","tráfico","ventas","tesoreria","tesorería","rrhh","e","ti","it"
        }

        # tomamos la "cola" del slug (de atrás hacia adelante) hasta toparnos con STOP
        tail_idx = []
        for i in range(len(low)-1, -1, -1):
            if low[i] in STOP:
                if tail_idx:
                    break
                else:
                    continue
            tail_idx.append(i)

        if tail_idx:
            tail_idx = list(reversed(tail_idx))
            candidate = " ".join(tokens[i] for i in tail_idx).strip()
            # limpieza rápida de restos
            candidate = re.sub(r"\b(sr|jr|ssr)\b", "", candidate, flags=re.I).strip()
            if candidate and candidate.lower() != "confidencial":
                return _normalize_company(candidate)

    # 4) Inferencia desde el TÍTULO (… en X | – X | — X)
    try:
        title = dp.locator("h1, header h1, #section-detalle h1").first
        ttxt = (title.inner_text() or "").strip() if title.count() else ""
    except Exception:
        ttxt = ""
    if ttxt:
        m = re.search(r"\s(?:en|para)\s+(.{3,})$", ttxt, re.I)
        if m:
            cand = _normalize_company(m.group(1))
            if cand and cand.lower() != "confidencial":
                return cand
        m = re.search(r"[—–-]\s*([^—–-]{3,})$", ttxt)
        if m:
            cand = _normalize_company(m.group(1))
            if cand and cand.lower() != "confidencial":
                return cand

    # 5) Confidencial
    try:
        if dp.get_by_text(re.compile(r"\bconfidencial\b", re.I)).first.count() or conf_jsonld:
            return "Confidencial"
    except Exception:
        if conf_jsonld:
            return "Confidencial"

    return ""


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
    
    def _enter_listing_from_home(self) -> None:
        """Desde la home de Bumeran, entra al listado clickeando 'Buscar trabajo'."""
        p = self.list_page

        # Intentos con varios selectores robustos del botón grande de la home
        for sel in [
            "#buscarTrabajo",                               # id que mostraste
            "button:has-text('Buscar trabajo')",
            "a:has-text('Buscar trabajo')",
            "button.sc-ktHwxA",                             # clase frecuente del CTA
        ]:
            btn = p.locator(sel).first
            if not btn.count() or not btn.is_visible():
                continue
            try:
                with p.expect_navigation(wait_until="domcontentloaded", timeout=max(self.timeout, 15000)):
                    btn.click(force=True)
            except PWTimeoutError:
                # Puede ser SPA: no navega, pero igual expone el listado/filters
                try:
                    btn.click(force=True)
                except Exception:
                    pass
            break  # no sigo probando otros selectores

        # Esperar a que aparezca listado o el form de filtros
        try:
            p.wait_for_selector(LISTING_SELECTOR, timeout=max(self.timeout, 20000), state="attached")
        except PWTimeoutError:
            # Si no hay selector de cards aún, al menos aseguramos que el form esté visible
            p.wait_for_selector(
                "form.sc-feJyhm, #busqueda, #lugar-de-trabajo, div.select__placeholder:has-text('Buscar empleo')",
                timeout=8000,
                state="visible"
            )
                        
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

        # 5) Entrar al listado SIEMPRE desde el botón grande de la home
        self._enter_listing_from_home()

        # 6) Si el usuario pasó query/ubicación, recién ahí llenamos inputs; si no, seguimos sin tocar filtros
        if self.query or self.location:
            self._buscar_con_inputs()
        else:
            # ya estamos en el listado; aseguramos el selector y seguimos
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
        data["empresa"] = _extract_company_bumeran(dp, self.timeout)

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
