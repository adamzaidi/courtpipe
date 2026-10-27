# Evaluation protocol: motion-to-dismiss outcomes

Status: proposal. This protocol is the bar for the model described in `docs/mtd/SPEC.md`. Nothing here is a measured result. Where a number appears, it is a sample-size rule, a chance baseline, a design threshold, or a count already returned by a public endpoint and cited in the spec. Outcome metrics are computed later, on a locked split, and compared with baselines fit on the training period only.

The project is not done when a model runs. It is done when the gates below are reported, including a failure if that is what the numbers say.

This protocol does not apply to the filing-time settlement track in `docs/EVALUATION.md`. Passing one track does not pass the other.

## Gates, in order

The gates are sequential. A later gate is not a substitute for an earlier one.

1. **Label audit.** On a hand-labeled sample, the automatic three-way label matches the rubric at the accuracy bar below. If it does not, stop. Do not train.
2. **Locked temporal evaluation.** On the test period, the model beats the judge and court baselines on ROC-AUC and on Brier score for `y_relief`, with uncertainty intervals that stay on the right side of zero difference. Macro-F1 on the three-way label is reported in the same run.
3. **Pipeline checks.** Unit tests, a leakage test, one command, and a recorded snapshot of the extract. The live CourtListener smoke test is required before the project is called done. It cannot be run until `COURTLISTENER_API_KEY` is set.

Unlike the settlement track, gates 1 and 2 also need the token. Docket entries, party roles, and document text are what the label and the features are made of, and those endpoints returned 401 without a token on 7 October 2026. Hand-written fixtures can prove the code path before the key exists. They cannot pass gate 1.

Skipping a gate, or choosing after seeing the test set to report only `y_relief` or only the three-way label, is a failure. Both are specified now, and both are reported.

## 1. Gold set and label accuracy

### What is being audited

The automatic labeler assigns `granted`, `granted_in_part`, or `denied` using the rules in the spec. The audit asks whether that assignment matches a written rubric applied by a person who reads the order's docket-entry description and, when the description does not state the disposition, the order or opinion text.

The auditor does not use later entries to infer what the order must have done. An amended complaint filed after the order, a notice of appeal, and a later settlement are out of the reading.

### Rubric

Apply the first matching rule.

1. **Not a readable ruling** (`insufficient_record`) if the order entry is missing, or the entry does not state a disposition and the order file and any linked opinion are both unavailable. These rows stay in the audit denominator for "could we check," and they leave the accuracy denominator. The count is reported. They are not matches.
2. **Not this task** if the document is a proposed order, a report and recommendation with no district-judge adoption, an appellate opinion, a motion for reconsideration, or an order that only resolves Rule 12(b)(1), Rule 12(b)(2), or some other non-12(b)(6) request. The automatic label is wrong on these rows. They stay in the accuracy denominator.
3. **Not a merits ruling** if the motion was withdrawn, stipulated, mooted, or converted to summary judgment under Rule 12(d). Same consequence: the automatic three-way label is wrong, and the row stays in the accuracy denominator.
4. **Link** the order to a document number when the order names one. If it names none, keep the link only when one 12(b)(6) motion was pending. If the link cannot be made, the row is `insufficient_record`.
5. **`granted`** if the 12(b)(6) request is granted as to every claim it attacks, or the complaint is dismissed in full on 12(b)(6). Leave to amend does not change this code.
6. **`granted_in_part`** if at least one attacked claim is dismissed on 12(b)(6) and at least one attacked claim survives. When the order splits defendants, score the corporate movant the row is about. If the order cannot be tied to that movant, use `insufficient_record`.
7. **`denied`** if the 12(b)(6) request is denied in full, including denied without prejudice.
8. If the order uses one verb for a motion that raised 12(b)(6) together with 12(b)(1) or 12(b)(2), and it does not separate the grounds, code that verb and mark `grounds_not_separated` in the notes. The three-way code still follows the verb.

Leave, recorded on every sufficient row and not part of the accuracy numerator:

- `leave_granted` if the order grants leave or sets a deadline to amend.
- `leave_denied` if the order says with prejudice, without leave, or denies leave.
- `leave_not_stated` otherwise. "Without prejudice" alone is `leave_not_stated`. The auditor writes down the phrase. The protocol does not pretend that phrase has one meaning.

