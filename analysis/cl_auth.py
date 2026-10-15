"""CourtListener credentials from the environment. Never log the value."""

from __future__ import annotations

import os
from typing import Optional

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

_TOKEN_NAMES = ("COURTLISTENER_API_TOKEN", "COURTLISTENER_API_KEY")
_PLACEHOLDER_MARKERS = (
    "your_api_key",
    "your_api_token",
    "changeme",
    "placeholder",
    "xxx",
)


def courtlistener_token() -> Optional[str]:
    """Return the token from COURTLISTENER_API_TOKEN, else COURTLISTENER_API_KEY.

    Placeholder values from .env.example are treated as missing.
    """
    for name in _TOKEN_NAMES:
        raw = os.getenv(name)
        if not raw:
            continue
        value = raw.strip()
        if not value:
            continue
        lowered = value.lower()
        if any(marker in lowered for marker in _PLACEHOLDER_MARKERS):
            continue
        return value
    return None


def courtlistener_email() -> str:
    return (os.getenv("COURTLISTENER_EMAIL") or "").strip()


def has_courtlistener_token() -> bool:
    return courtlistener_token() is not None


def auth_headers(product: str = "courtpipe") -> dict[str, str]:
    """Headers for CourtListener. The token is never included when absent."""
    email = courtlistener_email() or "local-research"
    headers = {"User-Agent": f"{product} ({email})"}
    token = courtlistener_token()
    if token:
        headers["Authorization"] = f"Token {token}"
    return headers


def token_env_names_present() -> list[str]:
    """Names of token env vars that are set. Does not return values."""
    present = []
    for name in _TOKEN_NAMES:
        raw = os.getenv(name)
        if raw and raw.strip() and not any(m in raw.lower() for m in _PLACEHOLDER_MARKERS):
            present.append(name)
    return present
