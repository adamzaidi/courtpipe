"""Build the synthetic MTD extract. Invented captions. Not a grant rate."""

from __future__ import annotations

import json
from pathlib import Path

NOS = ["160", "410", "480", "850"]
COURTS = ["nysd", "cand", "ded", "ilnd"]
FIRMS = ["North Counsel LLP", "Pacific Firm LLP", "Atlantic LLP", "Midwest LLP"]


def _docket(
    i: int,
    year: int,
    court: str,
    nos: str,
    label: str,
    *,
    opposition: bool,
    leave: str = "leave_not_stated",
    also_12b2: bool = False,
) -> dict:
    month = (i % 9) + 1
    complaint_day = f"{year}-{month:02d}-01"
    motion_day = f"{year}-{month:02d}-15"
    opp_day = f"{year}-{month:02d}-22"
    order_day = f"{year + 1}-{(month % 9) + 1:02d}-10" if month != 12 else f"{year + 1}-01-10"
    company = f"Acme {court.upper()} {nos} Holdings LLC"
    plaintiff = f"Plaintiff {i}"
    doc_motion = 15
    if label == "granted":
        order_desc = f"ORDER granting {doc_motion} Motion to Dismiss for Failure to State a Claim."
        if leave == "leave_granted":
            order_desc += " Plaintiff has leave to amend within 21 days."
        elif leave == "leave_denied":
            order_desc += " Dismissed with prejudice."
    elif label == "granted_in_part":
        order_desc = (
            f"ORDER granting in part and denying in part {doc_motion} "
            "Motion to Dismiss for Failure to State a Claim."
        )
    else:
        order_desc = f"ORDER denying {doc_motion} Motion to Dismiss for Failure to State a Claim."
    motion_desc = (
        f"MOTION to Dismiss for Failure to State a Claim by Defendant {company}."
    )
    if also_12b2:
        motion_desc = (
            f"MOTION to Dismiss under Rule 12(b)(6) and Rule 12(b)(2) by Defendant {company}."
        )
    complaint_text = (
        "This civil complaint alleges federal claims. Count I. Count II. "
        "The facts concern corporate disclosures and consumer accounts."
    )
    if nos == "160":
        complaint_text += " This is a class action on behalf of all shareholders."
    motion_text = "Defendant moves under Rule 12(b)(6). The pleading standard in Twombly and Iqbal applies."
    if nos == "850":
        motion_text += " The PSLRA also requires particularity under Rule 9(b)."
    opposition_text = "Plaintiff opposes and asks the court to keep the claims."
    entries = [
        {
            "id": i * 10 + 1,
            "document_number": 1,
            "date_filed": complaint_day,
            "time_filed": "09:00:00",
            "description": f"COMPLAINT against {company}.",
            "short_description": "Complaint",
            "is_available": True,
            "page_count": 20 + (i % 15),
            "plain_text": complaint_text,
            "attachments": [],
        },
        {
            "id": i * 10 + 2,
            "document_number": doc_motion,
            "date_filed": motion_day,
            "time_filed": "10:00:00",
            "description": motion_desc,
            "short_description": "Motion to Dismiss for Failure to State a Claim",
            "is_available": True,
            "page_count": 18,
            "plain_text": motion_text,
            "attachments": [{"description": "Exhibit A"}] if i % 3 == 0 else [],
        },
    ]
    if opposition:
        entries.append(
            {
                "id": i * 10 + 3,
                "document_number": 18,
                "date_filed": opp_day,
                "time_filed": "11:00:00",
                "description": "MEMORANDUM in Opposition to Motion to Dismiss.",
                "short_description": "Opposition",
                "is_available": True,
                "page_count": 16,
                "plain_text": opposition_text,
                "attachments": [],
            }
        )
    entries.append(
        {
            "id": i * 10 + 4,
            "document_number": 25,
            "date_filed": order_day,
            "time_filed": "14:00:00",
            "description": order_desc,
            "short_description": "Order on Motion to Dismiss for Failure to State a Claim",
            "is_available": True,
            "page_count": 8,
            "plain_text": "The court has considered the papers and rules as stated in the docket entry.",
            "attachments": [],
        }
    )
    return {
        "docket_id": 8000 + i,
        "court_id": court,
        "suitNature": f"{nos} Synthetic",
        "cause": "15:78m(a) Securities Exchange Act" if nos == "850" else "federal question",
        "jurisdiction": "Federal Question",
        "juryDemand": "Plaintiff",
        "assigned_to_id": f"judge-{court}",
        "dateFiled": complaint_day,
        "parties_have_party_type": True,
        "parties": [
            {"name": plaintiff, "party_types": ["Plaintiff"], "attorneys": ["Plaintiffs LLP"]},
            {
                "name": company,
                "party_types": ["Defendant"],
                "attorneys": [FIRMS[COURTS.index(court)]],
            },
        ],
        "entries": entries,
        "snapshot_date": "2024-06-01",
    }


def build_dockets() -> list[dict]:
    rows = []
    i = 1
    # Train 2016-2019: 32 rows. nysd grants more; opposition associated with denial.
    for year in (2016, 2017, 2018, 2019):
        for court in COURTS:
            nos = NOS[(i - 1) % 4]
            opposition = court in {"cand", "ilnd"}
            if court == "nysd":
                label = "granted" if i % 3 else "granted_in_part"
            elif court == "ded":
                label = "granted" if i % 2 else "denied"
            else:
                label = "denied" if opposition else "granted"
            leave = "leave_granted" if label == "granted" and i % 4 == 0 else (
                "leave_denied" if label == "granted" and i % 4 == 1 else "leave_not_stated"
            )
            rows.append(_docket(i, year, court, nos, label, opposition=opposition, leave=leave, also_12b2=(i % 7 == 0)))
            i += 1
    # Test 2020-2022: 24 rows, same generating process.
    for year in (2020, 2021, 2022):
        for court in COURTS:
            nos = NOS[(i - 1) % 4]
            opposition = court in {"cand", "ilnd"}
            if court == "nysd":
                label = "granted" if i % 3 else "granted_in_part"
            elif court == "ded":
                label = "granted" if i % 2 else "denied"
            else:
                label = "denied" if opposition else "granted"
            rows.append(_docket(i, year, court, nos, label, opposition=opposition))
            i += 1
    # Quarantine 2023: 4 rows, not scored.
    for court in COURTS:
        rows.append(_docket(i, 2023, court, "850", "granted", opposition=False))
        i += 1
    return rows


def write_extract(path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in build_dockets():
            handle.write(json.dumps(row) + "\n")
    return path


if __name__ == "__main__":
    write_extract(Path(__file__).with_name("extract.jsonl"))
