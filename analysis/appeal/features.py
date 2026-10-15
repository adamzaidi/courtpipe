"""Pre-decision features for appeal reversal. Appellate opinion text is forbidden."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from analysis.district_circuit import APPELLATE_COURTS, circuit_for_district

FORBIDDEN_FEATURE_FIELDS = {
    "disposition",
    "syllabus",
    "headnotes",
    "summary",
    "posture",
    "procedural_history",
    "history",
    "judges",
    "citation_count",
    "citeCount",
    "scdb_decision_direction",
    "plain_text",
    "html_with_citations",
    "decretal_excerpt",
    "label_text",
    "outcome_code",
    "outcome_label_fine",
    "date_terminated",
    "date_last_filing",
    "days_to_opinion",
}

CATEGORICAL_FEATURES = [
    "circuit",
    "case_type",
    "district_court",
    "district_judge_id",
    "prior_ruling_type",
    "appellant_class",
    "clock_kind",
]
NUMERIC_FEATURES = [
    "argument_held",
    "days_filing_to_argument",
    "time_since_judgment_days",
    "district_opinion_page_count",
    "district_opinion_page_missing",
    "district_citation_count",
    "district_text_missing",
    "judge_unknown",
    "panel_missing",
]
FEATURE_COLUMNS = CATEGORICAL_FEATURES + NUMERIC_FEATURES

_PRIOR = (
    ("summary_judgment", re.compile(r"summary judgment", re.I)),
    ("injunction", re.compile(r"injunct", re.I)),
    ("sentence", re.compile(r"\bsentenc", re.I)),
    ("jury", re.compile(r"\bjury\b", re.I)),
    ("bench", re.compile(r"\bbench\b", re.I)),
    ("dismissed", re.compile(r"\bdismiss", re.I)),
)


def parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not hasattr(value, "hour"):
        return value
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def prior_ruling_type(text: str | None) -> str:
    blob = text or ""
    if not blob:
        return "missing"
    for name, pattern in _PRIOR:
        if pattern.search(blob):
            return name
    return "other"


def resolve_clock(row: dict[str, Any]) -> tuple[date | None, str]:
    argued = parse_date(row.get("date_argued"))
    decision = parse_date(row.get("date_filed") or row.get("decision_date"))
    filed = parse_date(row.get("appeal_date_filed") or row.get("docket_date_filed"))
    if argued and decision and argued < decision:
        return argued, "argument"
    if filed:
        return filed, "appeal_filing"
    return None, "no_clock"


def build_feature_row(row: dict[str, Any], include_district_text: bool = True) -> dict[str, Any]:
    clock, kind = resolve_clock(row)
    judgment = parse_date(row.get("originating_date_judgment") or row.get("district_judgment_date"))
    gap = None
    if clock and judgment:
        gap = (clock - judgment).days
    court_id = str(row.get("court_id") or "").lower()
    district = str(row.get("appeal_from_id") or row.get("district_court") or "").lower()
    if district == "usdistct":
        district = "unknown"
    judge = row.get("assigned_to_id") or row.get("district_judge_id") or "unknown"
    if judge in (None, "", "None"):
        judge = "unknown"
    argued = parse_date(row.get("date_argued"))
    appeal_filed = parse_date(row.get("appeal_date_filed") or row.get("docket_date_filed"))
    days_arg = 0
    if argued and appeal_filed and kind == "argument":
        days_arg = max(0, (argued - appeal_filed).days)
    page = row.get("district_opinion_page_count")
    try:
        page_n = int(page)
        page_missing = 0
    except (TypeError, ValueError):
        page_n = 0
        page_missing = 1
    cites = row.get("district_citation_count")
    try:
        cites_n = int(cites)
    except (TypeError, ValueError):
        cites_n = 0
    district_text = str(row.get("district_opinion_plain_text") or "")
    panel = row.get("argument_judges") or []
    features = {
        "circuit": court_id if court_id in APPELLATE_COURTS else "unknown",
        "case_type": str(row.get("nature_of_suit") or row.get("appellate_case_type") or row.get("cause") or "unknown")[:80],
        "district_court": district or "unknown",
        "district_judge_id": str(judge),
        "prior_ruling_type": prior_ruling_type(row.get("district_disposition")),
        "appellant_class": str(row.get("appellant_class") or "unknown"),
        "clock_kind": kind,
        "argument_held": int(kind == "argument"),
        "days_filing_to_argument": days_arg,
        "time_since_judgment_days": 0 if gap is None else gap,
        "district_opinion_page_count": page_n,
        "district_opinion_page_missing": page_missing,
        "district_citation_count": cites_n,
        "district_text_missing": int(not bool(district_text)),
        "judge_unknown": int(str(judge) == "unknown"),
        "panel_missing": int(not bool(panel)),
        "timeline_inconsistent": int(gap is not None and gap < 0),
        "clock_date": clock.isoformat() if clock else None,
        "decision_date": (parse_date(row.get("date_filed") or row.get("decision_date")) or date.min).isoformat(),
    }
    if include_district_text:
        features["district_opinion_text"] = district_text
    return features


def assert_no_leakage(row: dict[str, Any]) -> None:
    for name in row:
        if name in FORBIDDEN_FEATURE_FIELDS:
            raise AssertionError(f"forbidden feature column {name}")
        lowered = name.lower()
        if lowered in {"disposition", "decretal_excerpt", "plain_text"}:
            raise AssertionError(f"forbidden feature column {name}")
    # Appellate opinion body must never sit under a feature name.
    if "appellate_plain_text" in row or "cluster_plain_text" in row:
        raise AssertionError("appellate opinion text in features")
