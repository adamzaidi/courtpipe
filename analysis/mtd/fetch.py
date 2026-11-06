"""Modest cached MTD extract from CourtListener. Token from the environment."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

import requests

from analysis.cl_client import BudgetExhausted, CourtListenerClient, DocketCapReached, RateLimited
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

# Network requests a new docket may use in one run before it moves to the large-docket
# queue (docket + parties + up to thirteen 100-entry pages). Nothing is dropped: a large
# docket resumes on later runs and its already-fetched pages come from the cache for free.
# Raised from 5 on 2026-11-06 once the EDU limits gave each run ~2,200 requests: at 5,
# about three in four new dockets were being queued.
NEW_DOCKET_ALLOWANCE = 15

# Share of a run's budget reserved for continuing large dockets. Unused reserve goes
# to new dockets. Raised from 0.3 on 2026-11-06 so the queue drains instead of growing.
LARGE_SHARE = 0.5

# Timeouts, connection errors and 5xx get this many attempts across runs before the
# docket is skipped. A 404/410 is skipped at once.
MAX_TRANSIENT_ATTEMPTS = 3

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


def _docket_row(
    client: CourtListenerClient, docket_id: int, hit: dict[str, Any], large: bool = False
) -> Optional[dict[str, Any]]:
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
        # True when the docket needed more than one run's allowance. Used for the
        # large-docket bias check in the evaluation report.
        "fetch_large": bool(large),
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
    state.setdefault("large", [])
    state.setdefault("attempts", {})
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


def _try_docket(
    client: CourtListenerClient, docket_id: int, hit: dict[str, Any], cap: Optional[int], large: bool
) -> tuple[str, Optional[dict[str, Any]], str]:
    """Fetch one docket under a per-docket request cap.

    Returns (status, row, detail) with status one of: done, out_of_scope, capped,
    transient, gone. BudgetExhausted (including RateLimited) propagates and ends the run.
    """
    client.docket_cap = None if cap is None else client.requests_made + cap
    client.track_cache()
    try:
        row = _docket_row(client, docket_id, hit, large=large)
        return ("out_of_scope", None, "") if row is None else ("done", row, "")
    except DocketCapReached:
        return "capped", None, ""
    except BudgetExhausted:
        raise
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        if status in (404, 410):
            return "gone", None, f"HTTP {status}"
        return "transient", None, f"HTTP {status}"
    except (requests.Timeout, requests.ConnectionError) as exc:
        return "transient", None, type(exc).__name__
    except (ValueError, KeyError, TypeError) as exc:  # malformed payload
        return "gone", None, f"malformed: {exc}"
    finally:
        client.docket_cap = None


def fetch_mtd_extract(
    out_path: Path,
    cache_dir: Path,
    max_dockets: int = 20,
    log=None,
    max_requests: Optional[int] = None,
    state_path: Optional[Path] = None,
    page_size: int = 20,
) -> Path:
    """Add up to ``max_dockets`` completed dockets to the extract. Requires a token.

    Resumable: search cursors, the queue of unvisited dockets, and the large-docket
    queue live in ``state_path`` (default ``<cache_dir>/../mtd_fetch_state.json``).
    Completed dockets are appended to ``out_path``.

    Each run first continues large dockets with up to LARGE_SHARE of the budget, then
    rotates across CANDIDATE_QUERIES for new dockets. A new docket that needs more than
    NEW_DOCKET_ALLOWANCE requests moves to the large queue instead of being truncated,
    so long cases are delayed, never dropped. The run stops cleanly before
    ``max_requests`` network calls or on repeated 429s.
    """
    log = log or logger.info
    out_path = Path(out_path)
    cache_dir = Path(cache_dir)
    state_path = Path(state_path) if state_path else cache_dir.parent / "mtd_fetch_state.json"
    client = CourtListenerClient(cache_dir=cache_dir, require_token=True, max_requests=max_requests)
    state = _load_state(state_path)
    have = _extract_ids(out_path)
    skipped = set(state["skipped"])
    queued = {d for q in state["queries"].values() for d, _ in q["pending"]} | {d for d, _ in state["large"]}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.touch()

    counts = {"added": 0, "added_large": 0, "moved_to_large": 0, "transient": 0, "cache_bytes_freed": 0}

    def settle_cache(status: str) -> None:
        """A finished or skipped docket's raw pages are redundant once its outcome is
        recorded: the extract row holds everything the pipeline reads. Capped and
        transient dockets keep theirs so they resume from cache. Call after the state
        that records the outcome is saved, so a crash in between costs a refetch,
        never a lost docket."""
        if status in ("done", "out_of_scope", "gone"):
            counts["cache_bytes_freed"] += client.drop_tracked_cache()
        else:
            client.stop_tracking_cache()

    def write_row(row: dict[str, Any]) -> None:
        with out_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
        have.add(int(row["docket_id"]))

    def skip(docket_id: int, detail: str) -> None:
        if detail:
            log("skip docket %s: %s", docket_id, detail)
        skipped.add(docket_id)
        state["skipped"].append(docket_id)
        state["attempts"].pop(str(docket_id), None)
        queued.discard(docket_id)

    def transient(docket_id: int, detail: str) -> bool:
        """Record a transient failure. True if the docket should stay queued."""
        counts["transient"] += 1
        key = str(docket_id)
        state["attempts"][key] = state["attempts"].get(key, 0) + 1
        if state["attempts"][key] >= MAX_TRANSIENT_ATTEMPTS:
            skip(docket_id, f"{detail}; gave up after {MAX_TRANSIENT_ATTEMPTS} attempts")
            return False
        log("retry later docket %s: %s", docket_id, detail)
        return True

    stop_reason = "max_dockets reached"
    try:
        # Phase 1: continue large dockets within the reserve.
        reserve_end = None if max_requests is None else client.requests_made + int(max_requests * LARGE_SHARE)
        tried: set[int] = set()
        while state["large"] and counts["added"] < max_dockets:
            if reserve_end is not None and client.requests_made >= reserve_end:
                break
            docket_id, hit = state["large"][0]
            if docket_id in tried:  # every large docket already attempted this run
                break
            tried.add(docket_id)
            cap = None if reserve_end is None else reserve_end - client.requests_made
            status, row, detail = _try_docket(client, docket_id, hit, cap, large=True)
            if status == "capped":
                client.stop_tracking_cache()
                break  # reserve used; the docket keeps its place at the front
            state["large"].pop(0)
            if status == "done":
                write_row(row)
                queued.discard(docket_id)
                state["attempts"].pop(str(docket_id), None)
                counts["added"] += 1
                counts["added_large"] += 1
            elif status == "transient" and transient(docket_id, detail):
                state["large"].append([docket_id, hit])
            elif status in ("gone", "out_of_scope"):
                skip(docket_id, detail)
            _save_state(state_path, state)
            settle_cache(status)

        # Phase 2: new dockets, rotating across the candidate searches.
        turn = 0
        while counts["added"] < max_dockets:
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
            # Peek, then pop only once there is an outcome: if the run ends mid-docket
            # (budget or 429), the docket keeps its place and resumes from the cache.
            status, row, detail = _try_docket(client, docket_id, hit, NEW_DOCKET_ALLOWANCE, large=False)
            qstate["pending"].pop(0)
            if status == "done":
                write_row(row)
                queued.discard(docket_id)
                state["attempts"].pop(str(docket_id), None)
                counts["added"] += 1
            elif status == "capped":
                state["large"].append([docket_id, hit])
                counts["moved_to_large"] += 1
            elif status == "transient":
                if transient(docket_id, detail):
                    qstate["pending"].append([docket_id, hit])
            else:
                skip(docket_id, detail)
            _save_state(state_path, state)
            settle_cache(status)
    except RateLimited:
        stop_reason = "rate limited (429)"
    except BudgetExhausted:
        stop_reason = "request budget used"

    run = {
        "requests": client.requests_made,
        "new_dockets": counts["added"],
        "completed_large": counts["added_large"],
        "moved_to_large": counts["moved_to_large"],
        "transient_failures": counts["transient"],
        "total_dockets": len(have),
        "large_queue": len(state["large"]),
        "skipped_total": len(skipped),
        "queued": len(queued),
        "cache_mb_freed": round(counts["cache_bytes_freed"] / 1_048_576, 1),
        "stop": stop_reason,
    }
    state["runs"].append(run)
    _save_state(state_path, state)
    log(
        "added %s dockets (%s from the large queue; %s total), %s moved to the large queue "
        "(%s waiting), %s requests, %.1f MB of finished-docket cache freed; stopped: %s",
        counts["added"], counts["added_large"], len(have), counts["moved_to_large"],
        len(state["large"]), client.requests_made, run["cache_mb_freed"], stop_reason,
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
