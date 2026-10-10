# Spec: federal appeals, affirmed or changed

Status: proposal. This document does not add code, data, or a model. Build only after Adam approves this spec. Nothing here has been run. No CourtListener API key is available yet.

This is track 4. The other tracks are the settlement and securities specs (`docs/SPEC.md`, `docs/EVALUATION.md`), the Integrated Database settlement classifier (`docs/idb/`), and the motion-to-dismiss spec (`docs/mtd/`, open PR #2). The same rules apply here: use only what existed before the event being predicted, test on newer cases than the training cases, beat simple baselines, report uncertainty, and keep an honest negative result if the model does not.

Sources read for this draft on 10 October 2026: the CourtListener bulk-data help page and the existing courtpipe README and specs. This draft did not download any bulk file, did not call the API, and did not count any rows. Every number below that looks like a size or rate is a planning assumption and is marked as one.

## The question and why it matters

> Before a federal court of appeals decides an appeal from a district court, how likely is it that the appeal ends in affirmance, and how likely is it that the district court's ruling is reversed, vacated, or remanded?

Appellate lawyers, litigation funders, and clients decide whether to appeal, settle, or cross-appeal on a guess about this. A calibrated base rate by circuit and case type is the useful product. A model is worth building only if it adds calibrated information beyond that base rate.

This is a research exercise. It is not legal advice and not a product that scores people.

Most federal appeals are affirmed. That makes accuracy a bad metric. The success bars below use ranking and calibration, not accuracy.

## What the current pipeline does, and why it is not this

`etl/transform.py` reads the text of an opinion and extracts what that opinion did (`affirmed`, `reversed`, `vacated`, `remanded`, `dismissed`, `mixed`, `other`). That is extraction. The words it matches are the outcome. This track needs the same outcome as a label and must never reuse that text as input. The extraction code can serve as one label source. It cannot serve as a feature source.

## Unit of prediction

**v1 unit: one appeal (one appellate docket) from one district court ruling in a civil case.**

- An appellate docket is the unit because the question, who appealed and the court they appealed to, exists at that level and is known at the start.
- Consolidated or cross appeals that share one opinion: keep one row per appellate docket, give them the same `decision_group_id`, and keep the whole group on one side of every split. Report results with the group as the bootstrap cluster.
- Issue-level prediction (which issue was reversed) is out of v1. An opinion often affirms on one issue and reverses on another, and issue labels need legal reading that this project cannot audit at scale. It is a later experiment, not a v1 target.
- Criminal appeals, immigration petitions for review of agency orders, and agency review are out of v1. Their base rates and processes differ and would mix populations. The population is civil appeals from federal district courts. Whether to add criminal appeals later is an open question.

## Data sources

### CourtListener bulk data (primary, when available)

Source: [Bulk Legal Data, Free Law Project wiki](https://www.courtlistener.com/help/api/bulk-data/), read 10 October 2026.

What the page states:

- Bulk files cover courts, dockets, opinion clusters, opinions, a citations map, parentheticals, oral arguments, judges, and an Integrated Database import. Files are PostgreSQL `COPY TO` CSV exports, UTF-8, with a header row.
- Files are snapshots, not deltas. Each file holds everything in the database at generation time.
- Files are regenerated quarterly, on the last day of March, June, September, and December. Check the date in the filename. Record it in every run.
- Field definitions come from the CourtListener `models.py` files and from `OPTIONS` requests to the REST API.
- The page states: "Our bulk data files are free of known copyright restrictions."
- The case-law embeddings (about 2 TB) are out of scope. Downloading them costs Free Law Project about $200 in AWS fees.

Terms and policy to check before any download: the bulk-data page above, CourtListener's terms of service, and its API policy. This draft read only the bulk-data page. It did not read the terms of service or the API policy, so it does not claim what they allow. The build is blocked until someone reads them and records the date and the relevant clauses in `docs/appeal-reversal-spec.md` (a short "terms check" note). Free Law Project asks users to use the forum for data questions, and a donation is encouraged for heavy use. Whether Adam wants to contribute is his decision.

Tables the build would need (names taken from the page's list, to be confirmed against the schema file that ships with each snapshot):

| Table | Use |
| --- | --- |
| Courts | Court id, jurisdiction, circuit mapping. Appellate courts are the 13 federal courts of appeals. |
| Dockets | Appellate and district dockets, docket number, dates filed and terminated, case name, nature of suit where present. The 2024 release notes list `parent_docket_id` and `federal_dn_*` fields, which may help link an appeal to its source. |
| Opinion clusters and opinions | The appellate decision. Source of the label, never of features. |
| Citations map | Who cites which opinion. Used only for the cohort definition and for the optional "later cited" analysis, never as a feature. |
| Integrated DB | The FJC Integrated Database merge, "when requested." Whether it covers appeals is unverified. |

Not verified in this draft, and each is a gate in the first milestone:

1. Whether an appellate docket carries a reliable link to its originating district docket and the district ruling's date.
2. Whether each decision has a usable disposition field or only opinion text.
3. Which share of federal civil appeals has an opinion at all. CourtListener's appellate coverage is mainly opinions the courts publish. Many appeals end in summary orders, unwritten decisions, or voluntary dismissals. This is the largest selection problem. See the risks.
4. Whether pre-decision information (briefs, argument calendars, panel assignment) exists in bulk data at all. It may not. If it does not, v1 features come from the dockets table and the district court side only.

### FJC Integrated Database, appellate file (candidate label and feature source, unverified)

The Federal Judicial Center also publishes an appellate case file as part of its Integrated Database. This draft did not open it. It may carry structured fields for circuit, filing year, origin, and a disposition code, which would give a cleaner label than opinion text. The first milestone checks whether it exists in a usable form and what its documentation says about disposition coding and use limits. If it does, it becomes the preferred label source, with CourtListener supplying linkage and text for audit.

### What this draft does not use

- The CourtListener REST API for the cohort. Unauthenticated calls to dockets, parties, docket entries, and opinions returned 401 on 7 October 2026 (recorded in PR #2). The API key is not available. It must come from the environment as `COURTLISTENER_API_KEY`, as the rest of courtpipe already does, and must never be committed, printed, or put in a report.
- PACER purchases. Out of scope.
- Scraping any site. If a source's terms forbid bulk collection, v1 waits for permission.

## Label

The label describes what the court of appeals did to the district court's ruling, at the level of the appeal.

### Fine disposition (recorded, not the main target)

`affirmed`, `reversed`, `vacated`, `remanded`, `mixed`, `dismissed`, `other`. These are the same fine labels the existing pipeline uses, so the vocabulary does not change.

### Mapping to the v1 target

| Disposition | Mapped label | Rule |
| --- | --- | --- |
| `affirmed` | `affirmed` (0) | The decision affirms the district court judgment in full. |
| `reversed` | `changed` (1) | Reversed in full. |
| `vacated` | `changed` (1) | Vacated, with or without remand. |
| `remanded` | `changed` (1) | Remanded for further proceedings, including "vacated and remanded." A remand alone with the judgment otherwise affirmed is `mixed`. |
| `affirmed in part, reversed in part` | `changed` (1) | Any part of the judgment is reversed or vacated. The target asks whether the district court won clean. A partial change is not a clean win. |
| `mixed` (cannot be classed from the text) | excluded | Goes to the audit queue. See below. |
| `dismissed` | excluded | Appeals dismissed for lack of jurisdiction, by stipulation, or for failure to prosecute are not a merits judgment on the district ruling. They are counted and reported. |
| `other` / unclear | excluded | Counted and reported. |

The headline target is binary: `changed` (any reversal, vacatur, or remand of any part) versus `affirmed`. It is named "affirmance versus change." The three-way split (affirmed, partially changed, wholly changed) is reported as a secondary result and is not a binding bar.

The "affirmed in part" mapping to `changed` is a decision for Adam. Mapping it to `affirmed` would be the other defensible choice. The spec fixes `changed` so that the question is whether the district court won cleanly. Adam can flip it before the build. Flipping after any test score is computed invalidates the run.

### Mixed and ambiguous cases

- Multiple defendants or claims with different results: any change makes the row `changed`.
- Cross appeals decided in one opinion: one row per appellate docket sharing a `decision_group_id`, labeled from the outcome for that appellant's challenge when the text separates them. When it does not, both rows take the group's label and the group is flagged.
- "Affirmed on alternative grounds" or "affirmed as modified": `affirmed` unless the modification changes the judgment's operative terms. Operative changes (damages, remedy, dismissal with or without prejudice) go to adjudication.
- Remand "for the limited purpose of" correcting a clerical error: `affirmed`, flagged for adjudication.
- En banc or later reversal of a panel decision: the label is the first panel decision for the appeal, with the later event recorded. It is not a feature.
- Unpublished or summary orders: included only if the text states a disposition.
- A label that depends on a heuristic regex is a candidate. It becomes a label only for rows that pass the audit rate below. Rows the labeler cannot decide are excluded and counted. They are never defaulted to `affirmed`.

## Population and split

- Population: appellate dockets decided on the merits in the 13 federal courts of appeals, civil, appeal from a federal district court, where a district ruling date and an appellate decision date are both known, where the written disposition is available, and where the label is not excluded above.
- Decision year range: to be fixed once the first milestone reports the counts per year. The planning assumption is 2005 to a recent complete year.
- **Temporal split by appellate decision date.** Train on earlier decisions, validate on a middle window, test on the newest complete window. A planning example: train 2005–2018, validate 2019–2020, test 2021–2023, quarantine 2024 and later until the end. The final dates are set before any test score is computed and recorded in the report.
- One `decision_group_id` is on one side of every split.
- A model that tunes on the test window invalidates the run. The validation window is for tuning.
- Each year's cohort is also reported on its own, so a shift over time shows.

## Features: what is allowed

The prediction instant is the date the appellate docket is opened (the notice of appeal or the docketing date, whichever is in the data and earlier). Everything used must be dated on or before that instant unless a later clock is declared in advance in the report. A declared later clock (for example, the date of oral argument) is allowed only if it is chosen before any test score is computed, every feature under it is dated before the decision, and the report names it. Switching clocks after a test score is computed invalidates the run.

Permitted when the data holds them and they pass the dating rule:

| Group | Examples |
| --- | --- |
| Appeal setting | Circuit, filing year and month, case type or nature of suit from the district docket, whether the appeal is from a final judgment, summary judgment, a motion to dismiss, or an interlocutory order when the district record says so. |
| District court | District, case duration before appeal, district-level ruling type, whether the district ruling had a written opinion before the appeal was filed. |
| Parties and posture | Appellant side (plaintiff or defendant), whether a government party is on either side, whether a party is an individual, a company, or the government, self-represented or counseled when the docket says so. |
| Prior history | Whether the district court's own ruling is among the cited opinions that existed before the appeal. Only citations dated before the prediction instant. |
| Text, pre-decision only | The district court opinion text, if it was written before the appeal. This is allowed only for the district court's ruling. Briefs or argument records are allowed only if they exist in the data and are dated before the decision. |
| Panel | Panel composition only if it is dated before the decision. It is a candidate for an optional ablation. See ethics. It is not in the base model. |

All features are fixed by a written feature list before modeling and listed in the report with the date source for each.

## Features: forbidden

The appellate opinion is the label source. Any field that comes from the appellate decision, or that is set by it, is excluded from every model and every baseline except the label.

- The appellate opinion text, headnotes, syllabus, and any summary or embedding of that text.
- The disposition field, or any text such as "AFFIRMED", "REVERSED", "VACATED", "REMANDED" taken from the decision.
- Whether the decision was published, precedential, unpublished, or a summary order. Publication is decided at decision time and correlates with reversal.
- The decision date, the length of the opinion, the number of judges who joined, dissent or concurrence, and the author of the opinion.
- Time from docketing to decision, and any docket entry dated after the prediction instant.
- Costs awarded, mandate issued, rehearing, petition for certiorari, and any later history.
- Later citations of the appellate decision (the citations map after the decision date), and any "cited by" count.
- Courtpipe's own extraction outputs for the appellate opinion: `outcome_code`, `outcome_label_fine`, `confidence`, `needs_review`, `disposition_zone_found`, `evidence_contains_strong_phrase`, `evidence_match_position`.
- Any field filled in by CourtListener after the decision, such as the cluster's disposition or procedural-history fields, unless the data dictionary shows it is set before the decision.
- A district court field updated after the appeal.

Leakage tests: the build must include offline fixtures that fail if a forbidden column name enters the feature matrix, and a test that shuffles the label and checks that the model score falls to chance. The leakage checks run before any score is reported.

## Baselines

All baselines use training-window data only and are scored on the same test rows.

1. **Majority class.** Always predict `affirmed`. Reports accuracy, which is the floor, and it is not a binding metric.
2. **Affirmance base rate by circuit.** Training-window share of `changed` per circuit.
3. **Base rate by circuit and case type.** Training-window share by circuit crossed with nature-of-suit group. Cells with fewer than 30 training rows back off to the circuit rate, and the report lists the cells that backed off.
4. **Base rate by circuit, case type, and decision-year trend.** Optional, to see whether a time trend matters. A baseline that cheats by using the test window is not allowed.
5. **Logistic regression on the permitted metadata only (no text).** A simple supervised floor before text or embeddings.

The model must beat baseline 3 and baseline 5, the strongest of the simple baselines, not just baseline 1.

## Metrics and success bars

The binding task is the binary `changed` versus `affirmed` score. The planning bars below are justified from base rates and sample sizes, and they are proposals for Adam. They are not measured results. The first milestone reports the real base rate and the test sample size, and the bars are re-confirmed with Adam against those numbers before any model is trained. The bars are fixed before the test window is scored.

Planning assumption on base rate: federal civil appeals are mostly affirmed, and the share changed in the published-opinion subset is higher than in all appeals. Both facts are expected, not measured here. The measured rate sets the work.

| # | Bar | Justification |
| --- | --- | --- |
| 1 | **Label audit passes** (see protocol). Binary label agreement with the adjudicated label has a 95% Wilson lower bound of at least 0.90. Cohen's kappa between the two readers is at least 0.70. Kappa below 0.60 stops the project. If more than 15% of the audit sample cannot be read, the audit did not happen. | A predictor cannot be better than its labels. With roughly 150 rows, a 0.90 lower bound requires about 0.95 observed agreement. |
| 2 | **Ranking.** Test ROC-AUC at least 0.65, and at least 0.03 above the best of baselines 3 and 5. The lower end of a 1,000-draw bootstrap 95% interval, resampling by `decision_group_id`, must stay above the best baseline's AUC. | An AUC near 0.5 is chance. Simple appeal-outcome studies that use only metadata are expected to land in the mid 0.6s. The 0.03 margin is the smallest gain worth a lawyer's attention. The cluster interval prevents a win from a few repeated cases. |
| 3 | **Probability quality.** Brier score at least 3% lower (relative) than the best baseline, with a bootstrap interval that excludes zero. Skill is reported as `1 - Brier_model / Brier_baseline`. | Brier rewards calibrated probabilities. A 3% gain is small and honest at a high base rate, where little room exists. |
| 4 | **Calibration.** Expected calibration error (10 equal-count bins) at most 0.05 on the test window, and a reliability plot with no bin more than 0.10 off the diagonal where the bin holds at least 30 rows. Report intercept and slope of a logistic recalibration on the test window. A slope outside 0.8 to 1.2 is a failure, and the report says so. | A forecast is useful only if "30%" means about 30%. The bars match what a decision-maker needs. Bins under 30 rows are too noisy to bind. |
| 5 | **Useful tail.** In the top decile of predicted change probability, the observed change rate is at least 1.5 times the test base rate, with a bootstrap interval that excludes 1.0. | A decision-maker acts on the cases the model flags. The 1.5 lift is the lowest worth acting on. |
| 6 | **Stability.** Bars 2 and 3 hold in a majority of the individual test years, and no circuit that holds at least 10% of the test rows drives the gain: dropping any one such circuit leaves bar 2 true. | A gain that exists in one year or one circuit is not a general result. |
| 7 | **Headline on the full cohort.** The scores above are on all test rows that satisfy the cohort rules, including rows with missing optional features. A score on a subset with complete text is reported as a coverage result and is not the headline. | A model that works only where data exists overstates the real task. |

**Pass** means all seven. **Fail** is reported as a negative result with the numbers. Bars 2, 3, and 5 are about the same model, so passing them is expected to move together. The success rule is "beat the baselines with intervals and be calibrated," not a fixed accuracy.

Also reported, not binding: accuracy at the 0.5 threshold, precision and recall at a fixed review budget (top 5% and top 10%), the three-way macro-F1, results per circuit with the sample size beside each, and results per year.

## Label-audit protocol

Run before any model is trained, and again on any change to the labeler.

- **Sample size.** 150 appeals, stratified. 50 that the labeler called `affirmed`, 50 `changed`, 30 that the labeler marked low confidence or excluded as `mixed`/`other`, and 20 `dismissed`. The stratified sample is for finding errors. A second simple random sample of 100 rows from the full cohort estimates the true agreement rate, and bar 1 is evaluated on that random sample.
- **Seed.** Fixed and recorded. The sample is drawn before the labeler is tuned and is never replaced after a bad result.
- **Readers.** Two readers label from the opinion text and its disposition section without seeing the automatic label or each other's label. In v1 the readers are Adam and one other person, or Adam and a second pass after at least a week. Adam says which in the open questions. A language model may assist as a third labeler. It may not be an audit reader, and its use must be stated.
- **Adjudication.** A reader disagreement is settled by a rule-based tie-break, written below, and a third read if the rule does not settle it.
  1. If the operative sentence states "affirmed" with no qualifier, the label is `affirmed`.
  2. If any part of the judgment, an award, a dismissal, or a ruling is reversed, vacated, or remanded, the label is `changed`.
  3. A remand that only asks for a ministerial correction is `affirmed`, flagged.
  4. If the disposition cannot be found in the text, the row is `unreadable`. It counts toward the 15% cap.
- **Report.** Agreement with the automatic label by stratum, kappa between readers, confusion matrix of the automatic label against the adjudicated label, the unreadable rate, and a list of error patterns with counts. Audit data is aggregate only. Case text is not committed.
- **Gate.** If bar 1 fails, the labeler or the FJC code mapping is fixed and the audit is redrawn with a new seed. The build does not continue on a failed audit.

## Ethics and framing

- **Research framing.** This is exploratory research on aggregate patterns. It is not legal advice, not a service, and not for use in deciding any real person's case.
- **Aggregate reporting only.** Results are reported by circuit, case type, and year. The project does not publish, rank, or visualize scores for individual judges, panels, or counsel. Cells with fewer than 30 cases are not reported by name.
- **No individual-judge outputs.** The base model has no judge or panel identity features. An ablation that adds panel composition may be run to test whether it adds anything, and if it does the report says that and does not name or rank judges. Per-judge model outputs are never written to a file that leaves the local machine.
- **Public records, no new personal data.** The data are public court records. Party names are not features. Individuals in the data (litigants, self-represented parties) are not named in any report, and no output is joined to other personal data.
- **Fairness check.** The report shows whether error rates differ by whether the appellant is self-represented, an individual, or the government, and says what it finds. This is a reported check, not a target to optimize.
- **No secrets, no personal data in the repo.** The API key is read from `COURTLISTENER_API_KEY` in the environment. `.env` is gitignored. Bulk files and derived tables live under a gitignored `data/` path. Only aggregate metrics and code are committed.
- **Terms.** The terms check described under data sources is complete before the first download.

## Risks

1. **Selection into opinions.** The cohort is appeals with a written, available decision. Appeals decided by unexplained orders, dismissed, or withdrawn never appear. Written and published decisions are more likely to be reversals than the typical appeal. The model learns that cohort's rate, not the national rate. The report states this, and the headline is "within the opinion cohort."
2. **Label noise.** Mixed outcomes, partial reversals, and modified affirmances. The audit measures it. Rows that cannot be classed are excluded, so the cohort can be cleaner than the real mix.
3. **Linkage failure.** If an appeal cannot be linked to its district court ruling, district-side features are missing, and those rows may differ from linked ones. The linked share is reported.
4. **Leakage through side doors.** Fields filled in after the decision, text that quotes the outcome, or the court's own summary. The forbidden list and fixtures guard this, and the leakage tests must pass before scoring.
5. **Weak signal.** Appeal outcomes depend on facts and law this project's features do not hold. The honest result may be a small or zero gain over the circuit-by-case-type base rate. That is a valid result.
6. **Time drift.** Reversal rates and case mix change by year and by circuit. The temporal split and per-year reporting measure the drift.
7. **Data availability.** No API key yet, bulk file size, and a dependency on CourtListener's quarterly snapshots. A snapshot date change alters labels, so every run records the snapshot file names.
8. **Small cells.** Some circuit-by-case-type cells are small. Backoff and reporting thresholds handle this.
9. **Misuse.** A calibrated reversal probability could be used to size up a judge or a litigant. The ethics rules limit what is published.

## Compute and cost

These are planning estimates, not measurements.

- **Money.** Bulk files are free to download. The one cost mentioned on the page is for the embeddings, which are out of scope. No PACER purchases. No paid API. A donation to Free Law Project is optional.
- **Disk.** The dockets and opinions bulk files are large (the page says the dockets table has "many millions of rows" and the opinions file is the largest). Plan for tens to hundreds of gigabytes for the full snapshot, to be confirmed against the file listing. v1 filters to appellate courts while streaming, so the working set is much smaller.
- **Compute.** Logistic regression and gradient boosted trees on metadata run on a laptop. A text baseline with TF-IDF on district opinions also fits on a laptop. Transformer embeddings of text are not in v1 and would need a decision on GPU time.
- **Time.** The expected effort is dominated by linkage and label checks, not by training.

## Milestones

Each milestone ends with a short written report and waits for Adam where marked.

0. **Approval.** Adam answers the open questions. Nothing is built before this.
1. **Feasibility, no model.** Read CourtListener's terms and API policy and record them. Open the bulk-data file listing and the schema. Check the four unverified items above and the FJC appellate file. Report counts: appellate civil dockets per year, the share with an opinion, the share linked to a district docket, the share with a parsable disposition. No labels, no model. Stop for Adam.
2. **Cohort and labeler.** Build the cohort filter, the label mapping, and the leakage fixtures with offline tests. Add the audit sample files. Stop for Adam to read the audit.
3. **Audit.** Run the audit protocol. Gate on bar 1. Stop for Adam.
4. **Baselines.** Compute baselines 1 to 5 on the validation window only, and freeze the feature list and the bars against the measured base rate. Stop for Adam to confirm the bars.
5. **Model and test.** Train on the training window, tune on validation, and score the test window once. Write the report with the full bars table, pass or fail, calibration plots, per-year and per-circuit results, and the fairness check.
6. **Review.** Adam decides whether to continue to an issue-level or panel-level extension, or stop with the negative result.

## Out of scope for v1

- Criminal, immigration, and agency appeals.
- Issue-level or claim-level prediction.
- Judge-level or panel-level scoring and any ranking of individuals.
- Buying PACER documents.
- Changes to the opinion labeler, the review queue, or the existing charts.
- Using the case-law embeddings.
- Any output presented as legal advice.

## Decisions needed before a build

1. Confirm the target: `changed` (any reversal, vacatur, or remand of any part) versus `affirmed`, and that "affirmed in part, reversed in part" is `changed`.
2. Confirm v1 is civil appeals from federal district courts, with criminal, immigration, and agency appeals deferred.
3. Confirm the unit is one appellate docket, with consolidated appeals grouped for splitting and bootstrapping.
4. Confirm the success bars (AUC at least 0.65 and 0.03 above the best baseline, Brier skill at least 3%, ECE at most 0.05, top-decile lift at least 1.5), or give different numbers. They are re-confirmed after the milestone 1 base rate.
5. Confirm the split, with the decision-year windows fixed after milestone 1 and before any test score.
6. Confirm the audit: 150 stratified rows plus 100 random rows, and who the second reader is.
7. Confirm panel composition stays out of the base model, with at most an unpublished ablation.
8. Confirm the data path: CourtListener bulk files, with the FJC appellate file as a preferred label source if it checks out. Confirm that the terms review happens first, and that a new `COURTLISTENER_API_KEY` is not needed until after milestone 1.
9. Confirm the opinion-cohort selection is acceptable, or ask for a plan to estimate it.
10. Confirm whether the repository stays public. The repo is shown as public on GitHub, and the spec assumes aggregate metrics only. Nothing sensitive is committed either way.
