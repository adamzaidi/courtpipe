#!/usr/bin/env bash
# The motion-to-dismiss fetch runs on Kaggle by itself (since 2026-11-21). This script
# is optional: it is for setup, code pushes, and local copies.
#
#   scripts/kaggle-mtd.sh setup    # once: create the private state dataset
#   scripts/kaggle-mtd.sh status   # is a run going, and what did the last one do
#   scripts/kaggle-mtd.sh pull     # download the current state and the last run's results
#   scripts/kaggle-mtd.sh ingest   # one-time: save an old-style run's output as the next dataset version
#   scripts/kaggle-mtd.sh push     # upload changes to kaggle/mtd-fetch/ (not needed for
#                                  # courtpipe code: the notebook installs the branch head)
#
# How it runs: Kaggle's scheduler starts the private notebook zaidiadam/courtpipe-mtd-fetch.
# Each run downloads the latest version of the private dataset zaidiadam/courtpipe-mtd-state,
# fetches for 11 hours at 3,000 requests/hour, scores the extract, and uploads its state as
# the next dataset version, refusing if another run saved first. Once every search and
# queue is empty, runs only re-score. Secrets on the notebook: COURTLISTENER_API_TOKEN and
# KAGGLE_API_TOKEN. Kaggle gives secrets only to browser-saved and scheduled versions, so a
# version pushed with `push` fails on the secret; reload the editor and Save Version after
# a push. Everything on Kaggle is case-level data and stays private. Local copies go to
# $COURTPIPE_DATA (default ~/courtpipe-data), with a backup to AZ when it is mounted.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DATA="${COURTPIPE_DATA:-$HOME/courtpipe-data}"
KAGGLE="$DATA/.kaggle-venv/bin/kaggle"
KERNEL="zaidiadam/courtpipe-mtd-fetch"
DATASET="zaidiadam/courtpipe-mtd-state"
BACKUP="/Volumes/AZ/courtpipe-data"

[ -f "$REPO/.env" ] && { set -a; . "$REPO/.env"; set +a; }
[ -n "${KAGGLE_API_TOKEN:-}" ] || { echo "KAGGLE_API_TOKEN is not set (.env)" >&2; exit 1; }
[ -x "$KAGGLE" ] || { echo "Kaggle CLI missing: python3 -m venv $DATA/.kaggle-venv && $DATA/.kaggle-venv/bin/pip install kaggle==2.2.5 six" >&2; exit 1; }

kernel_status() {  # prints running / queued / complete / error / cancel... / none
  local out
  out="$("$KAGGLE" kernels status "$KERNEL" 2>&1)" || { echo none; return; }
  echo "$out" | sed -n 's/.*"\(.*\)".*/\1/p' | tr 'A-Z' 'a-z' | sed 's/kernelworkerstatus\.//' | tail -1
}

run_count() {  # runs recorded in a state file, 0 if absent
  [ -f "$1" ] && python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["runs"]))' "$1" || echo 0
}

docket_count() {  # dockets in the local state copy (Kaggle may store the extract unpacked)
  local f
  for f in "$DATA/state/mtd_extract.jsonl" "$DATA/state/mtd_extract.jsonl.gz"; do
    [ -f "$f" ] && { gzip -dcf "$f" | wc -l | tr -d ' '; return; }
  done
  echo 0
}

backup() {
  if [ -d /Volumes/AZ ]; then
    mkdir -p "$BACKUP" && rsync -a --exclude .kaggle-venv "$DATA/" "$BACKUP/" && echo "backed up to $BACKUP"
  fi
}

pull() {  # download the last run's output into $DATA/runs/<time>; prints that directory
  local dir="$DATA/runs/$(date +%Y-%m-%d_%H%M%S)"
  mkdir -p "$dir"
  "$KAGGLE" kernels output "$KERNEL" -p "$dir" >/dev/null
  echo "$dir"
}

wait_dataset_ready() {
  for _ in $(seq 1 60); do
    if "$KAGGLE" datasets status "$DATASET" 2>/dev/null | grep -qi ready; then return 0; fi
    sleep 10
  done
  echo "dataset $DATASET not ready after 10 minutes" >&2; return 1
}

