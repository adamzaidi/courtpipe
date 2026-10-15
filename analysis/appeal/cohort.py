"""Appeal-reversal cohort from a local JSONL extract or a bulk-like table."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from analysis.district_circuit import APPELLATE_COURTS, EXCLUDED_DISTRICT_PARENT
from analysis.appeal.features import (
    FEATURE_COLUMNS,
    assert_no_leakage,
    build_feature_row,
    parse_date,
    resolve_clock,
)
from analysis.appeal.labeler import EXCLUDED, label_cluster

HEADLINE_FINES = {"affirmed", "reversed", "vacated", "remanded", "mixed"}


def load_extract(path: Path) -> list[dict[str, Any]]:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    payload = json.loads(text)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and "clusters" in payload:
        return list(payload["clusters"])
    raise ValueError(f"unrecognized appeal extract in {path}")


def _from_district(row: dict[str, Any]) -> bool:
    appeal_from = str(row.get("appeal_from_id") or row.get("district_court") or "").lower()
    juris = str(row.get("appeal_from_jurisdiction") or "FD").upper()
    if appeal_from == EXCLUDED_DISTRICT_PARENT:
        return False
    if not appeal_from:
        return False
    return juris in {"FD", "F"} or bool(appeal_from)


def build_rows(clusters: Iterable[dict[str, Any]]) -> tuple[pd.DataFrame, dict[str, int]]:
    funnel = {
        "clusters_in_thirteen": 0,
        "from_district": 0,
        "has_clock": 0,
        "headline": 0,
        "needs_text": 0,
        "no_clock": 0,
        "not_from_district": 0,
        "later_cluster": 0,
        "cluster_conflict": 0,
        "timeline_inconsistent": 0,
        "dismissed": 0,
        "coa": 0,
        "unmapped": 0,
        "affirmed_with_remand": 0,
    }
    labeled: list[dict[str, Any]] = []
    by_docket: dict[Any, list[dict[str, Any]]] = {}
    for raw in clusters:
        court = str(raw.get("court_id") or "").lower()
        if court not in APPELLATE_COURTS:
            continue
        funnel["clusters_in_thirteen"] += 1
        if not _from_district(raw):
            funnel["not_from_district"] += 1
            continue
        funnel["from_district"] += 1
        clock, kind = resolve_clock(raw)
        decision = parse_date(raw.get("date_filed") or raw.get("decision_date"))
        if clock is None or decision is None or not (clock < decision):
            funnel["no_clock"] += 1
            continue
        funnel["has_clock"] += 1
        parsed = label_cluster(raw)
        fine = parsed["fine"]
        if fine in funnel:
            funnel[fine] = funnel.get(fine, 0) + 1
        features = build_feature_row(raw, include_district_text=True)
        if features.get("timeline_inconsistent"):
            funnel["timeline_inconsistent"] += 1
            continue
        assert_no_leakage(features)
        row = {
            "cluster_id": raw.get("cluster_id") or raw.get("id"),
            "docket_id": raw.get("docket_id"),
            "parent_docket_id": raw.get("parent_docket_id"),
            "court_id": court,
            "case_name": raw.get("case_name") or "",
            "decision_date": decision,
            "clock_date": clock,
            "fine": fine,
            "y_disturb": parsed["y_disturb"],
            "excluded": parsed["excluded"],
            "label_source": parsed.get("label_source"),
            "precedential_status": raw.get("precedential_status"),
        }
        row.update(features)
        labeled.append(row)
        by_docket.setdefault(row["docket_id"], []).append(row)

    kept: list[dict[str, Any]] = []
    for docket_id, items in by_docket.items():
        items.sort(key=lambda r: r["decision_date"] or date.max)
        first_ok = None
        for item in items:
            if item["fine"] != "needs_text":
                first_ok = item
                break
        if first_ok is None:
            continue
        same_day = [i for i in items if i["decision_date"] == first_ok["decision_date"] and i["fine"] != "needs_text"]
        fines = {i["fine"] for i in same_day}
        if len(fines) > 1:
            funnel["cluster_conflict"] += 1
            continue
        for item in items:
            if item["cluster_id"] != first_ok["cluster_id"]:
                funnel["later_cluster"] += 1
        kept.append(first_ok)

    scored = []
    for row in kept:
        if row["fine"] in HEADLINE_FINES and row["y_disturb"] is not None:
            funnel["headline"] += 1
            scored.append(row)
        elif row["fine"] == "affirmed_with_remand":
            funnel["affirmed_with_remand"] += 1
        elif row["fine"] == "needs_text":
            funnel["needs_text"] += 1
    return pd.DataFrame(scored), funnel


def assign_splits(frame: pd.DataFrame, snapshot_year: int | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    if frame.empty:
        raise ValueError("no headline appeal rows to split")
    work = frame.copy()
    work["decision_date"] = pd.to_datetime(work["decision_date"]).dt.date
    work["year"] = pd.to_datetime(work["decision_date"]).dt.year
    if snapshot_year is None:
        snapshot_year = int(work["year"].max())
    y = snapshot_year
    train_end = y - 4  # years before Y-3
    test_years = {y - 3, y - 2, y - 1}
    work["split"] = "drop"
    work.loc[work["year"] <= train_end, "split"] = "train"
    work.loc[work["year"].isin(test_years), "split"] = "test"
    work.loc[work["year"] == y, "split"] = "quarantine"

    # One docket, one side: earliest decision date.
    earliest = work.groupby("docket_id")["decision_date"].transform("min")
    earliest_year = pd.to_datetime(earliest).dt.year
    work.loc[earliest_year <= train_end, "split"] = "train"
    work.loc[earliest_year.isin(list(test_years)), "split"] = "test"
    work.loc[earliest_year == y, "split"] = "quarantine"

    # Parent docket families: if mixed, all to train and drop from test.
    if "parent_docket_id" in work.columns:
        family = work["parent_docket_id"].fillna(work["docket_id"])
        work["_family"] = family
        mixed = work.groupby("_family")["split"].transform(lambda s: set(s) >= {"train", "test"})
        moved = int((mixed & work["split"].eq("test")).sum())
        work.loc[mixed, "split"] = "train"
    else:
        moved = 0

    # Drop test captions that also appear in training.
    train = work.loc[work["split"].eq("train")].copy()
    test = work.loc[work["split"].eq("test")].copy()
    train_names = set(train["case_name"].map(lambda v: re_norm(v)))
    leak = test["case_name"].map(lambda v: re_norm(v) in train_names)
    dropped = test.loc[leak].copy()
    test = test.loc[~leak].copy()
    if train.empty or test.empty:
        raise ValueError("training and test windows each need at least one scored row")
    if set(train["docket_id"]).intersection(set(test["docket_id"])):
        raise AssertionError("a docket id appeared in both splits")
    info = {
        "snapshot_year": y,
        "train_years": f"through {train_end}",
        "test_years": sorted(test_years),
        "quarantine_year": y,
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "quarantine_rows": int(work["split"].eq("quarantine").sum()),
        "family_moved_to_train": moved,
        "repeat_caption_dropped": int(leak.sum()),
        "test_positives": int(test["y_disturb"].sum()),
    }
    scored = pd.concat([train, test], ignore_index=True)
    return scored, info, dropped


def re_norm(value: object) -> str:
    text = "" if value is None else str(value).upper()
    return " ".join(__import__("re").sub(r"[^A-Z0-9]+", " ", text).split())


def feature_matrix(df: pd.DataFrame) -> pd.DataFrame:
    missing = [name for name in FEATURE_COLUMNS if name not in df.columns]
    if missing:
        raise AssertionError(f"feature columns missing: {missing}")
    leaked = [name for name in df.columns if name in {"disposition", "decretal_excerpt", "label_text", "plain_text"}]
    if leaked:
        raise AssertionError(f"forbidden columns in frame: {leaked}")
    return df.loc[:, FEATURE_COLUMNS].copy()
