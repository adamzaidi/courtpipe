# Evaluation protocol: securities class actions

Status: proposal. This protocol is the bar for the two tasks in `docs/SPEC.md`. Nothing here is a measured result of this repository. Where a number appears, it is a sample-size rule, a pre-registered floor, a published aggregate cited in the spec, or a count an endpoint returned. Outcome metrics are computed later, on a locked split, after the label audit passes.

The project is not done when a model runs. It is done when the gates below are reported, including a failure if that is what the numbers say. The two tasks pass or fail separately. A classification result is not an amount result.

The Integrated Database protocol is [`docs/idb/EVALUATION.md`](idb/EVALUATION.md). It is the bar for that separate track. It is not the bar for this one.

## Gates, in order

1. **File and terms.** The case list is a local copy of the Clearinghouse spreadsheet provided for non-commercial research under an NDA. If that file is not in hand, stop. Do not scrape the site, and do not train on Cornerstone or NERA aggregates.
2. **Label audit.** On a hand-audited sample, the status crosswalk and the settlement-fund figure match a written rubric often enough to clear the floors below. If they do not, stop. Do not train.
3. **Locked temporal evaluation.** On the test filings, the classifier beats the dismissal-rate baselines, and the amount model beats the median and size baselines, with bootstrap intervals on the right side of zero. Each task has its own gate.
4. **Pipeline checks.** Schema checks, leakage checks, one command, a recorded file hash, and an offline smoke test. The live CourtListener read waits on `COURTLISTENER_API_KEY`.

Skipping a gate, choosing the clock after seeing the test set, or swapping in a post-filing feature after seeing the test set, is a failure. The run is invalid and is not reported as a result.

## 1. Gold set and label accuracy

### Rubric

A person applies this rubric to a document the auditor is allowed to read: the complaint, dismissal order, or settlement stipulation the spreadsheet points to, or a public docket the auditor can open without buying PACER. The spreadsheet's status cell is what is being checked. The auditor does not "fix" the cell in place.

- **Settled** if the record says the parties settled the class case, including a dismissal that recites a settlement.
- **Dismissed** if the case was dismissed and the record does not recite a settlement.
- **Trial** if the case reached trial and has no settlement fund.
- **Remanded** if the case was remanded and the record shows no later dismissal or settlement.
- **Ongoing** if the record is still open.
- **Insufficient record** if the auditor cannot tie the row to a document they are allowed to read. These rows stay in the "could we check" count. They leave the accuracy denominator. They are not treated as matches.

For a settled row, the auditor also records the total settlement fund in nominal dollars, before attorneys' fees, as stated in the document. A partial payment that the document does not call the total fund is `amount_incomplete`.

The audit cannot start by crawling the Clearinghouse. If the site is down and the spreadsheet has no document pointers an auditor can open, the audit waits. That wait is a stop, not a waiver.

### Sample

Draw 100 rows from the spreadsheet after the cohort filters and before model fitting. Fix the seed in the report.

| Stratum | Rows |
| --- | --- |
| Coded `dismissed` | 40 |
| Coded `settled`, with a stated fund | 40 |
| Coded `trial` or `remanded` | 10 |
| Coded `ongoing` | 10 |

If a stratum has fewer rows than its quota, take all of them and report the shortfall. The ongoing rows test the censoring rule. They are reported separately. They are not in the resolved-status accuracy denominator.

One hundred is a design choice. At a sample proportion of 0.90, a simple random sample of 80 resolved rows (the dismissed and settled strata, if both fill) has a standard error of about `sqrt(0.9 * 0.1 / 80) ≈ 0.034`. That width can tell a crosswalk that matches the rubric about nine times in ten from one that matches it much less often. It is not a promise that the true accuracy sits inside any particular band.

Two people label independently. Disagreements are adjudicated by discussion, and the adjudication is the gold label. The report includes the confusion table, raw agreement, and Cohen's kappa.

If the two auditors assign the same status on at most 80% of the rows both of them could read, the rubric or the documents are too unstable to train on. Stop before fitting. Eighty percent is a floor on auditor agreement, chosen because this status is a short list (dismissed, settled, trial, remanded, ongoing) rather than a judgment call about a clerk code. It is not a measured agreement.

### Accuracy floors

On adjudicated resolved rows that are not `insufficient record`, status accuracy is the share whose gold label matches the spreadsheet label.

The status column is usable only if the lower end of a 95% Wilson interval on that accuracy is above 0.80. The amount column, on the settled rows with a stated fund that are not `insufficient record`, is usable only if the lower end of a 95% Wilson interval is above 0.80 for this match: the spreadsheet's nominal dollar fund equals the auditor's fund after the documented unit conversion (dollars versus millions) and before inflation adjustment.

