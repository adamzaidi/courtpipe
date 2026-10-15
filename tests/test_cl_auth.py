"""Token sanitization. Never assert on a real secret value."""

from __future__ import annotations

from analysis.cl_auth import (
    auth_headers,
    courtlistener_token,
    has_courtlistener_token,
    token_env_set_but_unusable,
)


def test_bidi_wrapped_hex_token_is_accepted(monkeypatch):
    hex_token = "a" * 40
    wrapped = f"\u2068{hex_token}\u2069"
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", wrapped)
    monkeypatch.delenv("COURTLISTENER_API_KEY", raising=False)
    assert courtlistener_token() == hex_token
    headers = auth_headers()
    assert headers["Authorization"] == f"Token {hex_token}"
    headers["Authorization"].encode("latin-1")


def test_token_prefix_is_stripped(monkeypatch):
    hex_token = "b" * 40
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", f"Token {hex_token}")
    monkeypatch.delenv("COURTLISTENER_API_KEY", raising=False)
    assert courtlistener_token() == hex_token


def test_prose_blob_is_not_a_token(monkeypatch):
    blob = "not a token " * 20 + "@ handle ~ name"
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", blob)
    monkeypatch.delenv("COURTLISTENER_API_KEY", raising=False)
    assert courtlistener_token() is None
    assert has_courtlistener_token() is False
    assert token_env_set_but_unusable() is True
    assert "Authorization" not in auth_headers()


def test_placeholder_still_ignored(monkeypatch):
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "your_api_token_here")
    monkeypatch.delenv("COURTLISTENER_API_KEY", raising=False)
    assert courtlistener_token() is None
    assert token_env_set_but_unusable() is False
