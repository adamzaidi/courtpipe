# Roadmap

What's next for courtpipe, in order. Check items off as they land and add the date. The rules in `CLAUDE.md` apply to every step: write the spec before scoring, use only pre-decision features, beat the best baseline with an interval above zero, and publish negative results.

Last updated 2026-11-20.

## Now

- [x] **Put large dockets off instead of capping them.** Done 2026-11-03. The first scheduled run ([41701285303](https://github.com/adamzaidi/courtpipe/actions/runs/41701285303), 2026-11-03) used all 110 requests and added **0 dockets**: one very large docket (7338509) paged through its entries until the budget ran out. A hard page cap would skew the cohort away from long, heavily litigated cases, and it would mislabel slow-to-resolve motions as unresolved. So instead: give each docket about 3 pages per run, move unfinished dockets to a large-docket queue, and save about 30% of each run's budget to continue them (cached pages are free). Report how many dockets are waiting in that queue, and don't count a model score as a result until the queue is empty. Report case type, era and court for large versus normal dockets, plus a score with large dockets left out. Record all of this as an amendment in `docs/mtd/SPEC.md`.
- [x] **Retry read timeouts instead of skipping the docket forever.** Done 2026-11-03. Right now a timeout puts the docket on the permanent `skipped` list (docket 16367238 on the first run). A timeout should send the docket back to the queue, and only a 404 should count as a permanent skip.
- [x] **Higher CourtListener API limit.** Granted 2026-11-05 as an EDU membership: 5,000/hour, no minute or day cap, renews 2027-05-04. Allowance raised to 15 and large-docket share to 50% (#8); finished dockets' raw pages pruned (#9).
- [x] **Move the fetch off GitHub.** Done 2026-11-20. GitHub `mtd-fetch` is disabled. The fetch runs in a private Kaggle notebook, 11 hours per run at 3,000/hour (about 33,000 requests, about 3,000 dockets), with state carried in a private Kaggle dataset. The extract keeps full filing text (SPEC amendment, 2026-11-20). Kaggle replaced the earlier plan of an overnight job on the AZ drive. AZ is now only a backup.
- [ ] **Run the Kaggle fetch until the searches and the large-docket queue are empty.** Runs are scheduled on Kaggle and save their own state (one-time switchover after the 2026-11-21 run: `ingest`, `push`, Save Version, turn on the schedule). Each run writes an aggregate progress page; `scripts/kaggle-mtd.sh pull` copies it to `docs/mtd/PROGRESS.md` to commit. Run log: 2026-11-20 run crashed on a search-page timeout after 2.7 h (617 dockets, saved; fixed in 0cdde46). 2026-11-21 run: 11.2 h, 27,409 requests, +2,844 dockets (3,461 total), 417 in the large queue, 1 of 8 searches finished, 100 retried requests and no failures. 2026-11-22 run: 28,377 requests, +3,420 dockets (6,881 total), the 417 queued large dockets finished and 233 newly queued, 3 of 8 searches finished; ingested as dataset version 2 runs. Provisional funnel: 26,113 MTD entries, 617 linked to an order, 289 labeled (141 train / 114 test). The motion-to-order link is the bottleneck (6,516 ambiguous); look at it once the fetch is done, before reading any score. Read `results/run_summary.json` each time. A run that adds 0 dockets means the fetcher has a problem, not a data result.

## Next

- [ ] **Settlement track: two-reader hand audit.** 150 rows in `docs/idb/audit_sample.csv`, with the rubric in `docs/idb/AUDIT_RUBRIC.md`. Code 13 counts as a validated settlement label only if the Wilson lower bound on precision is above 0.5. Update `docs/idb/RESULTS.md` and the README with the outcome either way.
- [ ] **Motion to dismiss: first real score.** Once the funnel shows labeled motions on both sides of the split, ideally with 40 or more training motions per case type so the baselines don't fall back to a constant (`docs/mtd/EVALUATION.md`), read the gates in the last Kaggle run's `results/` (`scripts/kaggle-mtd.sh pull`), and put the funnel and result in the README. Scores from a small extract are progress, not results.
- [ ] **Motion to dismiss: two-reader label audit.** Generate the 120-row sample on a local machine (`courtpipe evaluate-mtd --audit-out ...`). Never upload it, because it contains docket IDs. Labels are usable only if the 95% Wilson lower bound is above 0.80 and kappa is at least 0.60.

## Later

- [ ] **Appeal reversal: bulk-snapshot loader.** The spec's v1 data source is CourtListener's quarterly bulk snapshot, not the REST API. `analysis/appeal/` can score an extract, but nothing yet converts a bulk snapshot into one. Build that converter (local only, gitignored inputs), then run `evaluate-appeal`.
- [ ] **Appeal reversal: two-reader audit** (120 rows, seed `20261010`), using the same gates as above plus a Wilson lower bound above 0.85 for the two-way version of the label.
- [ ] **Write-up.** One results page across all tracks, covering wins and negatives alike, linked from the top of the README.

## Shelved

- **Securities class actions (Stanford SCAC).** Dropped 2026-11-03. The data request was never sent. `docs/SPEC.md` and `docs/EVALUATION.md` stay in the repo as a design record.

## Done

- 2026-10-10: Settlement-at-filing track scored on the FJC Integrated Database. The modeling gate fails (negative result). (#1)
- 2026-11-20: MTD fetch moved to Kaggle with full filing text.
- 2026-11-03: Motion-to-dismiss and appeal-reversal specs approved, pipelines built and tested on fixtures, README rewritten as a portfolio page, and a daily scheduled MTD fetch added on GitHub Actions. (#2–#6)
