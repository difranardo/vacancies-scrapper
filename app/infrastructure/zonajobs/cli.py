from __future__ import annotations
import argparse
import json
import pandas as pd

from . import scrape_zonajobs


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrapea Zonajobs")
    parser.add_argument("--query", default="")
    parser.add_argument("--location", default="")
    parser.add_argument("--pages", type=int, default=None)
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()

    resultados = scrape_zonajobs(
        query=args.query,
        location=args.location,
        max_pages=args.pages,
        headless=args.headless,
    )

    if resultados:
        df = pd.DataFrame(resultados)
        df.to_excel("zonajobs.xlsx", index=False)
        with open("zonajobs.json", "w", encoding="utf-8") as f:
            json.dump(resultados, f, ensure_ascii=False, indent=2)
        print(f"[SUCCESS] {len(resultados)} registros exportados.")
    else:
        print("[INFO] No se extrajeron datos.")


if __name__ == "__main__":
    main()