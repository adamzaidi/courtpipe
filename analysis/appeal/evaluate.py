"""Train and score the appeal-reversal model on a local extract."""

from __future__ import annotations

import json
import platform
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from analysis.appeal.cohort import assign_splits, build_rows, feature_matrix, load_extract
from analysis.appeal.features import CATEGORICAL_FEATURES, NUMERIC_FEATURES
from analysis.appeal.labeler import y_disturb_sensitivity  # used in notes / sensitivities mapping
from analysis.cl_auth import courtlistener_token
from analysis.pred_metrics import (
    brier,
    calibration_table,
    clustered_bootstrap,
    expected_calibration_error,
    jsonable,
    safe_auc,
    sha256_file,
)

BOOTSTRAP_SEED = 20261010
AUDIT_SEED = 20261010
RATE_BASELINES = ("circuit_rate", "case_type_rate", "circuit_case_type_rate", "judge_rate")
FINE_IN_BINARY = ["affirmed", "reversed", "vacated", "remanded", "mixed"]


def _git_commit() -> str:
    try:
        return (
            subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL)
            .decode()
            .strip()
        )
    except Exception:
        return "unknown"


def baseline_scores(train: pd.DataFrame, test: pd.DataFrame) -> dict[str, np.ndarray]:
    target = "y_disturb"
    prevalence = float(train[target].mean()) if len(train) else 0.0
    circuit = train.groupby("circuit")[target].agg(rate="mean", n="size")
    case_type = train.groupby("case_type")[target].agg(rate="mean", n="size")
    both = train.groupby(["circuit", "case_type"])[target].agg(rate="mean", n="size").reset_index()
    judge = train.groupby("district_judge_id")[target].agg(rate="mean", n="size")

    def cell(series, table, floor, fallback):
        rate = series.map(table["rate"]).to_numpy(dtype=float)
        count = series.map(table["n"]).fillna(0).to_numpy()
        out = np.where(count >= floor, rate, np.nan)
        return np.where(np.isfinite(out), out, fallback).astype(float)

    constant = np.full(len(test), prevalence)
    circuit_rate = cell(test["circuit"], circuit, 50, constant)
    case_type_rate = cell(test["case_type"], case_type, 50, constant)
    merged = test[["circuit", "case_type"]].merge(both, on=["circuit", "case_type"], how="left")
    combo = np.where(merged["n"].fillna(0) >= 50, merged["rate"].to_numpy(dtype=float), np.nan)
    combo = np.where(np.isfinite(combo), combo, case_type_rate)
    combo = np.where(np.isfinite(combo), combo, circuit_rate)
    combo = np.where(np.isfinite(combo), combo, constant)
    judge_ids = test["district_judge_id"].fillna("unknown")
    judge_rate = cell(judge_ids, judge, 40, circuit_rate)
    judge_rate = np.where(judge_ids.eq("unknown").to_numpy(), circuit_rate, judge_rate)
    return {
        "constant": constant,
        "majority_class": np.full(len(test), 1.0 if prevalence >= 0.5 else 0.0),
        "circuit_rate": circuit_rate,
        "case_type_rate": case_type_rate,
        "circuit_case_type_rate": combo.astype(float),
        "judge_rate": judge_rate,
    }


def _best_name(y, scores: dict[str, np.ndarray], metric: str) -> str:
    names = list(RATE_BASELINES)

    def value(name: str) -> float:
        if metric == "auc":
            score = safe_auc(y, scores[name])
            return -np.inf if score is None else score
        item = brier(y, scores[name])
        return np.inf if item is None else item

    if metric == "auc":
        return max(names, key=value)
    return min(names, key=value)


def _encoder() -> ColumnTransformer:
    return ColumnTransformer(
        [
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=True), CATEGORICAL_FEATURES),
            ("num", "passthrough", NUMERIC_FEATURES),
        ],
        remainder="drop",
    )


