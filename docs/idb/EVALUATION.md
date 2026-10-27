# Evaluation protocol: filing-time settlement prediction

Status: approved. This is the bar for the Integrated Database model in `docs/idb/SPEC.md`. It is not the bar for the securities class-action proposal in `docs/EVALUATION.md`.

The hand audit is produced as a sample for a person. Until that sample is filled in, `audit_gate` is `pending`. The command still fits the model and scores the locked split, and it records that the project is not done while the audit is pending. A validation failure exits non-zero. A pending audit does not discard the metrics.

## Gates, in order

The gates are sequential. A later gate is not a substitute for an earlier one.

1. **Label audit.** The primary label matches the written rubric often enough that it is better than a coin flip on the audited sample. If the completed audit fails that floor, stop and do not treat the model as usable. This build cannot fill in the audit. It writes the 150-row sample, sets `audit_gate` to `pending`, and still runs the modeling gate so the numbers exist for review.
2. **Locked temporal evaluation.** On the test period, the model beats the filing-time baselines on ROC-AUC and on Brier score, with uncertainty intervals that stay on the right side of zero difference.
3. **Pipeline checks.** Unit tests, schema checks, one command, and a recorded IDB file hash. The live CourtListener smoke test is required before the project is called done, and it cannot be run until `COURTLISTENER_API_KEY` is set. It is not required to finish gates 1 and 2, which use the public IDB only.

Skipping a gate, or choosing the target (`y_settle` versus `y_broad`) after seeing the test set, is a failure.

## 1. Gold set and label accuracy

### What is being audited

The primary label is `settled_out_of_court` (`DISP = 13`), defined in the spec. The audit asks whether that code, and the neighboring codes, match a written rubric applied to the case's public docket caption and disposition information.

The rubric, applied by a person, is:

- **Settled out of court** if the available record says the parties settled, compromised, or stipulated to dismissal because of a settlement, and the ending is not a consent judgment signed as affirmative relief.
- **Consent judgment** if the record shows an agreed judgment that grants relief and is entered by the court.
- **Voluntary dismissal** if the plaintiff withdrew under Rule 41(a) and the record does not say a settlement caused the withdrawal.
- **Judgment for plaintiff or defendant** only when a judgment on the merits, default, or motion is entered for that side.
- **Other** for transfers, remands, statistical closings, and anything that does not fit.
- **Insufficient record** if the IDB row cannot be tied to a docket the auditor can read. These rows stay in the audit denominator for "could we check," and they leave the precision denominator. The count is reported. They are not silently treated as matches.

v1's IDB row does not include docket text. The audit therefore needs a docket the auditor can open. Until a CourtListener token exists, auditors use the public docket pages already on CourtListener for rows that join on district, office, and docket number. Rows that do not join are `insufficient record`. The build does not invent a docket from the IDB caption.

### Sample

Draw 150 terminated cohort rows after the cohort filters, before model fitting:

| Stratum | Rows |
| --- | --- |
| `DISP = 13` | 50 |
| `DISP = 12` | 25 |
| `DISP = 5` | 25 |
| Judgment labels (`judgment_for_plaintiff`, `judgment_for_defendant`, `judgment_other`) | 25 |
| `other_dismissal` | 25 |

If a stratum has fewer rows than its quota, take all of them and report the shortfall. Stratify the draw by `NOS` so each of 160, 410, and 850 appears in the `DISP = 13` slice when those rows exist. Fix the random seed in the report.

One hundred fifty is a design choice, not a measured accuracy. At a sample proportion of one half, a simple random sample of 150 has a standard error of about `sqrt(0.25/150) ≈ 0.041`. That width can separate a label that matches the rubric about half the time from one that matches it much more often. It is not a promise that the true precision sits inside any particular band.

Two people label independently under the rubric. Disagreements are adjudicated by discussion and the adjudication is the gold label. The report includes a confusion table of the two people, raw agreement, and Cohen's kappa. If the two auditors assign the same label on at most half of the `DISP = 13` rows, the rubric is too unstable to support a model and the project stops before fitting.

### Label-accuracy bar

On the adjudicated `DISP = 13` rows that are not `insufficient record`, compute precision: the share whose gold label is settled out of court. Report a 95% Wilson interval.

