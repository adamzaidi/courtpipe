"""Label Rule 12(b)(6) orders from docket-entry descriptions.

The order text is a label store. Feature builders must not call this
on complaint or motion text and must not copy the return values into
the feature matrix.
"""

from __future__ import annotations

import re
from typing import Any

PROPOSED_ORDER = re.compile(r"text of proposed order|\bproposed order\b", re.I)
REPORT_AND_RECOMMENDATION = re.compile(
    r"report and recommendation|\brecommendation of the magistrate\b",
    re.I,
)
ADOPTS_R_AND_R = re.compile(r"\badopt", re.I)
RECONSIDERATION = re.compile(r"\breconsider", re.I)
WITHDRAWN = re.compile(r"\bwithdrawn\b|\bstipulat(?:ed|ion)\b", re.I)
MOOT = re.compile(r"\bas moot\b|\bmoot\b", re.I)
RULE_12D = re.compile(
    r"12\s*\(\s*d\s*\)|converted.{0,80}summary[- ]judgment|treat(?:ed|ing).{0,40}as.{0,20}summary",
    re.I,
)
RULE_12B6 = re.compile(r"12\s*\(\s*b\s*\)\s*\(\s*6\s*\)|failure to state a claim", re.I)
RULE_12B1 = re.compile(r"12\s*\(\s*b\s*\)\s*\(\s*1\s*\)", re.I)
RULE_12B2 = re.compile(r"12\s*\(\s*b\s*\)\s*\(\s*2\s*\)", re.I)
MOTION_TO_DISMISS = re.compile(r"motion to dismiss", re.I)
ORDERISH = re.compile(r"\border\b|\bminute entry\b|\bmemorandum opinion\b|\bopinion and order\b", re.I)
OPPOSITIONISH = re.compile(r"\bopposition\b|\breply brief\b|\bmemorandum in opposition\b", re.I)
MOTION_FILING = re.compile(r"^\s*motion\b|\bmotion to dismiss\b", re.I)
GRANT_IN_PART = re.compile(r"grant(?:ing|ed)?\s+in\s+part", re.I)
DENY_IN_PART = re.compile(r"deny(?:ing|ied)?\s+in\s+part", re.I)
GRANTING = re.compile(r"\bgrant(?:ing|ed)\b", re.I)
DENYING = re.compile(r"\bdeny(?:ing|ied)\b", re.I)
DOC_AFTER_VERB = re.compile(
    r"(?:grant(?:ing|ed)|deny(?:ing|ied))(?:\s+in\s+part(?:\s+and\s+deny(?:ing|ied)\s+in\s+part)?)?\s+(\d+)\s+motion",
    re.I,
)
LEAVE_GRANTED = re.compile(
    r"leave to amend|with leave|may amend|shall file an amended|amended complaint within",
    re.I,
)
LEAVE_DENIED = re.compile(r"with prejudice|without leave|leave to amend is denied|leave denied", re.I)
WITHOUT_PREJUDICE = re.compile(r"without prejudice", re.I)
FILED_BY = re.compile(r"(?:filed\s+by|by defendants?|by defendant)\s+(.+)$", re.I)


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def is_proposed_order(description: str) -> bool:
    return bool(PROPOSED_ORDER.search(_text(description)))


def is_report_and_recommendation(description: str) -> bool:
    text = _text(description)
    if not REPORT_AND_RECOMMENDATION.search(text):
        return False
    if ADOPTS_R_AND_R.search(text) and ORDERISH.search(text):
        return False
    return True


def is_reconsideration(description: str) -> bool:
    return bool(RECONSIDERATION.search(_text(description)))


def motion_grounds(description: str) -> dict[str, bool]:
    text = _text(description)
    b6 = bool(RULE_12B6.search(text))
    b1 = bool(RULE_12B1.search(text))
    b2 = bool(RULE_12B2.search(text))
    mtd = bool(MOTION_TO_DISMISS.search(text))
    jurisdictional_only = (b1 or b2) and not b6
    is_12b6 = bool(b6 or (mtd and not jurisdictional_only))
    return {
        "is_12b6": is_12b6,
        "also_12b1": bool(b1 and is_12b6),
        "also_12b2": bool(b2 and is_12b6),
        "jurisdictional_only": bool(jurisdictional_only),
    }


