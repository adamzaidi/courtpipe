"""Large-docket deferral, transient retries, 429 handling, configurable limits. Offline."""

from __future__ import annotations

import json

import pytest
import requests

import analysis.mtd.fetch as fetch
from analysis.cl_client import (
    BudgetExhausted,
    DocketCapReached,
    RateLimited,
    RateLimiter,
    configured_limits,
)

LARGE = 1  # first docket of query 0 has many entry pages
LARGE_PAGES = 12


class Behaviour:
    """Per-test switches the fake reads. Docket ids are query_index * 100 + n."""

    def __init__(self):
        self.timeouts: dict[int, int] = {}  # docket -> remaining timeouts
        self.gone: set[int] = set()
        self.rate_limit_after: int | None = None  # network requests before 429s start
        self.cache: set[tuple] = set()  # survives across runs, like the disk cache
        self.network = 0


class FakeClient:
    behaviour: Behaviour

    def __init__(self, cache_dir=None, require_token=True, max_requests=None):
        self.max_requests = max_requests
        self.requests_made = 0
        self.docket_cap = None

    def _get(self, key):
        if key in self.behaviour.cache:
            return
        if self.max_requests is not None and self.requests_made >= self.max_requests:
            raise BudgetExhausted("budget")
        if self.docket_cap is not None and self.requests_made >= self.docket_cap:
            raise DocketCapReached("cap")
        b = self.behaviour
        if b.rate_limit_after is not None and b.network >= b.rate_limit_after:
            raise RateLimited("429")
        self.requests_made += 1
        b.network += 1
        b.cache.add(key)

    def remaining(self):
        return None if self.max_requests is None else self.max_requests - self.requests_made

    def search(self, q, search_type="r", page_size=20):
        qi = fetch.CANDIDATE_QUERIES.index(q)
        self._get(("search", qi))
        return {"results": [{"docket_id": qi * 100 + n} for n in (1, 2, 3)], "next": None}

    def get_json(self, url, params=None):
        raise AssertionError("single-page searches in this fake")

    def docket(self, docket_id):
        b = self.behaviour
        if docket_id in b.gone:
            response = requests.Response()
            response.status_code = 404
            raise requests.HTTPError(response=response)
        if b.timeouts.get(docket_id, 0) > 0:
            b.timeouts[docket_id] -= 1
            self.requests_made += 1
            raise requests.Timeout("read timed out")
        self._get(("docket", docket_id))
        return {"court": "nysd", "nature_of_suit": "850 Securities/Commodities", "date_filed": "2018-01-01"}

    def docket_entries(self, docket_id):
        pages = LARGE_PAGES if docket_id == LARGE else 1
        for page in range(pages):
            self._get(("entries", docket_id, page))
        return []

    def parties(self, docket_id):
        self._get(("parties", docket_id))
        return []


@pytest.fixture
def behaviour(monkeypatch):
    b = Behaviour()
    FakeClient.behaviour = b
    monkeypatch.setattr(fetch, "CourtListenerClient", FakeClient)
    return b


def _run(tmp_path, max_requests=None, **kw):
    fetch.fetch_mtd_extract(
        tmp_path / "extract.jsonl",
        tmp_path / "cache" / "cl",
        log=lambda *a: None,
        max_requests=max_requests,
        max_dockets=kw.pop("max_dockets", 1000),
        **kw,
    )
    return json.loads((tmp_path / "cache" / "mtd_fetch_state.json").read_text())


def _rows(tmp_path):
    path = tmp_path / "extract.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_large_docket_is_deferred_not_dropped_and_others_keep_flowing(tmp_path, behaviour):
    state = _run(tmp_path, max_requests=30)
    assert [d for d, _ in state["large"]] == [LARGE]
    first = {r["docket_id"] for r in _rows(tmp_path)}
    assert first and LARGE not in first, "small dockets complete while the large one waits"

    for _ in range(10):
        state = _run(tmp_path, max_requests=30)
    rows = {r["docket_id"]: r for r in _rows(tmp_path)}
    assert LARGE in rows, "the large docket completes on later runs"
    assert rows[LARGE]["fetch_large"] is True
    assert all(not r["fetch_large"] for d, r in rows.items() if d != LARGE)
    assert state["large"] == []
    assert len(rows) == len(fetch.CANDIDATE_QUERIES) * 3


def test_large_reserve_does_not_starve_new_dockets(tmp_path, behaviour):
    _run(tmp_path, max_requests=30)
    before = len(_rows(tmp_path))
    state = _run(tmp_path, max_requests=30)
    run = state["runs"][-1]
    assert run["new_dockets"] - run["completed_large"] > 0
    assert len(_rows(tmp_path)) > before


def test_unlimited_budget_finishes_large_docket_next_run(tmp_path, behaviour):
    _run(tmp_path)  # with no budget, a large docket still moves to the queue in phase 2
    state = _run(tmp_path)  # and the next run's phase 1 finishes it (no reserve cap)
    assert LARGE in {r["docket_id"] for r in _rows(tmp_path)}
    assert state["large"] == []


# Budget 10 reaches query 1's first docket (101): query 0's search (1) + large docket 1
# capped at its allowance (5), then query 1's search (1) and docket 101.
def test_timeout_is_retried_on_a_later_run(tmp_path, behaviour):
    behaviour.timeouts[101] = 1
    state = _run(tmp_path, max_requests=10)
    assert state["attempts"] == {"101": 1}
    assert 101 not in state["skipped"]
    for _ in range(6):
        _run(tmp_path, max_requests=30)
    assert 101 in {r["docket_id"] for r in _rows(tmp_path)}


def test_persistent_timeout_is_skipped_after_three_attempts(tmp_path, behaviour):
    behaviour.timeouts[101] = 99
    for _ in range(8):
        state = _run(tmp_path, max_requests=30)
    assert 101 in state["skipped"]
    assert "101" not in state["attempts"]


def test_404_is_skipped_immediately(tmp_path, behaviour):
    behaviour.gone.add(101)
    state = _run(tmp_path, max_requests=10)
    assert 101 in state["skipped"]
    assert state["attempts"] == {}


def test_429_ends_the_run_without_skipping(tmp_path, behaviour):
    behaviour.rate_limit_after = 3
    state = _run(tmp_path, max_requests=30)
    assert state["runs"][-1]["stop"] == "rate limited (429)"
    assert state["skipped"] == []
    behaviour.rate_limit_after = None
    for _ in range(10):
        _run(tmp_path, max_requests=30)
    assert len(_rows(tmp_path)) == len(fetch.CANDIDATE_QUERIES) * 3


def test_limits_default_to_documented_values(monkeypatch):
    for name in ("CL_MAX_PER_MINUTE", "CL_MAX_PER_HOUR", "CL_MAX_PER_DAY"):
        monkeypatch.delenv(name, raising=False)
    assert configured_limits() == (5, 50, 125)
    assert RateLimiter().min_interval == pytest.approx(12.48)


def test_limits_come_from_environment(monkeypatch):
    monkeypatch.setenv("CL_MAX_PER_MINUTE", "20")
    monkeypatch.setenv("CL_MAX_PER_HOUR", "200")
    monkeypatch.setenv("CL_MAX_PER_DAY", "2500")
    limiter = RateLimiter()
    assert (limiter.per_minute, limiter.per_hour, limiter.per_day) == (20, 200, 2500)
    assert limiter.min_interval == pytest.approx(3.12)


def test_bad_limit_is_rejected(monkeypatch):
    monkeypatch.setenv("CL_MAX_PER_DAY", "0")
    with pytest.raises(ValueError):
        configured_limits()
