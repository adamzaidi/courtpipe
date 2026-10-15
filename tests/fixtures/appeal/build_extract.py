"""Build the synthetic appeal extract. Invented captions. Not an affirmance rate."""

from __future__ import annotations

import json
from pathlib import Path

CIRCUITS = ["ca2", "ca9", "ca5", "cadc"]
TYPES = ["securities", "prisoner", "other private civil", "contract"]


def _row(i: int, year: int, circuit: str, case_type: str, fine: str, argued: bool) -> dict:
    appeal_filed = f"{year - 1}-03-01"
    argued_on = f"{year}-01-15" if argued else None
    decided = f"{year}-06-15"
    judgment = f"{year - 2}-11-01"
    dispositions = {
        "affirmed": "The judgment of the district court is affirmed.",
        "reversed": "Reversed and remanded.",
        "vacated": "Vacated and remanded.",
        "remanded": "Remanded.",
        "mixed": "Affirmed in part, reversed in part, and remanded.",
        "affirmed_with_remand": "Affirmed and remanded.",
        "dismissed": "Appeal dismissed.",
        "coa": "Certificate of appealability denied.",
    }
    district = {"ca2": "nysd", "ca9": "cand", "ca5": "txsd", "cadc": "dcd"}[circuit]
    district_text = (
        "The district court granted summary judgment after a bench finding. "
        "The opinion discusses the record at length."
        if case_type != "prisoner"
        else "The district court dismissed the petition."
    )
    return {
        "cluster_id": 9000 + i,
        "docket_id": 5000 + i,
        "parent_docket_id": None,
        "court_id": circuit,
        "date_filed": decided,
        "date_argued": argued_on,
        "appeal_date_filed": appeal_filed,
        "disposition": dispositions[fine],
        "decretal_excerpt": "",
        "case_name": f"Synthetic {circuit.upper()} {i} v. United Widget Corp",
        "nature_of_suit": case_type,
        "appeal_from_id": district,
        "appeal_from_jurisdiction": "FD",
        "assigned_to_id": f"dj-{district}",
        "originating_date_judgment": judgment,
        "district_opinion_date": judgment,
        "district_opinion_page_count": 12 + (i % 10),
        "district_opinion_plain_text": district_text,
        "district_disposition": "summary judgment granted" if case_type != "prisoner" else "dismissed",
        "district_citation_count": i % 5,
        "appellant_class": "unknown",
        "argument_judges": ["A", "B", "C"] if argued else [],
        "precedential_status": "Published",
    }


def build_clusters() -> list[dict]:
    rows = []
    i = 1
    # Train through 2021 (snapshot year 2025 => train before 2022).
    for year in (2018, 2019, 2020, 2021):
        for circuit in CIRCUITS:
            case_type = TYPES[(i - 1) % 4]
            argued = circuit in {"ca9", "cadc"}
            # ca9/cadc disturb more; prisoner less.
            if case_type == "prisoner":
                fine = "affirmed" if i % 5 else "reversed"
            elif circuit in {"ca9", "cadc"}:
                fine = "reversed" if i % 2 else "mixed"
            else:
                fine = "affirmed" if i % 3 else "vacated"
            rows.append(_row(i, year, circuit, case_type, fine, argued))
            i += 1
    # Test 2022-2024
    for year in (2022, 2023, 2024):
        for circuit in CIRCUITS:
            case_type = TYPES[(i - 1) % 4]
            argued = circuit in {"ca9", "cadc"}
            if case_type == "prisoner":
                fine = "affirmed" if i % 5 else "remanded"
            elif circuit in {"ca9", "cadc"}:
                fine = "reversed" if i % 2 else "mixed"
            else:
                fine = "affirmed" if i % 3 else "vacated"
            rows.append(_row(i, year, circuit, case_type, fine, argued))
            i += 1
    # Quarantine 2025
    for circuit in CIRCUITS:
        rows.append(_row(i, 2025, circuit, "securities", "affirmed", True))
        i += 1
    # Excluded labels, counted in funnel if they pass other filters: add a few dismissed
    rows.append(_row(i, 2020, "ca2", "contract", "dismissed", False))
    i += 1
    rows.append(_row(i, 2020, "ca2", "contract", "affirmed_with_remand", False))
    return rows


def write_extract(path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in build_clusters():
            handle.write(json.dumps(row) + "\n")
    return path


if __name__ == "__main__":
    write_extract(Path(__file__).with_name("extract.jsonl"))
