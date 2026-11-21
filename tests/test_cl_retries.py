"""Request-level retries in the CourtListener client and search-page failures in the
MTD fetch. Offline."""

from __future__ import annotations

import json

import pytest
import requests

import analysis.cl_client as cl
import analysis.mtd.fetch as fetch
from tests.test_mtd_fetch_resume import FakeClient, _extract, _run


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self.headers = {}
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


class _Session:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "a" * 40)
    monkeypatch.setattr(cl.time, "sleep", lambda s: None)
    c = cl.CourtListenerClient(cache_dir=tmp_path, require_token=True)
    c.limiter.wait = lambda: None
    return c


def test_timeout_then_success_is_retried(client):
    client.session = _Session([requests.ReadTimeout("slow"), _Resp(200, {"ok": 1})])
    assert client.get_json("https://x/a") == {"ok": 1}
    assert client.session.calls == 2 and client.requests_made == 2


def test_502_then_success_is_retried(client):
    client.session = _Session([_Resp(502), _Resp(503), _Resp(200, {"ok": 2})])
    assert client.get_json("https://x/b") == {"ok": 2}
    assert client.requests_made == 3


def test_three_timeouts_raise(client):
    client.session = _Session([requests.ReadTimeout("slow")] * 3)
    with pytest.raises(requests.ReadTimeout):
        client.get_json("https://x/c")


def test_404_is_not_retried(client):
    client.session = _Session([_Resp(404)])
    with pytest.raises(requests.HTTPError):
        client.get_json("https://x/d")
    assert client.session.calls == 1


def test_retries_respect_the_budget(client):
    client.max_requests = 1
    client.session = _Session([requests.ReadTimeout("slow"), _Resp(200)])
    with pytest.raises(cl.BudgetExhausted):
        client.get_json("https://x/e")


class FlakySearch(FakeClient):
    """The first search page of query 0 times out once (after client retries)."""

    failed = False

    def search(self, q, search_type="r", page_size=20):
        if fetch.CANDIDATE_QUERIES.index(q) == 0 and not FlakySearch.failed:
            FlakySearch.failed = True
            self._spend()
            raise requests.ReadTimeout("slow")
        return super().search(q, search_type, page_size)


class DeadSearch(FakeClient):
    def search(self, q, search_type="r", page_size=20):
        self._spend()
        raise requests.ConnectionError("down")


class Boom(FakeClient):
    def parties(self, docket_id):
        raise RuntimeError("unexpected")


def _state(tmp_path):
    return json.loads((tmp_path / "cache" / "mtd_fetch_state.json").read_text())


def test_failed_search_page_is_retried_later_in_the_run(tmp_path, monkeypatch):
    FakeClient.instances, FlakySearch.failed = [], False
    monkeypatch.setattr(fetch, "CourtListenerClient", FlakySearch)
    _run(tmp_path)
    run = _state(tmp_path)["runs"][-1]
    assert run["search_failures"] == 1
    assert run["stop"] == "all candidate searches exhausted"
    assert {1, 2} <= set(_extract(tmp_path / "extract.jsonl")), "query 0's dockets still arrive"


def test_unreachable_search_ends_the_run_cleanly(tmp_path, monkeypatch):
    FakeClient.instances = []
    monkeypatch.setattr(fetch, "CourtListenerClient", DeadSearch)
    _run(tmp_path)
    run = _state(tmp_path)["runs"][-1]
    assert run["stop"] == "CourtListener search unreachable"
    assert run["search_failures"] == fetch.MAX_SEARCH_FAILURES


def test_unexpected_error_is_recorded_then_raised(tmp_path, monkeypatch):
    FakeClient.instances = []
    monkeypatch.setattr(fetch, "CourtListenerClient", Boom)
    with pytest.raises(RuntimeError):
        _run(tmp_path)
    assert _state(tmp_path)["runs"][-1]["stop"] == "error: RuntimeError"