Two people label independently under this rubric. Disagreements are adjudicated by discussion, and the adjudication is the gold label. The report includes a confusion table of the two people, raw agreement, and Cohen's kappa, on the three-way label, computed before adjudication.

If kappa is below 0.60, the rubric is too unstable to support a model and the project stops before fitting. The 0.60 line is a design choice for this protocol: below it, the two readers are not close enough that adjudication is cleaning small disagreements rather than inventing a label. It is not a measured kappa for this corpus.

If the two readers assign the same three-way label on at most half the rows they both marked as readable, the project also stops. That rule catches a sample where kappa is hard to interpret because almost every row was `insufficient_record` or the class mix is extreme.

### Sample

Draw 120 cohort rows after the labeler has assigned a three-way class and before any model is fit. The draw is stratified by the automatic label:

| Automatic label | Rows |
| --- | --- |
| `granted` | 40 |
| `granted_in_part` | 40 |
| `denied` | 40 |

If a class has fewer than 40 rows in the cohort, take all of them and report the shortfall. Within each class, spread the draw across nature-of-suit codes 160, 410, 480, and 850 as evenly as those rows exist. Fix the random seed at 20261007 and record it.

One hundred twenty is a design choice, not a measured accuracy. At a sample proportion of 0.80, a simple random sample of 120 has a standard error of about `sqrt(0.80 × 0.20 / 120) ≈ 0.037`. That width can separate a labeler that matches the rubric about four times in five from one that matches it about two times in three. It is not a promise that the true accuracy sits inside any particular band. Forty rows in each automatic class force the audit to look at partial grants even if that class is rare. A simple random sample would not.

If the number of rows with a readable gold label is under 80, the interval is too wide for the bar below. The gate does not pass, and the project stops.

### Label-accuracy bar

On rows whose gold label is not `insufficient_record`, compute exact-match accuracy: the share whose automatic three-way label equals the gold three-way label. Gold labels of "not this task" and "not a merits ruling" count as misses, because the labeler assigned a class anyway. Report a 95% Wilson interval.

The three-way label is usable for training only if the lower end of that interval is above 0.80.

The source of the label is an order that usually states a disposition, which is a firmer source than an administrative disposition code. The floor is therefore higher than a coin flip. It is not 0.95. Partial grants, multi-defendant orders, and mixed 12(b)(1)/12(b)(6) orders are genuinely ambiguous, and this protocol has not measured how common they are. A 0.95 floor would be an invention. 0.80 as a lower bound is the point at which label noise is no longer the main thing a later model error could be. The measured interval is the result. The threshold is the gate.

Fallback, still decided before any fit:

- If the three-way lower bound is above 0.70 and at or below 0.80, the three-way label fails. A binary label may be trained only for `y_relief`, and only if the Wilson lower bound for binary exact match on the same readable rows is above 0.85. The report says the three-way label failed. It does not call the binary model a three-way predictor.
- If the three-way lower bound is at or below 0.70, stop. The binary model is not a rescue.

The same table reports, with no extra pass-fail number:

- Per-class recall of the automatic label against gold, for the three classes.
- The cross-tab of gold disposition by gold leave modifier.
- The share of the 120 that were `insufficient_record`.
- The share marked `grounds_not_separated`.

If more than 20% of the 120 are `insufficient_record`, the audit did not happen. The sample was drawn from rows the labeler already classified, so an order entry had already been found. If more than one in five still cannot be read, the descriptions are too thin to be a label source. Do not train, and do not treat the missing files as confirmations. Twenty percent is a design choice for that reason.

Leave modifiers are reported, including agreement between the two readers. They have no numeric pass-fail bar in v1. "Without prejudice" is too unstable to gate the project, which is why it is not its own class.

## 2. Split

### Temporal split

The clock is the motion's `date_filed`.

- Training motions: 1 January 2016 through 31 December 2019.
- Test motions: 1 January 2020 through 31 December 2022.
- Quarantine: 1 January 2023 through 31 December 2023. Extracted, counted, and not scored. Not used to pick features, thresholds, or the target.

Fit every baseline and the model on the training period only. The test period is scored once.

An order dated in 2021 on a motion filed in 2019 is a training row. The order date is not the split key. Splitting on the order date would let the duration of the briefing, which differs by outcome, decide the split.