The label is usable for training only if the lower end of that interval is above 0.5. Below or equal to 0.5, code 13 is not reliably the rubric's settlement, and the build stops. There is no higher numeric target in this protocol. Alexander, Dahlberg, and Tucker's 2016–2017 crosswalk (cited in the spec) shows that party resolutions also sit in other IDB codes, so a 90% or 95% precision target would be an invention. The measured interval is the result.

The same table reports, without a pass-fail number:

- How often gold "settled out of court" sits on `DISP` 12, 5, 14, or 6.
- The share of the 150 that were `insufficient record`.

If more than half the `DISP = 13` sample is `insufficient record`, the audit did not happen. Do not train, and do not treat the missing dockets as confirmations.

## 2. Split

### Temporal split

- Training filings: `FILEDATE` from 1 October 2009 through 30 September 2017 (fiscal years 2010–2017).
- Test filings: `FILEDATE` from 1 October 2017 through 30 September 2021 (fiscal years 2018–2021).

Fit every baseline and the model on the training period only. The test period is scored once. Retuning after a test score, including a change from `y_settle` to `y_broad`, invalidates the run.

### Censoring

On the training period, compute the number of days from `FILEDATE` to `TERMDATE` and record the 95th percentile. `TERMDATE` is used only for this diagnostic and for the label's existence. It is not a feature.

The IDB extract must be one whose `last-modified` date (or an inside-file as-of date) is at least that many days after 30 September 2021. The cumulative zip inspected on 7 October 2026 was last modified 26 August 2026, which is past that filing window, but the build still computes the lag and records it. Test rows that are still pending are not in the file; the report states how the pending file was excluded so the test set is not quietly limited to fast terminations without anyone noticing. If the 95th-percentile duration from the training years extends past the extract's as-of date for a test filing, drop that filing and count the drop. Do not impute a disposition.

### No case leakage

A case key is `DISTRICT` + `OFFICE` + `DOCKET`. The key appears in only one split. Reopened origins are already out of the cohort.

If `MDLDOCK` is non-missing, every row with that MDL number is one group. The group takes the side of its earliest `FILEDATE`. If that rule would put any member in the test period and any member in the training period, the whole group goes to training and is removed from the test score. The count is reported.

### No party leakage

Normalize `DEF` with the spec's punctuation rule. After the temporal split, drop from the test set every row whose normalized `DEF` also appears in training. Repeat defendants are learnable as memorized names. Dropping them makes the test set a worse picture of repeat corporate filers, and the report says how many rows were dropped and what share of test `y_settle` that removed. A secondary score on the dropped rows may be printed. It is not the success score.

`corporate_via_residence` rows with a blank `DEF` cannot be checked for party overlap. They remain, and the report counts them separately.

## 3. Baselines and metrics

### Tasks scored

- **Primary.** Binary `y_settle` (`DISP = 13` versus every other in-cohort label).
- **Sensitivity, not the headline.** Binary `y_broad` (`DISP` in {5, 12, 13}). Reported in an appendix of the same run. It does not replace the primary target.
- **Secondary.** Multiclass macro-F1 on the in-cohort labels `settled_out_of_court`, `voluntary_dismissal`, `consent_judgment`, `judgment_for_plaintiff`, `judgment_for_defendant`, and a collapsed `other` (`judgment_other` and `other_dismissal`). Macro-F1 treats those classes equally, so a model can fail it while still ranking settlements well. Macro-F1 is reported. It is not the binding bar.

### Baselines

All baselines use training rows only.

| Name | Score it assigns to a test row |
| --- | --- |
| `constant` | The training prevalence of `y_settle`, for every row. |
| `nos_rate` | The training `y_settle` rate for that row's `NOS`. |
| `court_rate` | The training `y_settle` rate for that row's `DISTRICT`. |
| `nos_court_rate` | The training rate for that `NOS` and `DISTRICT` when the training cell has at least 50 rows. Otherwise the `NOS` rate. If that `NOS` has fewer than 50 training rows, the constant rate. |

