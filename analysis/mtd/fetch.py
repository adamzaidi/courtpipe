"""Modest cached MTD extract from CourtListener. Token from the environment."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

from analysis.cl_client import BudgetExhausted, CourtListenerClient
from analysis.mtd.corporate import party_type_label
from analysis.mtd.features import nature_of_suit

logger = logging.getLogger("courtpipe.mtd.fetch")

NOS_CLAUSES = (
    'suitNature:160',
    'suitNature:410',
    'suitNature:480',
    'suitNature:"850 Securities/Commodities"',
)

# Docket filing-date eras. Search only lists candidate dockets; the cohort and the
# train/test split are still decided by motion dates read from docket entries.
# Two eras so the training and test sides fill at the same pace.
FILING_ERAS = (
    ("2014-01-01", "2019-12-31"),
    ("2020-01-01", "2023-12-31"),
)

CANDIDATE_PHRASE = '"motion to dismiss"'

CANDIDATE_QUERIES = tuple(
    f"{nos} AND dateFiled:[{lo} TO {hi}] AND {CANDIDATE_PHRASE}"
    for lo, hi in FILING_ERAS
    for nos in NOS_CLAUSES
)

# Kept for callers that import the old name.
NOS_QUERIES = NOS_CLAUSES

IN_SCOPE_NOS = {"160", "410", "480", "850"}

# A docket costs at least three requests: docket, entries, parties.
MIN_REQUESTS_PER_DOCKET = 3

SMOKE_DOCKET_ID = 70649963  # public search hit cited in the spec; no document body committed


def _party_row(raw: dict[str, Any]) -> dict[str, Any]:
    raw_types = raw.get("party_types")
    if raw_types is None:
        raw_types = raw.get("type") if "type" in raw else raw.get("party_type")
    if isinstance(raw_types, list):
        types = [party_type_label(item) for item in raw_types]
    elif raw_types is None:
        types = None
    else:
        types = [party_type_label(raw_types)]
    attorneys = []
    for item in raw.get("attorneys") or []:
        if isinstance(item, dict):
            attorneys.append(item.get("name") or item.get("attorney") or "")
        else:
            attorneys.append(str(item))
    return {
        "name": raw.get("name") or raw.get("party") or "",
        "party_types": types,
        "attorneys": attorneys,
    }


def _entry_row(raw: dict[str, Any]) -> dict[str, Any]:
    recap = raw.get("recap_documents") or []
    first = recap[0] if recap else {}
    attachments = []
    for doc in recap[1:]:
        attachments.append({"description": doc.get("description") or doc.get("short_description") or ""})
    return {
        "id": raw.get("id"),
        "document_number": raw.get("entry_number") or first.get("document_number"),
        "date_filed": raw.get("date_filed"),
        "time_filed": raw.get("time_filed"),
        "description": raw.get("description") or "",
        "short_description": first.get("short_description") or raw.get("description") or "",
        "is_available": first.get("is_available"),
        "page_count": first.get("page_count"),
        "plain_text": (first.get("plain_text") or "")[:8000],
        "attachments": attachments,
    }


def _docket_id_from_hit(hit: dict[str, Any]) -> Optional[int]:
    docket_id = hit.get("docket_id") or hit.get("docketId")
    if docket_id is None:
        match = re.search(r"/docket/(\d+)/", str(hit.get("absolute_url") or ""))
        docket_id = int(match.group(1)) if match else None
    return int(docket_id) if docket_id is not None else None


def _docket_row(client: CourtListenerClient, docket_id: int, hit: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Fetch one docket. Returns None when the docket is out of NOS scope."""
    docket = client.docket(docket_id)
    entries = client.docket_entries(docket_id)
    parties = client.parties(docket_id)
    court = docket.get("court") or hit.get("court_id") or ""
    if isinstance(court, str) and court.startswith("http"):
        court = court.rstrip("/").split("/")[-1]
    nos = nature_of_suit(docket.get("nature_of_suit") or hit.get("suitNature"))
    if nos not in IN_SCOPE_NOS:
        return None
    return {
        "docket_id": docket_id,
        "court_id": str(court).lower(),
        "suitNature": docket.get("nature_of_suit") or hit.get("suitNature"),
        "cause": docket.get("cause") or hit.get("cause"),
        "jurisdiction": docket.get("jurisdiction") or hit.get("jurisdictionType"),
        "juryDemand": docket.get("jury_demand") or hit.get("juryDemand"),
        "assigned_to_id": docket.get("assigned_to_id") or hit.get("assignedTo"),
        "dateFiled": docket.get("date_filed") or hit.get("dateFiled"),
        "parties_have_party_type": True,
        "parties": [_party_row(p) for p in parties],
        "entries": [_entry_row(e) for e in entries],
        "snapshot_date": None,
    }


def _load_state(state_path: Path) -> dict[str, Any]:
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
    else:
        state = {}
    state.setdefault("version", 1)
    state.setdefault("queries", {})
    state.setdefault("skipped", [])
    state.setdefault("runs", [])
    for query in CANDIDATE_QUERIES:
        state["queries"].setdefault(query, {"started": False, "next": None, "exhausted": False, "pending": []})
    return state