### One docket, one side

A docket id appears in only one split. Every in-cohort motion on that docket takes the side of the earliest in-cohort motion's filing date. If that rule moves a later motion out of the test window, the later motion is dropped from the test score and counted. A model must not learn the ruling on the first motion and then be scored on the second motion in the same case.

### Unresolved motions are not denials

A motion with no first resolving order is out of the cohort. It is not labeled `denied`. The report counts unresolved motions by filing year.

On the training period, compute the number of days from the motion's `date_filed` to the order's `date_filed`, and record the 95th percentile. The extract's snapshot date must be at least that many days after 31 December 2022. If it is not, the test window is censored and the run stops. Do not impute a disposition. Test motions that remain unresolved after that wait are excluded and counted. They are not negatives.

The quarantine year is where the build shows the unresolved share for recent filings. It is not a second test set.

### Repeat defendants

The headline test keeps repeat corporate defendants. The question is what happens to this motion in this court, and the same company is sued more than once. Dropping every company seen in training would turn the test into a test about first-seen name strings.

A sensitivity score drops test rows whose normalized corporate-movant name appears in training. The report gives the number dropped and the share of test `y_relief` removed. If the AUC gain on the headline test disappears on this sensitivity, the result is a name effect and the report says so. The sensitivity does not replace the headline and does not, by itself, fail the gate.

## 3. Baselines and metrics

### Tasks scored

- **Binding.** Binary `y_relief` (`granted` or `granted_in_part` versus `denied`). ROC-AUC and Brier score.
- **Required, not the binding bar.** Three-way macro-F1 on `granted`, `granted_in_part`, and `denied`. Macro one-vs-rest ROC-AUC. Multiclass Brier score, the mean squared error of the three-class probability vector.
- **Descriptive.** The leave modifier cross-tab. No model is required to predict leave in v1.

Macro-F1 gives equal weight to the three classes, so a model can rank "any relief" well and still fail to separate partial grants from full grants. That is why macro-F1 is reported and why it is not the binding bar. An absolute F1 cutoff is not set. This protocol does not know the class mix in the cohort, because the extract has not been built.

### Baselines

All baselines use training rows only. Each baseline emits a probability of `y_relief`, and a three-class probability vector, equal to the training frequency in a cell. A constant score has ROC-AUC 0.5. Beating 0.5 only means the score is not constant.

| Name | Cell | Backoff |
| --- | --- | --- |
| `constant` | All training rows | None |
| `nos_rate` | The row's nature of suit | `constant` if that code has fewer than 40 training motions |
| `court_rate` | The row's `court_id` | `nos_rate` if that court has fewer than 40 training motions |
| `judge_rate` | The row's `assigned_to_id` | `court_rate` if the judge is unknown or has fewer than 40 training motions |

Forty is the backoff floor. At a proportion of one half, the standard error of a rate from 40 rows is about `sqrt(0.25 / 40) ≈ 0.079`. Below that, the court or nature-of-suit rate is the more stable story. The floor is a design choice, not an estimate of judge agreement.

The binding baseline is the best of `nos_rate`, `court_rate`, and `judge_rate` on the test set. "Best" is chosen per metric, on the test set, from those three only. `constant` is reported and is not eligible for "best." Choosing the winner on the test metric is a slightly harsh comparison. It is intentional. The model has to beat the stronger simple story, the judge's own grant rate included, not the weaker one.

For macro-F1, the baseline predicts the majority training class inside the same cell, with the same backoff. Ties go to the class with more training rows overall, then to `denied`, then to `granted`, then to `granted_in_part`.

### Primary metrics

| Metric | Direction | What it answers | Binding? |
| --- | --- | --- | --- |
| ROC-AUC for `y_relief` | Higher is better | Can the score rank motions that received any dismissal relief above motions that were denied? | Yes |
| Brier score for `P(y_relief)` | Lower is better | Are those probabilities close to the outcomes, not just well ordered? | Yes |
| Macro-F1 on the three-way label | Higher is better | Equal weight on granted, granted in part, and denied | Reported |
| Macro one-vs-rest ROC-AUC | Higher is better | Ranking quality for each class against the other two | Reported |
| Multiclass Brier | Lower is better | Whether the three probabilities are jointly close to the class | Reported |

