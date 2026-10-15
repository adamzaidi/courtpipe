"""Modest cached appeal extract. Bulk snapshot is the v1 corpus path.

Paging thirteen circuits through the REST API would exceed the default
rate limit. This module offers a small documented pull the owner runs
locally, plus a one-cluster smoke read.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from analysis.cl_client import CourtListenerClient
from analysis.district_circuit import APPELLATE_COURTS

logger = logging.getLogger("courtpipe.appeal.fetch")

# Public cluster used only for the authenticated smoke read. No opinion body is committed.
SMOKE_CLUSTER_ID = 11116544


def fetch_appeal_extract(
    out_path: Path,
    cache_dir: Path,
    max_clusters: int = 20,
    log=None,
) -> Path:
    """Small search pull of appellate opinions. Requires a token for cluster detail.

    Search hits do not include `disposition`. The optional cluster GET is how
    that field is filled when a token exists. Caps and caching keep the pull
    inside the documented rate limits.
    """
    log = log or logger.info
    client = CourtListenerClient(cache_dir=cache_dir, require_token=True)
    rows: list[dict[str, Any]] = []
    per = max(1, max_clusters // len(APPELLATE_COURTS[:4]))
    for court in APPELLATE_COURTS[:4]:
        if len(rows) >= max_clusters:
            break
        payload = client.search(f"court_id:{court}", search_type="o", page_size=min(10, per))
        for hit in payload.get("results") or []:
            if len(rows) >= max_clusters:
                break
            cluster_id = hit.get("cluster_id") or hit.get("id")
            if cluster_id is None:
                continue
            try:
                cluster = client.cluster(int(cluster_id))
            except Exception as exc:
                log("skip cluster %s: %s", cluster_id, exc)
                continue
            docket = cluster.get("docket") or {}
            if isinstance(docket, str):
                docket_id = docket.rstrip("/").split("/")[-1]
                docket = {"id": docket_id}
            originating = cluster.get("docket") if isinstance(cluster.get("docket"), dict) else {}
            snippet = ""
            opinions = hit.get("opinions") or []
            if opinions and isinstance(opinions[0], dict):
                snippet = str(opinions[0].get("snippet") or "")
            rows.append(
                {
                    "cluster_id": int(cluster_id),
                    "docket_id": docket.get("id") or hit.get("docket_id"),
                    "court_id": str(hit.get("court_id") or cluster.get("court_id") or court).lower(),
                    "date_filed": cluster.get("date_filed") or hit.get("dateFiled"),
                    "date_argued": docket.get("date_argued") or hit.get("dateArgued"),
                    "appeal_date_filed": docket.get("date_filed"),
                    "disposition": cluster.get("disposition") or "",
                    "decretal_excerpt": snippet[-1500:],
                    "case_name": cluster.get("case_name") or hit.get("caseName") or "",
                    "nature_of_suit": docket.get("nature_of_suit") or hit.get("suitNature") or "",
                    "appeal_from_id": str(
                        docket.get("appeal_from_id") or hit.get("appealFromId") or ""
                    ).lower(),
                    "appeal_from_jurisdiction": str(
                        docket.get("appeal_from_jurisdiction")
                        or hit.get("appealFromJurisdiction")
                        or "FD"
                    ),
                    "assigned_to_id": originating.get("assigned_to_id") if isinstance(originating, dict) else None,
                    "originating_date_judgment": None,
                    "district_opinion_plain_text": "",
                    "district_disposition": "",
                    "appellant_class": "unknown",
                    "argument_judges": hit.get("panel_ids") or [],
                    "precedential_status": cluster.get("precedential_status") or hit.get("status"),
                }
            )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    log("wrote %s clusters to %s", len(rows), out_path)
    return out_path


def smoke_cluster(cache_dir: Path, cluster_id: int = SMOKE_CLUSTER_ID) -> dict[str, Any]:
    client = CourtListenerClient(cache_dir=cache_dir, require_token=True)
    payload = client.cluster(int(cluster_id))
    if "date_filed" not in payload:
        raise RuntimeError("cluster missing date_filed")
    return {"ok": True, "cluster_id": int(cluster_id), "has_date_filed": True, "keys": sorted(payload.keys())[:20]}
