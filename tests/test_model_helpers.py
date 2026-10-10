"""Small model helpers. Does not train, and does not read the network."""

from __future__ import annotations

import numpy as np
import pandas as pd

from analysis.model import _build_features, _code_to_name, _metrics_row, _stable_label_list


def test_label_maps_match_transform_codes():
    assert _stable_label_list("coarse") == [0, 1, 2]
    assert _stable_label_list("fine") == [0, 1, 2, 3, 4, 5]
    coarse = _code_to_name("coarse")
    fine = _code_to_name("fine")
    assert coarse[1] == "affirmed_or_dismissed"
    assert coarse[2] == "changed_or_mixed"
    assert fine[1] == "affirmed"
    assert fine[3] == "vacated"
    assert fine[5] == "dismissed"
    assert "mixed" not in fine.values()


def test_metrics_row_perfect_predictions():
    y = [0, 1, 1, 2]
    metrics = _metrics_row(y, y)
    assert metrics["accuracy"] == 1.0
    assert metrics["f1_macro"] == 1.0
    assert metrics["f1_weighted"] == 1.0


def test_build_features_one_hot_and_buckets():
    df = pd.DataFrame(
        {
            "court": ["Ninth Circuit", None],
            "opinion_year": ["2018", "not-a-year"],
            "text_word_count": [100, 5000],
            "disposition_zone_found": [1, np.nan],
            "evidence_contains_strong_phrase": [1, 0],
            "evidence_match_position": [0.8, None],
        }
    )
    X = _build_features(df)
    assert len(X) == 2
    assert "opinion_year" in X.columns
    assert int(X.iloc[1]["opinion_year"]) == 0
    assert int(X.iloc[1]["court_Unknown"]) == 1
    assert int(X.iloc[0]["wordcount_bucket_<=300"]) == 1
    assert int(X.iloc[1]["wordcount_bucket_3001+"]) == 1
    assert int(X.isna().sum().sum()) == 0
