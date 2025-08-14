# interfaces/cli/main.py
from __future__ import annotations
import argparse, json, sys
import pandas as pd
from app.infrastructure.common.logging_utils import get_logger

def run_bumeran(args):
    from app.infrastructure.providers.bumeran.scraper import scrap_jobs_bumeran
    res = scrap_jobs_bumeran(query=args.query, location=args.location, max_pages=args.pages)
    return "bumeran", res

def run_zonajobs(args):
    from app.infrastructure.providers.zonajobs.scraper import scrape_zonajobs
    res = scrape_zonajobs(query=args.query, location=args.location, max_pages=args.pages, headless=args.headless)
    return "zonajobs", res

def run_computrabajo(args):
    from app.infrastructure.providers.computrabajo.scraper import scrape_computrabajo
    res = scrape_computrabajo(categoria=args.categoria, lugar=args.lugar, max_pages=args.pages, headless=args.headless)
    return "computrabajo", res

def export(nombre, resultados, out, fmt):
    log = get_logger()
    if not resultados:
        log.info("No se extrajeron datos.")
        return 2
    base = out or nombre
    if fmt in ("xlsx", "both"):
        pd.DataFrame(resultados).to_excel(f"{base}.xlsx", index=False)
    if fmt in ("json", "both"):
        with open(f"{base}.json", "w", encoding="utf-8") as f:
            json.dump(resultados, f, ensure_ascii=False, indent=2)
    log.info("%s registros exportados.", len(resultados))
    return 0

def main() -> int:
    parser = argparse.ArgumentParser(prog="jobscraper", description="Scraper unificado")
    parser.add_argument("--pages", type=int, default=None)
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--out", help="prefijo de archivo de salida")
    parser.add_argument("--format", choices=["json","xlsx","both"], default="both")

    sub = parser.add_subparsers(dest="provider", required=True)

    b = sub.add_parser("bumeran")
    b.add_argument("--query", default="")
    b.add_argument("--location", default="")
    b.set_defaults(func=run_bumeran)

    z = sub.add_parser("zonajobs")
    z.add_argument("--query", default="")
    z.add_argument("--location", default="")
    z.set_defaults(func=run_zonajobs)

    c = sub.add_parser("computrabajo")
    c.add_argument("--categoria", required=True)
    c.add_argument("--lugar", required=True)
    c.set_defaults(func=run_computrabajo)

    args = parser.parse_args()
    nombre, resultados = args.func(args)
    return export(nombre, resultados, args.out, args.format)

if __name__ == "_main_":
    sys.exit(main())