"""Normalisation helpers shared by every storefront.

All sources emit the same record shape so the output can be loaded straight into
pandas. Ratings are always exposed on both a 0-100 and a 0-5 scale.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Iterable

from .config import (
    AUTO_BATTLER_TERMS,
    MECHANICS,
    MULTIPLAYER_KEYWORDS,
    STEAM_CORE_TAGS,
    MULTIPLAYER_TAGS,
)

RECORD_FIELDS = [
    "source",
    "source_id",
    "title",
    "game_url",
    "developer",
    "publisher",
    "primary_genre",
    "genres",
    "tags",
    "matched_tags",
    "matched_queries",
    "rating_100",
    "rating_5",
    "rating_count",
    "review_count",
    "positive_count",
    "negative_count",
    "review_score_desc",
    "review_summary",
    "review_snippets",
    "price_usd",
    "is_free",
    "owners_band",
    "owners_min",
    "owners_max",
    "ccu",
    "release_date",
    "platforms",
    "description",
    "mechanics",
    "multiplayer_signals",
    "relevance_score",
    "is_multiplayer",
    "enriched",
    "store_fetched",
    "crawled_at",
]

_LATIN_LIMIT = 0x250


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def to_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def to_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def split_tags(value: Any) -> list[str]:
    """Turn a comma-separated string or an iterable into a clean list."""
    if value is None:
        return []
    if isinstance(value, str):
        items = [part.strip() for part in value.split(",")]
    elif isinstance(value, dict):
        items = [str(key).strip() for key in value]
    else:
        items = [str(part).strip() for part in value]
    return [item for item in items if item]


def normalize_rating(value: Any, scale: float) -> float | None:
    """Convert a rating from ``scale`` (max value) to a 0-100 float."""
    number = to_float(value)
    if number is None or scale <= 0:
        return None
    if number < 0:
        return None
    return round(min(number / scale, 1.0) * 100, 2)


def rating_from_counts(positive: Any, negative: Any) -> float | None:
    pos = to_float(positive) or 0.0
    neg = to_float(negative) or 0.0
    total = pos + neg
    if total <= 0:
        return None
    return round(pos / total * 100, 2)


def parse_owners_band(band: str | None) -> tuple[int | None, int | None]:
    """``'5,000,000 .. 10,000,000'`` -> ``(5000000, 10000000)``."""
    if not band:
        return None, None
    numbers = re.findall(r"[\d,]+", band)
    parsed = []
    for number in numbers[:2]:
        try:
            parsed.append(int(number.replace(",", "")))
        except ValueError:
            continue
    if len(parsed) == 2:
        return parsed[0], parsed[1]
    if len(parsed) == 1:
        return parsed[0], parsed[0]
    return None, None


def parse_installs(value: str | None) -> tuple[int | None, int | None]:
    """``'1,000,000+'`` -> ``(1000000, None)``."""
    if not value:
        return None, None
    numbers = re.findall(r"[\d,]+", value)
    if not numbers:
        return None, None
    try:
        return int(numbers[0].replace(",", "")), None
    except ValueError:
        return None, None


def searchable_text(*parts: Any) -> str:
    return " ".join(str(part) for part in parts if part).lower()


def match_mechanics(text: str) -> list[str]:
    """Return mechanic labels whose trigger terms appear in ``text``."""
    haystack = text.lower()
    labels = []
    for meta in MECHANICS.values():
        if any(term in haystack for term in meta["terms"]):
            labels.append(meta["label"])
    return labels


def multiplayer_terms(text: str) -> list[str]:
    """Multiplayer-related keywords present in ``text`` (deduplicated, stable order)."""
    haystack = text.lower()
    return [term for term in MULTIPLAYER_KEYWORDS if term in haystack]


def auto_battler_mentions(text: str) -> int:
    haystack = text.lower()
    return sum(1 for term in AUTO_BATTLER_TERMS if term in haystack)


def truncate(text: str | None, limit: int) -> str:
    if not text:
        return ""
    flat = re.sub(r"\s+", " ", text).strip()
    if len(flat) <= limit:
        return flat
    return flat[: limit - 3].rstrip() + "..."


_BBCODE = re.compile(r"\[/?(?:b|i|u|h1|h2|h3|list|\*|p|url[^\]]*|img[^\]]*|quote[^\]]*|table|tr|td|th|hr|code|spoiler|\*)\]")
_HTML_TAG = re.compile(r"<[^>]+>")


def clean_text(text: str | None) -> str:
    """Strip Steam BBCode / HTML markup and collapse whitespace."""
    if not text:
        return ""
    cleaned = _BBCODE.sub(" ", text)
    cleaned = _HTML_TAG.sub(" ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def is_latin_text(text: str, threshold: float = 0.8) -> bool:
    """True when most letters in ``text`` are Latin (Steam mislabels CJK reviews)."""
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return True
    latin = sum(1 for char in letters if ord(char) < _LATIN_LIMIT)
    return latin / len(letters) >= threshold


def build_review_summary(
    reviews: Iterable[dict[str, Any]],
    *,
    positive: int | None = None,
    negative: int | None = None,
    score_desc: str | None = None,
    source_label: str = "Steam",
    sample: bool = False,
    headline: str | None = None,
) -> tuple[str, str]:
    """Return ``(summary, snippets)`` built from sampled reviews.

    The summary is deterministic: rating split, then the most useful praise and
    the most useful criticism found in the sample. When ``sample`` is true the
    counts describe the sampled reviews rather than the full population, and
    ``headline`` can supply an authoritative rating line instead.
    """
    reviews = [
        {**review, "text": clean_text(review.get("text"))}
        for review in reviews
        if clean_text(review.get("text"))
    ]
    positive = positive or 0
    negative = negative or 0
    total = positive + negative

    parts: list[str] = []
    if headline:
        parts.append(headline)
    elif total:
        noun = "sampled reviews" if sample else f"{source_label} reviews"
        parts.append(f"{positive / total * 100:.0f}% of {total:,} {noun} are positive")
    if score_desc:
        parts.append(f"{source_label} verdict: {score_desc}")

    if not reviews:
        return ("; ".join(parts) + "." if parts else "", "")

    def rank(review: dict[str, Any]) -> tuple[int, int, int, int, int]:
        text = review.get("text") or ""
        language = str(review.get("language") or "en").lower()
        latin = 1 if is_latin_text(text) else 0
        is_english = 1 if language.startswith("en") else 0
        informative = 1 if 60 <= len(text) <= 800 else 0
        return (latin, is_english, informative, int(review.get("helpful") or 0), len(text))

    ordered = sorted(reviews, key=rank, reverse=True)
    praise = [r for r in ordered if (r.get("rating") or 0) >= 4]
    criticism = [r for r in ordered if (r.get("rating") or 5) <= 2]

    if praise:
        parts.append("Praise: " + truncate(praise[0]["text"], 180))
    if criticism:
        parts.append("Criticism: " + truncate(criticism[0]["text"], 180))

    snippets = " | ".join(truncate(r["text"], 220) for r in ordered[:3])
    return "; ".join(parts), snippets


def score_relevance(
    *,
    tags: Iterable[str],
    text: str,
    matched_tags: Iterable[str] = (),
) -> tuple[float, bool]:
    """Heuristic 0-20+ relevance score for the card / auto-battler focus."""
    from .config import CARD_GAME_TERMS, STEAM_TAGS  # config stays the single source

    tag_set = {tag for tag in tags if tag}
    matched = set(matched_tags) | tag_set

    score = 0.0
    for tag in matched:
        score += STEAM_TAGS.get(tag, 0.0)

    haystack = text.lower()
    score += 2.0 * auto_battler_mentions(haystack)
    score += min(1.5 * sum(1 for term in CARD_GAME_TERMS if term in haystack), 6.0)
    score += min(sum(0.5 for term in MULTIPLAYER_KEYWORDS if term in haystack), 3.0)
    if matched & STEAM_CORE_TAGS:
        score += 3.0

    is_multiplayer = bool(matched & MULTIPLAYER_TAGS) or any(
        term in haystack for term in ("multiplayer", "pvp", "online", "matchmaking", "asynchronous")
    )
    return round(score, 2), is_multiplayer


def make_record(**fields: Any) -> dict[str, Any]:
    """Return a record containing every schema field (missing ones as ``None``)."""
    record = {field: None for field in RECORD_FIELDS}
    record["genres"] = []
    record["tags"] = []
    record["matched_tags"] = []
    record["matched_queries"] = []
    record["mechanics"] = []
    record["platforms"] = []
    record["is_free"] = False
    record["is_multiplayer"] = False
    record["enriched"] = False
    record["store_fetched"] = False
    record["crawled_at"] = utcnow_iso()
    record.update(fields)
    return record
