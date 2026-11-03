"""Shared scoring helpers for the MTD and appeal-reversal tracks."""

from __future__ import annotations

import hashlib
import math
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

import numpy as np
from sklearn.metrics import brier_score_loss, roc_auc_score


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def jsonable(value):
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, (np.floating, float)):
        if not np.isfinite(value):
            return None
        return float(value)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if value is None or isinstance(value, str):
        return value
    return str(value)


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n <= 0:
        return None
    p = successes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denom
    margin = z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n) / denom
    return float(max(0.0, center - margin)), float(min(1.0, center + margin))


def safe_auc(y, scores) -> float | None:
    y = np.asarray(y)
    scores = np.asarray(scores, dtype=float)
    if len(y) == 0 or np.unique(y).size < 2:
        return None
    return float(roc_auc_score(y, scores))


def brier(y, scores) -> float | None:
    y = np.asarray(y)
    if len(y) == 0:
        return None
    return float(brier_score_loss(y, np.clip(np.asarray(scores, dtype=float), 0.0, 1.0)))


def multiclass_brier(y_idx: np.ndarray, proba: np.ndarray) -> float | None:
    if len(y_idx) == 0 or proba.size == 0:
        return None
    onehot = np.zeros_like(proba)
    rows = np.arange(len(y_idx))
    onehot[rows, y_idx] = 1.0
    return float(np.mean(np.sum((proba - onehot) ** 2, axis=1)))


def calibration_table(y, proba, bins: int = 10, min_n_report: int = 0) -> list[dict]:
    y = np.asarray(y)
    proba = np.asarray(proba, dtype=float)
    rows = []
    for index in range(bins):
        low = index / bins
        high = (index + 1) / bins
        if index == bins - 1:
            mask = (proba >= low) & (proba <= high)
        else:
            mask = (proba >= low) & (proba < high)
        count = int(mask.sum())
        mean_pred = float(proba[mask].mean()) if count else None
        observed = float(y[mask].mean()) if count else None
        reported = count >= min_n_report if min_n_report else count > 0
        rows.append(
            {
                "bin": index,
                "lo": low,
                "hi": high,
                "n": count,
                "mean_predicted": mean_pred if reported else None,
                "observed_rate": observed if reported else None,
                "status": "ok" if reported else ("empty" if count == 0 else "not reported"),
            }
        )
    return rows


def expected_calibration_error(y, proba, bins: int = 10) -> float | None:
    y = np.asarray(y)
    proba = np.asarray(proba, dtype=float)
    if len(y) == 0:
        return None
    table = calibration_table(y, proba, bins=bins)
    total = 0.0
    weight = 0
    for row in table:
        if row["n"] == 0 or row["mean_predicted"] is None or row["observed_rate"] is None:
            continue
        total += abs(row["mean_predicted"] - row["observed_rate"]) * row["n"]
        weight += row["n"]
    if weight == 0:
        return None
    return float(total / weight)


def _ci(values: list[float], min_n: int = 50) -> list[float] | None:
    array = np.asarray(values, dtype=float)
    array = array[np.isfinite(array)]
    if array.size < min_n:
        return None
    low, high = np.percentile(array, [2.5, 97.5])
    return [float(low), float(high)]


def clustered_bootstrap(
    y,
    model_p,
    baseline_p,
    groups: Iterable,
    draws: int = 1000,
    seed: int = 20261007,
    min_ci_n: int = 50,
) -> dict:
    """Resample groups (dockets or judges) with replacement."""
    y = np.asarray(y)
    model_p = np.asarray(model_p, dtype=float)
    baseline_p = np.asarray(baseline_p, dtype=float)
    groups = np.asarray(list(groups))
    unique, inverse = np.unique(groups, return_inverse=True)
    buckets = [np.where(inverse == i)[0] for i in range(len(unique))]
    rng = np.random.default_rng(seed)
    auc_model, auc_diff, brier_diff = [], [], []
    skipped = 0
    n_groups = len(buckets)
    for _ in range(draws):
        chosen = rng.integers(0, n_groups, n_groups)
        index = np.concatenate([buckets[i] for i in chosen])
        sample = y[index]
        if sample.min() == sample.max():
            skipped += 1
            continue
        try:
            model_auc = roc_auc_score(sample, model_p[index])
            base_auc = roc_auc_score(sample, baseline_p[index])
        except ValueError:
            skipped += 1
            continue
        model_brier = brier_score_loss(sample, np.clip(model_p[index], 0, 1))
        base_brier = brier_score_loss(sample, np.clip(baseline_p[index], 0, 1))
        auc_model.append(float(model_auc))
        auc_diff.append(float(model_auc - base_auc))
        brier_diff.append(float(base_brier - model_brier))
    return {
        "draws": draws,
        "draws_used": len(auc_model),
        "draws_skipped_one_class": skipped,
        "seed": seed,
        "n_groups": int(n_groups),
        "model_auc_ci95": _ci(auc_model, min_n=min_ci_n),
        "auc_difference_ci95": _ci(auc_diff, min_n=min_ci_n),
        "brier_improvement_ci95": _ci(brier_diff, min_n=min_ci_n),
    }


def redact_secrets(text: str, secrets: Iterable[str]) -> str:
    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[redacted]")
    return redacted
