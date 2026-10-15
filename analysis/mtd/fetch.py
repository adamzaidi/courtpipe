"""Modest cached MTD extract from CourtListener. Token from the environment."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from analysis.cl_client import CourtListenerClient
from analysis.mtd.corporate import party_type_label
from analysis.mtd.features import nature_of_suit

logger = logging.getLogger("courtpipe.mtd.fetch")

NOS_QUERIES = (
    'suitNature:160',
    'suitNature:410',
    'suitNature:480',
    'suitNature:"850 Securities/Commodities"',
)

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


def fetch_mtd_extract(
    out_path: Path,
    cache_dir: Path,
    max_dockets: int = 20,
    log=None,
) -> Path:
    """Walk a small set of RECAP dockets. Requires a token. Caches HTTP."""
    log = log or logger.info
    client = CourtListenerClient(cache_dir=cache_dir, require_token=True)
    seen: set[int] = set()
    dockets: list[dict[str, Any]] = []
    per_query = max(1, max_dockets // len(NOS_QUERIES))
    for query in NOS_QUERIES:
        if len(dockets) >= max_dockets:
            break
        remaining = max_dockets - len(dockets)
        page_size = min(20, max(per_query, remaining))
        log("search %s (page_size=%s)", query, page_size)
        payload = client.search(query, search_type="r", page_size=page_size)
        for hit in payload.get("results") or []:
            if len(dockets) >= max_dockets:
                break
            docket_id = hit.get("docket_id") or hit.get("docketId")
            if docket_id is None:
                absolute = str(hit.get("absolute_url") or "")
                match = re.search(r"/docket/(\d+)/", absolute)
                docket_id = int(match.group(1)) if match else None
            if docket_id is None:
                continue
            docket_id = int(docket_id)
            if docket_id in seen:
                continue
            seen.add(docket_id)
            try:
                docket = client.docket(docket_id)
                entries = client.docket_entries(docket_id)
                parties = client.parties(docket_id)
            except Exception as exc:
                log("skip docket %s: %s", docket_id, exc)
                continue
            court = docket.get("court") or hit.get("court_id") or ""
            if isinstance(court, str) and court.startswith("http"):
                court = court.rstrip("/").split("/")[-1]
            nos = nature_of_suit(docket.get("nature_of_suit") or hit.get("suitNature"))
            if nos not in {"160", "410", "480", "850"}:
                continue
            dockets.append(
                {
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
            )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        for row in dockets:
            handle.write(json.dumps(row) + "\n")
    log("wrote %s dockets to %s", len(dockets), out_path)
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
