"""Pre-order features for the motion-to-dismiss track.

The builder never copies order text, later entries, or opinion
disposition language into the matrix.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time
from typing import Any

from analysis.district_circuit import circuit_for_district
from analysis.mtd.corporate import classify_name, corporate_defendants, is_defendant_role
from analysis.mtd.labeler import motion_grounds

NOS_CODES = {"160", "410", "480", "850"}

FORBIDDEN_FEATURE_FIELDS = {
    "order_entry_id",
    "order_description",
    "order_plain_text",
    "order_document_id",
    "dateTerminated",
    "date_terminated",
    "DISP",
    "JUDGMENT",
    "PROCPROG",
    "TERMDATE",
    "outcome_code",
    "outcome_label_fine",
    "disposition_zone_found",
    "evidence_contains_strong_phrase",
    "evidence_match_position",
    "citeCount",
    "posture",
    "procedural_history",
    "syllabus",
    "days_motion_to_order",
}

FORBIDDEN_SUBSTRINGS = (
    "granted",
    "denied",
    "dismissed",
)

CATEGORICAL_FEATURES = [
    "court_id",
    "circuit",
    "nos",
    "cause",
    "jurisdiction_type",
    "jury_demand",
    "assigned_to_id",
    "movant_firm",
]
NUMERIC_FEATURES = [
    "days_complaint_to_motion",
    "n_amended_complaints_before_motion",
    "complaint_amended_while_pending",
    "n_defendants",
    "n_corporate_defendants",
    "opposition_filed",
    "reply_filed",
    "opposition_page_count",
    "reply_page_count",
    "complaint_page_count",
    "complaint_page_missing",
    "motion_page_count",
    "motion_page_missing",
    "complaint_claim_headings",
    "class_allegation",
    "twombly",
    "iqbal",
    "rule_9b",
    "pslra",
    "exhibit_attached",
    "complaint_text_missing",
    "motion_text_missing",
    "opposition_text_missing",
    "also_12b1",
    "also_12b2",
    "judge_unknown",
]
FEATURE_COLUMNS = CATEGORICAL_FEATURES + NUMERIC_FEATURES
TEXT_FEATURE_FIELDS = ("complaint_text", "motion_text", "opposition_text", "reply_text")

_COMPLAINT = re.compile(r"\b(amended\s+)?complaint\b|\bremoved\b", re.I)
_AMENDED_COMPLAINT = re.compile(r"amended complaint", re.I)
_OPPOSITION = re.compile(r"\bopposition\b|\boppose[ds]?\b|\bresponse to motion\b", re.I)
_REPLY = re.compile(r"\breply\b", re.I)
_CLASS = re.compile(r"\bclass action\b|\bon behalf of (all|a class)\b", re.I)
_CLAIM_HEADING = re.compile(r"\b(count|claim)\s+[ivx0-9]+\b", re.I)
_TWOMBLY = re.compile(r"\btwombly\b", re.I)
_IQBAL = re.compile(r"\biqbal\b", re.I)
_RULE9B = re.compile(r"9\s*\(\s*b\s*\)|rule\s+9\(b\)", re.I)
_PSLRA = re.compile(r"\bpslra\b|private securities litigation reform", re.I)


def parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def parse_time(value: Any) -> time | None:
    if value in (None, ""):
        return None
    if isinstance(value, time):
        return value
    text = str(value).strip()
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text[:8], fmt).time()
        except ValueError:
            continue
    return None


def entry_before_order(entry: dict[str, Any], order: dict[str, Any]) -> bool:
    """Spec same-day rule: keep only when strictly earlier."""
    entry_d = parse_date(entry.get("date_filed"))
    order_d = parse_date(order.get("date_filed"))
    if entry_d is None or order_d is None:
        return False
    if entry_d < order_d:
        return True
    if entry_d > order_d:
        return False
    entry_t = parse_time(entry.get("time_filed"))
    order_t = parse_time(order.get("time_filed"))
    if entry_t is None or order_t is None:
        return False
    return entry_t < order_t


def nature_of_suit(raw: Any) -> str:
    text = "" if raw is None else str(raw)
    match = re.search(r"\b(160|410|480|850)\b", text)
    return match.group(1) if match else ""


def _entry_text(entry: dict[str, Any]) -> str:
    return str(entry.get("plain_text") or "")


def _page_count(entry: dict[str, Any] | None) -> tuple[int, int]:
    if not entry:
        return 0, 1
    raw = entry.get("page_count")
    if raw in (None, ""):
        return 0, 1
    try:
        return int(raw), 0
    except (TypeError, ValueError):
        return 0, 1


def build_feature_row(
    docket: dict[str, Any],
    motion: dict[str, Any],
    order: dict[str, Any],
    *,
    include_text: bool = True,
) -> dict[str, Any]:
    """Features from pre-order entries and docket metadata only."""
    entries = list(docket.get("entries") or [])
    parties = list(docket.get("parties") or [])
    allowed = [e for e in entries if entry_before_order(e, order)]
    # The motion itself is always allowed: it predates the order by construction.
    motion_id = motion.get("id")
    if motion_id is not None and all(e.get("id") != motion_id for e in allowed):
        allowed.append(motion)

    complaints = [
        e
        for e in allowed
        if _COMPLAINT.search(str(e.get("description") or "") + " " + str(e.get("short_description") or ""))
    ]
    complaints.sort(key=lambda e: (parse_date(e.get("date_filed")) or date.min, parse_time(e.get("time_filed")) or time.min))
    operative = complaints[-1] if complaints else None
    amended_before_motion = 0
    motion_date = parse_date(motion.get("date_filed"))
    complaint_amended_while_pending = 0
    for entry in complaints:
        desc = str(entry.get("description") or "")
        if not _AMENDED_COMPLAINT.search(desc) and not _AMENDED_COMPLAINT.search(str(entry.get("short_description") or "")):
            continue
        filed = parse_date(entry.get("date_filed"))
        if filed and motion_date and filed < motion_date:
            amended_before_motion += 1
        if filed and motion_date and filed >= motion_date:
            complaint_amended_while_pending = 1

    oppositions = [e for e in allowed if _OPPOSITION.search(str(e.get("description") or "") + " " + str(e.get("short_description") or ""))]
    replies = [e for e in allowed if _REPLY.search(str(e.get("description") or "") + " " + str(e.get("short_description") or ""))]
    opposition = oppositions[-1] if oppositions else None
    reply = replies[-1] if replies else None

    n_def = 0
    for party in parties:
        try:
            if is_defendant_role(party):
                n_def += 1
        except Exception:
            continue
    corporates = corporate_defendants(parties)

    complaint_pages, complaint_missing = _page_count(operative)
    motion_pages, motion_missing = _page_count(motion)
    opp_pages, _ = _page_count(opposition)
    reply_pages, _ = _page_count(reply)

    complaint_text = _entry_text(operative) if operative else ""
    motion_text = _entry_text(motion)
    opposition_text = _entry_text(opposition) if opposition else ""
    reply_text = _entry_text(reply) if reply else ""

    attachments = motion.get("attachments") or []
    exhibit = 1 if attachments else 0

    judge = docket.get("assigned_to_id") or docket.get("assignedTo") or "unknown"
    if judge in (None, "", "None"):
        judge = "unknown"

    grounds = motion_grounds(str(motion.get("description") or "") + " " + str(order.get("description") or ""))
    # Grounds flags from the motion only for features; the order is a label store.
    motion_grounds_only = motion_grounds(str(motion.get("description") or ""))

    complaint_date = parse_date(operative.get("date_filed")) if operative else None
    days = 0
    if complaint_date and motion_date:
        days = max(0, (motion_date - complaint_date).days)

    movant_firm = "unknown"
    for party in corporates:
        attorneys = party.get("attorneys") or party.get("firms") or []
        if attorneys:
            movant_firm = str(attorneys[0])[:80]
            break

    nos = nature_of_suit(docket.get("suitNature") or docket.get("nature_of_suit"))
    court_id = str(docket.get("court_id") or "").lower()

    row = {
        "court_id": court_id or "unknown",
        "circuit": circuit_for_district(court_id),
        "nos": nos or "unknown",
        "cause": str(docket.get("cause") or "unknown")[:80],
        "jurisdiction_type": str(docket.get("jurisdiction") or docket.get("jurisdiction_type") or "unknown")[:40],
        "jury_demand": str(docket.get("juryDemand") or docket.get("jury_demand") or "unknown")[:40],
        "assigned_to_id": str(judge),
        "movant_firm": movant_firm,
        "days_complaint_to_motion": days,
        "n_amended_complaints_before_motion": amended_before_motion,
        "complaint_amended_while_pending": complaint_amended_while_pending,
        "n_defendants": n_def,
        "n_corporate_defendants": len(corporates),
        "opposition_filed": int(opposition is not None),
        "reply_filed": int(reply is not None),
        "opposition_page_count": opp_pages,
        "reply_page_count": reply_pages,
        "complaint_page_count": complaint_pages,
        "complaint_page_missing": complaint_missing,
        "motion_page_count": motion_pages,
        "motion_page_missing": motion_missing,
        "complaint_claim_headings": len(_CLAIM_HEADING.findall(complaint_text)) if complaint_text else 0,
        "class_allegation": int(bool(_CLASS.search(complaint_text) or _CLASS.search(str(operative.get("description") if operative else "")))),
        "twombly": int(bool(_TWOMBLY.search(motion_text))),
        "iqbal": int(bool(_IQBAL.search(motion_text))),
        "rule_9b": int(bool(_RULE9B.search(motion_text))),
        "pslra": int(bool(_PSLRA.search(motion_text))),
        "exhibit_attached": exhibit,
        "complaint_text_missing": int(not bool(complaint_text)),
        "motion_text_missing": int(not bool(motion_text)),
        "opposition_text_missing": int(not bool(opposition_text)),
        "also_12b1": int(motion_grounds_only["also_12b1"] or grounds["also_12b1"]),
        "also_12b2": int(motion_grounds_only["also_12b2"] or grounds["also_12b2"]),
        "judge_unknown": int(str(judge) == "unknown"),
        "complaint_available": int(bool(operative and operative.get("is_available"))),
        "motion_available": int(bool(motion.get("is_available"))),
        "opposition_available": int(bool(opposition and opposition.get("is_available"))),
        "order_available": int(bool(order.get("is_available"))),
    }
    if include_text:
        row["complaint_text"] = complaint_text
        row["motion_text"] = motion_text
        row["opposition_text"] = opposition_text
        row["reply_text"] = reply_text
    return row


def assert_no_leakage(row: dict[str, Any], order: dict[str, Any] | None = None) -> None:
    for name in row:
        if name in FORBIDDEN_FEATURE_FIELDS:
            raise AssertionError(f"forbidden feature column {name}")
        lowered = name.lower()
        if "order_description" in lowered or "order_plain" in lowered:
            raise AssertionError(f"forbidden feature column {name}")
    if order:
        banned = [
            str(order.get("description") or ""),
            str(order.get("plain_text") or ""),
            str(order.get("id") or ""),
        ]
        for value in row.values():
            if value is None:
                continue
            text = str(value)
            for item in banned:
                if item and len(item) > 8 and item in text:
                    raise AssertionError("order text leaked into a feature cell")


def scan_forbidden_tokens(row: dict[str, Any], extra_banned: tuple[str, ...] = FORBIDDEN_SUBSTRINGS) -> list[str]:
    """Used by the leakage fixture: pre-order text must not contain label verbs.

    Metadata columns such as court_id are not scanned for these tokens.
    """
    hits = []
    skip = set(CATEGORICAL_FEATURES) | {
        "complaint_available",
        "motion_available",
        "opposition_available",
        "order_available",
    }
    for name, value in row.items():
        if name in skip or name in NUMERIC_FEATURES:
            continue
        text = str(value or "").lower()
        for token in extra_banned:
            if token in text:
                hits.append(f"{name}:{token}")
    return hits
