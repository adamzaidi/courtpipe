"""Leakage fixtures: order text must not enter MTD features. No network."""

from __future__ import annotations

from analysis.mtd.features import (
    assert_no_leakage,
    build_feature_row,
    entry_before_order,
    scan_forbidden_tokens,
)

COMPLAINT = "This pleading states facts about a contract and a corporation. Count I."
MOTION = "Defendant asks the court to test the pleading under Twombly and Iqbal."


def _docket(label_word: str, court: str = "nysd") -> tuple[dict, dict, dict]:
    motion = {
        "id": 2,
        "document_number": 15,
        "date_filed": "2018-03-01",
        "time_filed": "10:00:00",
        "description": "MOTION to Dismiss for Failure to State a Claim by Defendant Acme Inc.",
        "short_description": "Motion to Dismiss",
        "is_available": True,
        "page_count": 10,
        "plain_text": MOTION,
        "attachments": [],
    }
    order = {
        "id": 99,
        "document_number": 25,
        "date_filed": "2018-06-01",
        "time_filed": "14:00:00",
        "description": f"ORDER {label_word} 15 Motion to Dismiss for Failure to State a Claim",
        "plain_text": f"The motion is {label_word}. Later opinion cites this outcome.",
        "is_available": True,
    }
    later = {
        "id": 100,
        "document_number": 30,
        "date_filed": "2018-09-01",
        "time_filed": "09:00:00",
        "description": "NOTICE OF APPEAL from the order that granted the motion",
        "plain_text": "Appellant notes that the motion was granted.",
    }
    docket = {
        "docket_id": 1,
        "court_id": court,
        "suitNature": "850 Securities/Commodities",
        "cause": "15:78m(a)",
        "jurisdiction": "Federal Question",
        "juryDemand": "None",
        "assigned_to_id": "j1",
        "parties": [
            {"name": "Pat Plaintiff", "party_types": ["Plaintiff"], "attorneys": []},
            {"name": "Acme Inc.", "party_types": ["Defendant"], "attorneys": ["Firm LLP"]},
        ],
        "entries": [
            {
                "id": 1,
                "document_number": 1,
                "date_filed": "2018-01-15",
                "time_filed": "09:00:00",
                "description": "COMPLAINT",
                "short_description": "Complaint",
                "is_available": True,
                "page_count": 12,
                "plain_text": COMPLAINT,
            },
            motion,
            order,
            later,
        ],
        "dateTerminated": "2019-01-01",
    }
    return docket, motion, order


def test_same_day_without_times_is_excluded():
    entry = {"date_filed": "2018-06-01", "time_filed": None}
    order = {"date_filed": "2018-06-01", "time_filed": None}
    assert entry_before_order(entry, order) is False
    earlier = {"date_filed": "2018-06-01", "time_filed": "09:00:00"}
    later_order = {"date_filed": "2018-06-01", "time_filed": "10:00:00"}
    assert entry_before_order(earlier, later_order) is True
    after = {"date_filed": "2018-06-02", "time_filed": "08:00:00"}
    assert entry_before_order(after, later_order) is False


def test_leakage_fixture_drops_order_and_later_text():
    hits = []
    for i in range(40):
        word = "granted" if i % 2 == 0 else "denied"
        docket, motion, order = _docket(word, court="nysd" if i % 2 == 0 else "cand")
        row = build_feature_row(docket, motion, order, include_text=True)
        assert_no_leakage(row, order)
        assert str(order["id"]) not in str(row.values())
        assert "NOTICE OF APPEAL" not in str(row.get("complaint_text"))
        assert "NOTICE OF APPEAL" not in str(row.get("motion_text"))
        found = scan_forbidden_tokens(row)
        hits.extend(found)
    assert hits == []


def test_court_feature_is_retained_when_order_is_uninformative():
    docket, motion, order = _docket("taking the matter under advisement", court="ded")
    order["description"] = "ORDER on Motion to Dismiss for Failure to State a Claim"
    order["plain_text"] = "The court has reviewed the papers."
    row = build_feature_row(docket, motion, order, include_text=True)
    assert row["court_id"] == "ded"
    assert row["circuit"] == "ca3"
