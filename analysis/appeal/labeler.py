"""Appellate disposition crosswalk from docs/appeal-reversal-spec.md.

The appellate opinion is the label source and is not a feature.
"""

from __future__ import annotations

import re
from typing import Any

PATTERNS = {
    "AFF": re.compile(r"\baffirm", re.I),
    "REV": re.compile(r"\brevers", re.I),
    "VAC": re.compile(r"\bvacat", re.I),
    "REM": re.compile(r"\bremand", re.I),
    "DIS": re.compile(r"\bdismiss", re.I),
    "COA": re.compile(r"certificate of appealability", re.I),
    "MOD": re.compile(r"\bmodif|\bamended\b", re.I),
}
IN_PART = re.compile(r"\bin part\b", re.I)

HEADLINE_POSITIVES = {"reversed", "vacated", "remanded", "mixed"}
HEADLINE_NEGATIVES = {"affirmed"}
EXCLUDED = {
    "affirmed_with_remand",
    "dismissed",
    "coa",
    "unmapped",
    "needs_text",
}


def normalize(text: str) -> str:
    lowered = (text or "").lower()
    return re.sub(r"[^a-z0-9]+", " ", lowered).strip()


def flags_for(text: str) -> dict[str, bool]:
    blob = normalize(text)
    return {name: bool(pattern.search(blob)) for name, pattern in PATTERNS.items()} | {
        "IN_PART": bool(IN_PART.search(blob)),
    }


def label_disposition(text: str) -> dict[str, Any]:
    blob = (text or "").strip()
    if not blob:
        return {
            "fine": "needs_text",
            "y_disturb": None,
            "excluded": True,
            "label_source_used": None,
        }
    flags = flags_for(blob)
    aff, rev, vac, rem = flags["AFF"], flags["REV"], flags["VAC"], flags["REM"]
    dis, coa, mod = flags["DIS"], flags["COA"], flags["MOD"]
    in_part = flags["IN_PART"]

    if coa and not rev and not vac:
        fine = "coa"
    elif dis and not (aff or rev or vac or rem):
        fine = "dismissed"
    elif aff and (rev or vac):
        fine = "mixed"
    elif dis and (aff or rev or vac or rem):
        fine = "mixed"
    elif in_part and aff and rem and not rev and not vac:
        fine = "mixed"
    elif aff and mod and not rev and not vac:
        fine = "mixed"
    elif rev:
        fine = "reversed"
    elif vac:
        fine = "vacated"
    elif aff and rem and not rev and not vac:
        fine = "affirmed_with_remand"
    elif rem and not aff:
        fine = "remanded"
    elif aff:
        fine = "affirmed"
    else:
        fine = "unmapped"

    if fine in HEADLINE_POSITIVES:
        y = 1
        excluded = False
    elif fine in HEADLINE_NEGATIVES:
        y = 0
        excluded = False
    else:
        y = None
        excluded = True
    return {"fine": fine, "y_disturb": y, "excluded": excluded, "flags": flags}


def label_cluster(cluster: dict[str, Any]) -> dict[str, Any]:
    disposition = str(cluster.get("disposition") or "").strip()
    decretal = str(cluster.get("decretal_excerpt") or "").strip()
    source = None
    text = ""
    if disposition:
        text = disposition
        source = "disposition_field"
    elif decretal:
        text = decretal[-1500:]
        source = "decretal"
    parsed = label_disposition(text)
    parsed["label_source"] = source
    parsed["label_text"] = text
    return parsed


def y_disturb_sensitivity(fine: str, mode: str) -> int | None:
    """Headline plus pre-registered sensitivities A/B for affirmed_with_remand."""
    if fine in HEADLINE_POSITIVES:
        return 1
    if fine == "affirmed":
        return 0
    if fine == "affirmed_with_remand":
        if mode == "A":
            return 0
        if mode == "B":
            return 1
    return None