These floors are stricter than the Integrated Database floor of 0.50 in `docs/idb/EVALUATION.md`. Code 13 in the Integrated Database is a noisy clerk code. A Clearinghouse status and a stated fund are supposed to be the fact itself. A column that is wrong on a large share of a small sample is a mapping error. The floors are pre-registered design choices. They are not measurements, and they are not a claim that 80% is the true accuracy of the database.

Also report, with no pass-fail number:

- How often gold "settled" sits on a row the spreadsheet called dismissed, and the reverse.
- The share of the 100 that were `insufficient record`.
- The share of coded-settled rows that were `amount_incomplete`.

If more than one third of the dismissed stratum, or of the settled stratum, is `insufficient record`, the audit of that stratum did not happen. Do not train.

## 2. Split

### Temporal split

Let Y be the last complete calendar year in the extract. The build records Y. It does not hard-code a calendar date from this draft.

- Unscored holdout: filings in years Y−3 through Y. These years are too recent to treat as resolved.
- Test filings: years Y−7 through Y−4.
- Training filings: every earlier filing year in the file, from 1996 forward.

If Y is 2025, that illustration is: train through 2017, test 2018–2021, hold out 2022–2025. The illustration is not a finding about the file. The file's Y may differ, and the build recomputes the windows.

The four-year holdout is a design choice tied to two published facts in the spec. Cornerstone's median time from filing to the settlement hearing, among cases that settled, was 3.5 years in its 2025 review. The same publisher's filings review says that 81% of ongoing core federal filings were filed in 2023–2025, and that early years show more dismissals than settlements. The 3.5-year figure is not a feature and is not itself the censoring rule.

Fit every baseline and both models on the training period only. Score the test period once. Retuning after a test score invalidates the run.

### Censoring inside the test window

Drop test-window rows labeled `ongoing`. Count them. Do not impute a dismissal or a settlement.

If ongoing rows are more than 15% of all test-window filings (resolved and ongoing together), the window has not resolved. Stop, move both the test window and the holdout four years earlier, and record the move. Fifteen percent is a design threshold. Cornerstone's ongoing share for core federal filings from 2015 to 2022 was 5%. A test window above 15% ongoing would be biased toward early dismissals. Do not refit until the window passes.

`trial` and `remanded` rows inside the test window are excluded from both scores and listed in the counts. They do not enter the 15% check.

### No case leakage and no issuer leakage

A case key is the Clearinghouse record id, or district plus docket number when that is the id the file uses. The key appears in only one split.

Normalize the issuer name by uppercasing and turning punctuation into spaces. After the temporal split, drop from the test set every row whose normalized issuer, or whose CIK, also appears in training. Repeat issuers are learnable as memorized names. The report states how many rows were dropped and what share of test settlements that removed. A secondary score on the dropped rows may be printed. It is not the success score.

Rows with a blank issuer name and no CIK cannot be checked. They remain, and the report counts them.

## 3. Baselines and metrics

### Task A. Dismissed versus settled

The scored rows are `dismissed` and `settled` only. `y_settle = 1` for `settled` and `0` for `dismissed`. The dismissal rate in a set is one minus the settlement rate. Baselines are stated as settlement probabilities so that Brier score has a single event. The report also prints the dismissal rate, which is the figure a reader should compare with the published aggregates.

All baselines use training rows only.

| Name | Probability of settlement assigned to a test row |
| --- | --- |
| `constant` | The training settlement rate, for every row. Equivalently, the training dismissal rate is one minus that number. |
| `circuit_rate` | The training settlement rate in the row's circuit. |
| `year_rate` | The training settlement rate in the row's filing year. |
| `circuit_year_rate` | The training rate for that circuit and filing year when the training cell has at least 50 rows. Otherwise the circuit rate. If that circuit has fewer than 50 training rows, the constant rate. |

The constant score has ROC-AUC 0.5. Beating 0.5 only means the score is not constant. The binding baseline is the best of `circuit_rate`, `year_rate`, and `circuit_year_rate` on the test set. "Best" is chosen per metric, on the test set, from those three. The comparison is harsh on purpose: the model has to beat the stronger simple story.

| Metric | Direction | What it answers |
| --- | --- | --- |
| ROC-AUC | Higher is better | Can the score rank cases that settled above cases that were dismissed? |
| Brier score | Lower is better | Are the probabilities close to the outcomes? |
| Reliability table, ten bins | Descriptive | Where the probabilities are over- or under-confident. A bin with fewer than 30 test rows is printed as `not reported`. |

### Task B. Settlement amount

Scored rows are test rows labeled `settled` with a stated total fund. The target is the natural log of the CPI-U-adjusted fund. Predictions are on that log scale.

