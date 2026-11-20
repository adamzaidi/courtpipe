"""Wall-clock limit and stored text length for the MTD fetch. Offline."""

from __future__ import annotations

import json

import pytest

import analysis.mtd.fetch as fetch
from tests.test_mtd_fetch_resume import FakeClient, _extract, _run

LONG_TEXT = "x" * 9000


class TextClient(FakeClient):
    def docket_entries(self, docket_id):
        self._spend()
        return [{"id": 1, "date_filed": "2018-02-01", "description": "MOTION to Dismiss",
                 "recap_documents": [{"plain_text": LONG_TEXT, "is_available": True}]}]


@pytest.fixture
def text_fake(monkeypatch):
    FakeClient.instances = []
    monkeypatch.setattr(fetch, "CourtListenerClient", TextClient)
    return TextClient


def _texts(path):
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return [e["plain_text"] for r in rows for e in r["entries"]]


def test_default_keeps_8000_chars(tmp_path, text_fake):
    _run(tmp_path, max_dockets=1)
    assert [len(t) for t in _texts(tmp_path / "extract.jsonl")] == [8000]


def test_text_chars_none_keeps_full_text(tmp_path, text_fake):
    _run(tmp_path, max_dockets=1, text_chars=None)
    assert _texts(tmp_path / "extract.jsonl") == [LONG_TEXT]


def test_time_limit_stops_between_dockets_and_resumes(tmp_path, text_fake, monkeypatch):
    clock = {"t": 0.0}

    def tick():
        clock["t"] += 30.0  # every check costs half a minute of fake time
        return clock["t"]

    monkeypatch.setattr(fetch.time, "monotonic", tick)
    _run(tmp_path, max_minutes=2)
    state = json.loads((tmp_path / "cache" / "mtd_fetch_state.json").read_text())
    assert state["runs"][-1]["stop"] == "time limit reached"
    first = _extract(tmp_path / "extract.jsonl")

    monkeypatch.setattr(fetch.time, "monotonic", lambda: 0.0)
    _run(tmp_path)
    ids = _extract(tmp_path / "extract.jsonl")
    assert len(ids) == len(set(ids)) and set(first) < set(ids)