Also report, as descriptive and not as gates: precision and recall for `y_relief` at the training-prevalence threshold, the test prevalence, and a reliability table with ten bins of predicted `P(y_relief)`. Empty bins are shown as empty. Expected calibration error is printed beside the table. It is not a separate gate. Brier already scores calibration and refinement together.

If binary Brier beats the baseline and multiclass Brier does not, the report says the probabilities separate "any relief" and do not separate partial grants from full grants. That sentence is required. The run can still pass the binding gate.

### Numeric bar

Compute a percentile cluster bootstrap with 1,000 resamples of test dockets, seed 20261007. Motions on the same docket stay together in a resample. For AUC and for macro-F1, the difference is model minus best baseline. For Brier, the difference is best baseline minus model, so a positive number still means the model is better.

The run succeeds on the modeling gate only if all of the following are true:

- Test ROC-AUC of the model on `y_relief` is greater than the best baseline AUC, and the 95% bootstrap interval for the difference has a lower bound greater than 0.
- Test Brier score of the model on `y_relief` is lower than the best baseline Brier score, and the 95% interval for that improvement has a lower bound greater than 0.
- The interval for the model's AUC itself has a lower bound greater than 0.5.

There is no absolute AUC cutoff. A cutoff such as "AUC at least 0.70" would be invented. This protocol does not know the court-level grant rates, because the docket extract has not been built. The baselines are the numbers the model has to beat, and they are computed from the training years of the same extract.

Macro-F1 does not have to clear its baseline for the modeling gate to pass. If it does not, the report says the model failed the three-way task and passed only the binary ranking task. Calling that a three-way outcome classifier is a failure of description.

Also report a judge-clustered bootstrap, same seed and same 1,000 resamples, as a sensitivity. If the docket-clustered interval clears 0 and the judge-clustered interval covers 0 or less, the result is concentrated in a few judges. The report says so. The gate stays the docket-clustered interval.

### Which model is scored

Two models are fit.

1. **Metadata.** Court, circuit, nature of suit, cause, dates and counts from the spec's allowed list, judge when known, movant counsel when known, and missingness indicators. No document text.
2. **Metadata plus text.** The same fields, plus the allowed text features from the complaint, the motion, the opposition, and the reply, each with a missingness indicator.

The binding score is model 2, scored on every labeled test row. A row with no complaint file still receives a prediction. Dropping that row from the headline is a failure.

A second table scores model 2 only on test rows where the complaint file and the motion memorandum are both `is_available`. Baselines for that table are refit on the training rows that meet the same availability rule. That table is a coverage result. It becomes the headline only if it is the same set of rows as the full test set.

The report prints the share `is_available` for the complaint, the motion memorandum, the opposition, and the order, in train and in test. This protocol does not guess those shares.

## 4. Slices

Report these slices on the full test set. For each slice print `n`, the count of `y_relief = 1`, the model AUC, the best baseline AUC, and the docket-clustered bootstrap interval for the difference.

| Slice | Rule |
| --- | --- |
| Nature of suit | One row for each of 160, 410, 480, and 850. |
| `court_id` | One row per district. |
| Circuit | One row per circuit, using the checked-in district-to-circuit map from the spec. |
| Judge | Rate only, and only under the minimums below. No "the model won for this judge" claim. |
| Text availability | Complaint and motion both available, versus either one missing. |
| Grounds | 12(b)(6) only, versus also 12(b)(1) or 12(b)(2). |
| Origin of the label text | Disposition read from the entry description, versus read from the order or opinion because the description was silent. |

**Minimum n.**

- A rate is printed only when the slice has at least 50 test motions and at least 10 motions with `y_relief = 1` and 10 with `y_relief = 0`. Otherwise the cell says `not reported` and includes `n`. At a proportion of 0.3, the standard error of a sample of 50 is about `sqrt(0.3 × 0.7 / 50) ≈ 0.065`. Fifty is enough to show a rate. It is not enough to declare that the model beat the baseline inside that court.
- A model-versus-baseline AUC comparison for a slice is printed only when the slice has at least 200 test motions and at least 20 of each binary class.
- Three-way macro-F1 for a slice is printed only when the slice has at least 200 test motions and at least 20 motions in each of the three classes.

