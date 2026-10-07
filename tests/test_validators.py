"""Post-load validation checks. They log; they do not mutate the frame."""

from __future__ import annotations

import logging

import pandas as pd

from utils.validators import _pct_nonempty, validate_processed


def _frame(**overrides) -> pd.DataFrame:
    rows = {
        "case_id": [1, 2],
        "court": ["U.S. Court of Appeals for the Ninth Circuit", "Supreme Court of California"],
        "jurisdiction_state": ["Federal", "California"],
        "citation": ["100 F.3d 200", "1 Cal. App. 5th 1"],
        "outcome_code": [1, 2],
        "outcome_code_fine": [1, 2],
        "outcome_label_fine": ["affirmed", "reversed"],
    }
    rows.update(overrides)
    return pd.DataFrame(rows)


def test_pct_nonempty_ignores_blank_unknown_and_nan():
    series = pd.Series(["Ninth Circuit", "", "Unknown", "nan", "  California  "])
    assert _pct_nonempty(series) == 40.0


def test_validate_processed_passes_clean_frame(caplog):
    with caplog.at_level(logging.INFO, logger="pipeline"):
        validate_processed(_frame())
    text = caplog.text
    assert "Processed DF schema: OK" in text
    assert "Outcome_code domain OK" in text
    assert "case_id uniqueness: OK" in text
    assert "Light validation: PASS" in text
    assert "PASS with warnings" not in text


def test_validate_processed_warns_on_schema_domain_and_duplicates(caplog):
    df = _frame(
        outcome_code=[1, 9],
        outcome_code_fine=[1, 8],
        case_id=[5, 5],
    )
    df = df.drop(columns=["citation"])
    with caplog.at_level(logging.INFO, logger="pipeline"):
        validate_processed(df)
    text = caplog.text
    assert "missing columns" in text
    assert "Invalid values in outcome_code" in text
    assert "Invalid values in outcome_code_fine" in text
    assert "Duplicate case_id rows: 1" in text
    assert "Light validation: PASS with warnings" in text
