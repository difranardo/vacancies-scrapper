from __future__ import annotations
import argparse
import json
import pandas as pd

from app.logging_utils import get_logger
from . import scrape_computrabajo


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrapea Computrabajo")
    parser.add_argument("--categoria", required=True)
    parser.add_argument("--lugar", required=True)
    parser.add_argument("--pages", type=int, default=None)
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()

    resultados = scrape_computrabajo(
        categoria=args.categoria,
        lugar=args.lugar,
        max_pages=args.pages,
        headless=args.headless,
    )

    if resultados:
        df = pd.DataFrame(resultados)
        df.to_excel("computrabajo.xlsx", index=False)
        with open("computrabajo.json", "w", encoding="utf-8") as f:
            json.dump(resultados, f, ensure_ascii=False, indent=2)
        get_logger().info("%s registros exportados.", len(resultados))
    else:
        get_logger().info("No se extrajeron datos.")


if __name__ == "__main__":
    main()