The constant score has ROC-AUC 0.5 by definition: it does not rank cases. Beating 0.5 only means the score is not constant. The binding baseline is the best of `nos_rate`, `court_rate`, and `nos_court_rate` on the test set. "Best" is chosen per metric, on the test set, from those three only. That is a slightly harsh comparison (the winner is selected on the test metric). It is intentional: the model has to beat the stronger simple story, not the weaker one.

For macro-F1, the baseline predicts the majority training class inside the same cell, with the same backoff. Ties go to the class with more training rows overall.

### Primary metrics

| Metric | Direction | What it answers |
| --- | --- | --- |
| ROC-AUC for `y_settle` | Higher is better | Can the score rank cases that received code 13 above cases that did not? |
| Brier score for `P(y_settle)` | Lower is better | Are the probabilities close to the outcomes, not just well ordered? |
| Macro-F1 on the six-way label | Higher is better | Secondary. Equal weight per class. |

Also report, as descriptive and not as gates: positive-class precision and recall at the training prevalence threshold, the test prevalence, and a reliability table with ten bins of predicted probability. Empty bins are shown as empty.

### Numeric bar

Compute a percentile bootstrap with 1,000 resamples of test rows, seed 20261007. For AUC and for macro-F1, the difference is model minus best baseline. For Brier, the difference is best baseline minus model, so a positive number still means the model is better.

The run succeeds on the modeling gate only if all of the following are true:

- Test ROC-AUC of the model is greater than the best baseline AUC, and the 95% bootstrap interval for the difference has a lower bound greater than 0.
- Test Brier score of the model is lower than the best baseline Brier score, and the 95% interval for that improvement has a lower bound greater than 0.
- The interval for the model's AUC itself has a lower bound greater than 0.5.

There is no absolute AUC or F1 cutoff. A cutoff such as "AUC at least 0.70" would be invented: this protocol does not know the NOS-level settlement rates in the cohort, because the IDB zip was not opened. The baselines are the numbers the model has to beat, and they are computed from the training years of the same file.

Macro-F1 does not have to clear its baseline for the modeling gate to pass. If it does not, the report says the model failed the six-way task and passed only the binary ranking task. Calling that a general outcome classifier is a failure of description.

## 4. Robustness

Report these slices on the test set. For each slice print `n`, the positive count, the model AUC, the best baseline AUC, and the bootstrap interval for the difference.

| Slice | Rule |
| --- | --- |
| `NOS` 160, 410, 850 | One row per code. |
| `DISTRICT` | One row per district. |
| `JURIS` | One row per jurisdiction code present. |
| Corporate rule | Name-suffix cases and `corporate_via_residence` cases, separately. |
| `ORIGIN` | Original (`1`) versus removed (`2`) versus the other allowed origins combined. |

**Minimum n.**

- A rate or an AUC for a slice is printed only when the slice has at least 50 test rows and at least 10 positive rows. Otherwise the cell says `not reported` and includes `n`.
- A model-versus-baseline comparison for a slice is printed only when the slice has at least 200 test rows. Smaller slices are too noisy for a claim that the model won inside that court or case type. Fifty is enough to show a rate: at a proportion of 0.3, the standard error of a sample of 50 is about `sqrt(0.3 * 0.7 / 50) ≈ 0.065`. Two hundred is the floor for a comparison, not a claim that 200 makes the interval small.

No slice is pooled into "all corporate litigation" to hide a court that failed the minimum. The overall test score remains the headline, and the slice table is how a reader sees whether one district or one NOS produced it.

Refits that drop one training year at a time are reported as a stability check. A sign change in the AUC difference in any dropped-year refit is reported as instability. It does not by itself fail the gate, and it blocks any sentence that says the result is stable across years.

## 5. Pipeline correctness

These checks are part of done. They are specified now so the build has a target. They are not implemented in this phase.

### Data validation

Before fitting, the loader rejects the file if any of the following fail:

