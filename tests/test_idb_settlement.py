"""Offline tests for the IDB code-13 settlement track. No network and no API key."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from analysis.idb_cohort import (
    FEATURE_COLUMNS,
    FORBIDDEN_FEATURE_FIELDS,
    assign_splits,
    build_cohort,
    classify_defendant,
    feature_frame,
    map_label,
    prepare_rows,
)
from analysis.idb_download import FJC_CIVIL_ZIP_URL, download_idb
from analysis.idb_evaluate import run_evaluation
from courtpipe.cli import main


def _row(**overrides):
    base = {
        "CIRCUIT": "2",
        "DISTRICT": "08",
        "OFFICE": "1",
        "DOCKET": "100",
        "ORIGIN": "1",
        "FILEDATE": "01/15/2012",
        "JURIS": "3",
        "NOS": "850",
        "RESIDENC": "-8",
        "JURY": "P",
        "CLASSACT": "1",
        "DEMANDED": "100",
        "COUNTY": "36061",
        "ARBIT": "-8",
        "MDLDOCK": "-8",
        "PLT": "PLAINTIFF",
        "DEF": "ACME INC",
        "TERMDATE": "06/01/2013",
        "DISP": "13",
        "JUDGMENT": "-8",
        "PROSE": "0",
        "IFP": "-8",
        "STATUSCD": "L",
        "PROCPROG": "4",
    }
    base.update(overrides)
    return base


def _fixture_rows():
    rows = [
        _row(DOCKET="1", FILEDATE="01/15/2012", DEF="ACME INC", NOS="850", DISP="13", DISTRICT="08"),
        _row(DOCKET="2", FILEDATE="02/15/2012", DEF="BETA CORP", NOS="410", DISP="6", JUDGMENT="2", DISTRICT="08"),
        _row(DOCKET="3", FILEDATE="03/15/2013", DEF="GAMMA LLC", NOS="160", DISP="13", DISTRICT="07"),
        _row(DOCKET="4", FILEDATE="05/15/2014", DEF="DELTA CORPORATION", NOS="850", DISP="14", DISTRICT="08"),
        _row(
            DOCKET="5",
            FILEDATE="01/15/2015",
            DEF="",
            JURIS="4",
            RESIDENC="14",
            DISP="13",
            DISTRICT="06",
            NOS="850",
        ),
        _row(DOCKET="6", FILEDATE="02/15/2015", DEF="EPSILON LLP", NOS="410", DISP="5", DISTRICT="06"),
        _row(DOCKET="7", FILEDATE="01/15/2016", DEF="ZETA HOLDINGS", NOS="160", DISP="13", DISTRICT="08"),
        _row(
            DOCKET="8",
            FILEDATE="06/15/2016",
            DEF="ETA COMPANY",
            NOS="850",
            DISP="6",
            JUDGMENT="1",
            DISTRICT="07",
        ),
        _row(DOCKET="9", FILEDATE="01/15/2014", DEF="XI INC", DISP="13", MDLDOCK="1234", DISTRICT="08"),
        _row(DOCKET="10", FILEDATE="01/15/2012", DEF="UNITED STATES OF AMERICA", DISP="13"),
        _row(DOCKET="11", FILEDATE="01/15/2012", DEF="SECURITIES AND EXCHANGE COMMISSION", DISP="13"),
        _row(DOCKET="12", FILEDATE="01/15/2012", DEF="THETA INC", DISP="0"),
        _row(DOCKET="13", FILEDATE="01/15/2012", DEF="KAPPA INC", ORIGIN="4", DISP="13"),
        _row(DOCKET="14", FILEDATE="01/15/2012", DEF="LAMBDA INC", STATUSCD="S", DISP="13"),
        _row(DOCKET="1", FILEDATE="03/01/2014", DEF="ACME INC", DISP="12"),
        _row(DOCKET="15", FILEDATE="04/15/2013", DEF="RHO INC", DISP="13", JUDGMENT="1"),
        _row(DOCKET="101", FILEDATE="01/15/2019", DEF="IOTA INC", NOS="850", DISP="13", DISTRICT="08"),
        _row(DOCKET="102", FILEDATE="06/15/2019", DEF="KAPPA CORP", NOS="410", DISP="14", DISTRICT="07"),
        _row(DOCKET="103", FILEDATE="03/15/2018", DEF="ACME INC", NOS="850", DISP="13", DISTRICT="08"),
        _row(DOCKET="104", FILEDATE="01/15/2020", DEF="LAMBDA LLC", NOS="160", DISP="12", DISTRICT="06"),
        _row(DOCKET="105", FILEDATE="06/15/2020", DEF="MU LTD", NOS="850", DISP="13", DISTRICT="08"),
        _row(
            DOCKET="106",
            FILEDATE="01/15/2021",
            DEF="",
            JURIS="4",
            RESIDENC="25",
            DISP="6",
            JUDGMENT="2",
            DISTRICT="06",
            NOS="160",
        ),
        _row(DOCKET="107", FILEDATE="09/15/2019", DEF="NU PLC", NOS="410", DISP="13", DISTRICT="07"),
        _row(
            DOCKET="108",
            FILEDATE="01/20/2019",
            DEF="OMICRON CORP",
            DISP="14",
            MDLDOCK="1234",
            DISTRICT="07",
            NOS="850",
        ),
        _row(DOCKET="16", FILEDATE="01/15/1900", DEF="OLD CORP", DISP="13", NOS="190"),
    ]
    return pd.DataFrame(rows)


def test_labels_follow_the_codebook_order():
    assert map_label(13, 1) == "settled_out_of_court"
    assert map_label(12, None) == "voluntary_dismissal"
    assert map_label(5, 1) == "consent_judgment"
    assert map_label(6, 1) == "judgment_for_plaintiff"
    assert map_label(6, 2) == "judgment_for_defendant"
    assert map_label(0, None) == "not_a_merits_ending"
    assert map_label(-8, None) == "not_a_merits_ending"
    assert map_label(14, None) == "other_dismissal"


def test_corporate_rules():
    assert classify_defendant("ACME INC", "3", "-8") == "name_suffix"
    assert classify_defendant("UNITED STATES OF AMERICA", "2", "-8") == "government"
    assert classify_defendant("SECURITIES AND EXCHANGE COMMISSION", "3", "-8") == "government"
    assert classify_defendant("U.S.A.", "1", "-8") == "government"
    assert classify_defendant("USA", "3", "-8") == "non_corporate"
    assert classify_defendant("DEPARTMENT STORE INC", "3", "-8") == "government"
    assert classify_defendant("L.L.C. HOLDCO", "3", "-8") == "name_suffix"
    assert classify_defendant("", "4", "14") == "corporate_via_residence"
    assert classify_defendant("", "3", "14") == "corporate_unknown"
    assert classify_defendant("PLAIN NAME", "4", "15") == "corporate_via_residence"


def test_feature_frame_excludes_outcome_fields():
    prepared, counts = prepare_rows(_fixture_rows())
    cohort, _counts = build_cohort(prepared, counts)
    cohort = cohort.copy()
    cohort["PROCPROG"] = "9"
    cohort["TERMDATE"] = cohort["TERMDATE"]
    features = feature_frame(cohort)
    assert list(features.columns) == FEATURE_COLUMNS
    for forbidden in FORBIDDEN_FEATURE_FIELDS:
        assert forbidden not in features.columns


def test_split_drops_repeat_defendants_and_keeps_spanning_mdl_in_train():
    prepared, counts = prepare_rows(_fixture_rows())
    cohort, _counts = build_cohort(prepared, counts)
    assert "UNITED STATES OF AMERICA" not in set(cohort["DEF"])
    assert (cohort["ORIGIN"] == "4").sum() == 0
    assert (cohort["label"] == "not_a_merits_ending").sum() == 0
    rho = cohort.loc[cohort["DOCKET"] == "15"].iloc[0]
    assert rho["y_settle"] == 1
    scored, info, _dropped = assign_splits(cohort, date(2026, 8, 26))
    assert info["party_leakage_dropped"] >= 1
    assert info["mdl_test_rows_moved_to_train"] >= 1
    test = scored.loc[scored["split"].eq("test")]
    assert "ACME INC" not in set(test["DEF"])
    assert "OMICRON CORP" not in set(test["DEF"])
    train = scored.loc[scored["split"].eq("train")]
    assert "OMICRON CORP" in set(train["DEF"])
    assert int(test["case_key"].duplicated().sum()) == 0


def test_censoring_drops_a_filing_whose_lag_passes_the_extract_date():
    prepared, counts = prepare_rows(_fixture_rows())
    cohort, _counts = build_cohort(prepared, counts)
    _scored, info, _dropped = assign_splits(cohort, date(2020, 7, 1))
    assert info["test_censored"] > 0


def test_download_does_not_fetch_when_the_file_exists(tmp_path, monkeypatch):
    dest = tmp_path / "cv88on.zip"
    dest.write_bytes(b"cached")

    def _boom(*_args, **_kwargs):
        raise AssertionError("download should not run")

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    assert download_idb(dest) == dest
    assert FJC_CIVIL_ZIP_URL.startswith("https://www.fjc.gov/")


def test_evaluate_settlement_writes_a_pending_audit(tmp_path):
    table = tmp_path / "tiny.csv"
    _fixture_rows().to_csv(table, index=False)
    report_path = tmp_path / "report.json"
    audit_path = tmp_path / "audit.csv"
    report = run_evaluation(
        table,
        report_path,
        audit_path=audit_path,
        as_of=date(2026, 8, 26),
        bootstrap_draws=200,
    )
    assert report["audit_gate"] == "pending"
    assert report["project_done"] is False
    assert report_path.exists()
    audit = pd.read_csv(audit_path)
    assert "gold_label" in audit.columns
    assert len(audit) > 0
    assert set(report["modeling_gate"]["bars"]) == {
        "roc_auc_beats_best_baseline",
        "brier_beats_best_baseline",
        "model_auc_ci_above_0.5",
    }
    assert "PROCPROG" not in report["primary"]["baselines"]


def test_cli_missing_file_exits_nonzero(tmp_path):
    code = main(
        [
            "evaluate-settlement",
            "--idb",
            str(tmp_path / "missing.zip"),
            "--report",
            str(tmp_path / "out.json"),
            "--audit-out",
            str(tmp_path / "audit.csv"),
        ]
    )
    assert code == 2
