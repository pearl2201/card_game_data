"""Crawl orchestration: discovery -> enrichment -> persistence."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
import time

from .config import (
    DEFAULT_ENRICH_LIMIT,
    DEFAULT_ITUNES_LIMIT,
    DEFAULT_PLAY_HITS,
    DEFAULT_REVIEWS_PER_GAME,
    GAMES_STORE,
    MIN_RELEVANCE,
    MOBILE_SEARCH_QUERIES,
    NON_GAME_GENRES,
    REVIEWS_STORE,
    SEARCH_QUERIES,
    STEAM_DISCOVERY_TAGS,
)
from .normalize import clean_text
from .sources.appstore import AppStoreSource
from .sources.play import PlaySource
from .sources.steam import SteamSource
from .storage import RecordStore, ReviewStore


@dataclass
class CrawlOptions:
    sources: tuple[str, ...] = ("steam", "google_play", "app_store")
    queries: list[str] = field(default_factory=lambda: list(dict.fromkeys(SEARCH_QUERIES + MOBILE_SEARCH_QUERIES)))
    steam_tags: list[str] = field(default_factory=lambda: list(STEAM_DISCOVERY_TAGS))
    steam_limit_per_tag: int | None = 400
    steam_enrich_limit: int = DEFAULT_ENRICH_LIMIT
    steam_time_budget: float = 15.0
    play_hits: int = DEFAULT_PLAY_HITS
    itunes_limit: int = DEFAULT_ITUNES_LIMIT
    reviews_per_game: int = DEFAULT_REVIEWS_PER_GAME
    review_games_limit: int = 80
    require_multiplayer: bool = False
    min_relevance: dict[str, float] = field(default_factory=lambda: dict(MIN_RELEVANCE))
    refresh: bool = False
    no_cache: bool = False
    dry_run: bool = False


class Crawler:
    def __init__(self, options: CrawlOptions) -> None:
        self.options = options
        self.store = RecordStore(GAMES_STORE)
        self.steam = SteamSource(reviews_per_game=options.reviews_per_game) if "steam" in options.sources else None
        self.play = PlaySource() if "google_play" in options.sources else None
        self.app_store = AppStoreSource() if "app_store" in options.sources else None
        if options.no_cache:
            if self.steam:
                self.steam.store.refresh = True
            if self.app_store:
                self.app_store.http.refresh = True
        self.new_records = 0
        self.new_reviews = 0

    # -- public ------------------------------------------------------------
    def run(self) -> dict:
        reviews_path = REVIEWS_STORE
        if self.options.dry_run:
            import tempfile
            from pathlib import Path

            reviews_path = Path(tempfile.gettempdir()) / "cardgame_market_dryrun_reviews.jsonl"
            reviews_path.unlink(missing_ok=True)

        with ReviewStore(reviews_path) as review_store:
            if self.steam:
                self._crawl_steam(review_store)
            if self.play:
                self._crawl_play(review_store)
            if self.app_store:
                self._crawl_app_store(review_store)

        self._apply_filters()
        if not self.options.dry_run:
            total = self.store.save()
            print(f"\nSaved {total:,} games -> {GAMES_STORE}")
            print(f"Added {self.new_reviews:,} review samples -> {REVIEWS_STORE}")
        return {
            "games": len(self.store),
            "new_games": self.new_records,
            "new_reviews": self.new_reviews,
            "cache": {
                "steam_store": self.steam.store.stats if self.steam else None,
                "app_store": self.app_store.http.stats if self.app_store else None,
            },
        }

    # -- helpers -----------------------------------------------------------
    def _needs_work(self, record: dict | None, *, require_reviews: bool = False) -> bool:
        if self.options.refresh or record is None:
            return True
        if require_reviews and not record.get("review_summary"):
            return True
        if not record.get("enriched"):
            return True
        if record.get("source") == "steam" and not record.get("store_fetched"):
            return True
        return False

    def _progress(self, label: str, index: int, total: int) -> None:
        if total and (index % 10 == 0 or index == total):
            print(f"    {label} {index}/{total}")

    # -- steam -------------------------------------------------------------
    def _crawl_steam(self, review_store: ReviewStore) -> None:
        assert self.steam is not None
        print("\n== Steam (SteamSpy tags + Store enrichment) ==")
        candidates = self.steam.discover(
            limit_per_tag=self.options.steam_limit_per_tag,
            tags=self.options.steam_tags,
        )
        print(f"  [steam] {len(candidates):,} unique apps discovered")

        records: list[dict] = []
        for appid, entry in candidates.items():
            existing = self.store.get("steam", appid)
            if existing is not None and not self.options.refresh:
                records.append(existing)
                continue
            record = self.steam.base_record(appid, entry)
            self.store.upsert(record)
            self.new_records += 1
            records.append(record)

        # Enrich the most promising games first: they carry the most reliable
        # review text and the most useful tags.
        priority = sorted(
            records,
            key=lambda r: (
                r.get("relevance_score") or 0,
                r.get("ccu") or 0,
                r.get("positive_count") or 0,
            ),
            reverse=True,
        )
        to_enrich = [record for record in priority if self._needs_work(record)]
        # Games added by discovery that are already enriched are skipped.
        to_enrich = to_enrich[: self.options.steam_enrich_limit]
        print(f"  [steam] enriching {len(to_enrich)} apps (store details + reviews)")

        started = time.monotonic()
        budget_seconds = self.options.steam_time_budget * 60
        for index, record in enumerate(to_enrich, start=1):
            if budget_seconds and time.monotonic() - started > budget_seconds:
                print(
                    f"  [steam] time budget of {self.options.steam_time_budget:g} min reached "
                    f"after {index - 1}/{len(to_enrich)} apps — re-run to continue (cached data is reused)"
                )
                break
            self._progress("enriching", index, len(to_enrich))
            reviews = self.steam.enrich(record, with_reviews=True)
            samples = [
                {
                    "source": "steam",
                    "source_id": record["source_id"],
                    "review_id": review.get("recommendationid"),
                    "rating": 5 if review.get("voted_up") else 2,
                    "text": clean_text(review.get("review")),
                    "title": None,
                    "helpful": review.get("votes_up"),
                    "date": _ts_to_iso(review.get("timestamp_created")),
                    "version": None,
                    "language": review.get("language"),
                    "playtime_hours": round((review.get("author") or {}).get("playtime_forever", 0) / 60, 1),
                }
                for review in reviews
            ]
            self.new_reviews += review_store.add_many(samples)
            self.store.upsert(record)

    # -- google play -------------------------------------------------------
    def _crawl_play(self, review_store: ReviewStore) -> None:
        assert self.play is not None
        print("\n== Google Play ==")
        found = self.play.discover(self.options.queries, hits_per_query=self.options.play_hits)
        print(f"  [play] {len(found):,} unique apps discovered")

        pending = [
            (app_id, queries)
            for app_id, queries in found.items()
            if self._needs_work(self.store.get("google_play", app_id))
        ]
        print(f"  [play] fetching details for {len(pending)} apps")

        records: list[dict] = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                pool.submit(self.play.details, app_id): (app_id, queries) for app_id, queries in pending
            }
            for index, future in enumerate(as_completed(futures), start=1):
                app_id, queries = futures[future]
                self._progress("details", index, len(futures))
                detail = future.result()
                if not detail:
                    continue
                if _is_non_game(detail.get("genre")):
                    continue
                record = self.play.build_record(app_id, detail, queries)
                self.store.upsert(record)
                records.append(record)
                self.new_records += 1

        top = sorted(
            records,
            key=lambda r: (r.get("relevance_score") or 0, r.get("rating_count") or 0),
            reverse=True,
        )[: self.options.review_games_limit]

        for index, record in enumerate(top, start=1):
            self._progress("reviews", index, len(top))
            reviews = self.play.fetch_reviews(record["source_id"], count=self.options.reviews_per_game)
            self.play.attach_review_summary(record, reviews)
            self.new_reviews += review_store.add_many(reviews)
            self.store.upsert(record)

    # -- app store ---------------------------------------------------------
    def _crawl_app_store(self, review_store: ReviewStore) -> None:
        assert self.app_store is not None
        print("\n== Apple App Store ==")
        found = self.app_store.discover(self.options.queries, limit=self.options.itunes_limit)
        print(f"  [app_store] {len(found):,} unique apps discovered")

        records: list[dict] = []
        for app_id, entry in found.items():
            existing = self.store.get("app_store", app_id)
            if existing is not None and not self.options.refresh:
                records.append(existing)
                continue
            record = self.app_store.build_record(app_id, entry)
            self.store.upsert(record)
            records.append(record)
            self.new_records += 1

        top = sorted(
            records,
            key=lambda r: (r.get("relevance_score") or 0, r.get("rating_count") or 0),
            reverse=True,
        )[: self.options.review_games_limit]

        pending = [record for record in top if self._needs_work(record, require_reviews=True)]
        print(f"  [app_store] fetching reviews for {len(pending)} apps")

        def fetch(record: dict) -> tuple[dict, list[dict]]:
            return record, self.app_store.fetch_reviews(
                record["source_id"], count=self.options.reviews_per_game
            )

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(fetch, record) for record in pending]
            for index, future in enumerate(as_completed(futures), start=1):
                self._progress("reviews", index, len(futures))
                record, reviews = future.result()
                self.app_store.attach_review_summary(record, reviews)
                self.new_reviews += review_store.add_many(reviews)
                self.store.upsert(record)

    # -- filters -----------------------------------------------------------
    def _apply_filters(self) -> None:
        dropped = 0
        for key in list(self.store.records):
            record = self.store.records[key]
            threshold = self.options.min_relevance.get(record.get("source"), 0.0)
            if (record.get("relevance_score") or 0) < threshold:
                del self.store.records[key]
                dropped += 1
                continue
            if self.options.require_multiplayer and not record.get("is_multiplayer"):
                del self.store.records[key]
                dropped += 1
        if dropped:
            print(f"\nFiltered out {dropped:,} off-topic games")


def _is_non_game(genre: str | None) -> bool:
    return bool(genre) and genre.strip().lower() in NON_GAME_GENRES


def _ts_to_iso(timestamp) -> str | None:
    if not timestamp:
        return None
    from datetime import datetime, timezone

    try:
        return datetime.fromtimestamp(int(timestamp), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def run_crawl(options: CrawlOptions) -> dict:
    return Crawler(options).run()