- Required columns exist: `CIRCUIT`, `DISTRICT`, `OFFICE`, `DOCKET`, `ORIGIN`, `FILEDATE`, `JURIS`, `NOS`, `RESIDENC`, `JURY`, `CLASSACT`, `DEMANDED`, `DEF`, `PLT`, `DISP`, `JUDGMENT`, `PROCPROG`, `TERMDATE`, `STATUSCD`.
- `DISP` values are inside the codebook set, including -8 for missing.
- `NOS` is a three-digit code from the codebook list.
- `FILEDATE` parses, and the training and test windows each contain at least one row after cohort filters. If a window is empty, the run stops.
- The feature matrix columns are exactly the allowed list in the spec. A test asserts that `DISP`, `JUDGMENT`, `PROCPROG`, `TERMDATE`, `NOJ`, `AMTREC`, and `TRCLACT` are absent from the matrix.
- Pending rows are absent from the cohort.
- Duplicate case keys inside a split are zero.

### Label-derivation tests

Unit tests, with tiny hand-written rows and no network, cover at least:

- `DISP = 13` maps to `settled_out_of_court` and `y_settle = 1`, even if `JUDGMENT` is filled.
- `DISP = 12` and `DISP = 5` do not set `y_settle`.
- `DISP = 6` and `JUDGMENT = 1` maps to `judgment_for_plaintiff`, not to settled.
- `DISP = 0` is `not_a_merits_ending` and is excluded.
- Defendant strings: `ACME INC` is corporate; `UNITED STATES OF AMERICA` is not; `SECURITIES AND EXCHANGE COMMISSION` is not; a blank `DEF` with `JURIS = 4` and `RESIDENC` second digit 4 is `corporate_via_residence`; a blank `DEF` otherwise is unknown and excluded.
- A feature builder given a row that includes `PROCPROG` does not copy that column into the matrix.

### One command

The build adds one command, documented in the README:

```bash
courtpipe evaluate-settlement --idb path/to/cv88on.zip --report data/model-eval/settlement_report.json
```

The command downloads nothing by itself. The operator passes a local IDB file. The report JSON includes the file's SHA-256, byte size, the codebook version named in the spec, the seed, the cohort counts, the audit summary, the test metrics, the bootstrap intervals, and the slice table. A second run on the same file and seed produces the same metrics. The command exits non-zero if a validation check fails or if the label-audit gate was not passed.

### Live smoke test

When `COURTLISTENER_API_KEY` is present, a separate command performs one authenticated read of a single public docket and checks that the response includes a docket number, a nature of suit, and a party list. It does not train, and it does not write those parties into the IDB training file. The docket id is fixed in the test so the check is repeatable.

Observed without a token on 7 October 2026: `GET /api/rest/v4/dockets/`, `/parties/`, and `/docket-entries/` each returned 401. The smoke test cannot be claimed to pass until it has been run with the rotated key. Gates 1 and 2 can still be completed from the FJC file alone. The project is not called done while this smoke test is unrun.

The opinion-pipeline tests that already exist stay as they are. They check disposition-word extraction. They are not evidence about settlement.

## 6. What failure looks like

Report these in plain language if they happen. Do not replace them with a chart of training accuracy.

| Outcome | What it means |
| --- | --- |
| Label-audit lower bound at or below 0.5, or auditors agree on at most half of the code-13 slice | Code 13 is not a usable settlement label under the rubric. Stop. |
| More than half of the code-13 audit sample has no readable docket | The audit was not done. Stop. |
| Model AUC interval covers 0.5, or the difference versus the best baseline covers 0 or less | The filing-time fields do not rank code 13 better than case type and court. That is "not enough signal," not a tuning miss. |
| Brier score does not improve on the best baseline | The scores are not usable probabilities even if the ranking looks better. Report the ranking and do not describe the output as a calibrated risk. |
| The entire AUC gain disappears when one NOS or one district above the minimum n is removed | The result is a slice effect. Say which slice. Do not state a cohort-wide finding. |
| Test prevalence of code 13 is extreme because of the party-leakage drop | Say so. A metric on a test set that lost most repeat defendants is a metric about first-time name strings. |
| Someone quotes the current opinion-model fixture scores, or a CourtListener full-text hit count, as a settlement rate | Those numbers are about other tasks. The fixture run in the README is 20 synthetic snippets. The search `count` values in the spec are archive hits. |

A negative result on the modeling gate is a completed evaluation. It is recorded in `settlement_report.json` with the same fields as a positive result. The README does not get a sentence that says the model predicts settlement unless the modeling gate passed and the label-audit gate passed.
