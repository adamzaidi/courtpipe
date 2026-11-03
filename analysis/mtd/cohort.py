"""Build the scored MTD cohort from a local extract of dockets."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from analysis.mtd.corporate import (
    MissingPartyTypeError,
    classify_name,
    corporate_defendants,
    is_defendant_role,
    match_movant,
)
from analysis.mtd.features import (
    FEATURE_COLUMNS,
    TEXT_FEATURE_FIELDS,
    assert_no_leakage,
    build_feature_row,
    entry_before_order,
    nature_of_suit,
    parse_date,
)
from analysis.mtd.labeler import (
    is_motion_filing,
    is_proposed_order,
    is_report_and_recommendation,
    label_order,
    y_relief,
)

NOS_CODES = {"160", "410", "480", "850"}
TRAIN_START = date(2016, 1, 1)
TRAIN_END = date(2019, 12, 31)
TEST_START = date(2020, 1, 1)
TEST_END = date(2022, 12, 31)
QUARANTINE_START = date(2023, 1, 1)
QUARANTINE_END = date(2023, 12, 31)
MOTION_WINDOW_START = date(2016, 1, 1)
MOTION_WINDOW_END = date(2023, 12, 31)


def load_extract(path: Path) -> list[dict[str, Any]]:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    payload = json.loads(text)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and "dockets" in payload:
        return list(payload["dockets"])
    raise ValueError(f"unrecognized extract shape in {path}")


def _motion_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    found = []
    for entry in entries:
        if is_motion_filing(str(entry.get("description") or ""), str(entry.get("short_description") or "")):
            found.append(entry)
    return found


def _link_order_to_motion(
    order_entry: dict[str, Any],
    parsed: dict[str, Any],
    motions: list[dict[str, Any]],
    pending: list[dict[str, Any]],
) -> dict[str, Any] | str:
    numbers = parsed.get("document_numbers") or []
    by_number = {str(m.get("document_number")): m for m in motions if m.get("document_number") is not None}
    if numbers:
        linked = []
        for number in numbers:
            motion = by_number.get(str(number))
            if motion is not None:
                linked.append(motion)
        if len(linked) == 1:
            return linked[0]
        if len(linked) > 1:
            return "multi"
        return "link_ambiguous"
    if len(pending) == 1:
        return pending[0]
    return "link_ambiguous"


def build_rows(dockets: Iterable[dict[str, Any]]) -> tuple[pd.DataFrame, dict[str, int]]:
    funnel = {
        "dockets_in_scope": 0,
        "mtd_motion_entries": 0,
        "linked_to_order": 0,
        "corporate_movant": 0,
        "complaint_in_recap": 0,
        "motion_in_recap": 0,
        "labeled_cohort": 0,
        "needs_text": 0,
        "link_ambiguous": 0,
        "movant_unknown": 0,
        "withdrawn_or_moot_or_12d": 0,
        "proposed_or_rr": 0,
        "unresolved": 0,
        "missing_party_type": 0,
    }
    rows: list[dict[str, Any]] = []
    for docket in dockets:
        court_id = str(docket.get("court_id") or "").lower()
        if court_id in {"", "usdistct"}:
            continue
        nos = nature_of_suit(docket.get("suitNature") or docket.get("nature_of_suit"))
        if nos not in NOS_CODES:
            continue
        parties = list(docket.get("parties") or [])
        try:
            if parties:
                _ = [is_defendant_role(p) for p in parties]
        except MissingPartyTypeError:
            funnel["missing_party_type"] += 1
            raise
        funnel["dockets_in_scope"] += 1
        entries = list(docket.get("entries") or [])
        motions = _motion_entries(entries)
        funnel["mtd_motion_entries"] += len(motions)
        orders = []
        for entry in entries:
            blob = str(entry.get("description") or "")
            if is_proposed_order(blob) or is_report_and_recommendation(blob):
                funnel["proposed_or_rr"] += 1
                continue
            parsed = label_order(blob)
            if parsed["exclude_reason"] in {"withdrawn", "moot", "rule_12d"}:
                funnel["withdrawn_or_moot_or_12d"] += 1
                continue
            if parsed["is_ruling"] or parsed["exclude_reason"] == "needs_text":
                orders.append((entry, parsed))

        used_motion_ids = set()
        for motion in motions:
            motion_date = parse_date(motion.get("date_filed"))
            if motion_date is None or motion_date < MOTION_WINDOW_START or motion_date > MOTION_WINDOW_END:
                continue
            later_orders = [
                (entry, parsed)
                for entry, parsed in orders
                if parse_date(entry.get("date_filed")) is not None
                and not entry_before_order(entry, {"date_filed": motion.get("date_filed"), "time_filed": motion.get("time_filed")})
                and parse_date(entry.get("date_filed")) >= motion_date
            ]
            later_orders.sort(key=lambda item: parse_date(item[0].get("date_filed")) or date.max)
            if not later_orders:
                funnel["unresolved"] += 1
                continue
            order_entry, parsed = later_orders[0]
            if parsed["exclude_reason"] == "needs_text":
                funnel["needs_text"] += 1
                continue
            pending = [
                m
                for m in motions
                if m.get("id") not in used_motion_ids
                and parse_date(m.get("date_filed")) is not None
                and parse_date(m.get("date_filed")) <= parse_date(order_entry.get("date_filed"))
            ]
            linked = _link_order_to_motion(order_entry, parsed, motions, pending)
            if linked == "link_ambiguous" or linked == "multi":
                funnel["link_ambiguous"] += 1
                continue
            if not isinstance(linked, dict):
                funnel["link_ambiguous"] += 1
                continue
            if linked.get("id") != motion.get("id") and str(linked.get("document_number")) != str(motion.get("document_number")):
                continue
            funnel["linked_to_order"] += 1
            filed_by = parsed.get("filed_by") or ""
            if not filed_by:
                blob = str(motion.get("description") or "")
                from analysis.mtd.labeler import extract_filed_by

                filed_by = extract_filed_by(blob)
            movant = match_movant(filed_by, parties)
            if movant is None:
                # Fall back: a corporate defendant is the movant when the motion names one.
                corporates = corporate_defendants(parties)
                named = []
                blob = (str(motion.get("description") or "") + " " + filed_by).upper()
                for party in corporates:
                    name = str(party.get("name") or "")
                    if name and name.upper() in blob:
                        named.append(party)
                if len(named) == 1:
                    movant = named[0]
                elif len(corporates) == 1 and filed_by:
                    movant = corporates[0]
                else:
                    funnel["movant_unknown"] += 1
                    continue
            if classify_name(movant.get("name")) != "corporate":
                continue
            try:
                if not is_defendant_role(movant):
                    continue
            except MissingPartyTypeError:
                funnel["missing_party_type"] += 1
                raise
            funnel["corporate_movant"] += 1
            label = parsed["label"]
            if label not in {"granted", "granted_in_part", "denied"}:
                funnel["needs_text"] += 1
                continue
            features = build_feature_row(docket, motion, order_entry, include_text=True)
            assert_no_leakage(features, order_entry)
            if features.get("complaint_available"):
                funnel["complaint_in_recap"] += 1
            if features.get("motion_available"):
                funnel["motion_in_recap"] += 1
            funnel["labeled_cohort"] += 1
            used_motion_ids.add(motion.get("id"))
            row = {
                "docket_id": docket.get("docket_id") or docket.get("id"),
                "motion_entry_id": motion.get("id"),
                "order_entry_id": order_entry.get("id"),
                "motion_date": parse_date(motion.get("date_filed")),
                "order_date": parse_date(order_entry.get("date_filed")),
                "court_id": str(docket.get("court_id") or "").lower(),
                "nos": nos,
                "label": label,
                "leave": parsed.get("leave"),
                "y_relief": y_relief(label),
                "movant_name": movant.get("name"),
                "label_source": parsed.get("label_source"),
                "assigned_to_id": features["assigned_to_id"],
                "snapshot_date": parse_date(docket.get("snapshot_date")),
            }
            row.update(features)
            rows.append(row)
    frame = pd.DataFrame(rows)
    return frame, funnel


def assign_splits(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    if frame.empty:
        raise ValueError("no labeled MTD rows to split")
    work = frame.copy()
    work["motion_date"] = pd.to_datetime(work["motion_date"]).dt.date
    work["order_date"] = pd.to_datetime(work["order_date"]).dt.date
    work["split"] = "drop"
    earliest = work.groupby("docket_id")["motion_date"].transform("min")
    train_mask = (earliest >= TRAIN_START) & (earliest <= TRAIN_END)
    test_mask = (earliest >= TEST_START) & (earliest <= TEST_END)
    quar_mask = (earliest >= QUARANTINE_START) & (earliest <= QUARANTINE_END)
    work.loc[train_mask, "split"] = "train"
    work.loc[test_mask, "split"] = "test"
    work.loc[quar_mask, "split"] = "quarantine"
    # Motions whose docket was assigned train because of an earlier motion, but
    # whose own date sits in the test window, are dropped from the test score.
    later_test = (work["split"].eq("train")) & (work["motion_date"] >= TEST_START) & (work["motion_date"] <= TEST_END)
    dropped_later = int(later_test.sum())
    train = work.loc[work["split"].eq("train")].copy()
    test = work.loc[work["split"].eq("test")].copy()
    if train.empty or test.empty:
        raise ValueError("training and test windows each need at least one scored row")
    if train["docket_id"].isin(set(test["docket_id"])).any():
        raise AssertionError("a docket id appeared in both splits")
    if train["motion_entry_id"].duplicated().any() or test["motion_entry_id"].duplicated().any():
        raise AssertionError("duplicate motion ids inside a split")
    durations = (pd.to_datetime(train["order_date"]) - pd.to_datetime(train["motion_date"])).dt.days
    info = {
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "quarantine_rows": int(work["split"].eq("quarantine").sum()),
        "dropped_later_motion_on_train_docket": dropped_later,
        "train_duration_p95_days": float(durations.quantile(0.95)) if len(durations) else None,
        "train_start": TRAIN_START.isoformat(),
        "train_end": TRAIN_END.isoformat(),
        "test_start": TEST_START.isoformat(),
        "test_end": TEST_END.isoformat(),
    }
    scored = pd.concat([train, test], ignore_index=True)
    return scored, info


def feature_frame(df: pd.DataFrame, include_text: bool = False) -> pd.DataFrame:
    columns = list(FEATURE_COLUMNS)
    if include_text:
        columns = columns + [name for name in TEXT_FEATURE_FIELDS if name in df.columns]
    missing = [name for name in FEATURE_COLUMNS if name not in df.columns]
    if missing:
        raise AssertionError(f"feature columns missing: {missing}")
    leaked = [name for name in FEATURE_COLUMNS if name in FORBIDDEN_FROM_FEATURES]
    if leaked:
        raise AssertionError(f"forbidden columns selected as features: {leaked}")
    return df.loc[:, [name for name in columns if name in df.columns]].copy()


FORBIDDEN_FROM_FEATURES = {
    "order_entry_id",
    "order_description",
    "order_plain_text",
    "label",
    "y_relief",
    "leave",
    "dateTerminated",
}
