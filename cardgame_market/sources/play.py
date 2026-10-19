"""Google Play discovery, details and review sampling."""

from __future__ import annotations

from typing import Iterable

from google_play_scraper import Sort, app as gp_app
from google_play_scraper import reviews as gp_reviews
from google_play_scraper import search as gp_search

from ..config import DEFAULT_PLAY_HITS, PLAY_COUNTRY, PLAY_LANG, PLAY_REVIEW_LANG
from ..normalize import (
    build_review_summary,
    clean_text,
    make_record,
    match_mechanics,
    multiplayer_terms,
    normalize_rating,
    parse_installs,
    score_relevance,
    to_float,
    to_int,
    truncate,
)

PLAY_APP_URL = "https://play.google.com/store/apps/details?id={app_id}&hl=en&gl=us"


class PlaySource:
    name = "google_play"

    def __init__(self, *, country: str = PLAY_COUNTRY, lang: str = PLAY_LANG) -> None:
        self.country = country
        self.lang = lang

    def discover(
        self,
        queries: Iterable[str],
        *,
        hits_per_query: int = DEFAULT_PLAY_HITS,
    ) -> dict[str, set[str]]:
        """Map appId -> set of queries that surfaced it."""
        found: dict[str, set[str]] = {}
        for query in queries:
            try:
                results = gp_search(
                    query,
                    lang=self.lang,
                    country=self.country,
                    n_hits=hits_per_query,
                )
            except Exception as exc:
                print(f"  [play] search {query!r} failed: {type(exc).__name__}: {exc}")
                continue
            print(f"  [play] search {query!r}: {len(results)} apps")
            for item in results:
                app_id = item.get("appId")
                if app_id:
                    found.setdefault(app_id, set()).add(query)
        return found

    def details(self, app_id: str) -> dict | None:
        try:
            return gp_app(app_id, lang=self.lang, country=self.country)
        except Exception as exc:
            print(f"  [play] details {app_id} failed: {type(exc).__name__}: {exc}")
            return None

    def build_record(self, app_id: str, detail: dict, matched_queries: Iterable[str]) -> dict:
        title = detail.get("title") or ""
        score = to_float(detail.get("score"))
        description = truncate(detail.get("description") or "", 1200)
        summary = detail.get("summary") or ""
        genres = detail.get("genre") or []
        if isinstance(genres, str):
            genres = [genres]
        installs = detail.get("installs")
        owners_min, owners_max = parse_installs(installs)
        price = to_float(detail.get("price"))
        is_free = bool(detail.get("free"))

        text = " ".join([title, summary, description, *genres])
        relevance, multiplayer = score_relevance(tags=[], text=text)

        return make_record(
            source=self.name,
            source_id=app_id,
            title=title,
            game_url=PLAY_APP_URL.format(app_id=app_id),
            developer=detail.get("developer"),
            publisher=detail.get("developer"),
            primary_genre=genres[0] if genres else None,
            genres=list(genres),
            tags=[],
            matched_queries=sorted(matched_queries),
            rating_100=normalize_rating(score, 5),
            rating_5=round(score, 2) if score is not None else None,
            rating_count=to_int(detail.get("ratings")),
            review_count=to_int(detail.get("reviews")),
            price_usd=0.0 if is_free else price,
            is_free=is_free,
            owners_band=installs,
            owners_min=owners_min,
            owners_max=owners_max,
            release_date=detail.get("released"),
            platforms=["android"],
            description=description or summary,
            mechanics=match_mechanics(text),
            multiplayer_signals=multiplayer_terms(text),
            relevance_score=relevance,
            is_multiplayer=multiplayer,
            enriched=True,
            store_fetched=True,
        )

    def fetch_reviews(self, app_id: str, *, count: int, rating: int | None = None) -> list[dict]:
        collected = self._fetch_reviews(app_id, count, rating)
        if not collected:
            return []
        # Make sure the sample contains both praise and criticism so the
        # generated summary is balanced.
        if not any((item.get("rating") or 0) >= 4 for item in collected):
            collected += self._fetch_reviews(app_id, min(count, 8), 5)
        if not any((item.get("rating") or 5) <= 2 for item in collected):
            collected += self._fetch_reviews(app_id, min(count, 8), 1)

        seen: set[str] = set()
        unique: list[dict] = []
        for item in collected:
            key = str(item.get("review_id"))
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique

    def _fetch_reviews(self, app_id: str, count: int, rating: int | None = None) -> list[dict]:
        try:
            results, _ = gp_reviews(
                app_id,
                lang=PLAY_REVIEW_LANG,
                country=self.country,
                sort=Sort.MOST_RELEVANT,
                count=count,
                filter_score_with=rating,
            )
        except Exception as exc:
            print(f"  [play] reviews {app_id} failed: {type(exc).__name__}: {exc}")
            return []
        return [
            {
                "source": self.name,
                "source_id": app_id,
                "review_id": item.get("reviewId"),
                "rating": item.get("score"),
                "text": clean_text(item.get("content")),
                "helpful": item.get("thumbsUpCount"),
                "date": item.get("at").isoformat() if item.get("at") else None,
                "version": item.get("reviewCreatedVersion"),
                "language": PLAY_REVIEW_LANG,
                "title": None,
            }
            for item in results
        ]

    def attach_review_summary(self, record: dict, reviews: list[dict]) -> None:
        scored = [r for r in reviews if r.get("rating") is not None]
        headline = None
        if record.get("rating_5") is not None:
            count = record.get("rating_count")
            headline = f"Google Play rating {record['rating_5']:.2f}/5"
            if count:
                headline += f" from {count:,} ratings"
        text, snippets = build_review_summary(
            reviews,
            positive=sum(1 for r in scored if r["rating"] >= 4),
            negative=sum(1 for r in scored if r["rating"] <= 2),
            source_label="Google Play",
            sample=True,
            headline=headline,
        )
        if not text:
            parts = []
            if record.get("rating_5") is not None:
                parts.append(f"Google Play rating {record['rating_5']:.2f}/5")
            if record.get("rating_count"):
                parts.append(f"{record['rating_count']:,} ratings")
            text = "; ".join(parts)
        if record.get("rating_100") is None and scored:
            average = sum(r["rating"] for r in scored) / len(scored)
            record["rating_5"] = round(average, 2)
            record["rating_100"] = round(average * 20, 2)
        record["review_summary"] = text
        record["review_snippets"] = snippets
