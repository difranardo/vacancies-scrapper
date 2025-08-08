from __future__ import annotations
import argparse
import json
import pandas as pd

from . import scrap_jobs_bumeran


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrapea Bumeran")
    parser.add_argument("--query", default="")
    parser.add_argument("--location", default="")
    parser.add_argument("--pages", type=int, default=None)
    args = parser.parse_args()

    results = scrap_jobs_bumeran(
        query=args.query, location=args.location, max_pages=args.pages
    )

    if results:
        df = pd.DataFrame(results)
        df.to_excel("bumeran.xlsx", index=False)
        with open("bumeran.json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"[SUCCESS] {len(results)} registros exportados.")
    else:
        print("[INFO] No se extrajeron datos.")


if __name__ == "__main__":
    main()