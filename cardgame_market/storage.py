"""JSONL persistence for games and reviews (append-friendly, resumable)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable


def _iter_jsonl(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except ValueError:
                continue


class RecordStore:
    """Keyed store backed by JSONL; rewrites atomically on save."""

    def __init__(self, path: Path, key: str = "source_id", source: str | None = None) -> None:
        self.path = path
        self.key = key
        self.source = source
        self.records: dict[str, dict] = {}
        self.load()

    def _key_for(self, record: dict) -> str:
        prefix = record.get("source") or self.source or ""
        return f"{prefix}:{record.get(self.key)}"

    def load(self) -> None:
        for record in _iter_jsonl(self.path):
            if self.source and record.get("source") != self.source:
                continue
            self.records[self._key_for(record)] = record

    def get(self, source: str, source_id: str) -> dict | None:
        return self.records.get(f"{source}:{source_id}")

    def upsert(self, record: dict) -> None:
        self.records[self._key_for(record)] = record

    def upsert_many(self, records: Iterable[dict]) -> None:
        for record in records:
            self.upsert(record)

    def save(self) -> int:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            for record in self.records.values():
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        tmp.replace(self.path)
        return len(self.records)

    def __len__(self) -> int:
        return len(self.records)


class ReviewStore:
    """Append-only review samples, de-duplicated by ``(source, game_id, review_id)``."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.seen: set[tuple[str, str, str]] = set()
        self.count = 0
        self._handle = None
        for review in _iter_jsonl(path):
            self.seen.add(self._seen_key(review))
            self.count += 1

    @staticmethod
    def _seen_key(review: dict) -> tuple[str, str, str]:
        return (
            str(review.get("source")),
            str(review.get("source_id")),
            str(review.get("review_id")),
        )

    def add(self, review: dict) -> bool:
        key = self._seen_key(review)
        if key in self.seen:
            return False
        self.seen.add(key)
        if self._handle is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self.path.open("a", encoding="utf-8")
        self._handle.write(json.dumps(review, ensure_ascii=False) + "\n")
        self.count += 1
        return True

    def add_many(self, reviews: Iterable[dict]) -> int:
        return sum(1 for review in reviews if self.add(review))

    def close(self) -> None:
        if self._handle is not None:
            self._handle.flush()
            self._handle.close()
            self._handle = None

    def __enter__(self) -> "ReviewStore":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


def load_jsonl(path: Path) -> list[dict]:
    return list(_iter_jsonl(path))
