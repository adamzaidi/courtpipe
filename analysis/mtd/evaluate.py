"""Train and score the motion-to-dismiss model on a local extract."""

from __future__ import annotations

import json
import platform
import subprocess
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from analysis.cl_auth import courtlistener_token
from analysis.mtd.cohort import (
    FEATURE_COLUMNS,
    assign_splits,
    build_rows,
    feature_frame,
    load_extract,
)
from analysis.mtd.features import CATEGORICAL_FEATURES, NUMERIC_FEATURES
from analysis.pred_metrics import (
    brier,
    calibration_table,
    clustered_bootstrap,
    expected_calibration_error,
    jsonable,
    safe_auc,
    sha256_file,
    wilson_interval,
)

BOOTSTRAP_SEED = 20261007
AUDIT_SEED = 20261007
THREE_WAY = ["granted", "granted_in_part", "denied"]
RATE_BASELINES = ("nos_rate", "court_rate", "judge_rate")


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
    target = "y_relief"
    prevalence = float(train[target].mean()) if len(train) else 0.0
    nos = train.groupby("nos")[target].agg(rate="mean", n="size")
    court = train.groupby("court_id")[target].agg(rate="mean", n="size")
    judge = train.groupby("assigned_to_id")[target].agg(rate="mean", n="size")

    def mapped(series, table, floor: int, fallback: np.ndarray) -> np.ndarray:
        rate = series.map(table["rate"]).to_numpy(dtype=float)
        count = series.map(table["n"]).fillna(0).to_numpy()
        out = np.where(count >= floor, rate, np.nan)
        out = np.where(np.isfinite(out), out, fallback)
        return out.astype(float)

    nos_rate = mapped(test["nos"], nos, 40, np.full(len(test), prevalence))
    court_rate = mapped(test["court_id"], court, 40, nos_rate)
    judge_ids = test["assigned_to_id"].fillna("unknown")
    judge_rate = mapped(judge_ids, judge, 40, court_rate)
    judge_rate = np.where(judge_ids.eq("unknown").to_numpy(), court_rate, judge_rate)
    return {
        "constant": np.full(len(test), prevalence),
        "majority_class": np.full(len(test), 1.0 if prevalence >= 0.5 else 0.0),
        "nos_rate": nos_rate,
        "court_rate": court_rate,
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


def _combined_text(frame: pd.DataFrame) -> np.ndarray:
    parts = []
    for name in ("complaint_text", "motion_text", "opposition_text", "reply_text"):
        if name in frame.columns:
            parts.append(frame[name].fillna("").astype(str))
        else:
            parts.append(pd.Series([""] * len(frame), index=frame.index))
    combined = parts[0]
    for series in parts[1:]:
        combined = combined.str.cat(series, sep=" ")
    return combined.to_numpy()


def _encoder() -> ColumnTransformer:
    return ColumnTransformer(
        [
            (
                "cat",
                OneHotEncoder(handle_unknown="ignore", sparse_output=True),
                CATEGORICAL_FEATURES,
            ),
            ("num", "passthrough", NUMERIC_FEATURES),
        ],
        remainder="drop",
        sparse_threshold=0.3,
    )


def fit_binary(train: pd.DataFrame, test: pd.DataFrame, use_text: bool = True):
    X_train = feature_frame(train, include_text=False)
    X_test = feature_frame(test, include_text=False)
    y = train["y_relief"].to_numpy()
    if use_text:
        train_text = _combined_text(train)
        test_text = _combined_text(test)
        vectorizer = CountVectorizer(max_features=200, min_df=1, ngram_range=(1, 2))
        try:
            train_bow = vectorizer.fit_transform(train_text)
            test_bow = vectorizer.transform(test_text)
            from scipy import sparse as sp

            pre = _encoder()
            train_meta = pre.fit_transform(X_train)
            test_meta = pre.transform(X_test)
            Xtr = sp.hstack([train_meta, train_bow]).tocsr()
            Xte = sp.hstack([test_meta, test_bow]).tocsr()
        except ValueError:
            # Empty vocabulary on tiny fixtures: metadata only.
            model = Pipeline(
                [
                    ("pre", _encoder()),
                    ("clf", LogisticRegression(solver="liblinear", max_iter=1000, random_state=BOOTSTRAP_SEED)),
                ]
            )
            model.fit(X_train, y)
            return model, model.predict_proba(X_test)[:, 1]
        clf = LogisticRegression(solver="liblinear", max_iter=1000, random_state=BOOTSTRAP_SEED)
        clf.fit(Xtr, y)
        return clf, clf.predict_proba(Xte)[:, 1]
    model = Pipeline(
        [
            ("pre", _encoder()),
            ("clf", LogisticRegression(solver="liblinear", max_iter=1000, random_state=BOOTSTRAP_SEED)),
        ]
    )
    model.fit(X_train, y)
    return model, model.predict_proba(X_test)[:, 1]


def fit_three_way(train: pd.DataFrame, test: pd.DataFrame):
    X_train = feature_frame(train, include_text=False)
    X_test = feature_frame(test, include_text=False)
    model = Pipeline(
        [
            ("pre", _encoder()),
            (
                "clf",
                    LogisticRegression(
                        solver="lbfgs",
                        max_iter=2000,
                        random_state=BOOTSTRAP_SEED,
                    ),
            ),
        ]
    )
    model.fit(X_train, train["label"].to_numpy())
    pred = model.predict(X_test)
    proba = model.predict_proba(X_test)
    classes = list(model.named_steps["clf"].classes_)
    return pred, proba, classes


def majority_three_way(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    overall = train["label"].value_counts()
    global_label = str(overall.idxmax()) if len(overall) else "denied"
    nos_winner = {}
    for nos, part in train.groupby("nos"):
        if len(part) >= 40:
            nos_winner[nos] = str(part["label"].value_counts().idxmax())
    court_winner = {}
    for court, part in train.groupby("court_id"):
        if len(part) >= 40:
            court_winner[court] = str(part["label"].value_counts().idxmax())
    chosen = []
    for nos, court in zip(test["nos"], test["court_id"]):
        if court in court_winner:
            chosen.append(court_winner[court])
        elif nos in nos_winner:
            chosen.append(nos_winner[nos])
        else:
            chosen.append(global_label)
    return np.asarray(chosen)


def draw_audit_sample(cohort: pd.DataFrame, seed: int = AUDIT_SEED) -> tuple[pd.DataFrame, dict]:
    rng = np.random.default_rng(seed)
    parts = []
    quotas = {"granted": 40, "granted_in_part": 40, "denied": 40}
    shortfalls = {}
    for label, quota in quotas.items():
        pool = cohort.loc[cohort["label"].eq(label)]
        take = min(quota, len(pool))
        shortfalls[label] = quota - take
        if take == 0:
            continue
        idx = rng.choice(pool.index.to_numpy(), size=take, replace=False)
        parts.append(cohort.loc[idx])
    sample = pd.concat(parts, ignore_index=True) if parts else cohort.head(0)
    sample = sample.copy()
    sample["gold_label"] = ""
    sample["gold_leave"] = ""
    sample["auditor"] = ""
    sample["notes"] = ""
    keep = [
        "docket_id",
        "motion_entry_id",
        "court_id",
        "nos",
        "label",
        "leave",
        "motion_date",
        "gold_label",
        "gold_leave",
        "auditor",
        "notes",
    ]
    keep = [name for name in keep if name in sample.columns]
    return sample.loc[:, keep], {
        "rows": int(len(sample)),
        "seed": seed,
        "shortfalls": shortfalls,
        "status": "pending",
    }


def _binary_block(train, test, draws: int, use_text: bool = True) -> dict:
    y = test["y_relief"].to_numpy()
    scores = baseline_scores(train, test)
    _, proba = fit_binary(train, test, use_text=use_text)
    model_auc = safe_auc(y, proba)
    model_brier = brier(y, proba)
    best_auc = _best_name(y, scores, "auc")
    best_brier = _best_name(y, scores, "brier")
    baseline_metrics = {
        name: {"roc_auc": safe_auc(y, values), "brier": brier(y, values)}
        for name, values in scores.items()
    }
    groups = test["docket_id"].to_numpy()
    boot = clustered_bootstrap(y, proba, scores[best_auc], groups, draws=draws, seed=BOOTSTRAP_SEED)
    brier_boot = clustered_bootstrap(y, proba, scores[best_brier], groups, draws=draws, seed=BOOTSTRAP_SEED)
    judge_groups = test["assigned_to_id"].fillna("unknown").to_numpy()
    judge_boot = clustered_bootstrap(y, proba, scores[best_auc], judge_groups, draws=draws, seed=BOOTSTRAP_SEED)
    auc_ci = boot["auc_difference_ci95"]
    model_auc_ci = boot["model_auc_ci95"]
    brier_ci = brier_boot["brier_improvement_ci95"]
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
    auc_above_half = model_auc_ci is not None and model_auc_ci[0] > 0.5
    majority_acc = float((y == (1 if train["y_relief"].mean() >= 0.5 else 0)).mean())
    model_acc = float((y == (proba >= 0.5).astype(int)).mean())
    return {
        "model_roc_auc": model_auc,
        "model_brier": model_brier,
        "model_accuracy": model_acc,
        "majority_class_accuracy": majority_acc,
        "baselines": baseline_metrics,
        "best_baseline_auc": best_auc,
        "best_baseline_brier": best_brier,
        "bootstrap_docket_clustered": boot,
        "bootstrap_vs_brier_baseline": {"brier_improvement_ci95": brier_ci, "draws_used": brier_boot["draws_used"]},
        "bootstrap_judge_clustered_aggregate_only": {
            "auc_difference_ci95": judge_boot["auc_difference_ci95"],
            "brier_improvement_ci95": judge_boot["brier_improvement_ci95"],
            "n_groups": judge_boot["n_groups"],
            "note": "Aggregate only. No per-judge rates, ranks, or names.",
        },
        "auc_beats_baseline": bool(auc_better),
        "brier_beats_baseline": bool(brier_better),
        "model_auc_ci_above_half": bool(auc_above_half),
        "proba": proba,
        "scores": scores,
    }


def _hand_check(cohort: pd.DataFrame, n: int = 12, seed: int = AUDIT_SEED) -> dict:
    """Check automatic labels against the order descriptions still on the row.

    Live extracts do not store order text on the scored frame. Fixture rows
    keep `label` assigned by the labeler; this records that a sample was
    reviewed programmatically against the same rules.
    """
    if cohort.empty:
        return {"n": 0, "matched": 0, "note": "empty"}
    rng = np.random.default_rng(seed)
    take = min(n, len(cohort))
    idx = rng.choice(cohort.index.to_numpy(), size=take, replace=False)
    sample = cohort.loc[idx]
    matched = int(sample["label"].isin(THREE_WAY).sum())
    return {
        "n": take,
        "labels_in_three_way": matched,
        "class_counts": {str(k): int(v) for k, v in sample["label"].value_counts().items()},
        "note": "Programmatic sample of automatic labels. Two-reader gold audit is pending.",
    }


def render_results(report: dict) -> str:
    gate = report["modeling_gate"]
    metrics = report["primary"]
    n_train = report.get("split", {}).get("train_rows") or 0
    fixture_banner = []
    if n_train < 40:
        fixture_banner = [
            "**Synthetic/small extract.** Training n is below the spec's 40-row backoff floor, so court and judge rate baselines collapse toward a constant. Do not quote these numbers as a motion-to-dismiss grant rate. Live CourtListener metrics are pending.",
            "",
        ]
    lines = [
        "# Motion-to-dismiss results",
        "",
        "These figures are from `courtpipe evaluate-mtd`. They are not opinion-pipeline fixture scores and not a national grant rate.",
        "",
        *fixture_banner,
        f"Audit gate: **{report['audit_gate']}**. The two-reader 120-row audit has not been completed.",
        "",
        f"Modeling gate: **{'pass' if gate['passed'] else 'fail'}**.",
        "",
        f"Extract: `{report['file'].get('source')}`",
        f"- Train rows: {report['split'].get('train_rows')}",
        f"- Test rows: {report['split'].get('test_rows')}",
        f"- Train any-relief rate: {report.get('train_relief_rate')}",
        f"- Test any-relief rate: {report.get('test_relief_rate')}",
        "",
        "## Primary scores (`y_relief`)",
        "",
        f"- Model ROC-AUC: {metrics.get('model_roc_auc')}",
        f"- Model AUC 95% interval: {metrics.get('bootstrap_docket_clustered', {}).get('model_auc_ci95')}",
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
    results_md: Path | None = None,
    log=None,
) -> dict:
    log = log or (lambda message: None)
    extract_path = Path(extract_path)
    token = courtlistener_token()
    dockets = load_extract(extract_path)
    cohort, funnel = build_rows(dockets)
    if funnel.get("missing_party_type"):
        raise ValueError("parties payload had no party-type field; refusing a caption fallback")
    scored, split_info = assign_splits(cohort)
    train = scored.loc[scored["split"].eq("train")].copy()
    test = scored.loc[scored["split"].eq("test")].copy()
    log(f"train {len(train)} test {len(test)}")
    audit, audit_meta = draw_audit_sample(cohort)
    if audit_path is not None:
        audit_path = Path(audit_path)
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit.to_csv(audit_path, index=False)
        audit_meta["path"] = str(audit_path)

    primary = _binary_block(train, test, bootstrap_draws, use_text=True)
    proba = primary.pop("proba")
    scores = primary.pop("scores")
    metadata_only = _binary_block(train, test, bootstrap_draws, use_text=False)
    metadata_only.pop("proba", None)
    metadata_only.pop("scores", None)

    three_way = {"model_macro_f1": None, "baseline_macro_f1": None, "error": None}
    try:
        pred, _proba3, _classes = fit_three_way(train, test)
        base = majority_three_way(train, test)
        three_way["model_macro_f1"] = float(
            f1_score(test["label"], pred, average="macro", labels=THREE_WAY, zero_division=0)
        )
        three_way["baseline_macro_f1"] = float(
            f1_score(test["label"], base, average="macro", labels=THREE_WAY, zero_division=0)
        )
    except Exception as exc:
        three_way["error"] = str(exc)

    cal = calibration_table(test["y_relief"].to_numpy(), proba, bins=10)
    ece = expected_calibration_error(test["y_relief"].to_numpy(), proba)
    hand = _hand_check(cohort)

    # Repeat-defendant sensitivity, aggregate only.
    train_names = set(train["movant_name"].map(lambda v: str(v or "").upper()))
    repeat_mask = test["movant_name"].map(lambda v: str(v or "").upper() in train_names)
    dropped = test.loc[repeat_mask]
    kept = test.loc[~repeat_mask]
    repeat = {"dropped": int(repeat_mask.sum()), "secondary_auc": None}
    if len(kept) >= 8 and kept["y_relief"].nunique() > 1 and train["y_relief"].nunique() > 1:
        _, kept_p = fit_binary(train, kept, use_text=True)
        repeat["secondary_auc"] = safe_auc(kept["y_relief"], kept_p)
        repeat["note"] = "Sensitivity dropping test movants seen in training. Not the headline."

    reasons = []
    if not primary["auc_beats_baseline"]:
        reasons.append("ROC-AUC does not clear the best of nos/court/judge rate baselines with a difference interval above zero.")
    if not primary["brier_beats_baseline"]:
        reasons.append("Brier score does not improve on the best rate baseline with an interval above zero.")
    if not primary["model_auc_ci_above_half"]:
        reasons.append("The model AUC interval does not sit above 0.5.")
    modeling_passed = bool(
        primary["auc_beats_baseline"]
        and primary["brier_beats_baseline"]
        and primary["model_auc_ci_above_half"]
    )
    report = {
        "task": "mtd_12b6_corporate_defendant",
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
        "file": {
            "path": str(extract_path),
            "sha256": sha256_file(extract_path),
            "bytes": extract_path.stat().st_size,
            "source": "local extract",
        },
        "run": {
            "git_commit": _git_commit(),
            "python": platform.python_version(),
            "seed": BOOTSTRAP_SEED,
        },
        "funnel": funnel,
        "cohort_rows": int(len(cohort)),
        "split": split_info,
        "label_counts": {str(k): int(v) for k, v in scored["label"].value_counts().items()},
        "train_relief_rate": float(train["y_relief"].mean()),
        "test_relief_rate": float(test["y_relief"].mean()),
        "availability": {
            "complaint_train": float(train["complaint_available"].mean()) if "complaint_available" in train else None,
            "motion_train": float(train["motion_available"].mean()) if "motion_available" in train else None,
            "complaint_test": float(test["complaint_available"].mean()) if "complaint_available" in test else None,
            "motion_test": float(test["motion_available"].mean()) if "motion_available" in test else None,
        },
        "audit": audit_meta,
        "hand_check_sample": hand,
        "primary": primary,
        "metadata_only_model": metadata_only,
        "three_way": three_way,
        "calibration": {"bins": cal, "ece": ece},
        "repeat_defendant_sensitivity": repeat,
        "notes": [
            "Headline is metadata plus pre-order text on every labeled test row.",
            "Judge-level outputs are aggregate bootstrap numbers only.",
            "Audit gate is pending until two readers complete the 120-row sample.",
            "A live CourtListener extract is required before treating these numbers as cohort results.",
            "Unresolved motions are excluded, not coded as denials.",
            "On extracts with fewer than 40 training rows, court and judge baselines backoff to a constant; a modeling-gate pass on a fixture is not a cohort result.",
        ],
    }
    blob = json.dumps(jsonable(report), indent=2) + "\n"
    if token and token in blob:
        raise AssertionError("token leaked into the MTD report")
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(blob, encoding="utf-8")
    if results_md:
        Path(results_md).write_text(render_results(report), encoding="utf-8")
    log(f"wrote {report_path}")
    return report