def fit_binary(train: pd.DataFrame, test: pd.DataFrame, use_text: bool = True):
    X_train = feature_matrix(train)
    X_test = feature_matrix(test)
    y = train["y_disturb"].to_numpy()
    if use_text and "district_opinion_text" in train.columns:
        vectorizer = CountVectorizer(max_features=200, min_df=1, ngram_range=(1, 2))
        try:
            train_bow = vectorizer.fit_transform(train["district_opinion_text"].fillna("").astype(str))
            test_bow = vectorizer.transform(test["district_opinion_text"].fillna("").astype(str))
            from scipy import sparse as sp

            pre = _encoder()
            Xtr = sp.hstack([pre.fit_transform(X_train), train_bow]).tocsr()
            Xte = sp.hstack([pre.transform(X_test), test_bow]).tocsr()
            clf = LogisticRegression(solver="liblinear", max_iter=1000, random_state=BOOTSTRAP_SEED)
            clf.fit(Xtr, y)
            return clf, clf.predict_proba(Xte)[:, 1]
        except ValueError:
            pass
    model = Pipeline(
        [
            ("pre", _encoder()),
            ("clf", LogisticRegression(solver="liblinear", max_iter=1000, random_state=BOOTSTRAP_SEED)),
        ]
    )
    model.fit(X_train, y)
    return model, model.predict_proba(X_test)[:, 1]


def draw_audit_sample(cohort: pd.DataFrame, seed: int = AUDIT_SEED) -> tuple[pd.DataFrame, dict]:
    rng = np.random.default_rng(seed)
    quotas = {
        "affirmed": 30,
        "reversed": 25,
        "vacated": 15,
        "remanded": 10,
        "mixed": 20,
        "affirmed_with_remand": 10,
        "dismissed": 10,
    }
    parts = []
    shortfalls = {}
    for label, quota in quotas.items():
        pool = cohort.loc[cohort["fine"].eq(label)] if "fine" in cohort.columns else cohort.head(0)
        take = min(quota, len(pool))
        shortfalls[label] = quota - take
        if take == 0:
            continue
        idx = rng.choice(pool.index.to_numpy(), size=take, replace=False)
        parts.append(cohort.loc[idx])
    sample = pd.concat(parts, ignore_index=True) if parts else cohort.head(0)
    sample = sample.copy()
    sample["gold_fine"] = ""
    keep = [c for c in ("docket_id", "cluster_id", "court_id", "fine", "y_disturb", "gold_fine") if c in sample.columns]
    return sample.loc[:, keep], {"rows": int(len(sample)), "seed": seed, "shortfalls": shortfalls, "status": "pending"}


def _binary_block(train, test, draws: int, use_text: bool = True) -> dict:
    y = test["y_disturb"].to_numpy()
    scores = baseline_scores(train, test)
    _, proba = fit_binary(train, test, use_text=use_text)
    model_auc = safe_auc(y, proba)
    model_brier = brier(y, proba)
    best_auc = _best_name(y, scores, "auc")
    best_brier = _best_name(y, scores, "brier")
    baseline_metrics = {name: {"roc_auc": safe_auc(y, values), "brier": brier(y, values)} for name, values in scores.items()}
    groups = test["docket_id"].to_numpy()
    boot = clustered_bootstrap(y, proba, scores[best_auc], groups, draws=draws, seed=BOOTSTRAP_SEED)
    brier_boot = clustered_bootstrap(y, proba, scores[best_brier], groups, draws=draws, seed=BOOTSTRAP_SEED)
    auc_ci = boot["auc_difference_ci95"]
    brier_ci = brier_boot["brier_improvement_ci95"]
    model_auc_ci = boot["model_auc_ci95"]
    auc_better = (
        model_auc is not None
        and baseline_metrics[best_auc]["roc_auc"] is not None
        and model_auc > baseline_metrics[best_auc]["roc_auc"]
        and auc_ci is not None
        and auc_ci[0] > 0
    )
    brier_better = (
        model_brier is not None
        and baseline_metrics[best_brier]["brier"] is not None
        and model_brier < baseline_metrics[best_brier]["brier"]
        and brier_ci is not None
        and brier_ci[0] > 0
    )
    majority_acc = float((y == (1 if train["y_disturb"].mean() >= 0.5 else 0)).mean())
    return {
        "model_roc_auc": model_auc,
        "model_brier": model_brier,
        "majority_class_accuracy": majority_acc,
        "baselines": baseline_metrics,
        "best_baseline_auc": best_auc,
        "best_baseline_brier": best_brier,
        "bootstrap_docket_clustered": boot,
        "bootstrap_vs_brier_baseline": {"brier_improvement_ci95": brier_ci, "draws_used": brier_boot["draws_used"]},
        "auc_beats_baseline": bool(auc_better),
        "brier_beats_baseline": bool(brier_better),
        "model_auc_ci_above_half": bool(model_auc_ci is not None and model_auc_ci[0] > 0.5),
        "proba": proba,
        "scores": scores,
    }


