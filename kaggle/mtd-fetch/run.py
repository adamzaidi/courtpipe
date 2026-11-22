"""courtpipe motion-to-dismiss fetch: one scheduled Kaggle run, no human in the loop.

Kaggle's scheduler starts this notebook (secrets are only given to browser-saved and
scheduled versions, not to `kaggle kernels push`). Each run:

1. installs courtpipe from the head of COURTPIPE_BRANCH and records the commit;
2. downloads the latest version of the private dataset zaidiadam/courtpipe-mtd-state
   with the Kaggle API (the attached input can be a stale version on scheduled runs);
3. fetches for up to FETCH_MINUTES, or skips fetching once the cohort is complete;
4. scores the extract and writes aggregate results and the progress page (counts only);
5. checks that nobody saved a newer state meanwhile, then uploads the new state as the
   next dataset version.

Everything here is case-level data, so the notebook, its output and the dataset stay
private. Secrets (labels): COURTLISTENER_API_TOKEN, KAGGLE_API_TOKEN. Never printed.
"""

import datetime as dt
import gzip
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tarfile

REPO_URL = "https://github.com/adamzaidi/courtpipe"
COURTPIPE_BRANCH = "kaggle-fetch"  # switch to "main" once the branch is merged
DATASET = "zaidiadam/courtpipe-mtd-state"
FETCH_MINUTES = 660  # Kaggle kills a run at 12 hours; leave an hour to score and save
LIMITS = {"CL_MAX_PER_MINUTE": "50", "CL_MAX_PER_HOUR": "3000", "CL_MAX_PER_DAY": "1000000"}

WORK = pathlib.Path("/kaggle/working")
DOWNLOAD = pathlib.Path("/tmp/state-in")
DATA = pathlib.Path("/tmp/courtpipe-data")  # scratch; only WORK/state and WORK/results are kept
CACHE = DATA / "cache" / "courtlistener"
STATE = DATA / "cache" / "mtd_fetch_state.json"
EXTRACT = DATA / "extracted" / "mtd_extract.jsonl"


def sh(*cmd, env=None, **kw):
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=True, env=env, **kw)


def find(root, name):
    hits = sorted(pathlib.Path(root).glob(f"**/{name}"))
    return hits[0] if hits else None


def run_count(path):
    return len(json.loads(pathlib.Path(path).read_text())["runs"]) if path and pathlib.Path(path).exists() else 0


def download_state(env):
    shutil.rmtree(DOWNLOAD, ignore_errors=True)
    DOWNLOAD.mkdir(parents=True)
    sh("kaggle", "datasets", "download", DATASET, "-p", str(DOWNLOAD), "--unzip", "-o", env=env,
       stdout=subprocess.DEVNULL)


def restore():
    """Unpack the downloaded state. Kaggle unpacks uploaded .gz/.tar files, so accept
    both the packed and the unpacked forms."""
    CACHE.mkdir(parents=True, exist_ok=True)
    EXTRACT.parent.mkdir(parents=True, exist_ok=True)
    state = find(DOWNLOAD, "mtd_fetch_state.json")
    if state:
        shutil.copy(state, STATE)
    gz, plain = find(DOWNLOAD, "mtd_extract.jsonl.gz"), find(DOWNLOAD, "mtd_extract.jsonl")
    if gz:
        with gzip.open(gz, "rb") as src, EXTRACT.open("wb") as dst:
            shutil.copyfileobj(src, dst)
    elif plain:
        shutil.copy(plain, EXTRACT)
    tar = find(DOWNLOAD, "cache.tar.gz") or find(DOWNLOAD, "cache.tar")
    if tar:
        with tarfile.open(tar) as t:
            t.extractall(CACHE.parent, filter="data")
    else:
        unpacked = next((p for p in DOWNLOAD.glob("**/courtlistener") if p.is_dir()), None)
        if unpacked:
            shutil.copytree(unpacked, CACHE, dirs_exist_ok=True)
    n = sum(1 for _ in EXTRACT.open()) if EXTRACT.exists() else 0
    print(f"restored: state={'yes' if state else 'no (first run)'}, runs={run_count(STATE)}, dockets in extract={n}", flush=True)
    if not state and n:
        sys.exit("extract present without its state file; refusing to start over on top of it")
    shutil.rmtree(DOWNLOAD, ignore_errors=True)


def cohort_complete():
    """True once every candidate search is exhausted and both queues are empty."""
    if not STATE.exists():
        return False
    s = json.loads(STATE.read_text())
    if not s.get("queries"):
        return False
    searches_done = all(q["exhausted"] and not q["pending"] for q in s["queries"].values())
    return searches_done and not s.get("large")