def is_motion_filing(description: str, short_description: str = "") -> bool:
    blob = _text(description) + " " + _text(short_description)
    if OPPOSITIONISH.search(blob):
        return False
    if is_candidate_order(description):
        return False
    grounds = motion_grounds(blob)
    if not grounds["is_12b6"]:
        return False
    return bool(MOTION_FILING.search(blob) or MOTION_TO_DISMISS.search(blob))


def is_candidate_order(description: str) -> bool:
    text = _text(description)
    if is_proposed_order(text) or is_report_and_recommendation(text) or is_reconsideration(text):
        return False
    if OPPOSITIONISH.search(text):
        return False
    if not ORDERISH.search(text):
        return False
    if not (MOTION_TO_DISMISS.search(text) or RULE_12B6.search(text)):
        return False
    return True


def is_excluded_disposition(description: str) -> str | None:
    text = _text(description)
    if WITHDRAWN.search(text):
        return "withdrawn"
    if MOOT.search(text):
        return "moot"
    if RULE_12D.search(text):
        return "rule_12d"
    return None


def linked_document_numbers(description: str) -> list[int]:
    return [int(n) for n in DOC_AFTER_VERB.findall(_text(description))]


def leave_modifier(description: str) -> str:
    text = _text(description)
    if LEAVE_DENIED.search(text) and not (WITHOUT_PREJUDICE.search(text) and not re.search(r"with prejudice", text, re.I)):
        if re.search(r"with prejudice|without leave|leave to amend is denied|leave denied", text, re.I):
            return "leave_denied"
    if re.search(r"with prejudice|without leave|leave to amend is denied|leave denied", text, re.I):
        return "leave_denied"
    if LEAVE_GRANTED.search(text) and not re.search(r"leave to amend is denied|without leave", text, re.I):
        return "leave_granted"
    return "leave_not_stated"


def three_way_label(description: str) -> str | None:
    """Return granted / granted_in_part / denied, or None if unreadable."""
    text = _text(description)
    if GRANT_IN_PART.search(text) or (
        GRANTING.search(text) and DENY_IN_PART.search(text)
    ) or (
        GRANTING.search(text) and DENYING.search(text) and re.search(r"in part", text, re.I)
    ):
        return "granted_in_part"
    if GRANTING.search(text) and DENYING.search(text) and not GRANT_IN_PART.search(text):
        # "granting in part and denying in part" already handled.
        if re.search(r"in part", text, re.I):
            return "granted_in_part"
    if GRANTING.search(text):
        return "granted"
    if DENYING.search(text):
        return "denied"
    return None


def extract_filed_by(description: str) -> str:
    match = FILED_BY.search(_text(description).replace("\n", " "))
    if not match:
        return ""
    return match.group(1).strip().rstrip(".")


def label_order(description: str) -> dict[str, Any]:
    """Parse one docket-entry description that might be a ruling."""
    text = _text(description)
    result: dict[str, Any] = {
        "is_ruling": False,
        "exclude_reason": None,
        "label": None,
        "leave": "leave_not_stated",
        "document_numbers": linked_document_numbers(text),
        "grounds": motion_grounds(text),
        "filed_by": extract_filed_by(text),
        "label_source": "entry_description",
    }
    if is_proposed_order(text):
        result["exclude_reason"] = "proposed_order"
        return result
    if is_report_and_recommendation(text):
        result["exclude_reason"] = "report_and_recommendation"
        return result
    if is_reconsideration(text):
        result["exclude_reason"] = "reconsideration"
        return result
    excluded = is_excluded_disposition(text)
    if excluded:
        result["exclude_reason"] = excluded
        return result
    if not is_candidate_order(text):
        result["exclude_reason"] = "not_an_order"
        return result
    label = three_way_label(text)
    if label is None:
        result["exclude_reason"] = "needs_text"
        return result
    result["is_ruling"] = True
    result["label"] = label
    result["leave"] = leave_modifier(text)
    return result


def y_relief(label: str | None) -> int | None:
    if label in {"granted", "granted_in_part"}:
        return 1
    if label == "denied":
        return 0
    return None
