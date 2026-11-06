"""Resumable, budgeted MTD fetch. Offline: a fake client stands in for CourtListener."""

from __future__ import annotations

import json

import pytest

import analysis.mtd.fetch as fetch
from analysis.cl_client import BudgetExhausted

PAGES_PER_QUERY = 2
HITS_PER_PAGE = 3
OUT_OF_SCOPE = {3}  # docket id whose NOS is outside 160/410/480/850


def _ids(query_index: int, page: int) -> list[int]:
    base = query_index * 100 + page * 10
    return [base + i + 1 for i in range(HITS_PER_PAGE)]


class FakeClient:
    """Each call costs one request, like an uncached CourtListener GET."""

    instances: list["FakeClient"] = []

    def __init__(self, cache_dir=None, require_token=True, max_requests=None):
        self.max_requests = max_requests
        self.requests_made = 0
        self.docket_calls: list[int] = []
        FakeClient.instances.append(self)

    # No cache in this fake; pruning is covered in test_mtd_fetch_large.py.
    def track_cache(self):
        pass

    def drop_tracked_cache(self):
        return 0

    def stop_tracking_cache(self):
        pass

    def _spend(self):
        if self.max_requests is not None and self.requests_made >= self.max_requests:
            raise BudgetExhausted("budget")
        self.requests_made += 1

    def remaining(self):
        return None if self.max_requests is None else self.max_requests - self.requests_made

    def _page(self, qi: int, page: int):
        nxt = f"next://{qi}/{page + 1}" if page + 1 < PAGES_PER_QUERY else None
        return {"results": [{"docket_id": d} for d in _ids(qi, page)], "next": nxt}

    def search(self, q, search_type="r", page_size=20):
        self._spend()
        return self._page(fetch.CANDIDATE_QUERIES.index(q), 0)

    def get_json(self, url, params=None):
        self._spend()
        qi, page = url.removeprefix("next://").split("/")
        return self._page(int(qi), int(page))

    def docket(self, docket_id):
        self._spend()
        self.docket_calls.append(docket_id)
        nos = "190 Other Contract" if docket_id % 100 in OUT_OF_SCOPE else "850 Securities/Commodities"
        return {"court": "nysd", "nature_of_suit": nos, "date_filed": "2018-01-01"}

    def docket_entries(self, docket_id):
        self._spend()
        return []

    def parties(self, docket_id):
        self._spend()
        return []


@pytest.fixture
def fake(monkeypatch):
    FakeClient.instances = []
    monkeypatch.setattr(fetch, "CourtListenerClient", FakeClient)
    return FakeClient


def _extract(path):
    return [json.loads(line)["docket_id"] for line in path.read_text().splitlines() if line.strip()]


def _run(tmp_path, **kw):
    return fetch.fetch_mtd_extract(
        tmp_path / "extract.jsonl",
        tmp_path / "cache" / "cl",
        log=lambda *a: None,
        **{"max_dockets": 1000, **kw},
    )


def test_budget_stops_cleanly_and_resume_adds_without_duplicates(tmp_path, fake):
    _run(tmp_path, max_requests=10)
    first = _extract(tmp_path / "extract.jsonl")
    assert FakeClient.instances[-1].requests_made <= 10
    assert first, "a budget of 10 covers one search page and at least one docket"

    for _ in range(40):
        _run(tmp_path, max_requests=10)
    ids = _extract(tmp_path / "extract.jsonl")
    assert len(ids) == len(set(ids)), "no docket is written twice"

    expected = {
        d
        for qi in range(len(fetch.CANDIDATE_QUERIES))
        for page in range(PAGES_PER_QUERY)
        for d in _ids(qi, page)
        if d % 100 not in OUT_OF_SCOPE
    }
    assert set(ids) == expected
    state = json.loads((tmp_path / "cache" / "mtd_fetch_state.json").read_text())
    assert state["runs"][-1]["stop"] == "all candidate searches exhausted"


def test_out_of_scope_docket_is_skipped_and_never_refetched(tmp_path, fake):
    _run(tmp_path)
    skipped = {3, 103}  # out-of-scope NOS on the first page of queries 0 and 1
    ids = _extract(tmp_path / "extract.jsonl")
    assert not skipped & set(ids)
    _run(tmp_path)
    assert not set(FakeClient.instances[-1].docket_calls) & skipped


def test_docket_interrupted_by_budget_is_kept_for_next_run(tmp_path, fake):
    # One search page (1) + docket (1) + entries (1) = 3; parties would be the 4th.
    _run(tmp_path, max_requests=3)
    out = tmp_path / "extract.jsonl"
    assert not out.exists() or _extract(out) == []
    state = json.loads((tmp_path / "cache" / "mtd_fetch_state.json").read_text())
    first_query = state["queries"][fetch.CANDIDATE_QUERIES[0]]
    assert first_query["pending"][0][0] == _ids(0, 0)[0]

    _run(tmp_path, max_requests=10)
    assert _ids(0, 0)[0] in _extract(tmp_path / "extract.jsonl")


def test_rotation_fills_both_filing_eras(tmp_path, fake):
    # Enough budget for every query's first page plus a few dockets.
    _run(tmp_path, max_requests=40)
    ids = _extract(tmp_path / "extract.jsonl")
    n_nos = len(fetch.NOS_CLAUSES)
    era_of = lambda d: (d // 100) // n_nos  # noqa: E731 - query index -> era
    assert {era_of(d) for d in ids} == {0, 1}


def test_max_dockets_caps_new_rows_per_run(tmp_path, fake):
    _run(tmp_path, max_dockets=2)
    assert len(_extract(tmp_path / "extract.jsonl")) == 2
    _run(tmp_path, max_dockets=2)
    assert len(_extract(tmp_path / "extract.jsonl")) == 4
