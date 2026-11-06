"""Rate-limited, cached CourtListener GET. Never logs tokens or Authorization."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

import requests

from analysis.cl_auth import auth_headers, courtlistener_token, token_env_set_but_unusable

logger = logging.getLogger("courtpipe.cl_client")

BASE = "https://www.courtlistener.com/api/rest/v4"
DEFAULT_CACHE = Path("data/cache/courtlistener")

# Documented authenticated defaults (wiki.free.law CourtListener REST v4 overview,
# checked 2026-11-03). The most restrictive window wins. If Free Law Project grants
# this account higher limits, set CL_MAX_PER_MINUTE / CL_MAX_PER_HOUR /
# CL_MAX_PER_DAY in the environment (GitHub repo variables for the workflow);
# no code change is needed.
DEFAULT_PER_MINUTE = 5
DEFAULT_PER_HOUR = 50
DEFAULT_PER_DAY = 125


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    value = int(raw)
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def configured_limits() -> tuple[int, int, int]:
    """(per_minute, per_hour, per_day) from CL_MAX_PER_* or the documented defaults."""
    return (
        _env_int("CL_MAX_PER_MINUTE", DEFAULT_PER_MINUTE),
        _env_int("CL_MAX_PER_HOUR", DEFAULT_PER_HOUR),
        _env_int("CL_MAX_PER_DAY", DEFAULT_PER_DAY),
    )


MAX_PER_MINUTE, MAX_PER_HOUR, MAX_PER_DAY = DEFAULT_PER_MINUTE, DEFAULT_PER_HOUR, DEFAULT_PER_DAY
MIN_INTERVAL_SEC = 12.5  # 5/min with a small buffer


class BudgetExhausted(RuntimeError):
    """Raised before a network request that would exceed the run's request budget."""


class RateLimited(BudgetExhausted):
    """CourtListener kept answering 429. Ends the run cleanly; nothing is skipped."""


class DocketCapReached(RuntimeError):
    """The current docket used its per-run request allowance. Its cached pages are kept."""


class RateLimiter:
    def __init__(
        self,
        per_minute: Optional[int] = None,
        per_hour: Optional[int] = None,
        per_day: Optional[int] = None,
        min_interval: Optional[float] = None,
    ):
        env_minute, env_hour, env_day = configured_limits()
        self.per_minute = per_minute or env_minute
        self.per_hour = per_hour or env_hour
        self.per_day = per_day or env_day
        # Spread requests evenly inside the minute window, with a 4% buffer.
        self.min_interval = min_interval if min_interval is not None else 60.0 / self.per_minute * 1.04
        self._stamps: list[float] = []
        self._last = 0.0

    def wait(self) -> None:
        now = time.time()
        gap = self.min_interval - (now - self._last)
        if gap > 0:
            time.sleep(gap)
            now = time.time()
        while True:
            now = time.time()
            self._stamps = [t for t in self._stamps if now - t < 86400]
            minute = sum(1 for t in self._stamps if now - t < 60)
            hour = sum(1 for t in self._stamps if now - t < 3600)
            day = len(self._stamps)
            waits = []
            if minute >= self.per_minute:
                waits.append(60 - (now - min(t for t in self._stamps if now - t < 60)))
            if hour >= self.per_hour:
                waits.append(3600 - (now - min(t for t in self._stamps if now - t < 3600)))
            if day >= self.per_day:
                waits.append(86400 - (now - min(self._stamps)))
            if not waits:
                break
            time.sleep(max(0.05, max(waits)))
        self._stamps.append(time.time())
        self._last = time.time()


