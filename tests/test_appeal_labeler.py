"""Appeal disposition crosswalk examples from the spec. No network."""

from __future__ import annotations

from analysis.appeal.labeler import label_cluster, label_disposition, y_disturb_sensitivity


def test_spec_examples():
    cases = [
        ("The judgment of the district court is affirmed.", "affirmed", 0),
        ("Reversed.", "reversed", 1),
        ("Reversed and remanded.", "reversed", 1),
        ("Vacated and remanded.", "vacated", 1),
        ("Remanded.", "remanded", 1),
        ("Affirmed and remanded.", "affirmed_with_remand", None),
        ("Affirmed in part, reversed in part, and remanded.", "mixed", 1),
        ("Affirmed in part and remanded in part.", "mixed", 1),
        ("Affirmed as modified.", "mixed", 1),
        ("Appeal dismissed.", "dismissed", None),
        ("Dismissed for lack of jurisdiction.", "dismissed", None),
        ("Certificate of appealability denied.", "coa", None),
    ]
    for text, fine, y in cases:
        parsed = label_disposition(text)
        assert parsed["fine"] == fine, text
        assert parsed["y_disturb"] == y, text


def test_blank_disposition_uses_decretal_and_does_not_copy_into_features():
    parsed = label_cluster(
        {
            "disposition": "",
            "decretal_excerpt": "For the reasons stated, we reverse.",
        }
    )
    assert parsed["fine"] == "reversed"
    assert parsed["label_source"] == "decretal"
    from analysis.appeal.features import assert_no_leakage, build_feature_row

    row = {
        "court_id": "ca9",
        "date_filed": "2019-06-01",
        "date_argued": "2019-01-01",
        "appeal_date_filed": "2018-06-01",
        "appeal_from_id": "cand",
        "originating_date_judgment": "2018-01-01",
        "disposition": "Reversed.",
        "decretal_excerpt": "we reverse",
        "district_opinion_plain_text": "The district court granted summary judgment.",
    }
    features = build_feature_row(row)
    assert_no_leakage(features)
    assert "disposition" not in features
    assert "we reverse" not in str(features.get("district_opinion_text"))


def test_sensitivities_do_not_become_headline():
    assert y_disturb_sensitivity("affirmed_with_remand", "A") == 0
    assert y_disturb_sensitivity("affirmed_with_remand", "B") == 1
    assert y_disturb_sensitivity("affirmed", "A") == 0
    assert y_disturb_sensitivity("reversed", "B") == 1