push_kernel() {
  if [ -n "$(git -C "$REPO" status --porcelain -- kaggle)" ]; then
    echo "uncommitted changes in kaggle/; commit first" >&2; exit 1
  fi
  "$KAGGLE" kernels push -p "$REPO/kaggle/mtd-fetch"
  echo "pushed $KERNEL code. This run will fail on the secret; that is expected."
  echo "Reload the editor before saving a version from it."
}

case "${1:-}" in
  setup)
    if "$KAGGLE" datasets status "$DATASET" >/dev/null 2>&1; then echo "$DATASET already exists"; exit 0; fi
    mkdir -p "$DATA/state"
    [ -n "$(ls -A "$DATA/state" 2>/dev/null)" ] || echo "Empty starting state for courtpipe's MTD fetch. Private: case-level data." > "$DATA/state/README.txt"
    cat > "$DATA/state/dataset-metadata.json" <<EOF
{"title": "courtpipe mtd state", "id": "$DATASET", "licenses": [{"name": "unknown"}]}
EOF
    "$KAGGLE" datasets create -p "$DATA/state" -r tar   # private unless --public is passed
    wait_dataset_ready
    echo "created $DATASET (private). Next: scripts/kaggle-mtd.sh start"
    ;;

  start)
    echo "Runs are scheduled on Kaggle and save their own state; nothing to start by hand."
    echo "To run one now: open the notebook editor and Save Version -> Save & Run All."
    echo "Use 'pull' for a local copy."
    ;;

  ingest)
    # One-time bridge (2026-11-21): runs started before the self-saving notebook leave
    # their state only in the notebook output. Save that output as the next dataset
    # version, if it extends the dataset's current state.
    status="$(kernel_status)"
    case "$status" in running|queued) echo "a run is still going ($status)" >&2; exit 1 ;; esac
    dir="$(pull)"; new="$dir/state"
    [ -f "$new/mtd_fetch_state.json" ] || { echo "the last run left no state in its output ($dir)" >&2; exit 1; }
    cur="$(mktemp -d)"
    "$KAGGLE" datasets download "$DATASET" -f mtd_fetch_state.json -p "$cur" -o >/dev/null
    for z in "$cur"/*.zip; do [ -f "$z" ] && unzip -oq "$z" -d "$cur"; done
    have="$(run_count "$cur/mtd_fetch_state.json")"; got="$(run_count "$new/mtd_fetch_state.json")"
    rm -rf "$cur"
    if [ "$got" -le "$have" ]; then
      echo "the last run's state ($got runs) does not extend the dataset's ($have runs); nothing to do" >&2; exit 1
    fi
    printf '{"title": "courtpipe mtd state", "id": "%s", "licenses": [{"name": "unknown"}]}\n' "$DATASET" > "$new/dataset-metadata.json"
    "$KAGGLE" datasets version -p "$new" -m "ingest of run output $(date +%Y-%m-%d)" >/dev/null 2>&1
    wait_dataset_ready
    echo "saved the last run's state as the next dataset version ($have -> $got runs)"
    backup
    ;;

  push)
    status="$(kernel_status)"
    case "$status" in running|queued) echo "a run is going ($status); pushing would replace it" >&2; exit 1 ;; esac
    push_kernel
    ;;

  status)
    echo "notebook: $(kernel_status)"
    "$KAGGLE" datasets status "$DATASET" >/dev/null 2>&1 && echo "dataset $DATASET: $("$KAGGLE" datasets status "$DATASET")"
    echo "local copy: $(docket_count) dockets (refresh with pull)"
    last="$(ls -d "$DATA"/runs/*/ 2>/dev/null | tail -1)"
    [ -n "$last" ] && [ -f "$last/results/run_summary.json" ] && { echo "last pulled run ($last):"; cat "$last/results/run_summary.json"; }
    ;;

  pull)
    # The dataset is the source of truth; the notebook output only holds the last run.
    mkdir -p "$DATA/state"
    "$KAGGLE" datasets download "$DATASET" -p "$DATA/state" --unzip -o >/dev/null
    dir="$(pull)"
    echo "state: $(ls "$DATA/state" | wc -l | tr -d ' ') files in $DATA/state; last run's output in $dir"
    [ -f "$dir/results/run_summary.json" ] && cat "$dir/results/run_summary.json"
    backup
    ;;

  *)
    sed -n '2,16p' "$0"; exit 1
    ;;
esac
