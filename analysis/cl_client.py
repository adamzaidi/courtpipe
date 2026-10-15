"""Rate-limited, cached CourtListener GET. Never logs tokens or Authorization."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

import requests

from analysis.cl_auth import auth_headers, courtlistener_token, token_env_set_but_unusable

logger = logging.getLogger("courtpipe.cl_client")

BASE = "https://www.courtlistener.com/api/rest/v4"
DEFAULT_CACHE = Path("data/cache/courtlistener")

# Documented authenticated defaults. The most restrictive window wins.
MAX_PER_MINUTE = 5
MAX_PER_HOUR = 50
MAX_PER_DAY = 125
MIN_INTERVAL_SEC = 12.5  # 5/min with a small buffer


class RateLimiter:
    def __init__(
        self,
        per_minute: int = MAX_PER_MINUTE,
        per_hour: int = MAX_PER_HOUR,
        per_day: int = MAX_PER_DAY,
        min_interval: float = MIN_INTERVAL_SEC,
    ):
        self.per_minute = per_minute
        self.per_hour = per_hour
        self.per_day = per_day
        self.min_interval = min_interval
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

    def __init__(self, cache_dir: Path | str = DEFAULT_CACHE, require_token: bool = True):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
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
        if use_cache and path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        self.limiter.wait()
        logger.info("GET %s", url)
        response = self.session.get(url, params=params, timeout=45)
        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After") or 20)
            logger.warning("CourtListener 429; sleeping %.1fs", min(retry_after, 120))
            time.sleep(min(retry_after, 120))
            self.limiter.wait()
            response = self.session.get(url, params=params, timeout=45)
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
