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
- CourtListener REST limits for authenticated users are low (5/min, 50/hr, 125/day); fetchers cache under `data/cache/courtlistener`. Use the bulk snapshot for appeal-scale pulls.
- Earlier PRs were written by Cursor background agents on `cursor/*` branches.
- The repo lives on iCloud-synced Desktop. Switching branches can create `file 2.py` sync-conflict copies; `.gitignore` ignores `* 2.*`. Delete them (after `cmp` against the original) rather than committing.
