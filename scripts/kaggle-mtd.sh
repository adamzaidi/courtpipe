#!/usr/bin/env bash
# Run the motion-to-dismiss fetch on Kaggle instead of this Mac.
#
#   scripts/kaggle-mtd.sh setup    # once: create the private state dataset
#   scripts/kaggle-mtd.sh start    # save the last run's output as the new state, then open the
#                                  # editor so you click Save Version to start the next run
#   scripts/kaggle-mtd.sh push     # upload new notebook code (only after kaggle/ or courtpipe changes)
#   scripts/kaggle-mtd.sh status   # is a run going, and what did the last one do
#   scripts/kaggle-mtd.sh pull     # download the last run's output without starting another
#
# Each Kaggle run fetches for 11 hours (about 33,000 requests at 3,000/hour), scores the
# extract, and leaves its state in its output. `start` downloads that output to
# $COURTPIPE_DATA (default ~/courtpipe-data, off iCloud) and uploads it as a new version of
# the private dataset zaidiadam/courtpipe-mtd-state.
#
# Runs are started from the browser (Save Version -> Save & Run All), not with
# `kaggle kernels push`: Kaggle gives secrets only to versions saved in the editor
# (confirmed 2026-11-20; pushed versions fail with HTTP 400 from UserSecretsClient).
# The notebook installs courtpipe from the head of its branch on GitHub at run time, so
# fetcher changes need only a git push. `push` is for changes to kaggle/mtd-fetch itself;
# reload the editor afterwards or Save Version fails with a ConcurrencyViolation.
#
# Needs KAGGLE_API_TOKEN in .env, the Kaggle CLI in $COURTPIPE_DATA/.kaggle-venv, and
# the CourtListener token stored once as a Kaggle Secret on the notebook (label
# COURTLISTENER_API_TOKEN). Everything on Kaggle is case-level data and stays private.
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

run_count() {  # completed runs recorded in a state file, 0 if absent
  [ -f "$1" ] && python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["runs"]))' "$1" || echo 0
}

open_editor() {
  echo "Start the next run in the browser: reload the editor, check Add-ons -> Secrets has"
  echo "COURTLISTENER_API_TOKEN checked, if the Input panel offers a newer version of"
  echo "courtpipe-mtd-state take it, then Save Version -> Save & Run All (Commit)."
  open "https://www.kaggle.com/code/$KERNEL/edit" 2>/dev/null || true
}

extract_lines() {  # dockets in a gzipped extract, 0 if absent
  [ -f "$1" ] && gzip -dc "$1" | wc -l | tr -d ' ' || echo 0
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
    status="$(kernel_status)"
    case "$status" in
      running|queued) echo "a run is still going ($status); wait for it to finish" >&2; exit 1 ;;
      none) echo "no notebook yet: run scripts/kaggle-mtd.sh push first" >&2; exit 1 ;;
      *)
        echo "last run: $status"
        dir="$(pull)"
        new="$dir/state"
        if [ ! -f "$new/mtd_fetch_state.json" ] || [ ! -f "$new/mtd_extract.jsonl.gz" ]; then
          echo "the last run left no state (see $dir); the dataset keeps the previous state" >&2
        else
          have="$(extract_lines "$DATA/state/mtd_extract.jsonl.gz")"
          got="$(extract_lines "$new/mtd_extract.jsonl.gz")"
          if [ "$got" -lt "$have" ]; then
            echo "the last run's extract has $got dockets but the saved state has $have; not overwriting. See $dir" >&2; exit 1
          fi
          runs_have="$(run_count "$DATA/state/mtd_fetch_state.json")"
          runs_got="$(run_count "$new/mtd_fetch_state.json")"
          # Nothing saved yet means nothing to protect (the 2026-11-20 run crashed before
          # recording itself; runs are now always recorded).
          if [ -f "$DATA/state/mtd_fetch_state.json" ] && [ "$runs_got" -le "$runs_have" ]; then
            echo "the last run started from an older state ($runs_got runs recorded, saved state has $runs_have)," >&2
            echo "probably a stale dataset version in the editor. Not overwriting. See $dir" >&2; exit 1
          fi
          cp "$new/mtd_fetch_state.json" "$new/mtd_extract.jsonl.gz" "$new/cache.tar.gz" "$DATA/state/"
          rm -f "$DATA/state/README.txt"
          echo "saving state: $have -> $got dockets"
          "$KAGGLE" datasets version -p "$DATA/state" -m "after run of $(date +%Y-%m-%d)" -r tar >/dev/null
          sleep 15
          wait_dataset_ready
        fi
        [ -f "$dir/results/run_summary.json" ] && cat "$dir/results/run_summary.json"
        backup
        ;;
    esac
    open_editor
    ;;

  push)
    status="$(kernel_status)"
    case "$status" in running|queued) echo "a run is going ($status); pushing would replace it" >&2; exit 1 ;; esac
    push_kernel
    ;;

  status)
    echo "notebook: $(kernel_status)"
    if [ -f "$DATA/state/mtd_extract.jsonl.gz" ]; then
      echo "saved state: $(extract_lines "$DATA/state/mtd_extract.jsonl.gz") dockets"
    fi
    last="$(ls -d "$DATA"/runs/*/ 2>/dev/null | tail -1)"
    [ -n "$last" ] && [ -f "$last/results/run_summary.json" ] && { echo "last pulled run ($last):"; cat "$last/results/run_summary.json"; }
    ;;

  pull)
    dir="$(pull)"; echo "downloaded to $dir"; ls "$dir"; backup
    ;;

  *)
    sed -n '2,16p' "$0"; exit 1
    ;;
esac
