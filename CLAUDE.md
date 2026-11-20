# courtpipe — working notes

**What to do next is in `ROADMAP.md`.** Check it at the start of a session and update it as items land.

Predicting outcomes in federal litigation against corporate defendants. The repo is a portfolio piece for data science roles and law school applications, so the README must stay accurate and recruiter-readable: lead with question, method, result.

## Tracks

| Track | Code | Spec | Results |
| --- | --- | --- | --- |
| Settlement at filing (FJC IDB) | `analysis/idb_*.py` | `docs/idb/SPEC.md`, `docs/idb/EVALUATION.md` | `docs/idb/RESULTS.md` — modeling gate FAILS (negative result) |
| Motion to dismiss (RECAP) | `analysis/mtd/` | `docs/mtd/SPEC.md`, `docs/mtd/EVALUATION.md` | fixture only until live extract |
| Appeal reversal (bulk opinions) | `analysis/appeal/` | `docs/appeal-reversal-spec.md` | fixture only until live extract |
| Opinion outcome labeler (original ETL) | `etl/`, `analysis/model.py` | — | extraction, not prediction |
| Securities class actions (Stanford SCAC) | — | `docs/SPEC.md`, `docs/EVALUATION.md` | shelved; not being pursued |

Spec decisions for MTD (PR #2) and appeal reversal (PR #3) were approved as written on 2026-11-03.

## Rules (non-negotiable — they are the point of the project)

- Spec first. Change a bar or a cohort rule in the spec before scoring, never after seeing test numbers.
- Features are pre-decision only; each spec lists forbidden fields. Leakage tests live in `tests/`.
- Temporal split, one docket per side. Model must beat the best rate baseline (picked on test, intentionally harsh) with a bootstrap CI lower bound > 0.
- Negative results are published as-is. Never call a model a "predictor" in docs unless its gate passed and its label audit passed.
- Fixture metrics are not results. Never quote them as findings.
- No case-level data committed (`data/cache/`, `data/extracted/`, `data/idb/` are gitignored). No per-judge scores published. Aggregates only.
- Tokens come from env (`COURTLISTENER_API_TOKEN`, fallback `COURTLISTENER_API_KEY`), loaded from a gitignored `.env`. Never print, log, or commit them. The GitHub repo secret is for Actions/Cursor only; local runs need `.env`.

## Dev

- `python -m venv .venv && .venv/bin/pip install -e ".[dev]" && .venv/bin/python -m pytest` (NumPy pinned <2 because of matplotlib <3.9).
- CLI: `courtpipe --help`. README charts: `python scripts/idb_figures.py`.
- CourtListener REST limits default to 5/min, 50/hr, 125/day and are read from `CL_MAX_PER_MINUTE` / `CL_MAX_PER_HOUR` / `CL_MAX_PER_DAY` (GitHub repo variables for `mtd-fetch`). Fetchers cache under `data/cache/courtlistener`. Use the bulk snapshot for appeal-scale pulls.
- **The MTD fetch runs on Kaggle** (since 2026-11-20): `scripts/kaggle-mtd.sh setup|start|status|pull`. Private notebook `zaidiadam/courtpipe-mtd-fetch` (code in `kaggle/mtd-fetch/run.py`, installs courtpipe from GitHub pinned to the pushed commit) and private dataset `zaidiadam/courtpipe-mtd-state` carrying state between runs. Local copies go to `~/courtpipe-data` (off iCloud), with a backup to `/Volumes/AZ/courtpipe-data` when AZ is mounted. The Kaggle CLI lives in `~/courtpipe-data/.kaggle-venv` (installing it in `.venv` breaks on missing `six`). `KAGGLE_API_TOKEN` is in `.env` (same token as the PokeCombo project; one Kaggle account). The CourtListener token is a Kaggle Secret on the notebook, label `COURTLISTENER_API_TOKEN`. **Kaggle gives secrets only to versions saved in the browser editor, not to `kaggle kernels push` versions** (those fail with HTTP 400), so each run is started by Adam clicking Save Version → Save & Run All; `start` saves state and opens the editor, `push` only uploads code changes. After a push, reload the editor or Save Version fails with a ConcurrencyViolation. The GitHub `mtd-fetch` workflow is disabled; don't run both against one CourtListener account.
- CourtListener EDU membership: 5,000/hour, no minute or day cap, renews 2027-05-04. Kaggle runs use 3,000/hour.
- `fetch-mtd` never truncates a docket. Big ones move to a large-docket queue and finish over later runs (see the 2026-11-03 SPEC amendment). Scores are provisional while that queue is non-empty.
- Earlier PRs were written by Cursor background agents on `cursor/*` branches.
- The repo lives on iCloud-synced Desktop. Switching branches can create `file 2.py` sync-conflict copies; `.gitignore` ignores `* 2.*`. Delete them (after `cmp` against the original) rather than committing.