No slice is pooled into "all corporate motions" to hide a court or a nature of suit that failed the minimum. The overall test score remains the headline.

Refits that drop one training year at a time are reported as a stability check. A sign change in the AUC difference in any dropped-year refit is reported as instability. It does not by itself fail the gate, and it blocks any sentence that says the result is stable across years.

If the entire AUC gain disappears when one nature of suit, or one court, above the comparison minimum is removed, the result is a slice effect. Say which slice. Do not state a cohort-wide finding.

## 5. Pipeline correctness

These checks are part of done. They are specified now so the build has a target. They are not implemented in this change.

### Data validation

Before fitting, the loader rejects the extract if any of the following fail:

- Every scored row has a docket id, a motion entry id, an order entry id, a motion `date_filed`, an order `date_filed`, a `court_id`, a nature-of-suit code in {160, 410, 480, 850}, and a label in {`granted`, `granted_in_part`, `denied`}.
- The order's timestamp is strictly after the motion's timestamp under the spec's same-day rule.
- No feature row contains the order entry id, the order description, or the order document id.
- `needs_text`, `link_ambiguous`, `movant_unknown`, withdrawn, moot, and Rule 12(d) rows are absent from the scored cohort and present in the funnel counts.
- Party-type was actually present on the parties payload. If it was not, the run stops before a corporate filter is guessed from the caption.
- Training and test windows each contain at least one scored row. If a window is empty, the run stops.
- Duplicate motion ids inside a split are zero. A docket id in both splits is zero.

### Label-derivation tests

Unit tests use tiny hand-written entries and no network. They cover at least:

- "ORDER granting 15 Motion to Dismiss for Failure to State a Claim" links to document 15 and labels `granted`.
- "ORDER denying 15 Motion to Dismiss for Failure to State a Claim" labels `denied`.
- "ORDER granting in part and denying in part 15 Motion to Dismiss for Failure to State a Claim" labels `granted_in_part`.
- The same grant, plus "with leave to amend within 21 days," stays `granted` and sets `leave_granted`.
- "Dismissed with prejudice" sets `leave_denied`. "Dismissed without prejudice" sets `leave_not_stated`.
- A description containing "Text of Proposed Order" is not a ruling, including the IBM / Red Hat pattern in the spec.
- A report and recommendation is not a ruling. A later district-judge order that adopts it is the ruling.
- A motion entry that cites only Rule 12(b)(2) is excluded. A motion that cites 12(b)(6) and 12(b)(2) is kept and flagged `also_12b2`.
- "Denied as moot" and "withdrawn" are excluded, not labeled `denied`.
- An entry filed on the order's calendar date is excluded from features when either timestamp lacks a time. It is kept when both times exist and the entry's time is earlier.
- A brief filed the day after the order is excluded from features.
- `Equifax, Inc.` as a defendant is corporate. `Securities and Exchange Commission` is not. `CT Healthcare Holdings, LLC` as a plaintiff is not a corporate movant. `UNITED STATES OF AMERICA` is not. A blank role is a stop, not a guess.
- The current opinion-text labeler, given an order that says "the motion is granted" and a complaint that says "dismissed," is not the function this task calls.

### Leakage test

A fixture of 40 synthetic motions is built so that the three-way label is a function of the word `granted` or `denied` inside the order description, and of nothing in the complaint or the motion. The feature builder is given the order description, the order text, a later docket entry, and an opinion that cites the outcome, along with the allowed pre-order fields.

The synthetic complaints and motions do not contain `granted`, `denied`, or `dismissed`. The test fails if any forbidden string appears in a feature column name or a feature cell. That is the whole leakage check. A small fixture AUC would move around by chance and is not used.

A second fixture uses a pre-order feature (court) that determines the label, with the order text present and uninformative. The builder must retain the court feature. This stops a leakage filter that drops every column.

### One command

The build adds one command, documented in the README when the build happens:

```bash
courtpipe evaluate-mtd --extract path/to/mtd_extract.jsonl --report data/model-eval/mtd_report.json
```

The command downloads nothing by itself. The operator passes a local extract produced by a separate fetch that reads `COURTLISTENER_API_KEY` from the environment. The report JSON includes:

