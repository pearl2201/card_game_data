"""Apple App Store discovery (iTunes Search API) and review sampling.

``app-store-scraper`` is used for reviews when it works. Apple changed the app
landing page in 2024 so the library's token scrape frequently fails; the direct
UGC endpoint below is used as a fallback so review text is still collected.
"""

from __future__ import annotations

from typing import Iterable

from app_store_scraper import AppStore

from ..config import APPLE_COUNTRY, DEFAULT_ITUNES_LIMIT
from ..http import ResilientSession
from ..normalize import (
    build_review_summary,
    clean_text,
    make_record,
    match_mechanics,
    multiplayer_terms,
    normalize_rating,
    score_relevance,
    to_float,
    to_int,
    truncate,
)

ITUNES_SEARCH = "https://itunes.apple.com/search"
APPLE_UGC = "https://itunes.apple.com/WebObjects/MZStore.woa/wa/userReviewsRow"
APP_URL = "https://apps.apple.com/{country}/app/id{app_id}"


class AppStoreSource:
    name = "app_store"

    def __init__(self, *, country: str = APPLE_COUNTRY) -> None:
        self.country = country
        self.http = ResilientSession(
            "app_store",
            cache_ttl=24 * 3600,
            min_interval=0.35,
            max_attempts=4,
            backoff=1.5,
        )
        # Library support is probed once; the upstream token scrape is broken.
        self._library_supported: bool | None = None

    # -- discovery ---------------------------------------------------------
    def discover(
        self,
        queries: Iterable[str],
        *,
        limit: int = DEFAULT_ITUNES_LIMIT,
    ) -> dict[str, dict]:
        found: dict[str, dict] = {}
        for query in queries:
            data = self.http.get(
                ITUNES_SEARCH,
                {
                    "term": query,
                    "country": self.country,
                    "entity": "software",
                    "limit": min(limit, 200),
                    "lang": "en_us",
                },
            )
            results = (data or {}).get("results") or []
            print(f"  [app_store] search {query!r}: {len(results)} apps")
            for item in results:
                app_id = str(item.get("trackId") or "")
                if not app_id:
                    continue
                entry = found.setdefault(app_id, {"result": item, "matched_queries": set()})
                entry["matched_queries"].add(query)
        return found

    # -- record ------------------------------------------------------------
    def build_record(self, app_id: str, entry: dict) -> dict:
        item = entry["result"]
        title = item.get("trackName") or ""
        genres = [genre for genre in item.get("genres") or []]
        description = truncate(item.get("description") or "", 1200)
        score = to_float(item.get("averageUserRating"))
        price = to_float(item.get("price"))
        is_free = bool(price == 0)

        text = " ".join([title, *genres, description])
        relevance, multiplayer = score_relevance(tags=[], text=text)

        return make_record(
            source=self.name,
            source_id=app_id,
            title=title,
            game_url=APP_URL.format(country=self.country, app_id=app_id),
            developer=item.get("artistName"),
            publisher=item.get("sellerName"),
            primary_genre=item.get("primaryGenreName"),
            genres=genres,
            matched_queries=sorted(entry["matched_queries"]),
            rating_100=normalize_rating(score, 5),
            rating_5=round(score, 2) if score is not None else None,
            rating_count=to_int(item.get("userRatingCount")),
            review_count=to_int(item.get("userRatingCount")),
            price_usd=price,
            is_free=is_free,
            release_date=(item.get("releaseDate") or "")[:10] or None,
            platforms=["ios"],
            description=description,
            mechanics=match_mechanics(text),
            multiplayer_signals=multiplayer_terms(text),
            relevance_score=relevance,
            is_multiplayer=multiplayer,
            enriched=True,
            store_fetched=True,
        )

    # -- reviews -----------------------------------------------------------
    def fetch_reviews(self, app_id: str, *, count: int = 20) -> list[dict]:
        reviews = self._reviews_via_library(app_id, count)
        if not reviews:
            reviews = self._reviews_via_ugc(app_id, count)
        return reviews

    def _reviews_via_library(self, app_id: str, count: int) -> list[dict]:
        if self._library_supported is False:
            return []
        try:
            store = AppStore(
                country=self.country,
                app_name=f"app-{app_id}",
                app_id=int(app_id),
                log_level="CRITICAL",
                log_interval=60,
            )
            store.review(how_many=count)
        except Exception:
            self._library_supported = False
            return []
        if not store.reviews:
            self._library_supported = False
            return []
        self._library_supported = True
        return [
            {
                "source": self.name,
                "source_id": app_id,
                "review_id": str(item.get("reviewId") or item.get("id") or ""),
                "rating": to_int(item.get("rating")),
                "text": clean_text(item.get("review") or item.get("content")),
                "title": item.get("title"),
                "helpful": None,
                "date": item.get("date").isoformat() if item.get("date") else None,
                "version": item.get("version"),
                "language": "en",
            }
            for item in store.reviews
        ]

    def _reviews_via_ugc(self, app_id: str, count: int) -> list[dict]:
        data = self.http.get(
            APPLE_UGC,
            {
                "id": app_id,
                "displayable-kind": 11,
                "startIndex": 0,
                "endIndex": max(count, 10),
                "sort": 4,
                "appVersion": "all",
            },
            encoding="auto",
            headers={
                "X-Apple-Store-Front": "143441-1,29",
                "User-Agent": "iTunes/12.12 (Windows; Microsoft Windows 10 x64) AppleWebKit/7604.400.21.0.4",
                "Accept": "application/json",
            },
        )
        rows = (data or {}).get("userReviewList") or []
        return [
            {
                "source": self.name,
                "source_id": app_id,
                "review_id": str(row.get("userReviewId") or ""),
                "rating": to_int(row.get("rating")),
                "text": clean_text(row.get("body")),
                "title": row.get("title"),
                "helpful": to_int(row.get("voteCount")),
                "date": row.get("date"),
                "version": row.get("appVersion"),
                "language": "en",
            }
            for row in rows
        ]

    def attach_review_summary(self, record: dict, reviews: list[dict]) -> None:
        scored = [r for r in reviews if r.get("rating") is not None]
        headline = None
        if record.get("rating_5") is not None:
            count = record.get("rating_count")
            headline = f"App Store rating {record['rating_5']:.2f}/5"
            if count:
                headline += f" from {count:,} ratings"
        text, snippets = build_review_summary(
            reviews,
            positive=sum(1 for r in scored if r["rating"] >= 4),
            negative=sum(1 for r in scored if r["rating"] <= 2),
            source_label="App Store",
            sample=True,
            headline=headline,
        )
        if not text:
            parts = []
            if record.get("rating_5") is not None:
                parts.append(f"App Store rating {record['rating_5']:.2f}/5")
            if record.get("rating_count"):
                parts.append(f"{record['rating_count']:,} ratings")
            text = "; ".join(parts)
        if record.get("rating_100") is None and scored:
            average = sum(r["rating"] for r in scored) / len(scored)
            record["rating_5"] = round(average, 2)
            record["rating_100"] = round(average * 20, 2)
        record["review_summary"] = text
        record["review_snippets"] = snippets
