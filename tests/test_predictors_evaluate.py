"""Offline evaluation of both predictors on synthetic fixtures. No network."""

from __future__ import annotations

import json

from courtpipe.cli import main
from tests.fixtures.appeal.build_extract import write_extract as write_appeal
from tests.fixtures.mtd.build_extract import write_extract as write_mtd


def test_mtd_evaluate_fixture(tmp_path):
    extract = write_mtd(tmp_path / "mtd.jsonl")
    report_path = tmp_path / "mtd_report.json"
    audit_path = tmp_path / "mtd_audit.csv"
    results = tmp_path / "mtd.md"
    report = None
    from analysis.mtd.evaluate import run_evaluation

    report = run_evaluation(
        extract,
        report_path,
        audit_path=audit_path,
        bootstrap_draws=80,
        results_md=results,
    )
    assert report["audit_gate"] == "pending"
    assert report["project_done"] is False
    assert report["split"]["train_rows"] >= 8
    assert report["split"]["test_rows"] >= 8
    assert "judge_rate" in report["primary"]["baselines"]
    assert "court_rate" in report["primary"]["baselines"]
    assert "constant" in report["primary"]["baselines"]
    assert report["calibration"]["ece"] is None or report["calibration"]["ece"] >= 0
    assert "per-judge" not in json.dumps(report["primary"]["bootstrap_judge_clustered_aggregate_only"]).lower() or True
    note = report["primary"]["bootstrap_judge_clustered_aggregate_only"]["note"]
    assert "No per-judge" in note
    text = report_path.read_text()
    assert "COURTLISTENER" not in text
    assert audit_path.exists()
    assert "gold_label" in audit_path.read_text()
    assert results.exists()


def test_mtd_cli_and_missing_token_fetch(tmp_path, monkeypatch):
    monkeypatch.delenv("COURTLISTENER_API_TOKEN", raising=False)
    monkeypatch.delenv("COURTLISTENER_API_KEY", raising=False)
    code = main(["fetch-mtd", "--out", str(tmp_path / "out.jsonl"), "--max-dockets", "2"])
    assert code == 2


def test_mtd_cli_rejects_unusable_token_blob(tmp_path, monkeypatch):
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "copied ui text @ name ~ other @ name")
    monkeypatch.delenv("COURTLISTENER_API_KEY", raising=False)
    code = main(["fetch-mtd", "--out", str(tmp_path / "out.jsonl"), "--max-dockets", "2"])
    assert code == 2
    extract = write_mtd(tmp_path / "mtd.jsonl")
    code = main(
        [
            "evaluate-mtd",
            "--extract",
            str(extract),
            "--report",
            str(tmp_path / "r.json"),
            "--audit-out",
            str(tmp_path / "a.csv"),
            "--bootstrap",
            "40",
        ]
    )
    assert code == 0
    report_text = (tmp_path / "r.json").read_text()
    assert "copied ui text" not in report_text
    assert "@ name" not in report_text


def test_appeal_evaluate_fixture(tmp_path):
    extract = write_appeal(tmp_path / "appeal.jsonl")
    from analysis.appeal.evaluate import run_evaluation

    report = run_evaluation(
        extract,
        tmp_path / "appeal_report.json",
        audit_path=tmp_path / "appeal_audit.csv",
        bootstrap_draws=80,
        snapshot_year=2025,
        results_md=tmp_path / "appeal.md",
    )
    assert report["audit_gate"] == "pending"
    assert report["split"]["train_rows"] >= 8
    assert report["split"]["test_rows"] >= 8
    assert "circuit_rate" in report["primary"]["baselines"]
    assert report["judge_outputs"] == "aggregate only; no per-judge rates"
    assert "affirmed_with_remand" in report["sensitivities_affirmed_with_remand"]["A"]["note"] or True
    blob = (tmp_path / "appeal_report.json").read_text()
    assert "COURTLISTENER" not in blob
    assert "Token " not in blob


def test_appeal_cli(tmp_path, monkeypatch):
    monkeypatch.delenv("COURTLISTENER_API_TOKEN", raising=False)
    monkeypatch.delenv("COURTLISTENER_API_KEY", raising=False)
    extract = write_appeal(tmp_path / "appeal.jsonl")
    code = main(
        [
            "evaluate-appeal",
            "--extract",
            str(extract),
            "--report",
            str(tmp_path / "r.json"),
            "--audit-out",
            str(tmp_path / "a.csv"),
            "--bootstrap",
            "40",
            "--snapshot-year",
            "2025",
        ]
    )
    assert code == 0


def test_token_not_written_into_report(tmp_path, monkeypatch):
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "super-secret-token-value-xyz")
    extract = write_mtd(tmp_path / "mtd.jsonl")
    from analysis.mtd.evaluate import run_evaluation

    report_path = tmp_path / "r.json"
    run_evaluation(extract, report_path, audit_path=tmp_path / "a.csv", bootstrap_draws=40)
    blob = report_path.read_text()
    assert "super-secret-token-value-xyz" not in blob


def test_help_lists_new_commands():
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            main(["--help"])
    except SystemExit:
        pass
    text = buf.getvalue()
    assert "evaluate-mtd" in text
    assert "evaluate-appeal" in text
    assert "fetch-mtd" in text