def _save_state(state_path: Path, state: dict[str, Any]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    tmp.replace(state_path)


def _extract_ids(out_path: Path) -> set[int]:
    ids: set[int] = set()
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                ids.add(int(json.loads(line)["docket_id"]))
    return ids


def _next_page(client: CourtListenerClient, query: str, qstate: dict[str, Any], page_size: int) -> list[dict[str, Any]]:
    if not qstate["started"]:
        payload = client.search(query, search_type="r", page_size=page_size)
        qstate["started"] = True
    else:
        payload = client.get_json(qstate["next"])
    qstate["next"] = payload.get("next")
    if not qstate["next"]:
        qstate["exhausted"] = True
    return payload.get("results") or []


def fetch_mtd_extract(
    out_path: Path,
    cache_dir: Path,
    max_dockets: int = 20,
    log=None,
    max_requests: Optional[int] = None,
    state_path: Optional[Path] = None,
    page_size: int = 20,
) -> Path:
    """Add up to ``max_dockets`` new candidate dockets to the extract. Requires a token.

    Resumable: search cursors and the queue of unvisited dockets live in
    ``state_path`` (default: ``<cache_dir>/../mtd_fetch_state.json``), and new
    dockets are appended to ``out_path``. Rotates across CANDIDATE_QUERIES so
    every case type and filing era fills at the same pace. Stops cleanly before
    ``max_requests`` network calls; cached responses are free, so a docket
    interrupted mid-fetch completes cheaply on the next run.
    """
    log = log or logger.info
    out_path = Path(out_path)
    cache_dir = Path(cache_dir)
    state_path = Path(state_path) if state_path else cache_dir.parent / "mtd_fetch_state.json"
    client = CourtListenerClient(cache_dir=cache_dir, require_token=True, max_requests=max_requests)
    state = _load_state(state_path)
    have = _extract_ids(out_path)
    skipped = set(state["skipped"])
    queued = {d for q in state["queries"].values() for d, _ in q["pending"]}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.touch()

    added = 0
    stop_reason = "max_dockets reached"
    turn = 0
    try:
        while added < max_dockets:
            active = [q for q in CANDIDATE_QUERIES if state["queries"][q]["pending"] or not state["queries"][q]["exhausted"]]
            if not active:
                stop_reason = "all candidate searches exhausted"
                break
            query = active[turn % len(active)]
            turn += 1
            qstate = state["queries"][query]
            if not qstate["pending"]:
                for hit in _next_page(client, query, qstate, page_size):
                    docket_id = _docket_id_from_hit(hit)
                    if docket_id is None or docket_id in have or docket_id in skipped or docket_id in queued:
                        continue
                    slim = {k: hit.get(k) for k in ("court_id", "suitNature", "cause", "jurisdictionType", "juryDemand", "assignedTo", "dateFiled")}
                    qstate["pending"].append([docket_id, slim])
                    queued.add(docket_id)
                _save_state(state_path, state)
                turn -= 1  # stay on this query so its new page yields a docket before rotating
                continue
            remaining = client.remaining()
            if remaining is not None and remaining < MIN_REQUESTS_PER_DOCKET:
                stop_reason = "request budget too low for another docket"
                break
            docket_id, hit = qstate["pending"][0]
            try:
                row = _docket_row(client, docket_id, hit)
            except BudgetExhausted:
                raise
            except Exception as exc:  # 404, malformed payload: skip this docket for good
                log("skip docket %s: %s", docket_id, exc)
                row = None
            qstate["pending"].pop(0)
            queued.discard(docket_id)
            if row is None:
                skipped.add(docket_id)
                state["skipped"].append(docket_id)
            else:
                with out_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(row) + "\n")
                have.add(docket_id)
                added += 1
            _save_state(state_path, state)
    except BudgetExhausted:
        stop_reason = "request budget used"

    run = {
        "requests": client.requests_made,
        "new_dockets": added,
        "total_dockets": len(have),
        "skipped_total": len(skipped),
        "queued": len(queued),
        "stop": stop_reason,
    }
    state["runs"].append(run)
    _save_state(state_path, state)
    log(
        "added %s dockets (%s total, %s queued) with %s requests; stopped: %s",
        added, len(have), len(queued), client.requests_made, stop_reason,
    )
    return out_path


def smoke_docket_entries(cache_dir: Path, docket_id: int = SMOKE_DOCKET_ID) -> dict[str, Any]:
    """One authenticated read. Does not train. Does not print a token."""
    client = CourtListenerClient(cache_dir=cache_dir, require_token=True)
    entries_payload = client.get_json(
        "https://www.courtlistener.com/api/rest/v4/docket-entries/",
        params={"docket": int(docket_id), "page_size": 5},
        use_cache=True,
    )
    results = entries_payload.get("results") or []
    if not results:
        raise RuntimeError("smoke docket returned no entries")
    first = results[0]
    if "description" not in first or "date_filed" not in first:
        raise RuntimeError("entry missing description or date_filed")
    recap = first.get("recap_documents") or []
    if recap and "is_available" not in recap[0]:
        raise RuntimeError("recap document missing is_available")
    parties_payload = client.get_json(
        "https://www.courtlistener.com/api/rest/v4/parties/",
        params={"docket": int(docket_id), "page_size": 5},
        use_cache=True,
    )
    party_keys = sorted((parties_payload.get("results") or [{}])[0].keys())
    return {
        "ok": True,
        "docket_id": int(docket_id),
        "n_entries_page": len(results),
        "party_keys": party_keys,
        "status": 200,
    }
