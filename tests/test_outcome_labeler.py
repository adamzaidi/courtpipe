"""Rule-based outcome labeling, confidence, and review flags. No network."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from etl.transform import (
    _label_outcome_from_text_with_meta,
    _normalize_text_url,
    transform_data,
)


def _expected_single_confidence(zone: int, pos: float, strong: int) -> float:
    confidence = 0.50
    confidence += 0.20 if zone else 0.0
    confidence += 0.20 if pos > 0.60 else 0.0
    confidence += 0.10 if strong else 0.0
    if (not strong) and pos < 0.35:
        confidence -= 0.15
    return max(0.0, min(1.0, confidence))


def _expected_mixed_confidence(zone: int, pos: float, strong: int) -> float:
    confidence = 0.55
    confidence += 0.15 if zone else 0.0
    confidence += 0.15 if pos > 0.60 else 0.0
    confidence += 0.10 if strong else 0.0
    return max(0.0, min(1.0, confidence))


def _needs_review(fine: str, confidence: float) -> int:
    needs = 0
    if fine in {"other", "mixed"}:
        needs = 1
    if confidence < 0.60:
        needs = 1
    return needs


def test_empty_text_is_other_with_zero_confidence():
    coarse, fine, fine_code, evidence, pos, zone, strong, conf = _label_outcome_from_text_with_meta("")
    assert (coarse, fine, fine_code) == (0, "other", 0)
    assert evidence == ""
    assert (pos, zone, strong, conf) == (0.0, 0, 0, 0.0)


def test_text_without_disposition_language_is_other():
    text = "The parties argued about corporate veil piercing and damages only."
    coarse, fine, fine_code, evidence, pos, zone, strong, conf = _label_outcome_from_text_with_meta(text)
    assert (coarse, fine, fine_code) == (0, "other", 0)
    assert evidence == ""
    assert zone == 0
    assert strong == 0
    assert conf == 0.25
    assert pos == 0.0


def test_affirm_with_strong_phrase_matches_confidence_formula():
    text = "The record is long. In this opinion the judgment is affirmed."
    coarse, fine, fine_code, evidence, pos, zone, strong, conf = _label_outcome_from_text_with_meta(text)
    assert (coarse, fine, fine_code) == (1, "affirmed", 1)
    assert zone == 1
    assert strong == 1
    assert "affirm" in evidence
    assert conf == pytest.approx(_expected_single_confidence(zone, pos, strong))
    assert conf >= 0.80


def test_reversed_and_remanded_labels_reversed_not_mixed():
    text = "The judgment is reversed and remanded for further proceedings in this opinion."
    coarse, fine, fine_code, evidence, pos, zone, strong, conf = _label_outcome_from_text_with_meta(text)
    assert (coarse, fine, fine_code) == (2, "reversed", 2)
    assert strong == 1
    assert "revers" in evidence
    assert conf == pytest.approx(_expected_single_confidence(zone, pos, strong))


def test_affirmed_in_part_and_reversed_in_part_is_mixed():
    text = "The opinion is affirmed in part and reversed in part."
    coarse, fine, fine_code, evidence, pos, zone, strong, conf = _label_outcome_from_text_with_meta(text)
    assert (coarse, fine, fine_code) == (2, "mixed", 0)
    assert strong == 1
    assert evidence
    assert conf == pytest.approx(_expected_mixed_confidence(zone, pos, strong))


def test_vacate_beats_later_reverse_when_there_is_no_affirm():
    # "order" is a disposition-zone hint. Keep the verbs after the zone word
    # so the search window still contains them.
    text = "In this opinion we vacated and reversed."
    coarse, fine, fine_code, evidence, *_rest = _label_outcome_from_text_with_meta(text)
    assert (coarse, fine, fine_code) == (2, "vacated", 3)
    assert "vacat" in evidence


def test_we_remand_is_remanded():
    text = "We remand for a new hearing on damages."
    coarse, fine, fine_code, evidence, pos, zone, strong, conf = _label_outcome_from_text_with_meta(text)
    assert (coarse, fine, fine_code) == (2, "remanded", 4)
    assert strong == 1
    assert conf == pytest.approx(_expected_single_confidence(zone, pos, strong))


def test_appeal_is_dismissed_is_dismissed():
    text = "Accordingly the appeal is dismissed."
    coarse, fine, fine_code, evidence, pos, zone, strong, conf = _label_outcome_from_text_with_meta(text)
    assert (coarse, fine, fine_code) == (1, "dismissed", 5)
    assert strong == 1
    assert "dismiss" in evidence
    assert conf == pytest.approx(_expected_single_confidence(zone, pos, strong))


def test_early_dismissed_without_strong_phrase_drops_confidence():
    text = "dismissed " + ("filler " * 80)
    coarse, fine, fine_code, evidence, pos, zone, strong, conf = _label_outcome_from_text_with_meta(text)
    assert (coarse, fine, fine_code) == (1, "dismissed", 5)
    assert zone == 0
    assert strong == 0
    assert pos < 0.35
    assert conf == pytest.approx(0.35)
    assert conf == pytest.approx(_expected_single_confidence(zone, pos, strong))


def test_normalize_text_url():
    assert _normalize_text_url("") == ""
    assert _normalize_text_url("unknown") == ""
    assert _normalize_text_url("  nan ") == ""
    assert _normalize_text_url("/opinion/9/") == "https://www.courtlistener.com/opinion/9/"
    assert _normalize_text_url("https://example.com/a") == "https://example.com/a"


def test_transform_sets_needs_review_and_does_not_fetch(tmp_path, monkeypatch):
    raw = tmp_path / "raw.csv"
    out = tmp_path / "processed.csv"
    review = tmp_path / "review.csv"
    pd.DataFrame(
        [
            {
                "case_id": 1,
                "case_name": "Affirmed Example",
                "court": "U.S. Court of Appeals for the Ninth Circuit",
                "citation": "1 F.3d 1",
                "opinion_year": 2020,
                "plain_text_url": "",
                "text_snippet": "In this opinion the judgment is affirmed.",
            },
            {
                "case_id": 2,
                "case_name": "Mixed Example",
                "court": "U.S. Court of Appeals for the Fifth Circuit",
                "citation": "2 F.3d 2",
                "opinion_year": 2019,
                "plain_text_url": "",
                "text_snippet": "The opinion is affirmed in part and reversed in part.",
            },
            {
                "case_id": 3,
                "case_name": "Unclear Example",
                "court": "Supreme Court of California",
                "citation": "3 Cal. App. 5th 3",
                "opinion_year": 2021,
                "plain_text_url": "",
                "text_snippet": "The parties argued about corporate veil piercing and damages only.",
            },
            {
                "case_id": 4,
                "case_name": "Weak Dismiss Example",
                "court": "U.S. District Court for the Southern District of New York",
                "citation": "4 F. Supp. 3d 4",
                "opinion_year": 2017,
                "plain_text_url": "",
                "text_snippet": "dismissed " + ("filler " * 80),
            },
        ]
    ).to_csv(raw, index=False)

    def _boom(url: str) -> str:
        raise AssertionError(f"transform tried to fetch {url}")

    monkeypatch.setattr("etl.transform._fetch_plain_text_slice", _boom)
    monkeypatch.setattr("etl.transform.REVIEW_PATH", str(review))

    df = transform_data(raw_path=str(raw), out_path=str(out))

    assert out.exists()
    assert review.exists()
    assert len(df) == 4

    by_case = df.set_index("case_id")
    assert by_case.loc[1, "outcome_label_fine"] == "affirmed"
    assert int(by_case.loc[1, "needs_review"]) == 0
    assert by_case.loc[2, "outcome_label_fine"] == "mixed"
    assert int(by_case.loc[2, "needs_review"]) == 1
    assert by_case.loc[3, "outcome_label_fine"] == "other"
    assert int(by_case.loc[3, "needs_review"]) == 1
    assert by_case.loc[4, "outcome_label_fine"] == "dismissed"
    assert float(by_case.loc[4, "outcome_confidence"]) < 0.60
    assert int(by_case.loc[4, "needs_review"]) == 1

    for _, row in df.iterrows():
        assert int(row["needs_review"]) == _needs_review(row["outcome_label_fine"], float(row["outcome_confidence"]))

    queued = pd.read_csv(review)
    assert set(queued["case_id"]) == {2, 3, 4}
    assert list(queued["outcome_confidence"]) == sorted(queued["outcome_confidence"].tolist())


FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "sample_opinions.csv"


def test_sample_fixture_labels_offline(tmp_path, monkeypatch):
    raw = pd.read_csv(FIXTURE)
    urls = raw["plain_text_url"].fillna("").astype(str)
    assert not urls.str.startswith(("http://", "https://")).any()

    def _boom(url: str) -> str:
        raise AssertionError(f"fixture transform tried to fetch {url}")

    monkeypatch.setattr("etl.transform._fetch_plain_text_slice", _boom)
    monkeypatch.setattr("etl.transform.REVIEW_PATH", str(tmp_path / "review.csv"))

    df = transform_data(raw_path=str(FIXTURE), out_path=str(tmp_path / "processed.csv"))
    assert len(df) == len(raw)
    allowed = {"affirmed", "dismissed", "reversed", "vacated", "remanded", "mixed", "other"}
    assert set(df["outcome_label_fine"]) <= allowed
    assert df["outcome_label_fine"].value_counts().to_dict() == {
        "affirmed": 4,
        "dismissed": 4,
        "reversed": 3,
        "other": 3,
        "mixed": 2,
        "remanded": 2,
        "vacated": 2,
    }
    assert int((df["needs_review"] == 1).sum()) == 7
    for _, row in df.iterrows():
        assert int(row["needs_review"]) == _needs_review(row["outcome_label_fine"], float(row["outcome_confidence"]))
