"""Search configuration for the card / auto-battler market crawl.

Everything here is data, not logic: tune the queries, tags and mechanic lexicon
without touching the crawler.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
CACHE_DIR = RAW_DIR / "cache"
PROCESSED_DIR = DATA_DIR / "processed"
REPORTS_DIR = DATA_DIR / "reports"

for _dir in (RAW_DIR, CACHE_DIR, PROCESSED_DIR, REPORTS_DIR):
    _dir.mkdir(parents=True, exist_ok=True)

GAMES_STORE = RAW_DIR / "games.jsonl"
REVIEWS_STORE = RAW_DIR / "reviews.jsonl"
GAMES_CSV = PROCESSED_DIR / "games.csv"
REVIEWS_CSV = PROCESSED_DIR / "reviews.csv"

# ---------------------------------------------------------------------------
# Storefronts
# ---------------------------------------------------------------------------
PLAY_COUNTRY = "us"
PLAY_LANG = "en"
PLAY_REVIEW_LANG = "en"
APPLE_COUNTRY = "us"
STEAM_COUNTRY = "us"
STEAM_LANG = "english"

# ---------------------------------------------------------------------------
# Keyword combinations (user-defined scraping templates)
# ---------------------------------------------------------------------------
SEARCH_QUERIES = [
    "auto battler card multiplayer",
    "asynchronous card deckbuilder pvp",
    "autochess card drafting shop",
    "auto combat deckbuilder",
]

# Shorter variants used for storefront search endpoints, which match loosely.
MOBILE_SEARCH_QUERIES = [
    "auto battler",
    "auto chess",
    "card battler",
    "deckbuilder pvp",
    "card game online pvp",
    "roguelike deckbuilder",
    "trading card game multiplayer",
    "asynchronous pvp card game",
]

# ---------------------------------------------------------------------------
# Steam tags (exact SteamSpy tag names) and weight in the relevance score.
# Core tags identify the genre; support tags identify multiplayer/loop signals.
# ---------------------------------------------------------------------------
STEAM_TAGS = {
    "Auto Battler": 5.0,
    "Auto Chess": 5.0,
    "Autochess": 5.0,
    "Card Battler": 4.0,
    "Card Game": 3.0,
    "Roguelike Deckbuilder": 3.0,
    "Trading Card Game": 2.5,
    "Deckbuilding": 2.0,
    "Asynchronous Multiplayer": 2.0,
    "Multiplayer": 1.5,
    "PvP": 1.5,
    "Online Co-Op": 1.0,
    "Competitive": 1.0,
    "Turn-Based Tactics": 1.0,
}

# A game must carry at least one of these tags to be considered on-topic.
STEAM_CORE_TAGS = {
    "Auto Battler",
    "Auto Chess",
    "Autochess",
    "Card Battler",
    "Card Game",
    "Roguelike Deckbuilder",
    "Trading Card Game",
    "Deckbuilding",
}

# Tags/keywords that indicate an online multiplayer focus.
MULTIPLAYER_TAGS = {
    "Multiplayer",
    "PvP",
    "Online Co-Op",
    "Competitive",
    "Asynchronous Multiplayer",
}

MULTIPLAYER_KEYWORDS = [
    "multiplayer",
    "pvp",
    "pvpve",
    "online",
    "matchmaking",
    "ranked",
    "ladder",
    "leaderboard",
    "asynchronous",
    "co-op",
    "coop",
    "live opponent",
    "real-time",
    "ghost",
]

# ---------------------------------------------------------------------------
# Deep mechanics lexicon. Used to mine descriptions and reviews, and to tag
# each game with the mechanics it talks about.
#   label  -> display name
#   group  -> board_placement / card_minion / turn_structure / multiplayer
#   terms  -> case-insensitive substring patterns
# ---------------------------------------------------------------------------
MECHANICS = {
    "grid_positioning": {
        "label": "Grid Positioning",
        "group": "board_placement",
        "terms": ["grid position", "grid-based", "positioning", "place units", "placement phase"],
    },
    "formation": {
        "label": "Formation",
        "group": "board_placement",
        "terms": ["formation", "frontline", "front line", "backline", "back line"],
    },
    "synergy_tags": {
        "label": "Synergy Tags",
        "group": "board_placement",
        "terms": ["synergy", "synergies", "synergize"],
    },
    "tribe_buffs": {
        "label": "Tribe Buffs",
        "group": "board_placement",
        "terms": ["tribe", "tribal", "faction bonus", "race bonus", "class bonus"],
    },
    "adjacency_effect": {
        "label": "Adjacency Effect",
        "group": "board_placement",
        "terms": ["adjacency", "adjacent"],
    },
    "bench_size": {
        "label": "Bench Size",
        "group": "board_placement",
        "terms": ["bench", "reserve slots"],
    },
    "card_drafting": {
        "label": "Card Drafting",
        "group": "card_minion",
        "terms": ["draft", "drafting", "pick phase"],
    },
    "shop_reroll": {
        "label": "Shop Reroll",
        "group": "card_minion",
        "terms": ["reroll", "re-roll", "refresh the shop", "roll the shop", "shop refresh"],
    },
    "gold_interest": {
        "label": "Gold Interest",
        "group": "card_minion",
        "terms": ["interest", "economy management", "gold income", "save gold"],
    },
    "golden_upgrade": {
        "label": "Golden Upgrade",
        "group": "card_minion",
        "terms": ["golden", "3-star", "three star", "star up", "upgrade unit"],
    },
    "combine_triple": {
        "label": "Combine Triple",
        "group": "card_minion",
        "terms": ["combine three", "three of a kind", "combine units", "triple"],
    },
    "deathrattle": {
        "label": "Deathrattle",
        "group": "card_minion",
        "terms": ["deathrattle", "death rattle", "on death", "when it dies"],
    },
    "trigger_sequence": {
        "label": "Trigger Sequence",
        "group": "card_minion",
        "terms": ["trigger order", "trigger sequence", "resolve order", "priority", "stack"],
    },
    "simultaneous_turns": {
        "label": "Simultaneous Turns",
        "group": "turn_structure",
        "terms": ["simultaneous turn", "simultaneous", "at the same time"],
    },
    "ghost_rounds": {
        "label": "Ghost Rounds",
        "group": "turn_structure",
        "terms": ["ghost", "asynchronous", "async pvp", "offline opponent"],
    },
    "damage_scaling": {
        "label": "Damage Scaling",
        "group": "turn_structure",
        "terms": ["damage scaling", "scaling damage", "round damage", "increasing damage"],
    },
    "elimination_bracket": {
        "label": "Elimination Bracket",
        "group": "turn_structure",
        "terms": ["elimination", "bracket", "last one standing", "last man standing", "survivor"],
    },
    "mmr": {
        "label": "MMR / Ranked Ladder",
        "group": "turn_structure",
        "terms": ["mmr", "matchmaking rating", "ranked ladder", "elo", "ranked mode"],
    },
    "asynchronous_pvp": {
        "label": "Asynchronous PvP",
        "group": "multiplayer",
        "terms": ["asynchronous pvp", "async pvp", "ghost data", "offline pvp", "battle recorded decks"],
    },
    "real_time_pvp": {
        "label": "Real-time PvP",
        "group": "multiplayer",
        "terms": ["real-time pvp", "live pvp", "head to head", "real time battles"],
    },
    "deterministic_lockstep": {
        "label": "Deterministic Lockstep",
        "group": "multiplayer",
        "terms": ["deterministic", "lockstep", "state synchronization", "client-side simulation"],
    },
    "serverless_validation": {
        "label": "Serverless Battle Validation",
        "group": "multiplayer",
        "terms": ["serverless", "battle validation", "server authoritative", "anti-cheat"],
    },
}

MECHANIC_GROUPS = {
    "board_placement": "Board & Placement",
    "card_minion": "Card & Minion",
    "turn_structure": "Turn Structure",
    "multiplayer": "Multiplayer Architecture",
}

# Terms that strongly suggest an auto-battler / autochess loop.
AUTO_BATTLER_TERMS = [
    "auto battler",
    "autobattler",
    "auto-battler",
    "auto chess",
    "autochess",
    "shop phase",
    "preparation phase",
    "automated combat",
    "auto combat",
]

# Terms that mark a store listing as a card / deckbuilding game. Used for the
# mobile stores, where there are no reliable tags.
CARD_GAME_TERMS = [
    "card battler",
    "card battle",
    "card game",
    "card-based",
    "deckbuilder",
    "deck building",
    "deck-building",
    "deckbuilding",
    "trading card",
    "collectible card",
    "ccg",
    "tcg",
    "roguelike deckbuilder",
    "card drafting",
    "minions",
    "strategic card",
]

# Tags used for Steam discovery (SteamSpy ``request=tag`` listings). Support
# tags such as Multiplayer/PvP are only used for scoring after enrichment,
# because their listings are far too broad to crawl.
STEAM_DISCOVERY_TAGS = [
    "Auto Battler",
    "Auto Chess",
    "Autochess",
    "Card Battler",
    "Card Game",
    "Roguelike Deckbuilder",
    "Trading Card Game",
    "Deckbuilding",
]

# A discovered game below this score is dropped as off-topic.
MIN_RELEVANCE = {"steam": 0.0, "google_play": 1.5, "app_store": 1.5}

# Play Store genres that are not games.
NON_GAME_GENRES = {
    "tools",
    "productivity",
    "finance",
    "photography",
    "communication",
    "shopping",
    "business",
    "education",
    "medical",
    "news & magazines",
    "books & reference",
    "lifestyle",
    "health & fitness",
}

DEFAULT_ENRICH_LIMIT = 150
DEFAULT_REVIEWS_PER_GAME = 20
DEFAULT_ITUNES_LIMIT = 100
DEFAULT_PLAY_HITS = 30
CACHE_TTL_SECONDS = 3 * 24 * 3600