| Name | Prediction |
| --- | --- |
| `median` | The training median of the log real fund, for every row. |
| `circuit_median` | The training median in the row's circuit when that circuit has at least 30 training settlements with a fund. Otherwise the overall training median. |
| `size_bin` | The training median inside the row's size quintile, when a size field passed the spec's dating rule (total assets, shares outstanding, or a compliant damages figure) and the quintile has at least 30 training settlements. Otherwise the overall median. |

If no size field passed the dating rule, `size_bin` is omitted and the report says the size rule could not be fit. The model then has to beat `median` and `circuit_median` only. v1 does not invent a market-cap column to keep the size rule alive.

| Metric | What it answers |
| --- | --- |
| MAE on the log fund | Typical absolute error on the log scale. The report also prints `exp(MAE)` as a plain-language translation. The translation is not a second gate. |
| Share within a factor of 2 | The share of test settlements where the absolute log error is at most `ln(2)`. The predicted fund is between half and twice the actual fund. |

Cornerstone's 2025 review states a median settlement of $17.3 million and an average of $40.6 million, in 2025 dollars, across 74 settlements. The average sitting well above the median is the published sign of a right tail. That shape is why a constant median can land many ordinary cases within a factor of two and still miss the large funds, and why an absolute MAE cutoff is not set here. The dispersion of this extract is unknown until the file is opened. The baselines are the numbers to beat.

### Bootstrap and the numeric bars

Percentile bootstrap, 1,000 resamples of the relevant test rows, seed `20261007`.

For AUC and for the factor-of-2 share, the difference is model minus best baseline. For Brier and for log MAE, the difference is best baseline minus model, so a positive number means the model is better.

Task A succeeds only if all of the following are true:

- Test ROC-AUC is greater than the best baseline AUC, and the 95% interval for the difference has a lower bound greater than 0.
- Test Brier score is lower than the best baseline Brier score, and the 95% interval for that improvement has a lower bound greater than 0.
- The interval for the model's own AUC has a lower bound greater than 0.5.

Task B succeeds only if both of the following are true:

- Log MAE is lower than the best amount baseline, and the 95% interval for the improvement has a lower bound greater than 0.
- The factor-of-2 share is higher than the best amount baseline's share, and the 95% interval for the difference has a lower bound greater than 0.

There is no absolute AUC floor such as 0.70, and no absolute dollar error. Those cutoffs would be invented. This protocol does not know the circuit-level rates or the fund dispersion in the spreadsheet, because the spreadsheet is not in hand.

A task that fails is reported as a failure. The other task's result still stands. Describing a classification-only pass as a model that "predicts settlement amounts" is a failure of description.

### External sanity check

After the extract is built, print the cohort's dismissal share, settlement share, ongoing share, and median nominal and real fund, next to the Cornerstone and NERA figures cited in the spec, for years those reports cover. The publishers use different filters and do not agree with each other (Cornerstone: 74 settlements in 2025, median $17.3 million, about $3.0 billion; NERA: 79 settlements, median $17 million, $2.9 billion). A gap between the extract and either publisher is described. It does not move a label and it does not enter the model.

## 4. Robustness

Report these slices on the test set.

Task A, for each slice: `n`, settled count, dismissed count, model AUC, best baseline AUC, and the bootstrap interval for the difference.

Task B, for each slice: `n` with a fund, model log MAE, best baseline log MAE, model factor-of-2 share, baseline factor-of-2 share.

| Slice | Rule |
| --- | --- |
| Circuit | One row per circuit. |
| Filing year | One row per test year. |
| Allegation family | Rule 10b-5, Section 11 or 1933 Act, and the rest, when the file has those flags. |
| Issuer matched to EDGAR | Matched and unmatched, separately, when EDGAR enrichment was used. |

Minimum sample sizes:

- A rate, an AUC, or an amount metric for a slice is printed only when the slice has at least 50 scored rows. Task A also needs at least 10 settled and 10 dismissed rows. Otherwise the cell says `not reported` and includes `n`.
- A model-versus-baseline comparison for a slice is printed only when the slice has at least 200 scored rows. Fifty is enough to show a rate: at a proportion of 0.4, the standard error of a sample of 50 is about `sqrt(0.4 * 0.6 / 50) ≈ 0.069`. Two hundred is the floor for a comparison.

No slice is pooled into "all securities class actions" to hide a circuit that failed the minimum. The overall test score remains the headline.

Refits that drop one training year at a time are a stability check. A sign change in either task's headline difference is reported as instability. It does not by itself fail the gate. It blocks any sentence that says the result is stable across years.

## 5. Pipeline correctness

These checks are part of done. They are specified now. They are not implemented in this phase.

### Data validation

