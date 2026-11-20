"""courtpipe motion-to-dismiss fetch, one Kaggle run.

Pushed by scripts/kaggle-mtd.sh, which pins COURTPIPE_REF to the commit it pushed
from. Reads the previous run's state from the private dataset
zaidiadam/courtpipe-mtd-state, fetches until the time limit, scores the extract,
and leaves the new state in /kaggle/working/state for the driver to pull.

Everything here is case-level data, so the notebook, its output and the dataset
must stay private. The CourtListener token comes from Kaggle Secrets
(label COURTLISTENER_API_TOKEN) and is never printed.
"""

import gzip
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tarfile

COURTPIPE_REF = "main"  # replaced with a commit SHA by scripts/kaggle-mtd.sh
FETCH_MINUTES = 660  # Kaggle kills a run at 12 hours; leave an hour to score and save
LIMITS = {"CL_MAX_PER_MINUTE": "50", "CL_MAX_PER_HOUR": "3000", "CL_MAX_PER_DAY": "1000000"}

INPUT = pathlib.Path("/kaggle/input")
WORK = pathlib.Path("/kaggle/working")
DATA = pathlib.Path("/tmp/courtpipe-data")  # scratch; only WORK/state and WORK/results are kept
CACHE = DATA / "cache" / "courtlistener"
STATE = DATA / "cache" / "mtd_fetch_state.json"
EXTRACT = DATA / "extracted" / "mtd_extract.jsonl"


def sh(*cmd, env=None):
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, env=env)


def find(name):
    hits = sorted(INPUT.glob(f"**/{name}"))
    return hits[0] if hits else None


def restore():
    """Copy the last saved state out of the read-only dataset. Kaggle may store an
    uploaded .gz/.tar either as uploaded or unpacked, so accept both forms."""
    CACHE.mkdir(parents=True, exist_ok=True)
    EXTRACT.parent.mkdir(parents=True, exist_ok=True)
    state = find("mtd_fetch_state.json")
    if state:
        shutil.copy(state, STATE)
    gz, plain = find("mtd_extract.jsonl.gz"), find("mtd_extract.jsonl")
    if gz:
        with gzip.open(gz, "rb") as src, EXTRACT.open("wb") as dst:
            shutil.copyfileobj(src, dst)
    elif plain:
        shutil.copy(plain, EXTRACT)
    tar = find("cache.tar.gz") or find("cache.tar")
    if tar:
        with tarfile.open(tar) as t:
            try:
                t.extractall(CACHE.parent, filter="data")
            except TypeError:  # Python without extraction filters; our own archive
                t.extractall(CACHE.parent)
    else:
        unpacked = next((p for p in INPUT.glob("**/courtlistener") if p.is_dir()), None)
        if unpacked:
            shutil.copytree(unpacked, CACHE, dirs_exist_ok=True)
    n = sum(1 for _ in EXTRACT.open()) if EXTRACT.exists() else 0
    print(f"restored: state={'yes' if state else 'no (first run)'}, dockets in extract={n}", flush=True)
    if not state and n:
        sys.exit("extract present without its state file; refusing to start over on top of it")


def save():
    out = WORK / "state"
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(STATE, out / "mtd_fetch_state.json")
    with EXTRACT.open("rb") as src, gzip.open(out / "mtd_extract.jsonl.gz", "wb", compresslevel=6) as dst:
        shutil.copyfileobj(src, dst)
    with tarfile.open(out / "cache.tar.gz", "w:gz") as t:
        t.add(CACHE, arcname="courtlistener")


def main():
    from kaggle_secrets import UserSecretsClient

    env = dict(os.environ, **LIMITS)
    env["COURTLISTENER_API_TOKEN"] = UserSecretsClient().get_secret("COURTLISTENER_API_TOKEN")

    sh(sys.executable, "-m", "pip", "install", "-q", "--no-deps",
       f"git+https://github.com/adamzaidi/courtpipe@{COURTPIPE_REF}")
    sh(sys.executable, "-m", "pip", "install", "-q", "python-dotenv")

    restore()
    os.chdir(DATA)  # courtpipe writes run logs under ./runs; keep them out of the output
    try:
        sh("courtpipe", "fetch-mtd", "--max-dockets", "1000000", "--text-chars", "0",
           "--max-minutes", str(FETCH_MINUTES), "--cache", str(CACHE),
           "--state", str(STATE), "--out", str(EXTRACT), env=env)
    finally:
        if STATE.exists():
            save()  # whatever was fetched is kept even if the fetch step failed

    results = WORK / "results"
    results.mkdir(exist_ok=True)
    scored = subprocess.run(
        ["courtpipe", "evaluate-mtd", "--extract", str(EXTRACT),
         "--report", str(results / "mtd_report.json"), "--results-md", str(results / "RESULTS.md")],
        env=env,
    )
    last = json.loads(STATE.read_text())["runs"][-1]
    last["scored"] = scored.returncode == 0
    (results / "run_summary.json").write_text(json.dumps(last, indent=1))
    print(json.dumps(last, indent=1))


if __name__ == "__main__":
    main()