def _cache_key(url: str, params: Optional[dict]) -> str:
    blob = url + "?" + urlencode(sorted((params or {}).items()), doseq=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class CourtListenerClient:
    """Modest authenticated (or public search) client with on-disk cache."""

    def __init__(
        self,
        cache_dir: Path | str = DEFAULT_CACHE,
        require_token: bool = True,
        max_requests: Optional[int] = None,
    ):
        self.max_requests = max_requests
        self.requests_made = 0
        # Absolute requests_made value at which the current docket must yield.
        self.docket_cap: Optional[int] = None
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # Cache files read or written since the last track_cache() call. The MTD fetch
        # uses this to delete a docket's raw pages once its extract row is written.
        self._tracked: Optional[set[Path]] = None
        self.require_token = require_token
        self.limiter = RateLimiter()
        self.session = requests.Session()
        self.session.headers.update(auth_headers())
        self._token_present = courtlistener_token() is not None
        if require_token and not self._token_present:
            extra = (
                " A token environment variable is set but is not a usable CourtListener "
                "credential (not token-shaped, or not latin-1). The value is not printed."
                if token_env_set_but_unusable()
                else ""
            )
            raise RuntimeError(
                "Set COURTLISTENER_API_TOKEN or COURTLISTENER_API_KEY in the environment."
                + extra
                + " This command does not run without a usable token. Evaluate against "
                "tests/fixtures instead, or export a token from your CourtListener profile."
            )

    def get_json(self, url: str, params: Optional[dict] = None, use_cache: bool = True) -> dict[str, Any]:
        key = _cache_key(url, params)
        path = self.cache_dir / f"{key}.json"
        if use_cache and self._tracked is not None:
            self._tracked.add(path)
        if use_cache and path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        self._spend()
        logger.info("GET %s", url)
        response = self.session.get(url, params=params, timeout=45)
        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After") or 20)
            logger.warning("CourtListener 429; sleeping %.1fs", min(retry_after, 120))
            time.sleep(min(retry_after, 120))
            self._spend()
            response = self.session.get(url, params=params, timeout=45)
            if response.status_code == 429:
                raise RateLimited("CourtListener returned 429 twice; ending the run")
        if response.status_code == 401:
            raise RuntimeError(
                "CourtListener returned 401. Re-authenticate COURTLISTENER_API_TOKEN "
                "or COURTLISTENER_API_KEY. The token is not printed."
            )
        response.raise_for_status()
        payload = response.json()
        if use_cache:
            path.write_text(json.dumps(payload), encoding="utf-8")
        return payload

    def track_cache(self) -> None:
        """Start recording which cache files the following requests touch."""
        self._tracked = set()

    def drop_tracked_cache(self) -> int:
        """Delete every cache file touched since track_cache(); stop tracking. Returns bytes freed."""
        freed = 0
        for path in self._tracked or ():
            try:
                freed += path.stat().st_size
                path.unlink()
            except FileNotFoundError:
                pass
        self._tracked = None
        return freed

    def stop_tracking_cache(self) -> None:
        """Stop recording without deleting anything (the docket will resume from cache)."""
        self._tracked = None

    def _spend(self) -> None:
        if self.max_requests is not None and self.requests_made >= self.max_requests:
            raise BudgetExhausted(f"request budget of {self.max_requests} used")
        if self.docket_cap is not None and self.requests_made >= self.docket_cap:
            raise DocketCapReached("docket request allowance used")
        self.requests_made += 1
        self.limiter.wait()

    def remaining(self) -> Optional[int]:
        """Network requests left in this run's budget (None = unlimited)."""
        if self.max_requests is None:
            return None
        return max(0, self.max_requests - self.requests_made)

    def search(self, q: str, search_type: str = "r", page_size: int = 20, **extra) -> dict[str, Any]:
        params = {"q": q, "type": search_type, "page_size": page_size}
        params.update({k: v for k, v in extra.items() if v is not None})
        return self.get_json(f"{BASE}/search/", params=params)

    def docket(self, docket_id: int) -> dict[str, Any]:
        return self.get_json(f"{BASE}/dockets/{int(docket_id)}/")

    def docket_entries(self, docket_id: int, page_size: int = 100) -> list[dict[str, Any]]:
        url = f"{BASE}/docket-entries/"
        params: Optional[dict] = {"docket": int(docket_id), "page_size": page_size}
        rows: list[dict[str, Any]] = []
        while url:
            payload = self.get_json(url, params=params)
            params = None
            rows.extend(payload.get("results") or [])
            url = payload.get("next")
        return rows

    def parties(self, docket_id: int, page_size: int = 100) -> list[dict[str, Any]]:
        url = f"{BASE}/parties/"
        params: Optional[dict] = {"docket": int(docket_id), "page_size": page_size}
        rows: list[dict[str, Any]] = []
        while url:
            payload = self.get_json(url, params=params)
            params = None
            rows.extend(payload.get("results") or [])
            url = payload.get("next")
        return rows

    def cluster(self, cluster_id: int) -> dict[str, Any]:
        return self.get_json(f"{BASE}/clusters/{int(cluster_id)}/")