def _hand_check(cohort: pd.DataFrame, n: int = 12, seed: int = AUDIT_SEED) -> dict:
    if cohort.empty:
        return {"n": 0}
    rng = np.random.default_rng(seed)
    take = min(n, len(cohort))
    sample = cohort.loc[rng.choice(cohort.index.to_numpy(), size=take, replace=False)]
    return {
        "n": take,
        "class_counts": {str(k): int(v) for k, v in sample["fine"].value_counts().items()},
        "note": "Programmatic sample of automatic fine labels. Two-reader gold audit is pending.",
    }


def render_results(report: dict) -> str:
    gate = report["modeling_gate"]
    metrics = report["primary"]
    n_train = report.get("split", {}).get("train_rows") or 0
    fixture_banner = []
    if n_train < 50:
        fixture_banner = [
            "**Synthetic/small extract.** Training n is below the spec's 50-row circuit backoff floor, so rate baselines collapse toward a constant. Bootstrap intervals on ~12 test rows are wide. Do not quote these numbers as an affirmance or reversal rate. Live bulk-snapshot metrics are pending.",
            "",
        ]
    lines = [
        "# Appeal-reversal results",
        "",
        "These figures are from `courtpipe evaluate-appeal`. They are not Table B-5 and not opinion-pipeline fixture scores.",
        "",
        *fixture_banner,
        f"Audit gate: **{report['audit_gate']}**.",
        f"Modeling gate: **{'pass' if gate['passed'] else 'fail'}**.",
        "",
        f"- Train rows: {report['split'].get('train_rows')}",
        f"- Test rows: {report['split'].get('test_rows')}",
        f"- Train disturb rate: {report.get('train_disturb_rate')}",
        f"- Test disturb rate: {report.get('test_disturb_rate')}",
        "",
        "## Primary scores (`y_disturb`)",
        "",
        f"- Model ROC-AUC: {metrics.get('model_roc_auc')}",
        f"- Best rate baseline for AUC ({metrics.get('best_baseline_auc')}): {metrics.get('baselines', {}).get(metrics.get('best_baseline_auc'), {}).get('roc_auc')}",
        f"- AUC difference interval: {metrics.get('bootstrap_docket_clustered', {}).get('auc_difference_ci95')}",
        f"- Model Brier: {metrics.get('model_brier')}",
        f"- Best rate baseline for Brier ({metrics.get('best_baseline_brier')}): {metrics.get('baselines', {}).get(metrics.get('best_baseline_brier'), {}).get('brier')}",
        f"- Brier improvement interval: {metrics.get('bootstrap_vs_brier_baseline', {}).get('brier_improvement_ci95')}",
        f"- Majority-class accuracy (descriptive): {metrics.get('majority_class_accuracy')}",
        f"- Expected calibration error: {report.get('calibration', {}).get('ece')}",
        "",
        "## Bars",
        "",
    ]
    for name, passed in gate["bars"].items():
        lines.append(f"- {name}: {'pass' if passed else 'fail'}")
    if gate.get("reasons"):
        lines.extend(["", "Reasons:"])
        for reason in gate["reasons"]:
            lines.append(f"- {reason}")
    lines.extend(["", "## Known limitations", ""])
    for note in report.get("notes") or []:
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def run_evaluation(
    extract_path: Path,
    report_path: Path,
    audit_path: Path | None = None,
    bootstrap_draws: int = 1000,
    snapshot_year: int | None = None,
    results_md: Path | None = None,
    log=None,
) -> dict:
    log = log or (lambda message: None)
    extract_path = Path(extract_path)
    token = courtlistener_token()
    clusters = load_extract(extract_path)
    cohort, funnel = build_rows(clusters)
    scored, split_info, dropped = assign_splits(cohort, snapshot_year=snapshot_year)
    train = scored.loc[scored["split"].eq("train")].copy()
    test = scored.loc[scored["split"].eq("test")].copy()
    log(f"train {len(train)} test {len(test)}")
    audit, audit_meta = draw_audit_sample(cohort)
    if audit_path is not None:
        Path(audit_path).parent.mkdir(parents=True, exist_ok=True)
        audit.to_csv(audit_path, index=False)
        audit_meta["path"] = str(audit_path)

    primary = _binary_block(train, test, bootstrap_draws, use_text=True)
    proba = primary.pop("proba")
    primary.pop("scores", None)
    metadata_only = _binary_block(train, test, bootstrap_draws, use_text=False)
    metadata_only.pop("proba", None)
    metadata_only.pop("scores", None)

    three_way = {"model_macro_f1": None, "baseline_macro_f1": None}
    try:
        from sklearn.dummy import DummyClassifier

        dummy = DummyClassifier(strategy="most_frequent")
        dummy.fit(feature_matrix(train), train["fine"])
        base = dummy.predict(feature_matrix(test))
        clf = Pipeline(
            [
                ("pre", _encoder()),
                ("clf", LogisticRegression(max_iter=2000, solver="lbfgs", random_state=BOOTSTRAP_SEED)),
            ]
        )
        clf.fit(feature_matrix(train), train["fine"])
        pred = clf.predict(feature_matrix(test))
        three_way["model_macro_f1"] = float(
            f1_score(test["fine"], pred, average="macro", labels=FINE_IN_BINARY, zero_division=0)
        )
        three_way["baseline_macro_f1"] = float(
            f1_score(test["fine"], base, average="macro", labels=FINE_IN_BINARY, zero_division=0)
        )
    except Exception as exc:
        three_way["error"] = str(exc)

    sensitivities = {}
    for mode in ("A", "B"):
        # Re-label affirmed_with_remand is not in the headline frame; report the mapping only.
        sensitivities[mode] = {
            "note": f"Sensitivity {mode} for affirmed_with_remand is pre-registered and is not the headline.",
            "mapping": "y_disturb=0" if mode == "A" else "y_disturb=1",
        }

    cal = calibration_table(test["y_disturb"].to_numpy(), proba, bins=10, min_n_report=30)
    ece = expected_calibration_error(test["y_disturb"].to_numpy(), proba)
    reasons = []
    if not primary["auc_beats_baseline"]:
        reasons.append("ROC-AUC does not clear the best circuit/case-type/judge rate baseline with a difference interval above zero.")
    if not primary["brier_beats_baseline"]:
        reasons.append("Brier score does not improve on the best rate baseline with an interval above zero.")
    if not primary["model_auc_ci_above_half"]:
        reasons.append("The model AUC interval does not sit above 0.5.")
    modeling_passed = bool(
        primary["auc_beats_baseline"] and primary["brier_beats_baseline"] and primary["model_auc_ci_above_half"]
    )
    report = {
        "task": "appeal_y_disturb",
        "audit_gate": "pending",
        "project_done": False,
        "modeling_gate": {
            "passed": modeling_passed,
            "bars": {
                "roc_auc_beats_best_baseline": primary["auc_beats_baseline"],
                "brier_beats_best_baseline": primary["brier_beats_baseline"],
                "model_auc_ci_above_0.5": primary["model_auc_ci_above_half"],
            },
            "reasons": reasons,
        },
        "file": {"path": str(extract_path), "sha256": sha256_file(extract_path), "bytes": extract_path.stat().st_size},
        "run": {"git_commit": _git_commit(), "python": platform.python_version(), "seed": BOOTSTRAP_SEED},
        "funnel": funnel,
        "split": split_info,
        "label_counts": {str(k): int(v) for k, v in scored["fine"].value_counts().items()},
        "train_disturb_rate": float(train["y_disturb"].mean()),
        "test_disturb_rate": float(test["y_disturb"].mean()),
        "audit": audit_meta,
        "hand_check_sample": _hand_check(cohort),
        "primary": primary,
        "metadata_only_model": metadata_only,
        "fine_macro_f1": three_way,
        "sensitivities_affirmed_with_remand": sensitivities,
        "repeat_caption_dropped": int(split_info.get("repeat_caption_dropped") or 0),
        "calibration": {"bins": cal, "ece": ece, "min_n_report": 30},
        "judge_outputs": "aggregate only; no per-judge rates",
        "notes": [
            "Headline event is y_disturb: reversed/vacated/remanded/mixed versus pure affirmance.",
            "affirmed_with_remand is excluded from the headline. Sensitivities A and B are printed and are not swapped in after seeing the test score.",
            "v1 features come from pre-decision fields. Appellate opinion text is the label store.",
            "A live bulk snapshot is required before treating fixture numbers as corpus results.",
            "Judge-level outputs are aggregate only.",
            "On extracts with fewer than 50 training rows, circuit and case-type baselines backoff to a constant; bootstrap intervals on a tiny test set are not a cohort result.",
        ],
    }
    blob = json.dumps(jsonable(report), indent=2) + "\n"
    if token and token in blob:
        raise AssertionError("token leaked into the appeal report")
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(blob, encoding="utf-8")
    if results_md:
        Path(results_md).write_text(render_results(report), encoding="utf-8")
    log(f"wrote {report_path}")
    return report
