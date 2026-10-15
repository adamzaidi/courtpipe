"""CourtListener credentials from the environment. Never log the value."""

from __future__ import annotations

import os
import re
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
# Bidirectional isolates and other format marks often survive a UI copy.
_FORMAT_CHARS = re.compile(r"[\u2066-\u2069\u200b-\u200f\u202a-\u202e\ufeff]")
# Django REST tokens are typically 40 hex chars. Allow a slightly wider single token.
_TOKEN_SHAPE = re.compile(r"^[A-Za-z0-9._-]{16,256}$")


def _sanitize_token(raw: str) -> Optional[str]:
    """Strip copy-paste format marks. Reject values that cannot be an HTTP token.

    The raw value is never logged or returned when it fails the shape check.
    """
    value = _FORMAT_CHARS.sub("", raw).strip()
    if value.lower().startswith("token "):
        value = value[6:].strip()
    if not value:
        return None
    lowered = value.lower()
    if any(marker in lowered for marker in _PLACEHOLDER_MARKERS):
        return None
    if not _TOKEN_SHAPE.fullmatch(value):
        return None
    try:
        value.encode("latin-1")
    except UnicodeEncodeError:
        return None
    return value


def courtlistener_token() -> Optional[str]:
    """Return the token from COURTLISTENER_API_TOKEN, else COURTLISTENER_API_KEY.

    Placeholder values from .env.example and non-token blobs are treated as missing.
    """
    for name in _TOKEN_NAMES:
        raw = os.getenv(name)
        if not raw:
            continue
        value = _sanitize_token(raw)
        if value:
            return value
    return None


def courtlistener_email() -> str:
    raw = (os.getenv("COURTLISTENER_EMAIL") or "").strip()
    try:
        raw.encode("latin-1")
    except UnicodeEncodeError:
        return "local-research"
    return raw


def has_courtlistener_token() -> bool:
    return courtlistener_token() is not None


def auth_headers(product: str = "courtpipe") -> dict[str, str]:
    """Headers for CourtListener. The token is never included when absent."""
    email = courtlistener_email() or "local-research"
    try:
        f"{product} ({email})".encode("latin-1")
    except UnicodeEncodeError:
        product, email = "courtpipe", "local-research"
    headers = {"User-Agent": f"{product} ({email})"}
    token = courtlistener_token()
    if token:
        headers["Authorization"] = f"Token {token}"
    return headers


def token_env_names_present() -> list[str]:
    """Names of token env vars that yield a usable token. Does not return values."""
    present = []
    for name in _TOKEN_NAMES:
        raw = os.getenv(name)
        if raw and _sanitize_token(raw):
            present.append(name)
    return present


def token_env_set_but_unusable() -> bool:
    """True when a token var is non-empty but not a usable CourtListener token.

    Used for error text only. Does not return or log the value.
    """
    if courtlistener_token() is not None:
        return False
    for name in _TOKEN_NAMES:
        raw = os.getenv(name)
        if raw and raw.strip() and not any(m in raw.lower() for m in _PLACEHOLDER_MARKERS):
            return True
    return False
