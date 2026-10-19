"""HTTP helpers: disk cache, retries, per-host rate limiting and a circuit breaker.

The Steam Store endpoints used here reset connections aggressively from some
networks. Every request therefore goes through :class:`ResilientSession`, which
retries with jittered exponential backoff and persists successful payloads so a
re-run never has to fetch the same URL twice.
"""

from __future__ import annotations

import hashlib
import json
import random
import threading
import time
from pathlib import Path
from typing import Any, Iterable

import requests

from .config import CACHE_DIR

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class CircuitOpen(RuntimeError):
    """Reserved for callers that prefer an exception over a ``None`` result."""


class ResilientSession:
    def __init__(
        self,
        name: str,
        *,
        cache_ttl: int = 0,
        min_interval: float = 0.0,
        max_attempts: int = 6,
        backoff: float = 2.0,
        timeout: float = 30.0,
        circuit_threshold: int = 4,
        circuit_cooldown: float = 60.0,
        user_agent: str = DEFAULT_UA,
        headers: dict[str, str] | None = None,
        refresh: bool = False,
    ) -> None:
        self.name = name
        self.cache_ttl = cache_ttl
        self.refresh = refresh
        self.min_interval = min_interval
        self.max_attempts = max_attempts
        self.backoff = backoff
        self.timeout = timeout
        self.circuit_threshold = circuit_threshold
        self.circuit_cooldown = circuit_cooldown

        self._headers = {"User-Agent": user_agent, "Accept-Language": "en-US,en;q=0.9"}
        if headers:
            self._headers.update(headers)

        self._session = self._new_session()
        self._lock = threading.Lock()
        self._last_request = 0.0
        self._fail_streak = 0
        self._open_until = 0.0

        self.stats = {"requests": 0, "cache_hits": 0, "failures": 0, "circuit_skips": 0}

    # -- internals ---------------------------------------------------------
    def _new_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update(self._headers)
        return session

    def _rotate(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass
        self._session = self._new_session()

    def _throttle(self) -> None:
        if self.min_interval <= 0:
            return
        with self._lock:
            wait = self.min_interval - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()

    # -- cache -------------------------------------------------------------
    def _cache_path(self, url: str, params: dict[str, Any] | None, namespace: str = "") -> Path:
        key = url
        if params:
            key += "?" + "&".join(f"{k}={params[k]}" for k in sorted(params))
        if namespace:
            key += f"#{namespace}"
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        prefix = self.name.replace("/", "_")
        return CACHE_DIR / f"{prefix}_{digest}.json"

    def _cache_read(
        self, url: str, params: dict[str, Any] | None, ttl: int, namespace: str = ""
    ) -> Any | None:
        if ttl <= 0:
            return None
        path = self._cache_path(url, params, namespace)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if ttl > 0 and time.time() - payload.get("fetched_at", 0) > ttl:
            return None
        self.stats["cache_hits"] += 1
        return payload.get("data")

    def _cache_write(
        self, url: str, params: dict[str, Any] | None, data: Any, status: int, namespace: str = ""
    ) -> None:
        if self.cache_ttl <= 0:
            return
        path = self._cache_path(url, params, namespace)
        payload = {"url": url, "params": params, "status": status, "fetched_at": time.time(), "data": data}
        tmp = path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            pass

    # -- public API --------------------------------------------------------
    @property
    def circuit_open(self) -> bool:
        return time.monotonic() < self._open_until

    def get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        cache_ttl: int | None = None,
        ok_status: Iterable[int] = (200,),
        encoding: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any | None:
        """Return decoded JSON (or text) for ``url``, or ``None`` if it never succeeded.

        ``encoding`` overrides the charset for endpoints that mislabel their bytes
        (Apple's UGC API declares UTF-8 but returns Windows-1252).
        """
        ttl = self.cache_ttl if cache_ttl is None else cache_ttl
        namespace = encoding or ""
        cached = None if self.refresh else self._cache_read(url, params, ttl, namespace)
        if cached is not None:
            return cached

        if self.circuit_open:
            self.stats["circuit_skips"] += 1
            return None

        last_error: str | None = None
        for attempt in range(1, self.max_attempts + 1):
            self._throttle()
            try:
                self.stats["requests"] += 1
                response = self._session.get(url, params=params, timeout=self.timeout, headers=headers)
                if response.status_code in ok_status:
                    data = self._decode(response, encoding)
                    self._fail_streak = 0
                    self._cache_write(url, params, data, response.status_code, namespace)
                    return data
                last_error = f"HTTP {response.status_code}"
                if response.status_code in (400, 401, 403, 404):
                    # Deterministic client errors: retrying will not help.
                    break
            except (requests.RequestException, ValueError, OSError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"[:160]
                self._rotate()

            if attempt < self.max_attempts:
                sleep_for = self.backoff * attempt + random.uniform(0, 0.75)
                time.sleep(sleep_for)

        self.stats["failures"] += 1
        self._fail_streak += 1
        if self._fail_streak >= self.circuit_threshold:
            self._open_until = time.monotonic() + self.circuit_cooldown
            self._fail_streak = 0
        if last_error:
            print(f"  [{self.name}] giving up on {url} ({last_error})")
        return None

    @staticmethod
    def _decode(response: requests.Response, encoding: str | None = None) -> Any:
        if encoding == "auto":
            # Apple's UGC endpoint mixes UTF-8 and Windows-1252 byte streams.
            try:
                text = response.content.decode("utf-8")
            except UnicodeDecodeError:
                text = response.content.decode("cp1252", errors="replace")
            try:
                return json.loads(text)
            except ValueError:
                return text
        if encoding:
            try:
                return json.loads(response.content.decode(encoding, errors="replace"))
            except ValueError:
                return response.content.decode(encoding, errors="replace")
        content_type = response.headers.get("Content-Type", "")
        if "json" in content_type or response.text.lstrip().startswith(("{", "[")):
            try:
                return response.json()
            except ValueError:
                pass
        return response.text