def save_output():
    out = WORK / "state"
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(STATE, out / "mtd_fetch_state.json")
    with EXTRACT.open("rb") as src, gzip.open(out / "mtd_extract.jsonl.gz", "wb", compresslevel=6) as dst:
        shutil.copyfileobj(src, dst)
    with tarfile.open(out / "cache.tar.gz", "w:gz") as t:
        t.add(CACHE, arcname="courtlistener")
    (out / "dataset-metadata.json").write_text(json.dumps(
        {"title": "courtpipe mtd state", "id": DATASET, "licenses": [{"name": "unknown"}]}))
    return out


def upload_state(out, started_from_runs, env, note):
    """Upload only if the dataset still holds the state this run started from."""
    check = pathlib.Path("/tmp/state-check")
    shutil.rmtree(check, ignore_errors=True)
    check.mkdir()
    try:
        sh("kaggle", "datasets", "download", DATASET, "-f", "mtd_fetch_state.json", "-p", str(check), "-o",
           env=env, stdout=subprocess.DEVNULL)
        for z in check.glob("*.zip"):
            shutil.unpack_archive(z, check)
        current = run_count(find(check, "mtd_fetch_state.json"))
    except subprocess.CalledProcessError:
        current = 0  # no state file yet (first run)
    if current != started_from_runs:
        sys.exit(f"dataset changed during this run ({started_from_runs} -> {current} runs recorded); "
                 "not uploading. This run's state is in the notebook output.")
    sh("kaggle", "datasets", "version", "-p", str(out), "-m", note, env=env, stdout=subprocess.DEVNULL)
    print("state uploaded as a new dataset version", flush=True)


def main():
    from kaggle_secrets import UserSecretsClient

    secrets = UserSecretsClient()
    env = dict(os.environ, **LIMITS)
    env["COURTLISTENER_API_TOKEN"] = secrets.get_secret("COURTLISTENER_API_TOKEN")
    env["KAGGLE_API_TOKEN"] = secrets.get_secret("KAGGLE_API_TOKEN")

    head = subprocess.run(["git", "ls-remote", REPO_URL, f"refs/heads/{COURTPIPE_BRANCH}"],
                          check=True, capture_output=True, text=True).stdout.split()[0]
    sh(sys.executable, "-m", "pip", "install", "-q", "--no-deps", f"git+{REPO_URL}@{head}")
    sh(sys.executable, "-m", "pip", "install", "-q", "python-dotenv", "kaggle==2.2.5", "six")

    download_state(env)
    restore()
    started_from = run_count(STATE)
    os.chdir(DATA)  # courtpipe writes run logs under ./runs; keep them out of the output

    complete = cohort_complete()
    fetch_ok = True
    if complete:
        print("cohort complete: every search exhausted and no docket queued; scoring only", flush=True)
    else:
        try:
            sh("courtpipe", "fetch-mtd", "--max-dockets", "1000000", "--text-chars", "0",
               "--max-minutes", str(FETCH_MINUTES), "--cache", str(CACHE),
               "--state", str(STATE), "--out", str(EXTRACT), env=env)
        except subprocess.CalledProcessError as exc:
            fetch_ok = False
            print(f"fetch failed (exit {exc.returncode}); saving and scoring what was fetched", flush=True)

    out = save_output() if STATE.exists() else None

    results = WORK / "results"
    results.mkdir(exist_ok=True)
    scored = subprocess.run(
        ["courtpipe", "evaluate-mtd", "--extract", str(EXTRACT),
         "--report", str(results / "mtd_report.json"), "--results-md", str(results / "RESULTS.md")],
        env=env,
    )
    runs = json.loads(STATE.read_text())["runs"] if STATE.exists() else []
    last = dict(runs[-1]) if runs and not complete else {}
    s = json.loads(STATE.read_text()) if STATE.exists() else {"queries": {}}
    last.update(
        finished=dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
        courtpipe_commit=head, fetch_ok=fetch_ok, scored=scored.returncode == 0,
        cohort_complete=complete,
        searches_finished=sum(1 for q in s["queries"].values() if q["exhausted"] and not q["pending"]),
        searches_total=len(s["queries"]),
    )
    report = results / "mtd_report.json"
    if report.exists():
        last["funnel"] = json.loads(report.read_text()).get("funnel")
    if STATE.exists():
        subprocess.run(["courtpipe", "mtd-progress", "--state", str(STATE), "--report", str(report),
                        "--out", str(results / "PROGRESS.md")], env=env)
    (results / "run_summary.json").write_text(json.dumps(last, indent=1))
    print(json.dumps(last, indent=1))

    if out is not None and not complete:
        upload_state(out, started_from, env,
                     f"run {last['finished']}: {last.get('total_dockets', '?')} dockets, "
                     f"{last.get('large_queue', '?')} large queued")
    if not fetch_ok:
        sys.exit("the fetch step failed; state and results were saved, see the log above")


if __name__ == "__main__":
    main()
