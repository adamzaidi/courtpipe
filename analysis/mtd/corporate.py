"""Corporate-defendant rules from docs/mtd/SPEC.md.

A blank party-type is a stop, not a caption guess.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

_PUNCT = re.compile(r"[^A-Z0-9]+")
_GOV_PHRASES = (
    "UNITED STATES",
    "STATE OF",
    "COMMONWEALTH",
    "CITY OF",
    "COUNTY OF",
    "DEPARTMENT",
    "SECRETARY",
    "COMMISSION",
    "DISTRICT ATTORNEY",
)
_SUFFIX_TOKENS = {
    "INC",
    "INCORPORATED",
    "CORP",
    "CORPORATION",
    "LLC",
    "LLP",
    "LP",
    "LTD",
    "LIMITED",
    "PLC",
    "BANCORP",
    "HOLDINGS",
    "COMPANY",
}
_SUFFIX_SEQUENCES = (
    ("L", "L", "C"),
    ("L", "L", "P"),
    ("P", "L", "C"),
    ("NATIONAL", "ASSOCIATION"),
    ("L", "P"),
    ("N", "A"),
)
_DEFENDANT_TYPES = {"defendant", "respondent", "cross defendant", "cross-defendant"}


class MissingPartyTypeError(ValueError):
    """Raised when the parties payload has no party-type field."""


def normalize_party(value: object) -> str:
    text = "" if value is None else str(value)
    return " ".join(_PUNCT.sub(" ", text.upper()).split())


def _has_suffix(tokens: list[str]) -> bool:
    if any(token in _SUFFIX_TOKENS for token in tokens):
        return True
    for seq in _SUFFIX_SEQUENCES:
        width = len(seq)
        for start in range(0, len(tokens) - width + 1):
            if tuple(tokens[start : start + width]) == seq:
                return True
    return False


def _is_government(normalized: str, tokens: list[str]) -> bool:
    if any(phrase in normalized for phrase in _GOV_PHRASES):
        return True
    for index in range(len(tokens) - 1):
        if tokens[index] == "U" and tokens[index + 1] == "S":
            return True
    return False


def classify_name(name: object) -> str:
    """government, corporate, or other. Role is applied separately."""
    normalized = normalize_party(name)
    tokens = normalized.split() if normalized else []
    if normalized and _is_government(normalized, tokens):
        return "government"
    if normalized and _has_suffix(tokens):
        return "corporate"
    return "other"


def _party_types(party: dict[str, Any]) -> list[str]:
    for key in ("party_types", "party_type", "type"):
        if key not in party:
            continue
        raw = party[key]
        if raw is None:
            return []
        if isinstance(raw, list):
            return [str(item) for item in raw]
        return [str(raw)]
    raise MissingPartyTypeError("parties payload has no party-type field")


def is_defendant_role(party: dict[str, Any]) -> bool:
    types = _party_types(party)
    for item in types:
        normalized = re.sub(r"[-_]+", " ", item.strip().lower())
        if normalized in _DEFENDANT_TYPES:
            return True
    return False


def corporate_defendants(parties: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Defendants whose names pass the corporate suffix rule."""
    found = []
    for party in parties:
        if not is_defendant_role(party):
            continue
        kind = classify_name(party.get("name"))
        if kind == "corporate":
            found.append(party)
    return found


def match_movant(filed_by: str, parties: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    needle = normalize_party(filed_by)
    if not needle:
        return None
    parties = list(parties)
    corporates = corporate_defendants(parties)
    for party in corporates:
        name = normalize_party(party.get("name"))
        if name and (name in needle or needle in name):
            return party
    return None
