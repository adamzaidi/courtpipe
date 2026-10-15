"""MTD order labeler. Hand-written entries. No network."""

from __future__ import annotations

from analysis.mtd.corporate import classify_name, is_defendant_role, match_movant
from analysis.mtd.labeler import label_order, motion_grounds, y_relief


def test_granting_links_document_and_labels_granted():
    parsed = label_order("ORDER granting 15 Motion to Dismiss for Failure to State a Claim")
    assert parsed["is_ruling"] is True
    assert parsed["label"] == "granted"
    assert parsed["document_numbers"] == [15]
    assert y_relief(parsed["label"]) == 1


def test_denying_labels_denied():
    parsed = label_order("ORDER denying 15 Motion to Dismiss for Failure to State a Claim")
    assert parsed["label"] == "denied"
    assert y_relief(parsed["label"]) == 0


def test_granting_in_part():
    parsed = label_order(
        "ORDER granting in part and denying in part 15 Motion to Dismiss for Failure to State a Claim"
    )
    assert parsed["label"] == "granted_in_part"
    assert y_relief(parsed["label"]) == 1


def test_grant_with_leave_stays_granted():
    parsed = label_order(
        "ORDER granting 15 Motion to Dismiss for Failure to State a Claim with leave to amend within 21 days"
    )
    assert parsed["label"] == "granted"
    assert parsed["leave"] == "leave_granted"


def test_with_prejudice_is_leave_denied_without_prejudice_is_not_stated():
    denied_leave = label_order(
        "ORDER granting 15 Motion to Dismiss for Failure to State a Claim. Dismissed with prejudice."
    )
    assert denied_leave["leave"] == "leave_denied"
    without = label_order(
        "ORDER granting 15 Motion to Dismiss for Failure to State a Claim. Dismissed without prejudice."
    )
    assert without["leave"] == "leave_not_stated"


def test_proposed_order_is_not_a_ruling():
    text = (
        "MOTION TO DISMISS FOR FAILURE TO STATE A CLAIM by Defendants "
        "International Business Machines Corporation, Red Hat, Inc. Text of Proposed Order."
    )
    parsed = label_order(text)
    assert parsed["is_ruling"] is False
    assert parsed["exclude_reason"] == "proposed_order"


def test_report_and_recommendation_is_not_a_ruling_adoption_is():
    rec = label_order(
        "REPORT AND RECOMMENDATION recommending that the Motion to Dismiss for Failure to State a Claim be granted"
    )
    assert rec["is_ruling"] is False
    assert rec["exclude_reason"] == "report_and_recommendation"
    adopt = label_order(
        "ORDER adopting the report and recommendation and granting 15 Motion to Dismiss for Failure to State a Claim"
    )
    assert adopt["is_ruling"] is True
    assert adopt["label"] == "granted"


def test_jurisdictional_only_out_mixed_grounds_kept():
    only = motion_grounds("MOTION to Dismiss for Lack of Personal Jurisdiction under Rule 12(b)(2)")
    assert only["jurisdictional_only"] is True
    assert only["is_12b6"] is False
    mixed = motion_grounds("MOTION to Dismiss under Rule 12(b)(6) and Rule 12(b)(2)")
    assert mixed["is_12b6"] is True
    assert mixed["also_12b2"] is True


def test_moot_and_withdrawn_excluded_not_denied():
    moot = label_order("ORDER denying as moot 15 Motion to Dismiss for Failure to State a Claim")
    assert moot["exclude_reason"] == "moot"
    withdrawn = label_order("ORDER that the Motion to Dismiss is withdrawn")
    assert withdrawn["exclude_reason"] == "withdrawn"


def test_corporate_and_government_names():
    assert classify_name("Equifax, Inc.") == "corporate"
    assert classify_name("Securities and Exchange Commission") == "government"
    assert classify_name("UNITED STATES OF AMERICA") == "government"
    plaintiff = {"name": "CT Healthcare Holdings, LLC", "party_types": ["Plaintiff"]}
    assert is_defendant_role(plaintiff) is False
    defendant = {"name": "CT Healthcare Holdings, LLC", "party_types": ["Defendant"]}
    assert is_defendant_role(defendant) is True
    movant = match_movant("filed by Equifax, Inc.", [{"name": "Equifax, Inc.", "party_types": ["Defendant"]}])
    assert movant is not None


def test_nested_party_types_from_courtlistener_payload():
    nested = {
        "name": "Equifax, Inc.",
        "party_types": [{"name": "Defendant", "date_terminated": None}],
    }
    assert is_defendant_role(nested) is True
    plaintiff = {
        "name": "CT Healthcare Holdings, LLC",
        "party_types": [{"name": "Plaintiff"}],
    }
    assert is_defendant_role(plaintiff) is False


def test_blank_party_type_is_a_stop():
    from analysis.mtd.corporate import MissingPartyTypeError

    try:
        is_defendant_role({"name": "Acme Inc."})
        raise AssertionError("expected MissingPartyTypeError")
    except MissingPartyTypeError:
        pass


def test_opinion_labeler_is_not_this_function():
    from etl.transform import _label_outcome_from_text_with_meta

    order = "the motion is granted"
    complaint = "plaintiff says the case should be dismissed"
    coarse, fine, *_ = _label_outcome_from_text_with_meta(complaint)
    parsed = label_order("ORDER granting 15 Motion to Dismiss for Failure to State a Claim")
    assert fine != parsed["label"]
    assert parsed["label"] == "granted"
    # The opinion labeler is a different function and is not called here.
    assert _label_outcome_from_text_with_meta is not label_order
    _ = order
