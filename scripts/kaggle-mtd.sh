#!/usr/bin/env bash
# Run the motion-to-dismiss fetch on Kaggle instead of this Mac.
#
#   scripts/kaggle-mtd.sh setup    # once: create the private state dataset
#   scripts/kaggle-mtd.sh start    # save the last run's output as the new state, start the next run
#   scripts/kaggle-mtd.sh status   # is a run going, and what did the last one do
#   scripts/kaggle-mtd.sh pull     # download the last run's output without starting another
#
# Each Kaggle run fetches for 11 hours (about 33,000 requests at 3,000/hour), scores the
# extract, and leaves its state in its output. `start` downloads that output to
# $COURTPIPE_DATA (default ~/courtpipe-data, off iCloud), uploads it as a new version of
# the private dataset zaidiadam/courtpipe-mtd-state, then pushes the notebook pinned to
# this repo's current commit. Your Mac only needs to be on for those few minutes.
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
  if [ -n "$(git -C "$REPO" status --porcelain -- kaggle analysis courtpipe)" ]; then
    echo "uncommitted changes in kaggle/, analysis/ or courtpipe/; commit and push first" >&2; exit 1
  fi
  local sha; sha="$(git -C "$REPO" rev-parse HEAD)"
  if ! git -C "$REPO" branch -r --contains "$sha" | grep -q .; then
    echo "commit $sha is not on GitHub yet; the notebook installs courtpipe from there. git push first" >&2; exit 1
  fi
  local tmp; tmp="$(mktemp -d)"
  cp "$REPO/kaggle/mtd-fetch/kernel-metadata.json" "$tmp/"
  sed "s/^COURTPIPE_REF = \"main\"/COURTPIPE_REF = \"$sha\"/" "$REPO/kaggle/mtd-fetch/run.py" > "$tmp/run.py"
  grep -q "COURTPIPE_REF = \"$sha\"" "$tmp/run.py" || { echo "could not pin COURTPIPE_REF" >&2; exit 1; }
  "$KAGGLE" kernels push -p "$tmp"
  rm -rf "$tmp"
  echo "started $KERNEL at courtpipe ${sha:0:7}; it runs about 12 hours. Check with: scripts/kaggle-mtd.sh status"
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
      none) echo "first run: starting from the empty state" ;;
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
