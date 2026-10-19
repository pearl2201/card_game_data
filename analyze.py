#!/usr/bin/env python
"""Analyse crawled data with pandas and write CSV/Markdown reports.

Examples
--------
    python analyze.py                          # exports CSV + report
    python analyze.py --min-ratings 500 --top 25
    python analyze.py --source steam --no-report
"""

from __future__ import annotations

import argparse
import sys

from cardgame_market.analysis import (
    build_report,
    export_csv,
    load_games,
    load_reviews,
    platform_overview,
    top_games,
)
from cardgame_market.config import REPORTS_DIR


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--min-ratings", type=int, default=100,
                        help="minimum number of ratings for the top-games table")
    parser.add_argument("--top", type=int, default=40, help="rows in the top-games table")
    parser.add_argument("--source", default=None,
                        help="limit the console view to one source (steam, google_play, app_store)")
    parser.add_argument("--no-csv", action="store_true", help="skip writing data/processed CSVs")
    parser.add_argument("--no-report", action="store_true", help="skip writing data/reports")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)

    games = load_games()
    reviews = load_reviews()
    if games.empty:
        print("No data yet — run `python crawl.py` first.")
        return 1

    if not args.no_csv:
        export_csv(games, reviews)
        print("Wrote data/processed/games.csv and data/processed/reviews.csv")

    print("\nStorefront overview")
    print(platform_overview(games).to_string(index=False))

    subset = games if not args.source else games[games["source"] == args.source]
    top = top_games(subset, min_ratings=args.min_ratings, limit=args.top)
    if not top.empty:
        print(f"\nTop {args.top} games by rating (>= {args.min_ratings} ratings)")
        columns = ["source", "title", "rating_100", "rating_count", "price_usd"]
        print(top[[c for c in columns if c in top.columns]].to_string(index=False))
    else:
        print("\nNo games matched the rating threshold.")

    if not args.no_report:
        result = build_report(games, reviews, min_ratings=args.min_ratings, top_n=args.top)
        print(f"\nReports written to {REPORTS_DIR}")
        for name, table in result["tables"].items():
            if not table.empty:
                print(f"  - {name}.csv ({len(table)} rows)")
        print("  - market_report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
