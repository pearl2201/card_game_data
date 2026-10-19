"""Pandas analysis and reporting for the crawled market data."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .config import (
    GAMES_CSV,
    GAMES_STORE,
    MECHANIC_GROUPS,
    REPORTS_DIR,
    REVIEWS_CSV,
    REVIEWS_STORE,
)

LIST_COLUMNS = ["genres", "tags", "matched_tags", "matched_queries", "mechanics", "platforms"]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def load_games(path: Path = GAMES_STORE) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_json(path, lines=True, convert_dates=False)
    for column in LIST_COLUMNS:
        if column not in frame.columns:
            frame[column] = [[] for _ in range(len(frame))]
        frame[column] = frame[column].apply(lambda value: value if isinstance(value, list) else [])
    numeric = ["rating_100", "rating_5", "rating_count", "review_count", "price_usd", "ccu",
               "relevance_score", "owners_min", "owners_max", "positive_count", "negative_count"]
    for column in numeric:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if "is_multiplayer" in frame.columns:
        frame["is_multiplayer"] = frame["is_multiplayer"].astype("boolean")
    if "release_date" in frame.columns:
        frame["release_year"] = pd.to_datetime(
            frame["release_date"], errors="coerce", format="mixed", dayfirst=False
        ).dt.year
    return frame


def load_reviews(path: Path = REVIEWS_STORE) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_json(path, lines=True, convert_dates=False)
    if "rating" in frame.columns:
        frame["rating"] = pd.to_numeric(frame["rating"], errors="coerce")
    return frame


def flatten(frame: pd.DataFrame) -> pd.DataFrame:
    """List columns become ' | ' separated strings so the CSV opens cleanly."""
    flat = frame.copy()
    for column in LIST_COLUMNS:
        if column in flat.columns:
            flat[column] = flat[column].apply(
                lambda value: " | ".join(str(item) for item in value) if isinstance(value, list) else ""
            )
    text_columns = ["review_summary", "review_snippets", "description", "primary_genre"]
    for column in text_columns:
        if column in flat.columns:
            flat[column] = flat[column].fillna("")
    return flat


def explode_column(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    if frame.empty or column not in frame.columns:
        return pd.DataFrame(columns=[column, "count"])
    exploded = frame[[column, "source", "rating_100"]].explode(column)
    exploded = exploded[exploded[column].notna()]
    return exploded.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Analyses
# ---------------------------------------------------------------------------
def platform_overview(games: pd.DataFrame) -> pd.DataFrame:
    if games.empty:
        return pd.DataFrame()
    grouped = games.groupby("source")
    overview = pd.DataFrame(
        {
            "games": grouped.size(),
            "rated_games": grouped["rating_100"].apply(lambda s: s.notna().sum()),
            "median_rating": grouped["rating_100"].median().round(1),
            "mean_rating": grouped["rating_100"].mean().round(1),
            "total_ratings": grouped["rating_count"].sum(),
            "multiplayer_share": grouped["is_multiplayer"].mean().mul(100).round(0),
            "enriched_games": grouped["enriched"].apply(lambda s: s.fillna(False).sum()),
            "median_price_usd": grouped["price_usd"].median(),
        }
    )
    overview["total_ratings"] = overview["total_ratings"].fillna(0).astype("int64")
    overview["multiplayer_share"] = overview["multiplayer_share"].astype("Int64")
    return overview.reset_index().sort_values("games", ascending=False)


def top_games(
    games: pd.DataFrame,
    *,
    min_ratings: int = 100,
    limit: int = 40,
    source: str | None = None,
) -> pd.DataFrame:
    if games.empty:
        return pd.DataFrame()
    subset = games
    if source:
        subset = subset[subset["source"] == source]
    subset = subset[
        subset["rating_100"].notna()
        & (subset["rating_count"].fillna(0) >= min_ratings)
    ]
    columns = [
        "source",
        "title",
        "rating_100",
        "rating_count",
        "review_count",
        "primary_genre",
        "tags",
        "price_usd",
        "owners_band",
        "ccu",
        "release_date",
        "is_multiplayer",
        "game_url",
        "review_summary",
    ]
    available = [column for column in columns if column in subset.columns]
    return (
        subset.sort_values(["rating_100", "rating_count"], ascending=False)[available]
        .head(limit)
        .reset_index(drop=True)
    )


def tag_frequency(games: pd.DataFrame, *, limit: int = 40) -> pd.DataFrame:
    exploded = explode_column(games, "tags")
    if exploded.empty:
        return pd.DataFrame()
    counts = exploded[exploded["tags"].astype(str).str.len() > 0].groupby("tags").agg(
        games=("tags", "size"),
        median_rating=("rating_100", "median"),
    )
    counts["median_rating"] = counts["median_rating"].round(1)
    return counts.sort_values("games", ascending=False).head(limit).reset_index()


def mechanic_frequency(games: pd.DataFrame) -> pd.DataFrame:
    exploded = explode_column(games, "mechanics")
    if exploded.empty:
        return pd.DataFrame()
    exploded["group"] = exploded["mechanics"].map(
        {meta["label"]: MECHANIC_GROUPS.get(meta["group"], meta["group"]) for meta in _mechanic_meta()}
    )
    counts = exploded.groupby(["group", "mechanics"]).agg(
        games=("mechanics", "size"),
        median_rating=("rating_100", "median"),
    )
    counts["median_rating"] = counts["median_rating"].round(1)
    return counts.sort_values(["group", "games"], ascending=[True, False]).reset_index()


def _mechanic_meta():
    from .config import MECHANICS

    return MECHANICS.values()


def mechanic_by_source(games: pd.DataFrame) -> pd.DataFrame:
    exploded = explode_column(games, "mechanics")
    if exploded.empty:
        return pd.DataFrame()
    table = pd.crosstab(
        exploded["mechanics"].to_numpy(),
        exploded["source"].to_numpy(),
    )
    return table.sort_values(table.columns.tolist(), ascending=False)


def genre_frequency(games: pd.DataFrame, *, limit: int = 25) -> pd.DataFrame:
    exploded = explode_column(games, "genres")
    if exploded.empty:
        return pd.DataFrame()
    exploded = exploded[exploded["genres"].astype(str).str.len() > 0]
    counts = exploded.groupby("genres").agg(
        games=("genres", "size"),
        median_rating=("rating_100", "median"),
    )
    counts["median_rating"] = counts["median_rating"].round(1)
    return counts.sort_values("games", ascending=False).head(limit).reset_index()


def price_bands(games: pd.DataFrame) -> pd.DataFrame:
    if games.empty:
        return pd.DataFrame()
    priced = games[games["price_usd"].notna()].copy()
    if priced.empty:
        return pd.DataFrame()
    bins = [-0.01, 0.0, 4.99, 9.99, 19.99, 39.99, 1_000_000]
    labels = ["Free", "$0.01-4.99", "$5-9.99", "$10-19.99", "$20-39.99", "$40+"]
    priced["price_band"] = pd.cut(priced["price_usd"], bins=bins, labels=labels)
    result = priced.groupby("price_band", observed=False).agg(
        games=("price_usd", "size"),
        median_rating=("rating_100", "median"),
        median_ratings_count=("rating_count", "median"),
    )
    result["median_rating"] = result["median_rating"].round(1)
    return result.reset_index()


def query_coverage(games: pd.DataFrame) -> pd.DataFrame:
    if games.empty or "matched_queries" not in games.columns:
        return pd.DataFrame()
    exploded = explode_column(games, "matched_queries")
    if exploded.empty:
        return pd.DataFrame()
    counts = exploded.groupby("matched_queries").agg(
        games=("matched_queries", "size"),
        median_rating=("rating_100", "median"),
    )
    counts["median_rating"] = counts["median_rating"].round(1)
    return counts.sort_values("games", ascending=False).reset_index()


def rating_histogram(games: pd.DataFrame) -> pd.DataFrame:
    rated = games[games["rating_100"].notna()]
    if rated.empty:
        return pd.DataFrame()
    bins = [0, 20, 40, 60, 70, 80, 90, 95, 101]
    labels = ["<20", "20-39", "40-59", "60-69", "70-79", "80-89", "90-94", "95-100"]
    rated = rated.assign(band=pd.cut(rated["rating_100"], bins=bins, labels=labels, right=False))
    return pd.crosstab(rated["band"].to_numpy(), rated["source"].to_numpy()).reset_index()


def review_themes(reviews: pd.DataFrame) -> pd.DataFrame:
    """Count mechanic keywords across review text."""
    if reviews.empty or "text" not in reviews.columns:
        return pd.DataFrame()
    from .normalize import match_mechanics

    labelled = reviews.assign(
        mechanics=reviews["text"].fillna("").map(match_mechanics)
    )
    exploded = labelled.explode("mechanics")
    exploded = exploded[exploded["mechanics"].notna()]
    if exploded.empty:
        return pd.DataFrame()
    counts = exploded.groupby(["mechanics", "source"]).size().reset_index(name="mentions")
    return counts.sort_values("mentions", ascending=False)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def build_report(
    games: pd.DataFrame,
    reviews: pd.DataFrame,
    *,
    min_ratings: int = 100,
    top_n: int = 40,
    out_dir: Path = REPORTS_DIR,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    tables = {
        "platform_overview": platform_overview(games),
        "top_games": top_games(games, min_ratings=min_ratings, limit=top_n),
        "tags": tag_frequency(games),
        "genres": genre_frequency(games),
        "mechanics": mechanic_frequency(games),
        "mechanics_by_source": mechanic_by_source(games).reset_index(),
        "price_bands": price_bands(games),
        "query_coverage": query_coverage(games),
        "rating_histogram": rating_histogram(games),
        "review_themes": review_themes(reviews),
    }
    for name, table in tables.items():
        if not table.empty:
            table.to_csv(out_dir / f"{name}.csv", index=False, encoding="utf-8-sig")

    markdown = _render_markdown(games, reviews, tables, min_ratings=min_ratings)
    (out_dir / "market_report.md").write_text(markdown, encoding="utf-8")
    return {"tables": tables, "markdown": markdown}


def _markdown_table(frame: pd.DataFrame, limit: int = 25, drop: tuple[str, ...] = ()) -> str:
    if frame.empty:
        return "_(no data)_\n"
    slim = frame.drop(columns=[c for c in drop if c in frame.columns]).head(limit).copy()
    for column in slim.columns:
        if str(slim[column].dtype) == "boolean":
            slim[column] = slim[column].map({True: "yes", False: "no"})
    slim = slim.fillna("")
    return slim.to_markdown(index=False) + "\n"


def _render_markdown(
    games: pd.DataFrame,
    reviews: pd.DataFrame,
    tables: dict[str, pd.DataFrame],
    *,
    min_ratings: int,
) -> str:
    lines: list[str] = ["# Card / Auto-Battler Market Report", ""]
    if games.empty:
        return "\n".join(lines + ["_No data yet. Run `python crawl.py` first._"])

    lines += [
        f"- Games analysed: **{len(games):,}**",
        f"- Review samples: **{len(reviews):,}**",
        f"- Enriched games (store details + reviews): **{int(games['enriched'].fillna(False).sum()):,}**",
        f"- Multiplayer games: **{int(games['is_multiplayer'].fillna(False).sum()):,}**",
        "",
        "## Storefront overview",
        "",
        _markdown_table(tables["platform_overview"]),
        "## Top rated games",
        "",
        f"Filtered to games with at least {min_ratings:,} ratings.",
        "",
        _markdown_table(
            tables["top_games"],
            limit=40,
            drop=("review_summary", "game_url", "tags", "owners_band", "ccu", "review_count"),
        ),
        "## Most common Steam tags",
        "",
        _markdown_table(tables["tags"], limit=30),
        "## Most common mechanics in descriptions",
        "",
        _markdown_table(tables["mechanics"], limit=40),
        "## Mechanics by storefront",
        "",
        _markdown_table(tables["mechanics_by_source"], limit=40),
        "## Genres",
        "",
        _markdown_table(tables["genres"]),
        "## Price bands vs rating",
        "",
        _markdown_table(tables["price_bands"]),
        "## Rating distribution",
        "",
        _markdown_table(tables["rating_histogram"]),
        "## Search-query coverage (mobile)",
        "",
        _markdown_table(tables["query_coverage"]),
    ]
    if not tables["review_themes"].empty:
        lines += ["## Mechanics mentioned in review samples", "", _markdown_table(tables["review_themes"])]
    return "\n".join(lines)


def export_csv(games: pd.DataFrame, reviews: pd.DataFrame) -> None:
    if not games.empty:
        flatten(games).to_csv(GAMES_CSV, index=False, encoding="utf-8-sig")
    if not reviews.empty:
        reviews.to_csv(REVIEWS_CSV, index=False, encoding="utf-8-sig")
