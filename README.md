# Card / Auto-Battler Market Research Crawler

Crawl **Steam**, **Google Play** and the **Apple App Store** for card games,
auto battlers, roguelike deckbuilders and asynchronous / online card PvP games.
Everything lands in one normalised schema so it can be explored with pandas.

Built on `steamspypi`, `google-play-scraper` and `app-store-scraper`, plus a few
direct storefront endpoints for data those libraries do not expose.

---

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python crawl.py          # crawl all three storefronts
python analyze.py        # export CSV + write reports
```

On Windows use `.venv\Scripts\activate` instead of `source .venv/bin/activate`.

### Why `app-store-scraper` is not in `requirements.txt`

Version 0.3.5 pins `requests==2.23.0` **exactly**, so it can never resolve
alongside the modern `requests` this project needs:

```
ERROR: Cannot install -r requirements.txt (line 2) and requests>=2.31
  app-store-scraper 0.3.5 depends on requests==2.23.0
```

It is also non-functional upstream — Apple removed the `web-experience-app`
config block the library scrapes its bearer token from, so it always returns
zero reviews. The App Store crawler therefore talks to the iTunes Search API and
Apple's `userReviewsRow` endpoint directly, which works.

If you still want the package (e.g. to retry if Apple restores the endpoint):

```bash
pip install --no-deps -r requirements-optional.txt
```

`--no-deps` is required so it does not downgrade `requests`/`urllib3`. `pip check`
will then warn about the version pin; that warning is harmless.

Outputs:

| Path | Contents |
|---|---|
| `data/raw/games.jsonl` | one JSON object per game (full schema, lists intact) |
| `data/raw/reviews.jsonl` | sampled reviews, deduplicated |
| `data/raw/cache/` | HTTP response cache (re-runs do not re-fetch) |
| `data/processed/games.csv` | flattened games table for pandas/Excel |
| `data/processed/reviews.csv` | flattened reviews table |
| `data/reports/*.csv` | analysis tables |
| `data/reports/market_report.md` | human-readable summary |

---

## Running unattended with `screen`

```bash
cd ~/card_game_data
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

screen -S crawl                 # start a named session
./run_crawl.sh --steam-enrich-limit 2000 --steam-budget 0
#   or: python -u crawl.py --steam-enrich-limit 2000 --steam-budget 0
# then detach:  Ctrl+A  then  D
```

Close the SSH connection. Later:

```bash
screen -ls                      # find the session
screen -r crawl                 # reattach
```

Start it already detached, in one command:

```bash
screen -dmS crawl bash -c 'cd ~/card_game_data && ./run_crawl.sh --steam-enrich-limit 2000 --steam-budget 0'
```

Notes:

* `python -u` (or `run_crawl.sh`, which uses it) keeps output unbuffered, otherwise the log stays empty until the buffer flushes.
* If the crawl finishes while you are detached, the screen window closes and its output is gone. `run_crawl.sh` writes `logs/crawl-<timestamp>.log` so nothing is lost; bare `screen -L` writes `screenlog.0` instead.
* Data is checkpointed every 25 games (`--checkpoint-every`), and SIGTERM/Ctrl+C still flushes everything, so killing the session mid-run keeps what was already crawled. Re-running resumes where it stopped.

## How discovery works

### Steam
Discovery uses **SteamSpy tag listings** (`request=tag`): `Auto Battler`,
`Auto Chess`, `Autochess`, `Card Battler`, `Card Game`,
`Roguelike Deckbuilder`, `Trading Card Game`, `Deckbuilding`.

This is deliberately tag-driven rather than keyword-driven, because Steam's
search API is not stable enough to crawl at scale and tags are what the market
actually uses to find these games.

Enrichment is two-tier:

1. **SteamSpy `appdetails`** (fast, reliable) → full tag cloud, genre, languages.
2. **Steam Store `appdetails` + `appreviews`** (rate limited, occasionally
   resets connections) → release date, platforms, description, price,
   review verdict and English review samples. Review samples always contain at
   least one positive and one negative review when the game has them, so the
   generated summary is balanced.

Store enrichment is best-effort and **resumable**: records that never reached the
Store keep `store_fetched = false` and the next run retries them. `--steam-budget`
caps how many minutes a single run spends there.

### Google Play
`google_play_scraper.search()` for each query in `SEARCH_QUERIES` +
`MOBILE_SEARCH_QUERIES`, then `app()` for details and `reviews()` (most relevant)
for review samples. If the sample happens to contain only positive or only
negative reviews, the missing side is topped up with a filtered request so the
generated summary stays balanced.

### Apple App Store
`iTunes Search API` for discovery and ratings, then review sampling through
`app-store-scraper`. That library scrapes an API token from the app landing page,
which Apple removed in 2024, so it silently returns nothing on many apps. When it
does, its results are used; otherwise the crawler falls back to Apple's
`userReviewsRow` UGC endpoint (which mixes UTF-8 and Windows-1252 bytes — handled).

---

## The normalised schema

Every row in `games.csv` has the same columns regardless of storefront:

| Column | Meaning |
|---|---|
| `source` | `steam`, `google_play` or `app_store` |
| `source_id` | Steam appid / Android package / iTunes trackId |
| `title` | game name |
| `game_url` | canonical store URL |
| `developer`, `publisher` | self-explanatory |
| `primary_genre`, `genres` | genre list (Steam genres come from SteamSpy) |
| `tags` | full tag list (Steam) — union of SteamSpy tags and discovery tags |
| `matched_tags` | the discovery tags the game was found under |
| `matched_queries` | mobile search queries that surfaced the app |
| `rating_100` | **primary score**, normalised to 0–100 |
| `rating_5` | same score on a 0–5 scale |
| `rating_count` | number of ratings/reviews behind the score |
| `review_count` | text reviews available (mobile) / total reviews (Steam) |
| `positive_count`, `negative_count` | Steam thumbs up/down |
| `review_score_desc` | Steam verdict, e.g. "Very Positive" |
| `review_summary` | **short digest of the review sample** (rating split + best praise + best criticism) |
| `review_snippets` | up to three of the most useful review excerpts |
| `price_usd`, `is_free` | price in USD |
| `owners_band`, `owners_min`, `owners_max` | SteamSpy ownership estimate |
| `ccu` | SteamSpy concurrent users |
| `release_date`, `release_year` | release info (year is derived on load) |
| `platforms` | `windows`, `mac`, `linux`, `android`, `ios` |
| `description` | store description (truncated to 800–1200 chars) |
| `mechanics` | mechanic labels detected in the description |
| `multiplayer_signals` | multiplayer keywords detected in the description |
| `relevance_score` | heuristic fit for the card / auto-battler focus |
| `is_multiplayer` | `true` / `false`; **empty** means "not enriched yet, unknown" |
| `enriched` | details were fetched beyond the discovery listing |
| `store_fetched` | the Steam Store (not just SteamSpy) answered for this app |
| `crawled_at` | ISO timestamp |

Ratings are comparable across stores: Steam uses
`positive / (positive + negative) × 100`, mobile uses `score / 5 × 100`.
Note mobile store scores are inflated by short-session 5-star reviews; compare
distributions, not raw values.

---

## Mechanics lexicon

`cardgame_market/config.py` contains a lexicon of operational keywords grouped as
**Board & Placement**, **Card & Minion**, **Turn Structure** and
**Multiplayer Architecture** (grid positioning, synergy tags, shop reroll, gold
interest, combine triple, deathrattle, ghost rounds, MMR, deterministic lockstep,
…). Each crawled description and review is scanned for those terms, so you can
answer questions such as "how many auto battlers advertise interest mechanics?"
straight from the `mechanics` column.

Edit `MECHANICS` to add your own vocabulary; re-running analysis re-tags
descriptions without re-crawling (re-crawl to re-tag older records).

---

## CLI reference

### `crawl.py`

```
--sources steam,google_play,app_store   which storefronts to crawl
--steam-tag "TAG"                       add a SteamSpy tag (repeatable)
--steam-limit-per-tag 400               apps taken per tag, best-reviewed first (0 = all)
--steam-enrich-limit 150                apps that get Store details + reviews
--steam-budget 15                       minutes per run for Store enrichment (0 = unlimited)
--play-hits 30                          results per Google Play query
--itunes-limit 100                      results per iTunes query (max 200)
--reviews-per-game 20                   review samples per game
--review-games 80                       mobile games that get review sampling
--query "..."                           replace the default mobile queries (repeatable)
--min-rating 1.5                        override the relevance cut-off
--require-multiplayer                   keep only games with a multiplayer signal
--refresh                               re-crawl records already stored
--no-cache                              bypass the on-disk response cache
--dry-run                               crawl without writing data/
```

### `analyze.py`

```
--min-ratings 100   minimum ratings for the top-games table
--top 40            rows in the top-games table
--source steam      restrict the console view to one storefront
--no-csv            skip data/processed export
--no-report         skip data/reports
```

---

## Using pandas directly

```python
import pandas as pd

games = pd.read_csv("data/processed/games.csv")
reviews = pd.read_csv("data/processed/reviews.csv")

# Best rated games with a meaningful sample size
top = games.query("rating_count >= 1000").nlargest(20, "rating_100")[
    ["source", "title", "rating_100", "rating_count", "price_usd"]
]

# Which mechanics are advertised most often?
mech = games["mechanics"].fillna("").str.split(" \| ").explode()
mech[mech != ""].value_counts().head(15)

# Auto-battler vs deckbuilder ratings
games[games["tags"].str.contains("Auto Battler", na=False)].groupby("source")["rating_100"].median()
```

`data/processed/games.csv` is written with a UTF-8 BOM so Excel opens non-ASCII
titles correctly; use `encoding="utf-8-sig"` if pandas complains.

---

## Notes and limitations

* **Steam Store endpoints reset connections** from some networks. The HTTP layer
  retries with jittered backoff, caches every successful response and opens a
  circuit breaker after repeated failures. A partial Steam run is normal; re-run
  to fill in the gaps (cached responses are reused).
* **SteamSpy tag listings are noisy** — a few games carry a tag loosely. Keep
  `matched_tags` in mind and use `--min-rating` or `--require-multiplayer` when
  you need a tighter slice.
* Only the top `--steam-enrich-limit` apps get Store details; the rest still have
  SteamSpy ratings, ownership, CCU and tag data. `is_multiplayer` is `None` for
  those rather than a misleading `false`.
* Mobile ratings are cumulative lifetime averages; a relaunched or long-running
  game can look better than it currently is.
* Apple Arcade variants (`Monster Train+`) appear as separate apps and usually
  have no price.
