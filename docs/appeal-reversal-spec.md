# Spec: appeal affirmance and reversal

Status: proposal. This document does not add code, data, or a model. Build only after the choices at the end are approved.

This is a fourth track. It does not change the opinion labeler, the review queue, the Integrated Database settlement track in `docs/idb/`, or the securities class-action proposal in `docs/SPEC.md`. The motion-to-dismiss proposal is a separate document and is not the plan here. The tracks do not share a label, a clock, or a training file.

No Granola notes in the last 30 days discussed this project. The proposal is from the current courtpipe code, public CourtListener responses collected on 10 October 2026, the CourtListener bulk-export script on that date, the CourtListener terms and REST API docs, and the Administrative Office Table B-5 for the year ending 30 September 2025. Counts below are figures those pages stated, JSON fields an endpoint returned, or columns in that table. This draft did not download a bulk snapshot and did not count rows in one.

## What the current pipeline actually does

`etl/transform.py` labels an opinion by searching its text, preferring the tail, for `vacate`, `reverse`, `remand`, `affirm`, and `dismiss`. `analysis/model.py` trains on court, opinion year, a word-count bucket, and three fields taken from that same labeling pass: `disposition_zone_found`, `evidence_contains_strong_phrase`, and `evidence_match_position`.

That is outcome extraction. The words the labeler matches are the outcome, and several model features are functions of those words. The fine labels the code emits are `affirmed`, `dismissed`, `reversed`, `vacated`, `remanded`, `mixed`, and `other`. An appellate opinion that says "we reverse" is the event this track wants to predict, so that opinion cannot be an input. v1 leaves the opinion labeler, the review queue, and the existing charts as they are.

## Question, and why it matters

At a declared time before a federal court of appeals decides an appeal from a district-court judgment, estimate the probability that the court disturbs that judgment.

The binary event is `y_disturb = 1` when the appellate disposition reverses, vacates, or remands the district ruling, or mixes an affirmance with any of those, and `y_disturb = 0` when the disposition is a pure affirmance. Vacate and remand count on the disturb side. The fine labels below stay on every row. A model that only separates pure affirmances from everything else has to say so when mixed and remand rows are what produced the score.

Why this question:

- Affirmance is the common ending in the national merits tables, so a system that always predicts affirmance looks accurate and is useless. The bar below is ranking and calibration against circuit and case-type rates, not raw accuracy.
- The appellate opinion states the ending in its own text. A model that reads that text is the current extractor, not a forecast.
- The same corpus can support a later issue-level coder. v1 does not pretend a single disposition string is an issue split.

