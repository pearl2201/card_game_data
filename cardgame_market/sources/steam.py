"""Steam discovery (SteamSpy tags) and enrichment (Store appdetails + reviews)."""

from __future__ import annotations

import time
from typing import Any, Iterable

import steamspypi

from ..config import (
    DEFAULT_REVIEWS_PER_GAME,
    MULTIPLAYER_TAGS,
    STEAM_COUNTRY,
    STEAM_LANG,
    STEAM_TAGS,
)
from ..http import ResilientSession
from ..normalize import (
    build_review_summary,
    make_record,
    match_mechanics,
    multiplayer_terms,
    parse_owners_band,
    rating_from_counts,
    score_relevance,
    split_tags,
    to_float,
    to_int,
    truncate,
)

STEAM_STORE = "https://store.steampowered.com"
STEAM_APP_URL = "https://store.steampowered.com/app/{appid}/"


class SteamSource:
    name = "steam"

    def __init__(self, *, reviews_per_game: int = DEFAULT_REVIEWS_PER_GAME) -> None:
        self.reviews_per_game = reviews_per_game
        # Steam Store resets connections under load: long backoff, patient retries.
        self.store = ResilientSession(
            "steam_store",
            cache_ttl=3 * 24 * 3600,
            min_interval=0.8,
            max_attempts=8,
            backoff=1.2,
            timeout=25,
            circuit_threshold=4,
            circuit_cooldown=45,
        )
        self._tag_cache: dict[str, dict[str, dict]] = {}

    # -- discovery ---------------------------------------------------------
    def _steamspy(self, payload: dict[str, Any], attempts: int = 4) -> dict | None:
        for attempt in range(1, attempts + 1):
            try:
                data = steamspypi.download(payload)
                if isinstance(data, dict):
                    return data
            except Exception as exc:  # steamspypi raises bare exceptions
                if attempt == attempts:
                    print(f"  [steamspy] {payload.get('tag') or payload.get('request')} failed: {exc}")
            time.sleep(1.5 * attempt)
        return None

    def tag_games(self, tag: str, *, refresh: bool = False) -> dict[str, dict]:
        """All SteamSpy appids carrying ``tag`` (cached per process)."""
        if not refresh and tag in self._tag_cache:
            return self._tag_cache[tag]
        data = self._steamspy({"request": "tag", "tag": tag}) or {}
        self._tag_cache[tag] = data
        return data

    def discover(
        self,
        *,
        limit_per_tag: int | None = None,
        tags: Iterable[str] | None = None,
    ) -> dict[str, dict]:
        """Union of SteamSpy tag listings, keyed by appid.

        Each value carries the tag hits so relevance can be scored without a
        per-app request.
        """
        wanted = list(tags or STEAM_TAGS)
        candidates: dict[str, dict] = {}

        for tag in wanted:
            games = self.tag_games(tag)
            items = list(games.values())
            if limit_per_tag:
                items = sorted(items, key=lambda g: to_int(g.get("positive")) or 0, reverse=True)[
                    :limit_per_tag
                ]
            print(f"  [steam] tag {tag!r}: {len(games):,} apps (using {len(items)})")
            for info in items:
                appid = str(info.get("appid") or "").strip()
                if not appid:
                    continue
                entry = candidates.setdefault(appid, {"info": info, "matched_tags": set()})
                entry["matched_tags"].add(tag)
        return candidates

    # -- record building ---------------------------------------------------
    def base_record(self, appid: str, entry: dict) -> dict:
        info: dict = entry["info"]
        matched_tags = sorted(entry["matched_tags"])
        title = info.get("name") or ""
        owners_band = info.get("owners")
        owners_min, owners_max = parse_owners_band(owners_band)
        rating = rating_from_counts(info.get("positive"), info.get("negative"))
        positive = to_int(info.get("positive")) or 0
        negative = to_int(info.get("negative")) or 0

        price_cents = to_float(info.get("price"))
        price_usd = round(price_cents / 100, 2) if price_cents is not None else None
        is_free = bool(price_usd == 0)

        description = ""
        relevance, multiplayer = score_relevance(
            tags=matched_tags,
            text=f"{title} {description}",
            matched_tags=matched_tags,
        )

        return make_record(            source=self.name,
            source_id=appid,
            title=title,
            game_url=STEAM_APP_URL.format(appid=appid),
            developer=info.get("developer") or None,
            publisher=info.get("publisher") or None,
            tags=matched_tags,
            matched_tags=matched_tags,
            rating_100=rating,
            rating_5=round(rating / 20, 2) if rating is not None else None,
            rating_count=positive + negative,
            review_count=positive + negative,
            positive_count=positive,
            negative_count=negative,
            price_usd=price_usd,
            is_free=is_free,
            owners_band=owners_band,
            owners_min=owners_min,
            owners_max=owners_max,
            ccu=to_int(info.get("ccu")),
            description=description,
            relevance_score=relevance,
            is_multiplayer=None,
            enriched=False,
        )

    # -- enrichment --------------------------------------------------------
    def enrich(self, record: dict, *, with_reviews: bool = True) -> list[dict]:
        """Augment ``record`` with SteamSpy details, Store details and review samples.

        SteamSpy is reliable, so tags/genre are always refreshed. The Steam Store
        endpoints reset connections from some networks; when they fail the record
        keeps its SteamSpy data and ``store_fetched`` stays false so a later run
        can retry the enrichment.
        """
        appid = record["source_id"]
        catalog = self._steamspy({"request": "appdetails", "appid": appid}) or {}
        store = self._store_appdetails(appid) or {}

        tags = split_tags(catalog.get("tags"))
        # SteamSpy's appdetails tag cloud is truncated to the top ~20 tags, so a
        # game discovered through a tag may not list it back. Keep both views.
        all_tags = list(dict.fromkeys([*(record.get("matched_tags") or []), *tags])) or list(
            record.get("tags") or []
        )
        genres = split_tags(catalog.get("genre")) or split_tags(
            [g.get("description") for g in store.get("genres") or []]
        )
        categories = [c.get("description", "") for c in store.get("categories") or []]

        description = truncate(
            store.get("short_description") or store.get("detailed_description") or "",
            800,
        )
        long_text = " ".join(
            [
                record.get("title") or "",
                description,
                store.get("detailed_description") or "",
                *all_tags,
                *categories,
            ]
        )

        price_overview = store.get("price_overview") or {}
        price_usd = record.get("price_usd")
        if price_overview.get("final") is not None:
            price_usd = round(price_overview["final"] / 100, 2)
        is_free = bool(store.get("is_free")) or bool(price_usd == 0)

        relevance, multiplayer = score_relevance(
            tags=all_tags,
            text=long_text,
            matched_tags=record.get("matched_tags") or [],
        )
        if any(tag in MULTIPLAYER_TAGS for tag in all_tags) or any(
            "multi" in category.lower() or "pvp" in category.lower() for category in categories
        ):
            multiplayer = True

        platforms = [key for key, value in (store.get("platforms") or {}).items() if value]

        record.update(
            {
                "tags": all_tags,
                "genres": genres,
                "primary_genre": genres[0] if genres else None,
                "description": description or (record.get("description") or ""),
                "developer": (store.get("developers") or [record.get("developer")])[0],
                "publisher": (store.get("publishers") or [record.get("publisher")])[0],
                "release_date": (store.get("release_date") or {}).get("date")
                or record.get("release_date"),
                "platforms": platforms or record.get("platforms") or [],
                "price_usd": price_usd,
                "is_free": is_free,
                "relevance_score": relevance,
                "is_multiplayer": multiplayer,
                "mechanics": match_mechanics(long_text),
                "multiplayer_signals": multiplayer_terms(long_text),
                "enriched": True,
            }
        )

        reviews: list[dict] = []
        if with_reviews:
            summary, reviews = self._reviews(appid)
            if summary:
                record["review_score_desc"] = summary.get("review_score_desc")

            sample = [
                {
                    "rating": 5 if review.get("voted_up") else 2,
                    "text": review.get("review") or "",
                    "helpful": review.get("votes_up"),
                    "language": review.get("language"),
                }
                for review in reviews
            ]
            text, snippets = build_review_summary(
                sample,
                positive=record.get("positive_count"),
                negative=record.get("negative_count"),
                score_desc=record.get("review_score_desc"),
            )
            record["review_summary"] = text
            record["review_snippets"] = snippets

        record["store_fetched"] = bool(store) or bool(reviews)
        return reviews

    def _store_appdetails(self, appid: str) -> dict | None:
        data = self.store.get(
            f"{STEAM_STORE}/api/appdetails",
            {"appids": appid, "cc": STEAM_COUNTRY, "l": STEAM_LANG},
        )
        if not isinstance(data, dict):
            return None
        entry = data.get(appid) or {}
        if not entry.get("success"):
            return None
        return entry.get("data")

    def _reviews(self, appid: str) -> tuple[dict | None, list[dict]]:
        """English reviews when available, topped up with other languages.

        Steam's language filter can leave small or non-English games with almost
        no usable text, which makes the review summary useless. The sample is
        also topped up with the missing sentiment so the summary always has both
        a praise and a criticism when the game has any.
        """
        summary, reviews = self._fetch_reviews(appid, "english")
        if len(reviews) < 5:
            fallback_summary, fallback_reviews = self._fetch_reviews(appid, "all")
            seen = {review.get("recommendationid") for review in reviews}
            reviews += [
                review for review in fallback_reviews if review.get("recommendationid") not in seen
            ]
            summary = summary or fallback_summary

        has_positive = any(review.get("voted_up") for review in reviews)
        has_negative = any(not review.get("voted_up") for review in reviews)
        if reviews and not (has_positive and has_negative):
            review_type = "positive" if not has_positive else "negative"
            _, top_up = self._fetch_reviews(appid, "english", review_type=review_type)
            seen = {review.get("recommendationid") for review in reviews}
            reviews += [review for review in top_up if review.get("recommendationid") not in seen]
        return summary, reviews

    def _fetch_reviews(
        self, appid: str, language: str, review_type: str = "all"
    ) -> tuple[dict | None, list[dict]]:
        data = self.store.get(
            f"{STEAM_STORE}/appreviews/{appid}",
            {
                "json": 1,
                # filter=all collapses to a single "most helpful" review for
                # most apps; filter=recent returns a full page.
                "filter": "recent",
                "language": language,
                "review_type": review_type,
                "purchase_type": "all",
                "num_per_page": self.reviews_per_game,
            },
        )
        if isinstance(data, dict) and data.get("success"):
            return data.get("query_summary"), data.get("reviews") or []
        return None, []
