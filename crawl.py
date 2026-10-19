#!/usr/bin/env python
"""Crawl Steam, Google Play and the Apple App Store for card / auto-battler games.

Examples
--------
    python crawl.py                                  # all sources, defaults
    python crawl.py --sources steam --steam-enrich-limit 300
    python crawl.py --sources google_play --play-hits 50 --review-games 120
    python crawl.py --require-multiplayer --refresh
"""

from __future__ import annotations

import argparse
import json
import signal
import sys

from cardgame_market.config import (
    DEFAULT_ENRICH_LIMIT,
    DEFAULT_ITUNES_LIMIT,
    DEFAULT_PLAY_HITS,
    DEFAULT_REVIEWS_PER_GAME,
    MIN_RELEVANCE,
    MOBILE_SEARCH_QUERIES,
    SEARCH_QUERIES,
    STEAM_DISCOVERY_TAGS,
)
from cardgame_market.pipeline import CrawlOptions, run_crawl


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--sources",
        default="steam,google_play,app_store",
        help="comma separated subset of: steam, google_play, app_store",
    )
    parser.add_argument("--steam-tag", action="append", dest="steam_tags",
                        help="extra SteamSpy tag to crawl (repeatable)")
    parser.add_argument("--steam-limit-per-tag", type=int, default=400,
                        help="max apps taken from each SteamSpy tag listing (0 = all)")
    parser.add_argument("--steam-enrich-limit", type=int, default=DEFAULT_ENRICH_LIMIT,
                        help="how many Steam apps get store details + reviews")
    parser.add_argument("--steam-budget", type=float, default=15.0,
                        help="minutes to spend on Steam Store enrichment per run (0 = unlimited)")
    parser.add_argument("--play-hits", type=int, default=DEFAULT_PLAY_HITS,
                        help="results per Google Play search query")
    parser.add_argument("--itunes-limit", type=int, default=DEFAULT_ITUNES_LIMIT,
                        help="results per iTunes search query (max 200)")
    parser.add_argument("--reviews-per-game", type=int, default=DEFAULT_REVIEWS_PER_GAME)
    parser.add_argument("--review-games", type=int, default=80,
                        help="how many mobile games get review sampling")
    parser.add_argument("--query", action="append", dest="queries",
                        help="replace the default mobile search queries (repeatable)")
    parser.add_argument("--min-rating", type=float, default=None,
                        help="override minimum relevance score for the current run")
    parser.add_argument("--require-multiplayer", action="store_true",
                        help="keep only games with a multiplayer/PvP signal")
    parser.add_argument("--refresh", action="store_true",
                        help="re-crawl records that were already stored")
    parser.add_argument("--no-cache", action="store_true",
                        help="bypass the on-disk response cache (implies fresh HTTP calls)")
    parser.add_argument("--checkpoint-every", type=int, default=25,
                        help="save progress to disk every N processed games (0 = only at the end)")
    parser.add_argument("--dry-run", action="store_true", help="crawl but do not write data/")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stdout.reconfigure(line_buffering=True)
    args = build_parser().parse_args(argv)

    # Treat SIGTERM (systemd stop, docker stop, `kill`) like Ctrl+C so the
    # crawler still flushes its data on the way out.
    def _on_sigterm(signum, frame):
        raise KeyboardInterrupt

    if hasattr(signal, "SIGTERM"):
        try:
            signal.signal(signal.SIGTERM, _on_sigterm)
        except (ValueError, OSError):
            pass

    sources = tuple(item.strip() for item in args.sources.split(",") if item.strip())
    unknown = set(sources) - {"steam", "google_play", "app_store"}
    if unknown:
        print(f"Unknown source(s): {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2

    options = CrawlOptions(
        sources=sources,
        queries=args.queries
        or list(dict.fromkeys(SEARCH_QUERIES + MOBILE_SEARCH_QUERIES)),
        steam_tags=list(dict.fromkeys(list(STEAM_DISCOVERY_TAGS) + (args.steam_tags or []))),
        steam_limit_per_tag=args.steam_limit_per_tag or None,
        steam_enrich_limit=args.steam_enrich_limit,
        steam_time_budget=args.steam_budget,
        play_hits=args.play_hits,
        itunes_limit=args.itunes_limit,
        reviews_per_game=args.reviews_per_game,
        review_games_limit=args.review_games,
        checkpoint_every=args.checkpoint_every,
        require_multiplayer=args.require_multiplayer,
        min_relevance={**MIN_RELEVANCE, **({s: args.min_rating for s in sources} if args.min_rating is not None else {})},
        refresh=args.refresh,
        no_cache=args.no_cache,
        dry_run=args.dry_run,
    )

    try:
        stats = run_crawl(options)
    except KeyboardInterrupt:
        print("\nInterrupted — progress already written to data/raw/")
        return 130
    print("\nDone.")
    print(json.dumps(stats, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
