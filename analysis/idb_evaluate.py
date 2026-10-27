"""Train and score the filing-time IDB settlement model.

The hand audit is not performed here. The command writes the sample and
sets audit_gate to pending, then still scores the locked split.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, f1_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from analysis.idb_cohort import (
    CATEGORICAL_FEATURES,
    FEATURE_COLUMNS,
    FORBIDDEN_FEATURE_FIELDS,
    SIX_WAY_LABELS,
    assign_splits,
    build_cohort,
    draw_audit_sample,
    feature_frame,
    load_candidate_rows,
    prepare_rows,
    resolve_table_path,
    sha256_file,
)

BOOTSTRAP_SEED = 20261007
AUDIT_SEED = 20261007
RATE_BASELINES = ("nos_rate", "court_rate", "nos_court_rate")


def _jsonable(value):
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (np.floating, float)):
        if not np.isfinite(value):
            return None
        return float(value)
    # bool is a subclass of int, so this check has to come first.
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if value is None or isinstance(value, str):
        return value
    return str(value)


def _safe_auc(y, scores) -> float | None:
    y = np.asarray(y)
    if len(y) == 0 or np.unique(y).size < 2:
        return None
    return float(roc_auc_score(y, scores))


def _brier(y, scores) -> float | None:
    y = np.asarray(y)
    if len(y) == 0:
        return None
    return float(brier_score_loss(y, np.clip(scores, 0.0, 1.0)))


def baseline_scores(train: pd.DataFrame, test: pd.DataFrame, target: str = "y_settle") -> dict[str, np.ndarray]:
    """Filing-time rates. Unseen cells fall back as the spec describes."""
    prevalence = float(train[target].mean())
    nos = train.groupby("NOS")[target].agg(rate="mean", n="size")
    court = train.groupby("DISTRICT")[target].agg(rate="mean", n="size")
    both = train.groupby(["NOS", "DISTRICT"])[target].agg(rate="mean", n="size").reset_index()
    nos_rate = test["NOS"].map(nos["rate"]).astype(float).fillna(prevalence).to_numpy()
    court_rate = test["DISTRICT"].map(court["rate"]).astype(float).fillna(prevalence).to_numpy()
    merged = test[["NOS", "DISTRICT"]].merge(both, on=["NOS", "DISTRICT"], how="left")
    cell_n = merged["n"].fillna(0).to_numpy()
    cell_rate = merged["rate"].to_numpy(dtype=float)
    nos_n = test["NOS"].map(nos["n"]).fillna(0).to_numpy()
    nos_only = test["NOS"].map(nos["rate"]).to_numpy(dtype=float)
    combined = np.where(cell_n >= 50, cell_rate, np.where(nos_n >= 50, nos_only, prevalence))
    combined = np.where(np.isfinite(combined), combined, prevalence)
    return {
        "constant": np.full(len(test), prevalence),
        "nos_rate": nos_rate,
        "court_rate": court_rate,
        "nos_court_rate": combined.astype(float),
    }


def _best_name(y, scores: dict[str, np.ndarray], metric: str) -> str:
    names = list(RATE_BASELINES)

    def value(name: str) -> float:
        if metric == "auc":
            score = _safe_auc(y, scores[name])
            return -np.inf if score is None else score
        brier = _brier(y, scores[name])
        return np.inf if brier is None else brier

    if metric == "auc":
        return max(names, key=value)
    return min(names, key=value)


def _encoder() -> ColumnTransformer:
    return ColumnTransformer(
        [
            (
                "cat",
                OneHotEncoder(handle_unknown="ignore", sparse_output=True),
                CATEGORICAL_FEATURES,
            )
        ],
        remainder="passthrough",
        sparse_threshold=0.3,
    )


def fit_binary(train: pd.DataFrame, test: pd.DataFrame, target: str = "y_settle"):
    features_train = feature_frame(train)
    features_test = feature_frame(test)
    if any(name in features_train.columns for name in FORBIDDEN_FEATURE_FIELDS):
        raise AssertionError("forbidden column in the feature matrix")
    if list(features_train.columns) != FEATURE_COLUMNS:
        raise AssertionError("feature matrix is not the approved column list")
    model = Pipeline(
        [
            ("pre", _encoder()),
            (
                "clf",
                LogisticRegression(solver="liblinear", max_iter=1000, random_state=BOOTSTRAP_SEED),
            ),
        ]
    )
    model.fit(features_train, train[target].to_numpy())
    proba = model.predict_proba(features_test)[:, 1]
    return model, proba


def _ci(values: list[float]) -> list[float] | None:
    array = np.asarray(values, dtype=float)
    array = array[np.isfinite(array)]
    if array.size < 100:
        return None
    low, high = np.percentile(array, [2.5, 97.5])
    return [float(low), float(high)]


def bootstrap_binary(y, model_p, baseline_p, draws: int = 1000, seed: int = BOOTSTRAP_SEED) -> dict:
    rng = np.random.default_rng(seed)
    y = np.asarray(y)
    model_p = np.asarray(model_p, dtype=float)
    baseline_p = np.asarray(baseline_p, dtype=float)
    auc_model, auc_diff, brier_diff = [], [], []
    skipped = 0
    for _ in range(draws):
        index = rng.integers(0, len(y), len(y))
        sample = y[index]
        if sample.min() == sample.max():
            skipped += 1
            continue
        model_auc = roc_auc_score(sample, model_p[index])
        base_auc = roc_auc_score(sample, baseline_p[index])
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
        "model_auc_ci95": _ci(auc_model),
        "auc_difference_ci95": _ci(auc_diff),
        "brier_improvement_ci95": _ci(brier_diff),
    }


def calibration_table(y, proba, bins: int = 10) -> list[dict]:
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
        if count == 0:
            rows.append(
                {
                    "bin": index,
                    "lo": low,
                    "hi": high,
                    "n": 0,
                    "mean_predicted": None,
                    "observed_rate": None,
                }
            )
            continue
        rows.append(
            {
                "bin": index,
                "lo": low,
                "hi": high,
                "n": count,
                "mean_predicted": float(proba[mask].mean()),
                "observed_rate": float(y[mask].mean()),
            }
        )
    return rows


def _winner(counts: pd.Series, overall: pd.Series) -> str:
    top = counts.max()
    tied = list(counts[counts == top].index)
    if len(tied) == 1:
        return str(tied[0])
    return str(max(tied, key=lambda label: (int(overall.get(label, 0)), label)))


def majority_baseline(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    overall = train["label6"].value_counts()
    global_label = _winner(overall, overall)
    nos_winner = {}
    for nos, part in train.groupby("NOS"):
        if len(part) >= 50:
            nos_winner[nos] = _winner(part["label6"].value_counts(), overall)
    cell_winner = {}
    for key, part in train.groupby(["NOS", "DISTRICT"]):
        if len(part) >= 50:
            cell_winner[key] = _winner(part["label6"].value_counts(), overall)
    chosen = []
    for nos, district in zip(test["NOS"], test["DISTRICT"]):
        if (nos, district) in cell_winner:
            chosen.append(cell_winner[(nos, district)])
        elif nos in nos_winner:
            chosen.append(nos_winner[nos])
        else:
            chosen.append(global_label)
    return np.asarray(chosen)


def multiclass_f1(train: pd.DataFrame, test: pd.DataFrame) -> dict:
    baseline = majority_baseline(train, test)
    base_f1 = float(
        f1_score(test["label6"], baseline, average="macro", labels=SIX_WAY_LABELS, zero_division=0)
    )
    model_f1 = None
    error = None
    try:
        pipe = Pipeline(
            [
                ("pre", _encoder()),
                (
                    "clf",
                    LogisticRegression(
                        solver="saga",
                        max_iter=400,
                        tol=1e-3,
                        random_state=BOOTSTRAP_SEED,
                    ),
                ),
            ]
        )
        pipe.fit(feature_frame(train), train["label6"].to_numpy())
        predicted = pipe.predict(feature_frame(test))
        model_f1 = float(
            f1_score(test["label6"], predicted, average="macro", labels=SIX_WAY_LABELS, zero_division=0)
        )
    except Exception as exc:  # secondary metric only; the binary gate still stands
        error = str(exc)
    return {
        "model_macro_f1": model_f1,
        "baseline_macro_f1": base_f1,
        "binding": False,
        "error": error,
    }


def _slice_report(test: pd.DataFrame, proba: np.ndarray, scores: dict[str, np.ndarray], draws: int) -> list[dict]:
    y = test["y_settle"].to_numpy()
    masks: list[tuple[str, np.ndarray]] = []
    for nos in ("160", "410", "850"):
        masks.append((f"NOS {nos}", test["NOS"].eq(nos).to_numpy()))
    for district in sorted(test["DISTRICT"].unique()):
        masks.append((f"DISTRICT {district}", test["DISTRICT"].eq(district).to_numpy()))
    for juris in sorted(test["JURIS"].unique()):
        masks.append((f"JURIS {juris}", test["JURIS"].eq(juris).to_numpy()))
    for rule in ("name_suffix", "corporate_via_residence"):
        masks.append((f"corporate {rule}", test["corporate_rule"].eq(rule).to_numpy()))
    masks.append(("ORIGIN original", test["ORIGIN"].eq("1").to_numpy()))
    masks.append(("ORIGIN removed", test["ORIGIN"].eq("2").to_numpy()))
    masks.append(("ORIGIN other allowed", ~test["ORIGIN"].isin(["1", "2"]).to_numpy()))

    rows = []
    for name, mask in masks:
        count = int(mask.sum())
        positives = int(y[mask].sum()) if count else 0
        row = {
            "slice": name,
            "n": count,
            "positives": positives,
            "model_auc": None,
            "best_baseline_auc": None,
            "best_baseline": None,
            "auc_difference_ci95": None,
            "comparison": "not reported",
        }
        if count < 50 or positives < 10 or count - positives < 1:
            rows.append(row)
            continue
        local_scores = {key: value[mask] for key, value in scores.items()}
        local_y = y[mask]
        best = _best_name(local_y, local_scores, "auc")
        row["model_auc"] = _safe_auc(local_y, proba[mask])
        row["best_baseline_auc"] = _safe_auc(local_y, local_scores[best])
        row["best_baseline"] = best
        row["comparison"] = "auc only"
        if count >= 200 and row["model_auc"] is not None:
            boot = bootstrap_binary(local_y, proba[mask], local_scores[best], draws=draws)
            row["auc_difference_ci95"] = boot["auc_difference_ci95"]
            row["comparison"] = "model versus baseline"
        rows.append(row)
    return rows


def _stability(train: pd.DataFrame, test: pd.DataFrame, full_diff: float | None) -> list[dict]:
    rows = []
    y = test["y_settle"].to_numpy()
    # MDL groups that span the cut can move a few later filings into train.
    # Drop only the designed training years, FY2010–FY2017.
    present = {int(year) for year in train["fiscal_year"].unique()}
    years = [year for year in range(2010, 2018) if year in present]
    for year in years:
        reduced = train.loc[train["fiscal_year"] != year]
        record = {"dropped_fiscal_year": year, "train_rows": int(len(reduced)), "auc_difference": None, "sign_change": None}
        if reduced["y_settle"].nunique() < 2 or len(reduced) < 20:
            record["sign_change"] = "not fit"
            rows.append(record)
            continue
        scores = baseline_scores(reduced, test)
        _, proba = fit_binary(reduced, test)
        model_auc = _safe_auc(y, proba)
        best = _best_name(y, scores, "auc")
        base_auc = _safe_auc(y, scores[best])
        if model_auc is None or base_auc is None or full_diff is None:
            record["sign_change"] = "not fit"
            rows.append(record)
            continue
        diff = model_auc - base_auc
        record["auc_difference"] = diff
        record["best_baseline"] = best
        record["sign_change"] = bool(np.sign(diff) != np.sign(full_diff) and diff != 0 and full_diff != 0)
        rows.append(record)
    return rows


def _binary_block(train, test, target: str, draws: int) -> dict:
    y = test[target].to_numpy()
    scores = baseline_scores(train, test, target=target)
    _, proba = fit_binary(train, test, target=target)
    model_auc = _safe_auc(y, proba)
    model_brier = _brier(y, proba)
    best_auc = _best_name(y, scores, "auc")
    best_brier = _best_name(y, scores, "brier")
    baseline_metrics = {}
    for name, values in scores.items():
        baseline_metrics[name] = {"roc_auc": _safe_auc(y, values), "brier": _brier(y, values)}
    boot = bootstrap_binary(y, proba, scores[best_auc], draws=draws)
    brier_boot = bootstrap_binary(y, proba, scores[best_brier], draws=draws)
    # The AUC interval is paired with the AUC winner. The Brier interval is paired
    # with the Brier winner. Reuse the Brier half of a second bootstrap.
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
    return {
        "model_roc_auc": model_auc,
        "model_brier": model_brier,
        "baselines": baseline_metrics,
        "best_baseline_auc": best_auc,
        "best_baseline_brier": best_brier,
        "bootstrap_vs_auc_baseline": boot,
        "bootstrap_vs_brier_baseline": {
            "brier_improvement_ci95": brier_ci,
            "draws_used": brier_boot["draws_used"],
        },
        "auc_beats_baseline": bool(auc_better),
        "brier_beats_baseline": bool(brier_better),
        "model_auc_ci_above_half": bool(auc_above_half),
        "proba": proba,
        "scores": scores,
    }


def _days(value) -> str:
    if isinstance(value, (int, float)) and np.isfinite(value):
        return f"{float(value):.1f}"
    return str(value)


def render_results(report: dict) -> str:
    gate = report["modeling_gate"]
    cohort = report["cohort"]
    metrics = report["primary"]
    lines = [
        "# IDB settlement results",
        "",
        "These figures are from one run of `courtpipe evaluate-settlement` on the public FJC civil file. They are not the 20-row opinion fixture in the README.",
        "",
        f"Audit gate: **{report['audit_gate']}**. The 150-row sample is `docs/idb/audit_sample.csv`. The rubric is `docs/idb/AUDIT_RUBRIC.md`. The project is not done while this gate is pending.",
        "",
        f"Modeling gate: **{'pass' if gate['passed'] else 'fail'}**.",
        "",
        "## Cohort",
        "",
        f"- Nature-of-suit 160/410/850 rows read: {cohort.get('nos_rows')}",
        f"- Cohort after filters and de-duplication: {cohort.get('cohort_rows')}",
        f"- Train rows scored: {report['split'].get('train_rows')}",
        f"- Test rows scored: {report['split'].get('test_rows')}",
        f"- Test rows dropped because the defendant name was in training: {report['split'].get('party_leakage_dropped')}",
        (
            "- Test rows dropped by the duration rule: "
            f"{report['split'].get('test_censored')}. These rows are already terminated. "
            "A case lasting as long as the training 95th percentile "
            f"({_days(report['split'].get('train_duration_p95_days'))} days) would not have been "
            "observable by the extract as-of date, so the filing is left out of the score."
        ),
        f"- Train settlement rate (code 13): {report.get('train_settlement_rate')}",
        f"- Test settlement rate (code 13): {report.get('test_settlement_rate')}",
        "",
        "## Primary scores",
        "",
        f"- Model ROC-AUC: {metrics.get('model_roc_auc')}",
        f"- Model AUC 95% interval: {metrics.get('bootstrap_vs_auc_baseline', {}).get('model_auc_ci95')}",
        f"- Best rate baseline for AUC ({metrics.get('best_baseline_auc')}): {metrics.get('baselines', {}).get(metrics.get('best_baseline_auc'), {}).get('roc_auc')}",
        f"- AUC difference interval (model minus that baseline): {metrics.get('bootstrap_vs_auc_baseline', {}).get('auc_difference_ci95')}",
        f"- Model Brier: {metrics.get('model_brier')}",
        f"- Best rate baseline for Brier ({metrics.get('best_baseline_brier')}): {metrics.get('baselines', {}).get(metrics.get('best_baseline_brier'), {}).get('brier')}",
        f"- Brier improvement interval (baseline minus model): {metrics.get('bootstrap_vs_brier_baseline', {}).get('brier_improvement_ci95')}",
        "",
        "A bar passes only when the model is better than that baseline and the interval's lower end is above zero. The model's own AUC interval must also sit above 0.5.",
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
    lines.extend(
        [
            "",
            "Macro-F1 on the six-way label is reported in the JSON and is not a binding bar.",
            "",
            f"File SHA-256: `{report['file']['sha256']}`",
            f"Bytes: {report['file']['bytes']}",
            f"As-of date used for censoring: {report['split'].get('as_of')}",
            "",
        ]
    )
    return "\n".join(lines)


def run_evaluation(
    idb_path: Path,
    report_path: Path,
    audit_path: Path | None = None,
    as_of: date | None = None,
    bootstrap_draws: int = 1000,
    log=None,
) -> dict:
    log = log or (lambda message: None)
    idb_path = Path(idb_path)
    source_stamp = None
    table_path, zip_as_of = resolve_table_path(idb_path)
    if as_of is None:
        as_of = zip_as_of or datetime.fromtimestamp(table_path.stat().st_mtime).date()
        source_stamp = "zip member" if zip_as_of else "table mtime"

    log("hashing the IDB file")
    file_info = {
        "path": str(idb_path),
        "table_path": str(table_path),
        "sha256": sha256_file(idb_path),
        "bytes": idb_path.stat().st_size,
        "as_of_source": source_stamp,
    }
    raw = load_candidate_rows(table_path, log=log)
    scanned = int(raw.attrs.get("rows_scanned", 0))
    outside = int(raw.attrs.get("nos_outside_window", 0))
    prepared, counts = prepare_rows(raw)
    del raw
    counts["rows_scanned"] = scanned
    counts["nos_outside_window_not_loaded"] = outside
    cohort, counts = build_cohort(prepared, counts)
    del prepared
    audit, audit_meta = draw_audit_sample(cohort, seed=AUDIT_SEED)
    if audit_path is not None:
        audit_path = Path(audit_path)
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit.to_csv(audit_path, index=False)
        audit_meta["path"] = str(audit_path)
    log(f"cohort {counts['cohort_rows']:,} rows; audit sample {audit_meta['rows']}")

    scored, split_info, dropped = assign_splits(cohort, as_of)
    train = scored.loc[scored["split"].eq("train")].copy()
    test = scored.loc[scored["split"].eq("test")].copy()
    log(f"train {len(train):,} test {len(test):,}; fitting logistic regression")

    primary = _binary_block(train, test, "y_settle", bootstrap_draws)
    proba = primary.pop("proba")
    scores = primary.pop("scores")
    full_auc = primary["model_roc_auc"]
    best_auc_value = primary["baselines"][primary["best_baseline_auc"]]["roc_auc"]
    full_diff = None if full_auc is None or best_auc_value is None else full_auc - best_auc_value

    log("fitting the sensitivity and six-way models")
    broad = _binary_block(train, test, "y_broad", bootstrap_draws)
    broad.pop("proba", None)
    broad.pop("scores", None)
    macro = multiclass_f1(train, test)

    log("slices and year-drop refits")
    slices = _slice_report(test, proba, scores, bootstrap_draws)
    stability = _stability(train, test, full_diff)
    sign_changes = [row["dropped_fiscal_year"] for row in stability if row.get("sign_change") is True]

    leaked_score = None
    if len(dropped) >= 50 and dropped["y_settle"].nunique() > 1:
        _, leaked_p = fit_binary(train, dropped)
        leaked_score = {
            "n": int(len(dropped)),
            "roc_auc": _safe_auc(dropped["y_settle"], leaked_p),
            "note": "Secondary. Not the success score.",
        }

    reasons = []
    if not primary["auc_beats_baseline"]:
        reasons.append("ROC-AUC does not clear the best filing-time rate baseline with a difference interval above zero.")
    if not primary["brier_beats_baseline"]:
        reasons.append("Brier score does not improve on the best filing-time rate baseline with an interval above zero.")
    if not primary["model_auc_ci_above_half"]:
        reasons.append("The model AUC interval does not sit above 0.5.")
    if sign_changes:
        reasons.append(
            "The AUC difference changes sign when a training fiscal year is dropped: "
            + ", ".join(str(year) for year in sign_changes)
            + ". That blocks a stability claim. It does not by itself fail the modeling gate."
        )

    modeling_passed = bool(
        primary["auc_beats_baseline"]
        and primary["brier_beats_baseline"]
        and primary["model_auc_ci_above_half"]
    )
    label_counts = {str(key): int(value) for key, value in scored["label"].value_counts().items()}
    report = {
        "task": "idb_disp_13_filing_time",
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
        "file": file_info,
        "cohort": counts,
        "split": split_info,
        "label_counts_scored": label_counts,
        "train_settlement_rate": float(train["y_settle"].mean()),
        "test_settlement_rate": float(test["y_settle"].mean()),
        "audit": audit_meta,
        "primary": primary,
        "calibration": calibration_table(test["y_settle"].to_numpy(), proba),
        "slices": slices,
        "stability_drop_one_fiscal_year": stability,
        "party_leakage_secondary": leaked_score,
        "y_broad_sensitivity": broad,
        "macro_f1": macro,
        "notes": [
            "file_year is (calendar year - 2015) / 5, one numeric trend, so later test years are not unseen dummy columns.",
            "demanded_bin is a coarse bin plus demanded_missing. The raw dollar figure is not a feature.",
            "Positive class is DISP 13 only. DISP 12 and DISP 5 stay in the cohort with y_settle 0.",
            "y_broad and macro-F1 are reported and are not the headline gate.",
            "The hand audit has not been done. Do not describe this model as a settled case until that gate passes and the modeling gate passes.",
        ],
    }
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(_jsonable(report), indent=2) + "\n")
    log(f"wrote {report_path}")
    return report
