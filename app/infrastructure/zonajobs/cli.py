from __future__ import annotations
import argparse
import json
import pandas as pd

from app.logging_utils import get_logger
from . import scrape_zonajobs


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Scrapea Zonajobs. "
            "Utiliza --json-path y --excel-path para especificar las rutas de exportación."
        )
    )
    parser.add_argument("--query", default="")
    parser.add_argument("--location", default="")
    parser.add_argument("--pages", type=int, default=None)
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--json-path", default="zonajobs.json")
    parser.add_argument("--excel-path", default="zonajobs.xlsx")
    args = parser.parse_args()

    resultados = scrape_zonajobs(
        query=args.query,
        location=args.location,
        max_pages=args.pages,
        headless=args.headless,
    )

    if resultados:
        try:
            df = pd.DataFrame(resultados)
            df.to_excel(args.excel_path, index=False)
            with open(args.json_path, "w", encoding="utf-8") as f:
                json.dump(resultados, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            get_logger().error("Error al exportar los datos: %s", exc)
        else:
            get_logger().info("%s registros exportados.", len(resultados))
    else:
        get_logger().info("No se extrajeron datos.")


if __name__ == "__main__":
    main()