Table B-5 of the [Statistical Tables for the Federal Judiciary](https://www.uscourts.gov/sites/default/files/document/jb_b5_0930.2025.pdf), 12 months ending 30 September 2025, is a sanity check and is not this cohort. The table excludes the Federal Circuit. One footnote says the Affirmed column includes appeals affirmed in part and reversed in part. Another says the printed percent reversed leaves out original proceedings. On the national row, 24,318 appeals were terminated on the merits: 16,900 affirmed or enforced, 2,943 dismissed, 1,845 reversed, 246 remanded, 158 other, and 2,226 certificates of appealability. Those six merit columns sum to 24,318. The table prints 7.9 percent reversed for that national row, not the ratio 1,845 / 24,318. Other private civil is printed as 11.5 percent reversed, on a row whose merit columns are 647 reversed and 5,602 terminated on the merits. U.S. prisoner petitions are printed as 3.9 percent reversed, on a row whose merit columns are 57 reversed and 1,444 terminated on the merits. The table prints 36.1 percent reversed for the D.C. Circuit and 5.7 percent reversed for the Second Circuit. Those differences are why a single national accuracy number is the wrong bar, and why the model has to beat a circuit rate and a case-type rate. They are not labels, and they are not this extract's measured rates.

## Unit of prediction

v1 predicts one appeal, not one issue.

One scored row is one appellate opinion cluster on one appellate docket, and that docket is an appeal from a federal district court. The cluster's disposition, or the decretal paragraph when the disposition field is empty, states one judgment-level result. CourtListener does not store a separate field per issue ("affirmed on liability, reversed on damages"). Splitting a mixed disposition into issue rows would invent a taxonomy. Mixed stays one row with the fine label `mixed`.

A docket can hold more than one cluster: a merits opinion, an amended opinion, a denial of rehearing. v1 keeps the earliest cluster on that docket that receives a fine label other than `needs_text`. Later clusters on the same docket are `later_cluster`. They are counted and they are not scored. If two clusters on the same docket and the same `date_filed` receive different fine labels, the docket is `cluster_conflict` and leaves the scored set.

Cross-appeals and consolidated appeals stay one row. The row describes what the disposition string says happened to the judgment. It does not assign a winner per party.

Issue-level prediction is a later track. It needs a claim schema and a reading of the opinion beyond the decretal sentence. It is out of v1.

## Labels

The label source is the appellate cluster's `disposition` field. That field is free text. The bulk export includes it on `search_opinioncluster`. The public opinion-search hit inspected on 10 October 2026 did not include a `disposition` key. A search for `disposition:reversed` returned `count` 0. That zero is a failed filter, not a count of reversals.

If `disposition` is blank, the labeler may read the last 1,500 characters of the lead or combined opinion and nothing earlier in that opinion. `label_source` is `disposition_field` or `decretal`. The characters used for the label are stored with the label. They are not features. If both sources are blank, the label is `needs_text`. The row is counted in the funnel and omitted from training and test.

Normalize the chosen string by lowercasing it and turning punctuation into spaces.

| Flag | Pattern |
| --- | --- |
| AFF | `\baffirm` |
| REV | `\brevers` |
| VAC | `\bvacat` |
| REM | `\bremand` |
| DIS | `\bdismiss` |
| COA | `certificate of appealability` |
| MOD | `\bmodif` or `\bamended\b` |

Apply the first matching rule.

| Order | Condition | Fine label | Binary role |
| --- | --- | --- | --- |
| 1 | COA is set, and REV and VAC are not | `coa` | Excluded. A certificate ruling is not a merits disposition of the district judgment. |
| 2 | DIS is set, and AFF, REV, VAC, and REM are not | `dismissed` | Excluded. The appeal went out on jurisdiction, timeliness, or a voluntary dismissal. That is not an affirmance of the district ruling. |
| 3 | AFF is set, and REV or VAC is set | `mixed` | `y_disturb = 1`. The judgment was not left as it stood. |
| 4 | DIS is set, and any of AFF, REV, VAC, or REM is set | `mixed` | `y_disturb = 1`. |
| 5 | `in part` occurs with AFF and REM, and REV and VAC are not set | `mixed` | `y_disturb = 1`. |
| 6 | AFF and MOD are set, and REV and VAC are not | `mixed` | `y_disturb = 1`. "Affirmed as modified" is not coded as a pure affirmance. |
| 7 | REV is set | `reversed` | `y_disturb = 1`. Includes "reversed and remanded." |
| 8 | VAC is set | `vacated` | `y_disturb = 1`. Includes "vacated and remanded." |
| 9 | AFF and REM are set, and REV and VAC are not | `affirmed_with_remand` | Excluded from the headline binary. See below. |
| 10 | REM is set, and AFF is not | `remanded` | `y_disturb = 1`. |
| 11 | AFF is set | `affirmed` | `y_disturb = 0`. |
| 12 | Anything else, including a bare "enforced" | `unmapped` | Excluded. Listed. Not folded into affirmance or reversal. |

Examples the unit tests must lock, once a build exists:

- "The judgment of the district court is affirmed." → `affirmed`
- "Reversed." → `reversed`
- "Reversed and remanded." → `reversed`
- "Vacated and remanded." → `vacated`
- "Remanded." → `remanded`
- "Affirmed and remanded." → `affirmed_with_remand`
- "Affirmed in part, reversed in part, and remanded." → `mixed`
- "Affirmed in part and remanded in part." → `mixed`
- "Affirmed as modified." → `mixed`
- "Appeal dismissed." → `dismissed`
- "Dismissed for lack of jurisdiction." → `dismissed`
- "Certificate of appealability denied." → `coa`

`y_disturb = 1` for `reversed`, `vacated`, `remanded`, and `mixed`. `y_disturb = 0` for `affirmed` only. `affirmed_with_remand`, `dismissed`, `coa`, `unmapped`, and `needs_text` are out of the headline score and are counted.

### Why affirmed-and-remanded is excluded

"Affirmed and remanded" affirms and also sends the case back. Coding it as a reversal treats a remand for proceedings consistent with the opinion as a win for the appellant. Coding it as an affirmance ignores the remand. Table B-5's footnote puts "affirmed in part and reversed in part" inside Affirmed, which is this spec's `mixed`, and Table B-5 keeps a separate Remanded column. The table does not say which column receives "affirmed and remanded." v1 does not guess.

Two sensitivities are pre-registered. Sensitivity A scores `affirmed_with_remand` as `y_disturb = 0`. Sensitivity B scores it as `y_disturb = 1`. Both are printed. Neither becomes the headline after the test score is seen. Swapping the headline to the sensitivity that passes is a failure.

## Clock

The information set is whatever is dated on or before the clock. The clock is not the appellate opinion's filing date. Using that date as the clock makes "days until decision" computable, and that duration is known only because the decision exists.

1. If the appellate docket's `date_argued` is present and strictly earlier than the cluster's `date_filed`, the clock is `date_argued`.
2. Otherwise the clock is the appellate docket's `date_filed`, which is the appeal's filing date in the CourtListener docket table.
3. If neither date exists, or either date is missing in a way that fails rule 1 and leaves rule 2 empty, the row is `no_clock` and leaves the scored set.

A district-court document dated on the clock date is excluded. Bulk dates are dates, not times, so a same-day document cannot be shown to be earlier.

Time since judgment is the number of days from the district judgment date to the clock. It does not use the appellate `date_filed` of the opinion. The district judgment date is `originating_court_information.date_judgment` when that field is present, and otherwise the `date_filed` of the linked district opinion. A negative gap is `timeline_inconsistent`. The row is excluded and counted. It is not a feature.

## Permitted features

Every feature below is known at the clock, or it is missing. Missing is its own value. v1 does not impute it and does not fill it from the appellate opinion.

| Feature | Source | Rule |
| --- | --- | --- |
| Circuit | Appellate `court_id` | One of `ca1`–`ca11`, `cadc`, `cafc`. |
| Case type | Docket `nature_of_suit`, else `appellate_case_type_information`, else `cause` | Categorical. A blank stays blank. v1 does not map these strings onto the Administrative Office's nature-of-proceeding rows. |
| District court | `appeal_from_id`, else the court on the linked originating docket | A federal district court. The generic parent `usdistct` is not a court feature. |
| District judge | `originating_court_information.assigned_to_id` or `ordering_judge_id`, else the district docket's `assigned_to_id` | An id, used inside the model. The report does not name the judge. See the ethics section. Unknown stays unknown. |
| Prior-ruling type | District cluster `disposition`, only when that cluster's `date_filed` is strictly before the clock | Coarse tokens only: `dismissed`, `summary_judgment`, `injunction`, `sentence`, `jury`, `bench`, `other`, `missing`. This is not the appellate crosswalk and it is not the label. |
| Appellant identity class | A party role, on a record dated on or before the clock, that identifies who filed the notice of appeal | Classes: `government`, `corporate`, `individual`, `unknown`. The quarterly bulk script does not export parties or docket entries, so bulk-only v1 leaves this `unknown` unless a pre-decision field on the docket states it. |
| Panel composition | Judges named on an oral-argument record whose `date_argued` is on or before the clock | Allowed only from that pre-decision record. If the argument record has a date and no judge names, panel is missing. |
| Argument held | `date_argued` on or before the clock | Boolean. Days from the appeal's filing date to `date_argued` are allowed when both are on or before the clock. |
| Briefing-stage docket entries | Entry date on or before the clock | Permitted in principle: existence of a brief, a reply, and pre-clock page counts. The bulk export does not contain docket entries. v1 does not page the entries API to build them. See data sources. |
| District opinion length | `page_count`, or word count of `plain_text`, of the linked district opinion | The linked opinion is the latest district cluster on the originating docket with `date_filed` strictly before the clock. No link means missing, not zero. |
| District opinion citations | Rows in the citation map whose citing opinion is that district opinion | Those cites were in the district opinion when it was filed. |
| District opinion text | `plain_text` of that same district opinion | Bag of words in the second model only. A missing file is a missingness indicator, not an empty document. |
| Time since judgment | District judgment date to the clock, in days | Defined above. |

The first model uses only fields that can be filled from the bulk tables for every scored row, with an explicit missing value. The second model adds district-opinion length, outgoing citation count, and the bag of words, each with a missingness indicator. The headline score is the second model on every labeled test row. A row with no district opinion still receives a prediction. A score restricted to rows that have district-opinion text is a coverage result. It is not the cohort result.

## Forbidden features

These reveal the outcome or exist only because the appellate opinion was published. They stay in the label store or out of the extract. A test must show they are absent from the feature matrix.

- The appellate opinion text, including `plain_text`, `html_with_citations`, the search snippet, headmatter, and the decretal excerpt used as the label.
- Cluster fields written from that opinion: `disposition`, `syllabus`, `headnotes`, `summary`, `posture`, `procedural_history`, `history`, `judges`, `citation_count`, `scdb_decision_direction`, and the panel join tables `search_opinioncluster_panel` and `search_opinioncluster_non_participating_judges`.
- Any citation-map row whose citing opinion is an opinion on the appellate cluster. The appellate opinion's own `cites` list is the same leak.
- Citation-map rows that cite the district opinion when the citing cluster's `date_filed` is after the clock. Later attention to the district opinion is not a pre-decision fact. The citation map has no edge date. The citing opinion's cluster date is the date.
- Parentheticals describing the appellate opinion, and parentheticals whose describing opinion is dated after the clock.
- Appellate `date_terminated`, `date_last_filing`, and any duration that subtracts a start date from the opinion's `date_filed`.
- The current courtpipe outcome fields: `outcome_code`, `outcome_label_fine`, evidence, confidence, and disposition-zone flags.
- Judge names, reversal rates, or ranks in any published table, chart, or JSON field. The id may sit in the matrix. The report may not.
- Caption order as a stand-in for who appealed. In a criminal appeal the caption is often "United States v. Defendant" when the defendant appealed. That proxy is forbidden. Unknown stays unknown.
- The Administrative Office percent-reversed figures. They are a sanity check after the extract exists. They are not training labels.
- Case-law embeddings of the appellate opinion. The published embedding dump is an embedding of opinion text, which is the label source.

`citation_count` on the appellate cluster counts later cites to the decision being predicted. It grows after the clock. It is leakage even when the column is easy to join.

## Baselines

All baselines use training rows only. The score is `P(y_disturb)`.

| Name | Probability assigned to a test row |
| --- | --- |
| `constant` | The training rate of `y_disturb`, for every row. This is the probability form of the majority-class predictor. Its ROC-AUC is 0.5. |
| `majority_class` | The training majority class, as a hard label, for an accuracy report only. |
| `circuit_rate` | The training rate in the row's circuit. If that circuit has fewer than 50 training rows, `constant`. |
| `case_type_rate` | The training rate for the row's case-type value. If that value has fewer than 50 training rows, `constant`. |
| `circuit_case_type_rate` | The training rate for that circuit and case type when the cell has at least 50 rows. Otherwise `case_type_rate`, then `circuit_rate`, then `constant`. |
| `judge_rate` | The training rate for the district-judge id when that id is known and has at least 40 training rows. Otherwise `circuit_rate`. |

Fifty is the backoff floor for circuit and case type. At a proportion of 0.10, the standard error of a rate from 50 rows is about `sqrt(0.10 × 0.90 / 50) ≈ 0.042`. Below that, the constant rate is the more stable story. Forty is the judge floor, carried over as a design choice from the motion-to-dismiss protocol so a handful of appeals cannot define a judge rate. Neither floor is a measured affirmance rate.

The binding baseline is the best of `circuit_rate`, `case_type_rate`, `circuit_case_type_rate`, and `judge_rate` on the test set. "Best" is chosen per metric, on the test set, from those four. `constant` is reported and is not eligible. Choosing the winner on the test metric is harsh on purpose. The model has to beat the stronger simple story, including the district judge's own historical disturb rate, not the weaker one.

`majority_class` accuracy is printed so a reader can see the trap. Table B-5's printed reversal shares are small next to its affirmance column, and the Affirmed column is the large one. A test set with that shape makes "always predict affirmance" accurate and silent about a particular appeal. Accuracy is not a gate. Beating majority-class accuracy is not a pass.

For a reported macro-F1 on the fine labels that remain in the binary (`affirmed`, `reversed`, `vacated`, `remanded`, `mixed`), the baseline predicts the majority training class inside the same cell, with the same backoff. Ties go to the class with more training rows overall, then to `affirmed`.

## Metrics and success bars

Nothing here is a measured result. The numbers are sample-size rules, pre-registered floors, or published aggregates cited above.

### Modeling metrics

| Metric | Direction | What it answers | Binding? |
| --- | --- | --- | --- |
| ROC-AUC for `y_disturb` | Higher is better | Can the score rank appeals that disturb the judgment above appeals that affirm it? | Yes |
| Brier score for `P(y_disturb)` | Lower is better | Are the probabilities close to the outcomes? This is the calibration bar. | Yes |
| Reliability table, ten bins, and expected calibration error | Descriptive | Where the probabilities are over- or under-confident. A bin with fewer than 30 test rows is `not reported`. | No |
| Accuracy against `majority_class` | Descriptive | Shows the base-rate trap. | No |
| Macro-F1 on the five in-binary fine labels | Higher is better | Equal weight on affirmed, reversed, vacated, remanded, and mixed. | Reported |

Precision and recall for `y_disturb` at the training-prevalence threshold are descriptive. They are not gates.

### Numeric bar

Percentile bootstrap, 1,000 resamples of test dockets, seed `20261010`. Appeals on the same docket stay together. For AUC, the difference is model minus best baseline. For Brier, the difference is best baseline minus model, so a positive number means the model is better.

The modeling gate passes only if all of the following are true:

- Test ROC-AUC is greater than the best baseline AUC, and the 95 percent interval for the difference has a lower bound greater than 0.
- Test Brier score is lower than the best baseline Brier score, and the 95 percent interval for that improvement has a lower bound greater than 0.
- The interval for the model's own AUC has a lower bound greater than 0.5.

There is no accuracy floor. There is no absolute AUC floor such as 0.70. An absolute cutoff would be invented. This protocol does not know the circuit-level disturb rate in the CourtListener extract, because the snapshot has not been opened. Table B-5 shows that the national reversal share and the circuit shares are different numbers, and that the Affirmed column is not this spec's pure affirmance. The baselines fit on the training years are the numbers to beat.

Macro-F1 does not have to clear its baseline for the gate to pass. If it does not, the report says the model failed the five-way task and passed only the binary task. Calling that a disposition classifier is a failure of description.

If AUC clears the bar and Brier does not, the report may say the score ranks appeals. It may not call the output a calibrated risk.

A negative result is a completed evaluation. It is written with the same fields as a positive result. The README does not gain a sentence that says the model predicts reversal unless the label-audit gate and the modeling gate both passed.

### Which model is scored

1. **Metadata.** Circuit, case type, district court, district judge id when known, prior-ruling type, appellant class, argument-held, days from filing to argument, time since judgment, and missingness indicators. No opinion text.
2. **Metadata plus district-opinion text.** The same fields, plus length, outgoing citation count, and a bag of words from the linked district opinion.

The binding score is model 2 on every labeled test row. Baselines for the coverage table are refit on the training rows that have a linked district opinion. That table is a coverage result.

The report prints the share of train and test rows with a linked district opinion, a non-missing judge id, a non-missing panel, and a known appellant class. This protocol does not guess those shares.

## Temporal validation

The split key is the appellate cluster's `date_filed`, the decision date. Features still have to respect the clock, which is earlier than that date. An opinion filed in the test window can use a district judgment from the training window. It cannot use another appellate decision from the test window. Baselines and both models are fit on the training period only. The test period is scored once.

Let Y be the last complete calendar year in the snapshot. A year is complete when the snapshot's generation date, taken from the bulk filename, is on or after 1 January of the next year. The build records the filename date and Y. It does not hard-code a year from this draft.

- Training decisions: every appellate `date_filed` in a year before Y−3.
- Test decisions: years Y−3 through Y−1.
- Quarantine: year Y, and any later partial year. Extracted, counted, and not scored. Not used to choose features, thresholds, or the target.

If the snapshot is generated in October 2026 and contains decisions through 2025, the illustration is: train through 2021, test 2022–2024, quarantine 2025. The illustration is not a finding about the file.

The one-year quarantine is a design choice. The bulk files are quarterly snapshots, not a feed, and opinions can land in the database after their `date_filed`. Scoring the newest complete year would favor whatever the snapshot had finished ingesting. Three test years are a design choice so a circuit slice can clear the minimums below. Neither choice is a measured publication lag.

If the test window has fewer than 200 rows with `y_disturb = 1`, move the test window and the quarantine back one year, once, and record the move. Do not keep moving until the window passes. Two hundred positives is a design floor so the bootstrap is not a handful of reversals. It is not a forecast of how many reversals the extract contains.

Fit nothing on the quarantine. Retuning after a test score, including promoting sensitivity A or B to the headline, invalidates the run.

### No docket leakage

The case key is the appellate docket id. It appears in only one split. Later clusters are already unscored.

If `parent_docket_id` is present, every docket in that family is one group. The group takes the side of its earliest decision date. If that rule would put any member in the test period and any member in training, the whole group goes to training and is removed from the test score. The count is reported.

### Repeat captions

Parties are not in the bulk export, so v1 cannot drop repeat appellants by party id. After the temporal split, drop from the test set every row whose normalized appellate `case_name` (uppercase, punctuation to spaces) also appears in training. The report states how many rows were dropped and what share of test `y_disturb = 1` that removed. A secondary score on the dropped rows may be printed. It is not the success score. A repeated caption is a weak proxy for a repeated party. The report says that.

## Label-audit protocol

The audit asks whether the crosswalk matches a written rubric applied by a person. The auditor reads the disposition string and, when `label_source` is `decretal`, the decretal excerpt and no earlier page. The auditor does not use a later rehearing denial, a news article, or Table B-5 to decide the label.

### Rubric

- **Affirmed** if the court affirms and does not reverse, vacate, remand, modify, or dismiss any part of the appeal.
- **Reversed** if the court reverses, including when it also remands, and does not also affirm.
- **Vacated** if the court vacates, including when it also remands, and does not reverse and does not also affirm.
- **Remanded** if the court remands and does not affirm, reverse, or vacate.
- **Affirmed with remand** if the court affirms and remands, without reversing, vacating, modifying, or using "in part."
- **Mixed** if the court affirms in part and disturbs in part, dismisses in part and decides in part, or affirms as modified.
- **Dismissed** if the appeal is dismissed and the court does not affirm, reverse, vacate, or remand the judgment.
- **COA** if the ruling is only a certificate of appealability.
- **Unmapped** if the text is present and none of those descriptions fit.
- **Insufficient record** if the auditor cannot read a disposition sentence. These rows stay in the "could we check" count and leave the accuracy denominator. They are not matches.

Two people label independently. Disagreements are adjudicated by discussion, and the adjudication is the gold label. The report includes the confusion table, raw agreement, and Cohen's kappa on the fine label, computed before adjudication.

If kappa is below 0.60, stop before fitting. The 0.60 line is a design choice: below it, adjudication would be inventing a label rather than cleaning small disagreements. It is not a measured kappa. If the two readers assign the same fine label on at most half of the rows both marked readable, stop as well.

### Sample

Draw 120 scored-cohort rows after the automatic label is assigned and before any model is fit. Seed `20261010`.

| Automatic fine label | Rows |
| --- | --- |
| `affirmed` | 30 |
| `reversed` | 25 |
| `vacated` | 15 |
| `remanded` | 10 |
| `mixed` | 20 |
| `affirmed_with_remand` | 10 |
| `dismissed` | 10 |

If a stratum has fewer rows than its quota, take all of them and report the shortfall. Within each stratum, spread the draw across circuits as evenly as those rows exist.

One hundred twenty is a design choice. At a sample proportion of 0.80, a simple random sample of 120 has a standard error of about `sqrt(0.80 × 0.20 / 120) ≈ 0.037`. That width can separate a crosswalk that matches the rubric about four times in five from one that matches it about two times in three. It is not a promise that the true accuracy sits inside any particular band. The strata force the audit to read reversals, vacaturs, remands, mixed dispositions, affirmed-and-remanded, and dismissals even when affirmances dominate.

If fewer than 80 rows have a readable gold label, the interval is too wide for the bar below. Stop.

### Accuracy floors

On rows whose gold label is not `insufficient record`, fine-label accuracy is the share whose automatic fine label equals the gold fine label. Gold `unmapped` on a row the labeler sent to a scored class is a miss. Report a 95 percent Wilson interval.

The fine label is usable only if the lower end of that interval is above 0.80.

The source is a disposition sentence that is supposed to state the result. That is a firmer source than an Integrated Database clerk code, where the floor in `docs/idb/EVALUATION.md` is a Wilson lower bound above 0.50. It is not a 0.95 floor. Mixed language, "as modified," and "in part" are genuinely ambiguous, and this protocol has not measured how common they are. A lower bound of 0.80 is the point at which label noise is no longer the main explanation for a later model error. The threshold is the gate. The measured interval is the result.

On the same readable rows whose gold fine label is `affirmed`, `reversed`, `vacated`, `remanded`, or `mixed`, binary accuracy is the share whose automatic `y_disturb` equals the gold `y_disturb`. The binary collapse is usable only if the lower end of its Wilson interval is above 0.85. The collapse is mechanical once the fine label is right, so the binary floor is tighter. A fine-label pass with a binary failure means the collapse code is wrong. Stop.

Fallback, still decided before any fit:

- If the fine-label lower bound is above 0.70 and at or below 0.80, the fine label fails. A binary model may be trained only if the binary Wilson lower bound on the same readable rows is above 0.85. The report says the fine label failed.
- If the fine-label lower bound is at or below 0.70, stop. The binary model is not a rescue.

Also report, with no extra pass-fail number: per-class recall, the share of the 120 that were `insufficient record`, and the share of gold `affirmed_with_remand`.

If more than 20 percent of the 120 are `insufficient record`, the audit did not happen. The sample was drawn from rows the labeler already classified, so a sentence had already been found. If more than one in five still cannot be read, the disposition field is too thin to be a label source. Do not train. Twenty percent is a design choice for that reason.

## Slices

Report these slices on the full test set. For each slice print `n`, the count of `y_disturb = 1`, the model AUC, the best baseline AUC, and the docket-clustered bootstrap interval for the difference.

| Slice | Rule |
| --- | --- |
| Circuit | One row per circuit, including `cafc`. |
| Case type | One row per nature-of-suit or appellate case-type value that clears the minimum. |
| Decision year | One row per test year. |
| Prior-ruling type | The coarse district tokens. |
| District opinion | Linked and not linked, separately. |
| Clock | Argument date, versus appeal filing date. |
| Label source | `disposition_field` versus `decretal`. |

A rate is printed only when the slice has at least 50 test rows and at least 10 rows of each binary class. Otherwise the cell says `not reported` and includes `n`. At a proportion of 0.10, the standard error of a sample of 50 is about `sqrt(0.10 × 0.90 / 50) ≈ 0.042`. Fifty can show a rate. It cannot support a claim that the model beat the baseline inside that circuit.

A model-versus-baseline comparison for a slice is printed only when the slice has at least 200 test rows and at least 30 rows with `y_disturb = 1`.

No slice is pooled into "all federal appeals" to hide a circuit that failed the minimum. The overall test score remains the headline.

Refits that drop one training year at a time are a stability check. A sign change in the AUC difference is reported as instability. It does not by itself fail the gate. It blocks any sentence that says the result is stable across years.

If the entire AUC gain disappears when one circuit above the comparison minimum is removed, the result is a circuit effect. Say which circuit.

## Fairness and judge-level modeling

District-judge identity and panel composition are allowed as inputs under the rules above. They are not allowed as published scores.

The report, the charts, the JSON, and the README must not contain:

- a named judge, a CourtListener person id, judge initials, or a panel listed with a reversal rate, an affirmance rate, a rank, a coefficient, or a partial dependence
- a sorted list from which a reader can recover those rates
- a tool or example that answers "how often does this judge get reversed"

The `judge_rate` baseline appears as one aggregate AUC and one aggregate Brier score. The same rule applies if a panel-rate diagnostic is computed: one aggregate number, no member-level table.

This track is also not a use covered by the Fair Credit Reporting Act. The CourtListener terms, last modified 5 August 2026, prohibit using the Services or information derived from them as a factor in credit, insurance, employment, government benefits, housing, or any other purpose under 15 U.S.C. § 1681b(a), and prohibit generating a consumer report. v1 does not score parties for any of those purposes. The judge rule above is narrower and is mandatory even though a judge's reversal rate is not a consumer report.

## Data sources

v1 is built from one CourtListener bulk snapshot. It is not built by paging the REST API.

### Bulk files

The [bulk legal data](https://www.courtlistener.com/help/api/bulk-data/) page, read on 10 October 2026, states that Free Law Project provides bulk files to developers, legal researchers, journalists, and the public. Files are PostgreSQL `COPY` CSV snapshots, UTF-8, with a header row, regenerated quarterly on the last day of March, June, September, and December, beginning at 3:00 AM Pacific. Each file contains the database at generation time. The page says the bulk data files are free of known copyright restrictions. It points readers at `models.py` and at HTTP `OPTIONS` for field definitions, and it notes that the API and the CSV do not always match field for field.

The export script [`scripts/make_bulk_data.sh`](https://github.com/freelawproject/courtlistener/blob/0d54b8ee5db1bf1722f7b9df9ad847d3fafa90db/scripts/make_bulk_data.sh) at commit `0d54b8ee` (committed 7 October 2026) writes those CSVs to `s3://com-courtlistener-storage/bulk-data/` with a public-read ACL. The tables that matter here, and the columns this spec relies on, are:

| Bulk table | Role in v1 |
| --- | --- |
| `search_court` | Circuit and district metadata. `jurisdiction`, `id`, `in_use`. |
| `search_docket` | Appellate docket: `court_id`, `appeal_from_id`, `date_filed`, `date_argued`, `nature_of_suit`, `cause`, `appellate_case_type_information`, `assigned_to_id`, `parent_docket_id`, `case_name`. |
| `search_originatingcourtinformation` | District link: `docket_number`, `date_judgment`, `date_filed`, `assigned_to_id`, `ordering_judge_id`. |
| `search_opinioncluster` | Label store (`disposition`, `date_filed`) and the forbidden opinion-side fields. |
| `search_opinion` | District-opinion text and page count. Appellate text is labels only. |
| `search_opinionscited` | Citation map: `citing_opinion_id`, `cited_opinion_id`, `depth`. |
| `search_citation` | Reporter citations. Not required for v1 features. |
| `people_db_person`, `people_db_position` | Resolve a judge id. Names from these tables do not enter the report. |
| `audio_audio` | Pre-decision panel source: `judges`, `docket_id`, joined to `date_argued`. |
| `search_opinioncluster_panel` | Present in the export. Forbidden as a feature. It is an attribute of the published cluster. |

The same script does not export docket entries, parties, or RECAP documents. Briefing-stage entries and a reliable appellant role are therefore not in the quarterly snapshot. v1 does not reconstruct them by crawling. A later phase can add them only under the rate limits below, and only for a sample that is declared before the test score. That phase is not v1.

Downloading the opinion CSV is the large transfer. The bulk page's note that case-law embeddings cost Free Law Project about $200 in AWS transfer fees applies to the embedding dump. v1 does not download embeddings. This draft states no byte size for the opinion CSV. The build records the filename, the generation date, and the SHA-256 of each file it loads.

The snapshot stays on the operator's machine. It is not committed. `*.csv` is already gitignored except named fixtures. The build also gitignores the compressed bulk directory. No API token is written into the snapshot, the report, or the repository.

### Terms

The [CourtListener terms](https://wiki.free.law/c/terms/courtlistener/courtlistenercom-terms-of-service-and-policies), last modified 5 August 2026, define the Services as the website, the REST API and its webhooks, the MCP server, and the accounts that support them. The terms do not name the S3 bulk bucket. Bulk use is authorized on the bulk-data page itself: the files are offered to the public and described as free of known copyright restrictions. That is the path v1 uses.

The terms that do govern the Services, including any API call:

- No use that violates applicable law, and no use that would make Free Law Project a consumer reporting agency. The FCRA prohibition is quoted in the ethics section.
- No sharing, reselling, pooling, or transferring account credentials or API tokens. A team or a product needs a commercial agreement.
- No use of multiple accounts, clients, or credential rotation to exceed rate limits. Creating more than one account per project, person, or organization is forbidden.
- If results are republished, they must not be presented as produced, endorsed, or verified by Free Law Project.

Judicial opinions are generally public. The copyright policy on the same terms page warns that some filings contain third-party material that can remain copyrighted. v1's text feature is the district court's own opinion, not exhibits attached to a brief. v1 does not download exhibits.

### Rate limits

The [REST API v4.7](https://www.courtlistener.com/help/api/rest/) page states that authenticated users may make up to 5 requests per minute, 50 requests per hour, and 125 requests per day, unless a membership or a commercial agreement raises the limit. The windows roll. All three limits apply at once. The most restrictive one controls the next request. Changes to a limit can take up to 30 minutes to propagate. The usage API reports remaining quota and has its own throttle.

Those limits are why the corpus comes from the bulk snapshot. Paging clusters, opinions, and citation edges for thirteen circuits would exceed the default daily cap by orders of magnitude and would violate the anti-evasion rule if it were spread across accounts. The API is reserved for a one-request smoke test after a key exists.

### What was reachable without a token on 10 October 2026

| Request | Result |
| --- | --- |
| `OPTIONS /api/rest/v4/clusters/` | 401, authentication credentials were not provided. |
| `GET /api/rest/v4/opinions/` | 401 |
| `GET /api/rest/v4/docket-entries/` | 401 |
| `GET /api/rest/v4/people/` | 401 |
| `GET /api/rest/v4/opinions-cited/` | 401 |
| `GET /api/rest/v4/courts/?jurisdiction=F` | 200, `count` 127. Includes `ca1`–`ca11`, `cadc`, `cafc`, and `scotus`. |
| `GET /api/rest/v4/courts/?jurisdiction=FD` | 200, `count` 125. Includes the generic parent `usdistct`. |
| `GET /api/rest/v4/search/?type=o&q=court_id:ca9` | 200, `count` 138,055. Opinion hits, not clusters and not the cohort. |
| `GET /api/rest/v4/search/?type=o&q=court_id:ca2 AND disposition:reversed` | 200, `count` 0. The disposition operator did not return reversals. |

A Ninth Circuit search hit included `panel_ids`, `panel_names`, `dateArgued`, `citeCount`, `posture`, `syllabus`, `procedural_history`, and an opinion object with a snippet and a `cites` list. It did not include `disposition`. `panel_names` was empty on that hit while `dateArgued` was earlier than `dateFiled`. Those fields are documented so the feature rules have something to point at. The hit is not a sample of labels.

`COURTLISTENER_API_KEY` is not available for this proposal. When a build exists, the key comes from the environment or from a gitignored `.env`, the same way `etl/extract.py` already reads it. `.env.example` keeps a placeholder. The key is not committed, not pasted into the report, and not required to approve this spec.

### Cohort the build must filter

All of the following:

- Appellate `court_id` is one of `ca1`, `ca2`, `ca3`, `ca4`, `ca5`, `ca6`, `ca7`, `ca8`, `ca9`, `ca10`, `ca11`, `cadc`, `cafc`.
- The appeal is from a federal district court: `appeal_from_id` has jurisdiction `FD` and is not `usdistct`, or the originating-court record links a district docket. Rows with neither link are `not_from_district`. They leave the cohort. That drops agency petitions and original proceedings, which Table B-5 counts separately.
- A clock exists.
- The fine label is one of the binary labels, for the headline score. Excluded labels are counted.
- `scotus` is out. The Supreme Court is not a court of appeals.
- The Federal Circuit is in the cohort and is its own slice. It is left out of any comparison to Table B-5, because that table excludes it.

`precedential_status` is recorded and is not a filter. Unpublished affirmances stay in when they have a disposition sentence. Rows that become `needs_text` are counted. They are not treated as affirmances.

### Funnel the build must print

This proposal does not fill these cells.

1. Appellate clusters in the thirteen circuits.
2. Of those, dockets linked to a district court.
3. Of those, rows with a clock.
4. Of those, rows with a fine label, by label.
5. The headline cohort, by circuit and by decision year.
6. The share with a linked district opinion, a judge id, and an oral-argument panel.

Until those cells are filled from a snapshot, there is no cohort size to defend. The Ninth Circuit search `count` of 138,055 is not that size.

### External sanity check

After the extract exists, print the headline disturb rate and the pure-affirmance rate next to Table B-5's 7.9 percent reversed and 16,900 affirmed or enforced out of 24,318 merits terminations, for the year the table covers, and state the mismatches: this cohort is opinion clusters with a parsable sentence, Table B-5 is an administrative termination count, Table B-5's Affirmed column includes partial reversals, and Table B-5 omits the Federal Circuit. A gap is described. It does not move a label.

## Pipeline checks

These checks are part of done. They are not implemented in this change.

### Validation

Before fitting, the loader rejects the extract if any of the following fail:

- Every scored row has an appellate docket id, a cluster id, a decision date, a clock date strictly before the decision date, a circuit id in the thirteen, and a binary label.
- The feature matrix contains none of the forbidden fields listed above.
- `needs_text`, `no_clock`, `not_from_district`, `later_cluster`, `cluster_conflict`, `timeline_inconsistent`, `dismissed`, `coa`, `unmapped`, and `affirmed_with_remand` are absent from the headline score and present in the funnel.
- Training and test windows each contain at least one scored row and, after the single backward move if it was required, at least 200 test rows with `y_disturb = 1`.
- Duplicate docket ids inside a split are zero. A docket id in both splits is zero.
- The bulk path is local. The command does not call the CourtListener API.

### Label tests

Unit tests use hand-written strings and no network. They cover every example in the label table, plus: a blank disposition with a decretal "we reverse" labels `reversed` and does not copy that sentence into the feature row; "affirmed and remanded" is excluded from the headline; "reversed and remanded" is `y_disturb = 1`.

### One command, when a build is approved

```bash
courtpipe evaluate-appeal --bulk path/to/bulk-dir --report data/model-eval/appeal_report.json
```

The command downloads nothing. The report JSON includes the bulk filenames, generation date, SHA-256 of each loaded file, the seed, the clock rule, the funnel, the windows, the audit summary, both models' metrics, the bootstrap intervals, the slice table, and the Table B-5 sanity check. A second run on the same files and seed produces the same metrics. The command exits non-zero if validation fails or if the label-audit gate was not passed. The report contains no API key and no per-judge rate.

### Offline smoke test

A second invocation runs on a tiny synthetic fixture with invented captions and no network. It checks that the loader accepts a well-formed file, that a feature builder refuses an appellate `disposition` column and an appellate `plain_text` column, and that the process writes a report whose `result` field is `smoke`. The fixture's labels are invented. Quoting them as an affirmance rate is a failure.

### Live read

When `COURTLISTENER_API_KEY` is set, a separate command performs one authenticated `GET` of a single public cluster and checks that the JSON includes `date_filed`. It does not train and it does not page. The cluster id is fixed in the test. Observed without a token on 10 October 2026, the clusters endpoint returned 401. The live read cannot be claimed to pass until it has been run. Gates for the audit and the model can still be completed from the bulk snapshot alone. If the fitted model used any field that required the API, the project is not called done while this read is unrun.

## What failure looks like

| Outcome | What it means |
| --- | --- |
| The bulk snapshot is not on disk | Stop. Do not page the API to assemble a corpus under the default rate limit. |
| Fine-label Wilson lower bound at or below 0.70, kappa below 0.60, or more than 20 percent of the audit unreadable | The disposition crosswalk is not a usable label. Stop. |
| Fine-label lower bound above 0.70 and at or below 0.80, and the binary lower bound is above 0.85 | The binary model may be reported. The fine label failed. Say that. |
| Test positive count stays under 200 after one backward move | The extract cannot yet support the bootstrap floor. Stop. |
| AUC difference interval covers 0 or less, or the model's own AUC interval covers 0.5 | Pre-decision fields do not rank disturbance better than circuit, case type, and the judge rate. That is "not enough signal." |
| Brier does not improve on the best baseline | The scores are not usable probabilities. Report the ranking only if AUC passed, and do not describe the output as a calibrated risk. |
| The gain disappears when one circuit above the minimum is removed | The result is a circuit effect. Name the circuit. |
| The gain disappears when the district-judge id is removed from the model | The model was memorizing judges. Say so. Do not publish the judge table that would make the mechanism visible as a scorecard. |
| Someone quotes the opinion-pipeline fixture scores, the Ninth Circuit search `count`, or Table B-5's 7.9 percent as this model's result | Those numbers are about other tasks or other databases. |

## Out of scope for v1

- Any change to the opinion labeler, the review queue, the charts, the Integrated Database track, or the securities proposal.
- Training a model in this change.
- Buying PACER documents or calling a RECAP purchase endpoint.
- Paging the REST API to build the cohort.
- Supreme Court merits votes, bankruptcy appellate panels, agency petitions, and original proceedings.
- Issue-level affirmance and reversal.
- Embeddings, large language models, and appellate-opinion text features.
- A published reversal rate for a named judge, or a "federal appeals" rate that ignores the cohort definition.

## Decisions needed before a build

1. The headline event is `y_disturb`: reversed, vacated, remanded, and mixed versus pure affirmance. `affirmed_with_remand` is excluded from the headline. Sensitivity A treats it as affirmance. Sensitivity B treats it as disturbance. Confirm or fold that phrase into one class before any test score.
2. The unit is one appellate cluster on one docket from a district court, not one issue. Confirm or specify an issue schema.
3. The courts are the thirteen circuits, including the Federal Circuit, which stays out of the Table B-5 comparison. Agency petitions and original proceedings are out. Confirm or drop the Federal Circuit.
4. The clock is the argument date when that date is before the opinion, and otherwise the appeal's filing date. Time since judgment uses the clock, not the opinion date. Confirm or move the clock to the notice of appeal only.
5. The data path is one quarterly bulk snapshot. Briefing-stage docket entries and appellant party role are permitted and are not in that snapshot, so v1 leaves appellant class unknown and omits entry features. Panel comes only from a pre-decision oral-argument record. Confirm or wait for an API allowance large enough to attach entries without evading the rate limit.
6. District-judge id may be a feature. Individual judge scores are not published. The model has to beat `judge_rate` as an aggregate baseline. Confirm.
7. Success is the audit floors and the AUC and Brier bars in this document. There is no accuracy gate and no fixed AUC cutoff. A negative result is reported as a result. Confirm.

Build starts after those are confirmed. Until then there is nothing to train.