Before fitting, the loader rejects the file if any of the following fail:

- A status column and a filing-date column exist, and the crosswalk covers every status value or sends the remainder to `unmapped`.
- Filing dates parse, and the training window and the test window each contain at least one scored row. An empty window stops the run.
- The feature matrix contains only columns that the spec allows at the declared clock. A test asserts that the settlement fund, status, termination date, docket-entry count, and any column dated after the prediction instant are absent from the matrix.
- `ongoing`, `trial`, `remanded`, and `unmapped` rows are absent from both scored sets.
- Settled rows with `amount_incomplete` are absent from the amount task and present in the classification task.
- Duplicate case keys inside a split are zero.
- The spreadsheet path is local. The command has no network call to securities.stanford.edu.

### One command

The build adds one command, documented in the README when it exists:

```bash
courtpipe evaluate-securities --scac path/to/scac.xlsx --report data/model-eval/securities_report.json
```

The command downloads nothing. The operator passes the local NDA file. The report JSON includes the file's SHA-256, byte size, the seed, the clock, the cohort counts, the windows, the audit summary, both tasks' metrics, the bootstrap intervals, the slice table, and the external sanity-check figures. A second run on the same file and seed produces the same metrics. The command exits non-zero if a validation check fails or if the label-audit gate was not passed.

The spreadsheet and any row-level extract are gitignored. They are not committed. Whether the aggregate report may be committed depends on the NDA, which is a decision in the spec.

### Offline smoke test

A second invocation runs without the NDA file and without a network:

```bash
courtpipe evaluate-securities --scac tests/fixtures/securities_smoke.xlsx --smoke
```

The fixture is a handful of synthetic rows with fake issuer names. It checks that the schema loader accepts a well-formed file, that a feature builder refuses a settlement-fund column, and that the process writes a report whose `result` field is `smoke`. It exits 0. The fixture's labels and dollars are invented. Quoting them as a dismissal rate or a median settlement is a failure under the table below.

This smoke test does not exist yet. It is a build target.

### Live read

When `COURTLISTENER_API_KEY` is present, a separate command performs one authenticated read of a single public docket and checks that the response includes a docket number and a filing date. It does not train, and it does not write that docket into the spreadsheet.

Observed without a token on 7 October 2026: the dockets, parties, and docket-entries endpoints each returned 401. The live read cannot be claimed to pass until it has been run with the key. Gates 1 through 3 can still be completed from the spreadsheet alone. If the fitted model used any RECAP field, the project is not called done while this read is unrun. If the model used only the spreadsheet and EDGAR, the README says the CourtListener path was not part of the fit.

The opinion-pipeline tests that already exist stay as they are. They check disposition-word extraction. They are not evidence about securities class actions.

## 6. What failure looks like

Report these in plain language if they happen.

| Outcome | What it means |
| --- | --- |
| The NDA spreadsheet is not available | Stop. The Winter 2026 outage and a refused request are not permission to scrape. The Integrated Database classifier in `docs/idb/` is a separate track, and it has no settlement-amount target. |
| Status or amount Wilson lower bound at or below 0.80, or auditors agree on at most 80% of readable rows | The column is not a usable label under the rubric. Stop. |
| More than one third of the dismissed or settled audit stratum has no readable document | That stratum's audit was not done. Stop. |
| Ongoing rows exceed 15% of the test window after one backward move | The extract cannot yet support a resolved test set. Stop. |
| Task A AUC interval covers 0.5, or the difference versus the best rate baseline covers 0 or less | Filing-time fields do not rank settlement better than circuit and year. That is "not enough signal." |
| Task A Brier score does not improve on the best baseline | The scores are not usable probabilities even if the ranking looks better. Report the ranking and do not describe the output as a calibrated risk. |
| Task B fails MAE, the factor-of-2 share, or both | The amount model does not beat a median. Say which bar failed. Do not describe the output as a settlement-size estimate. |
| The entire gain on either task disappears when one circuit above the minimum n is removed | The result is a circuit effect. Say which circuit. |
| The size baseline was skipped | Say so. Beating a median when size was unavailable is a weaker claim than beating a size rule. |
| Someone quotes the opinion-model fixture scores, a CourtListener hit count, a Cornerstone median, or a NERA median as this model's result | Those numbers are about other tasks or other databases. The smoke fixture is synthetic. The publisher figures are sanity checks. |

A negative result on a modeling gate is a completed evaluation. It is recorded in `securities_report.json` with the same fields as a positive result. The README does not get a sentence that says the model predicts dismissal or settlement size unless the matching gate passed and the label-audit gate passed.

The approved IDB evaluation that was built is in [`docs/idb/EVALUATION.md`](idb/EVALUATION.md).
