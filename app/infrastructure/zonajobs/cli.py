from __future__ import annotations
import argparse
import json
import pandas as pd

from app.logging_utils import get_logger
from . import scrape_zonajobs


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrapea Zonajobs")
    parser.add_argument("--query", default="")
    parser.add_argument("--location", default="")
    parser.add_argument("--pages", type=int, default=None)
    args = parser.parse_args()

    resultados = scrape_zonajobs(
        query=args.query,
        location=args.location,
        max_pages=args.pages,
    )

    if resultados:
        df = pd.DataFrame(resultados)
        df.to_excel("zonajobs.xlsx", index=False)
        with open("zonajobs.json", "w", encoding="utf-8") as f:
            json.dump(resultados, f, ensure_ascii=False, indent=2)
        get_logger().info("%s registros exportados.", len(resultados))
    else:
        get_logger().info("No se extrajeron datos.")


if __name__ == "__main__":
    main()