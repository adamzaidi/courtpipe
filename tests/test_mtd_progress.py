from analysis.mtd.progress import build_progress, write_progress
import json


def _state():
    return {
        "queries": {"a": {"exhausted": True, "pending": []}, "b": {"exhausted": False, "pending": [1]}},
        "large": [5, 6],
        "runs": [
            {"requests": 100, "new_dockets": 8, "total_dockets": 10, "transient_failures": 1, "stop": "time limit reached"},
            {"finished": "2026-11-22T04:00+00:00", "minutes": 660.0, "requests": 50, "new_dockets": 5,
             "total_dockets": 15, "transient_failures": 0, "stop": "time limit reached"},
        ],
    }


def _report():
    funnel = {
        "dockets_in_scope": 15, "mtd_motion_entries": 20, "outside_window": 2, "unresolved": 3,
        "order_text_unclear": 4, "link_ambiguous": 5, "first_order_rules_on_other_motion": 1,
        "linked_to_order": 5, "movant_unknown": 1, "not_corporate_defendant": 1, "label_unclear": 0,
        "labeled_cohort": 3, "motion_entries_look_like_briefs": 6,
    }
    return {"funnel": funnel, "split": {"train_rows": 2, "test_rows": 1}, "audit_gate": "pending",
            "modeling_gate": {"passed": False}, "primary": {"model_roc_auc": 0.777}}


def test_status_and_runs():
    page = build_progress(_state(), _report())
    assert "| Dockets collected | 15 |" in page
    assert "| Searches finished | 1 of 2 |" in page
    assert "| API requests to date | 150 |" in page
    assert "| Large dockets waiting (collected over several runs) | 2 |" in page
    assert "| 2 | 2026-11-22T04:00+00:00 | 11.0 | 50 |" in page
    assert "2 dockets were collected before run 1" in page
    assert "did not record their finish time" in page


def test_funnel_adds_up_and_no_scores():
    page = build_progress(_state(), _report())
    assert "| **Matched to its ruling** | **5** | **25%** | |" in page
    assert "Other (" not in page  # every motion accounted for
    assert "6 of the 20 entries" in page
    assert "0.777" not in page  # no test metric is ever printed
    assert "Modeling gate: not yet met" in page


def test_unaccounted_motions_are_shown():
    report = _report()
    report["funnel"]["mtd_motion_entries"] = 22
    assert "| Other (" in build_progress(_state(), report)


def test_without_report(tmp_path):
    state = tmp_path / "s.json"
    state.write_text(json.dumps(_state()))
    out = write_progress(state, None, tmp_path / "PROGRESS.md")
    text = out.read_text()
    assert "Dockets collected" in text and "From dockets" not in text