- the git commit, the Python version, and the seed
- the snapshot date of the extract and the SHA-256 of the extract file
- the funnel counts from the spec
- the audit summary, kappa, the Wilson interval, and whether gate 1 passed
- the test metrics, the bootstrap intervals, the judge-clustered sensitivity, and the slice table
- the availability shares for complaint, motion, opposition, and order
- the repeat-defendant sensitivity

A second run on the same extract and seed produces the same metrics. The command exits non-zero if a validation check fails, if the leakage test fails, or if the label-audit gate was not passed. A passed command writes the report even when the modeling gate fails. A negative result uses the same fields as a positive one.

The API key does not appear in the report. A test greps the report for the token value when the variable is set in the test environment, and fails if it is found.

### Live smoke test

When `COURTLISTENER_API_KEY` is present, a separate command performs one authenticated read of docket entries for a single docket id pinned in the test file. It checks that the response is 200, that at least one entry has `description` and `date_filed`, and that at least one nested RECAP document has an `is_available` field. It then reads parties for that docket and records the top-level keys. It does not train. It does not write entry text into the training extract. It does not print the token.

The docket id is chosen once from a public search hit after the key works, then committed as an integer. No document body is committed.

Observed without a token on 7 October 2026: `GET /api/rest/v4/dockets/`, `/parties/`, `/docket-entries/`, `/recap-documents/`, and `/opinions/` each returned 401, `Authentication credentials were not provided.` The smoke test cannot be claimed to pass until it has been run with the rotated key.

The opinion-pipeline tests that already exist stay as they are. They check disposition-word extraction on synthetic opinions. They are not evidence about motions to dismiss. The fixture scores in the README are 20 synthetic snippets. They are not a grant rate.

### What can be checked before the key exists

Public search still answers, and the counts in the spec can be re-requested. Fixture tests of the labeler, the corporate-name rules, and the leakage filter can be added and run in CI with no network. Those checks are necessary and they are not gate 1. Gate 1 starts when an authenticated extract exists and a person has applied the rubric to 120 rows.

## 6. What failure looks like

Report these in plain language if they happen. Do not replace them with a chart of training accuracy.

| Outcome | What it means |
| --- | --- |
| Three-way Wilson lower bound at or below 0.70, or kappa below 0.60, or reader agreement at or below half of the readable rows | The label is not usable. Stop. Do not fit a binary model to paper over it. |
| Three-way lower bound above 0.70 and at or below 0.80, and binary lower bound above 0.85 | The three-way label fails. A binary `y_relief` model may be reported only with that sentence attached. |
| More than 20% of the audit sample is `insufficient_record`, or fewer than 80 rows are readable | The audit was not done. Stop. |
| The feature table contains order text, a later entry, or an opinion that cites the outcome | The run is invalid. A high test AUC in that condition is leakage. |
| Model AUC interval covers 0.5, or the difference versus the best baseline covers 0 or less | The pre-order material does not rank relief better than judge, court, and nature of suit. That is "not enough signal," not a tuning miss. |
| Brier score does not improve on the best baseline | The scores are not usable probabilities even if the ranking looks better. Report the ranking and do not describe the output as a calibrated risk. |
| Binary metrics pass and macro-F1, or multiclass Brier, does not beat its baseline | The model separates any relief from denial and does not separate the three classes. Say that. |
| The entire AUC gain disappears when one nature of suit or one court above the minimum is removed | The result is a slice effect. Name the slice. |
| The entire AUC gain disappears when repeat defendants are dropped, or when the bootstrap clusters by judge | The result is a name effect or a handful of judges. Say which. |
| The full-test score fails and the available-PDF subset passes | The result describes motions whose files were in RECAP. It does not describe the cohort. |
| The parties payload has no party type, and a caption rule was used instead | The corporate filter was not the one in the spec. The run is invalid. |
| Someone quotes a CourtListener `count`, the README fixture scores, or an FJC settlement code as a motion-to-dismiss grant rate | Those numbers are about other tasks. The search counts in the spec are archive hits. The README fixture is 20 synthetic snippets. `DISP` is the settlement track. |

A negative result on the modeling gate is a completed evaluation. It is recorded in `mtd_report.json` with the same fields as a positive result. The README does not get a sentence that says the model predicts motion-to-dismiss outcomes unless the label-audit gate passed and the modeling gate passed.
