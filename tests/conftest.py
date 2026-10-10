"""Shared pytest fixtures. Tests must not call the network."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _block_http(monkeypatch):
    """CourtListener calls need an API key. Unit tests stay offline."""

    def _blocked(*args, **kwargs):
        raise RuntimeError("HTTP is disabled in tests")

    monkeypatch.setattr("requests.sessions.Session.request", _blocked)
