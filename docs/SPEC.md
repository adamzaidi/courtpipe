# Spec: filing-time settlement prediction for corporate civil cases

Status: proposal. This document does not add code, data, or a model. Build only after this spec and `docs/EVALUATION.md` are approved.

The README's question is how opinion-level outcomes vary across courts, and which opinions need human review because the extraction is uncertain. It is explicit about the boundary: the pipeline labels what the court did in the opinion, it is not a docket-level record, and it is not an attempt to recover the full case result. Adam's goal for this phase is narrower and different: predict whether cases against corporate parties end in settlement rather than dismissal or judgment for one side. This spec keeps the README's auditability rules and changes the target, the clock, and the data source so that goal can be attempted honestly.

No Granola notes discussed this project. The proposal below is from the README, the current code, the FJC civil codebook, and public CourtListener responses collected on 7 October 2026.

## What the current pipeline actually does

`etl/transform.py` labels an opinion by searching its text, preferring the tail, for `vacate`, `reverse`, `remand`, `affirm`, and `dismiss`. Confidence goes up when those words sit near `opinion`, `judgment`, `order`, or a phrase such as `we affirm`. `analysis/model.py` then trains logistic regression and a random forest on court, opinion year, a word-count bucket, and three fields taken from that same labeling pass: `disposition_zone_found`, `evidence_contains_strong_phrase`, and `evidence_match_position`.

That is outcome extraction, not prediction. The words the labeler matches are the outcome, and several model features are functions of those words. The fine labels the code emits are `affirmed`, `dismissed`, `reversed`, `vacated`, `remanded`, `mixed`, and `other`. There is no settlement label. The comment in `data/reference-tables/courtlistener_data_dictionary.csv` that lists Settlement as a fine label does not match the code. A full-text opinion query for `corporation` is also not a corporate-party filter: on 7 October 2026, unauthenticated `GET /api/rest/v4/search/?type=o&q=corporation` returned `count` 2,052,794.

Appellate affirmance and reversal are not the district-court ending of a suit against a company. Cases that settle often never produce a merits opinion, so an opinion corpus under-represents settlement and then, when it does contain disposition language, reveals the ending in the text.

## Prediction question for v1

At filing, for a federal district civil case in the cohort below, estimate the probability that the Administrative Office disposition code will be **13, settled**: "the action was disposed of after settlement between parties out of court."

The quote is from Appendix A of the FJC codebook `Civil Codebook 1988 Forward 10252023.pdf`, on the public page [Civil cases filed, terminated, and pending from SY 1988 to present](https://www.fjc.gov/research/idb/civil-cases-filed-terminated-and-pending-sy-1988-present). The codebook was retrieved on 7 October 2026.

v1 does not predict appellate disposition, and it does not predict the outcome from opinion text.

## Label set

Codes are the `DISP` field in that codebook. `JUDGMENT` is filled for cases disposed of by a final judgment. It is the wrong field for an out-of-court settlement, and the codebook does not define it as the winner of a settled case.

| Label | Rule | Role in v1 |
| --- | --- | --- |
| `settled_out_of_court` | `DISP = 13` | Primary positive class. Codebook: settlement between the parties out of court. |
| `voluntary_dismissal` | `DISP = 12` | Separate. Codebook: plaintiff withdrew under Rule 41(a). Some of these are settlements. Some are abandonments. v1 does not call them settled. |
| `consent_judgment` | `DISP = 5` | Separate. Codebook: a judgment agreed by the parties and signed by the judge, granting affirmative relief, including agreements reached after trial started. Adjacent to settlement. Not the primary positive class. |
| `judgment_for_plaintiff` | `DISP` is 4, 6, 7, 8, 9, 15, or 17, and `JUDGMENT = 1` | Secondary. Direction of a judgment. Consent judgments stay in the row above. |
| `judgment_for_defendant` | Same `DISP` set, and `JUDGMENT = 2` | Secondary. |
| `judgment_other` | Same `DISP` set, and `JUDGMENT` is 0, 3, 4, or -8 | Judgment was entered, winner not recorded as one side. |
| `other_dismissal` | `DISP` is 2, 3, or 14 | Want of prosecution, lack of jurisdiction, or other dismissal. |
| `not_a_merits_ending` | `DISP` is 0, 1, 10, 11, 16, 18, 19, or 20, or `DISP` is missing (-8) | Transfer, remand, MDL transfer, remand to an agency, bankruptcy stay, statistical closing, magistrate-judge appeal. Excluded from the training and test cohorts. |

A row receives exactly one label, first match in the table from the top. `DISP = 13` never also receives a plaintiff/defendant judgment label.

The binary target is `y_settle = 1` when the label is `settled_out_of_court`, and `0` for every other label that remains in the cohort. `not_a_merits_ending` is excluded before the split, and the exclusion count is reported.

### Why this is the closest achievable settlement label

The codebook itself separates out-of-court settlement (13), Rule 41(a) voluntary dismissal (12), and consent judgment (5). Clerks do not apply that distinction consistently. Charlotte S. Alexander, Nathan Dahlberg, and Anne M. Tucker, *Settlement as Construct*, 119 Nw. U. L. Rev. 65 (2024), crosswalked docket sheets to the IDB for closed civil cases filed in all 94 districts in 2016 and 2017. In their matched scope of 328,869 cases, 168,312 (51%) had IDB code 5, 12, or 13. Their docket models marked party resolution on 94% of those. Another 37,915 cases had a docket signal of party resolution and a different IDB code, often 14 (other dismissal, 19,697) or 6 (motion before trial, 5,169). Those figures describe that study's 2016–2017 closed-civil scope. They are not a measurement of this repository's future extract.

So:

- Code 13 is a real administrative label, with a written definition, on a public national file.
- Code 13 under-counts party resolutions that clerks put in other codes, and codes 12 and 5 mix settlement with other endings.
- A model trained on code 13 predicts clerk-coded out-of-court settlement, not the full set of compromises a lawyer would call a settlement.
- v1 reports codes 12 and 5 as their own labels and as a sensitivity flag `y_broad = 1` when `DISP` is 5, 12, or 13. `y_broad` is not the primary target. Swapping it in after seeing test metrics is a failure under `docs/EVALUATION.md`.

Opinion text and RECAP docket prose are worse primary label sources for v1. Settlements are often absent from opinions. When the word appears, it often describes a contract, a prior settlement, or a class-settlement hearing rather than the ending of the case being predicted. RECAP entry text can show a stipulation of dismissal, but the entries API is not usable without a token (below), and entry wording is not a stable code.

Judgment-for-plaintiff and judgment-for-defendant are kept because the codebook has `JUDGMENT`. They are secondary. They are undefined for code 13, and they are missing often enough that a five-way "settled / dismissed / plaintiff / defendant / other" partition would hide the missingness. The table above keeps the missingness visible.

## What counts as a case against a corporate party

v1 uses the IDB fields `DEF` (first listed defendant) and, for diversity cases only, `RESIDENC`. The codebook does not provide the full party list, party type, or later-added defendants. A case with a corporate defendant who is not first-listed will be missed. That limitation is part of the label.

Normalize `DEF` by uppercasing and turning punctuation into spaces. Then:

1. **Government.** If the normalized string contains any of these, it is governmental and is not a corporate defendant, even if it also contains a company suffix: `UNITED STATES`, token sequence `U S`, `STATE OF`, `COMMONWEALTH`, `CITY OF`, `COUNTY OF`, `DEPARTMENT`, `SECRETARY`, `COMMISSION`, `DISTRICT ATTORNEY`.
2. **Company suffix.** Otherwise the defendant is corporate if the tokens include one of: `INC`, `INCORPORATED`, `CORP`, `CORPORATION`, `LLC`, `LLP`, `LP`, `LTD`, `LIMITED`, `PLC`, `BANCORP`, `HOLDINGS`, `COMPANY`, or the token sequences `L L C`, `L L P`, `L P`, `P L C`, `N A`, `NATIONAL ASSOCIATION`.
3. **Diversity incorporation flag.** If `JURIS = 4` and the second digit of `RESIDENC` is 4 or 5, the codebook is recording the defendant as incorporated or as having its principal place of business in a state. That case is corporate even when the name rule fails, and it is tagged `corporate_via_residence` so the audit can separate the two rules. This flag exists only for diversity jurisdiction.
4. **Unknown.** If `DEF` is blank and rule 3 does not fire, the case is `corporate_unknown` and leaves the cohort. It is not coded as non-corporate.

`CO`, `BANK`, `GROUP`, `ASSOCIATION`, and bare `PC` are intentionally not suffixes. They match too many non-companies. The cost is missing some banks, associations, and short names.

A case enters the corporate cohort only through rule 2 or rule 3, and only if rule 1 did not fire.

On 7 October 2026 an unauthenticated RECAP search hit for a securities docket returned `party` including both `Geek Securities, Inc.` and `Securities and Exchange Commission`. The name rule would keep the company and the government rule would drop the Commission. v1 does not read that RECAP party array. The example is only a check that the two rules point in different directions. The IDB still sees only the first-listed name.

## Prediction time and leakage

v1 predicts **at filing**. The information set is the civil cover sheet and the filing fields in the IDB. Nothing recorded at termination is a feature.

### Allowed features

| Field | Why it is known at filing |
| --- | --- |
| `CIRCUIT`, `DISTRICT`, `OFFICE` | Court where the case was filed. |
| `ORIGIN` | How it was filed (original, removed, and so on). |
| `FILEDATE` | Filing date. The model may use calendar month and a coarse year bin. It may not use `TERMDATE`. |
| `JURIS` | Cover-sheet jurisdiction. |
| `NOS` | Nature of suit, the cover-sheet case type. |
| `RESIDENC` | Diversity citizenship codes, only meaningful when `JURIS = 4`. |
| `JURY` | Jury demand at filing. |
| `CLASSACT` | Class-action allegation at filing. This is not `TRCLACT`, which is the class ruling at termination. |
| `DEMANDED` | Amount demanded, in thousands, with the codebook's warning that courts have not always scaled it. Use a missingness indicator and coarse bins, not the raw dollar figure as a precise number. |
| `COUNTY` | County of the first plaintiff, or of the first defendant when the United States is the plaintiff. |
| `ARBIT` | Arbitration-program flag at filing, for courts in that program. |
| `PROSE` | Pro se flag. Blank before October 1995; the v1 years are after that. |
| `IFP` | Fee status, captured since October 2000. |

The corporate rule is an inclusion rule. Inside a cohort that was already filtered to corporate defendants, the suffix flag is nearly constant and is not a feature.

### Forbidden features

These fields describe the ending or the path to the ending. They are labels, or they leak the label:

- `DISP`, `JUDGMENT`, `NOJ`, `AMTREC`
- `TERMDATE`, `TDATEUSE`, `TAPEYEAR`
- `PROCPROG` (procedural progress **at termination**)
- `TRCLACT`, `TERMJUDG`, `TERMMAG`, `TRMARB`
- `DJOINED`, `PRETRIAL`, `TRIBEGAN`, `TRIALEND` (the codebook says these dates were rarely entered and are no longer used; they are also post-filing)
- `STATUSCD` as a feature (it is only used to drop pending rows)
- `MDLDOCK` (an MDL number can be assigned after filing)
- `TITL`, `SECTION`, `SUBSECT` (optional, and not clearly frozen at filing)
- Opinion text, citation text, and every current courtpipe outcome field (`outcome_code`, `outcome_label_fine`, evidence, confidence, disposition-zone flags)
- RECAP `dateTerminated`, docket-entry text, and any event dated after `FILEDATE`
- Judge identity from `FILEJUDG` or `FILEMAG`. Both are blank on the public-use files.

`PROCPROG` is the field someone would reach for to build an "after the motion to dismiss" model. The codebook defines it as the point the case had reached **when it was disposed of**. Using it as a feature tells the model whether the case died before an answer, during trial, or after trial. That is leakage. Conditioning the cohort on `PROCPROG` ("only cases that reached pretrial") also selects on a post-filing path. v1 does neither.

An "after the complaint" or "after the motion-to-dismiss ruling" model needs events with dates, taken only from entries timestamped before the prediction instant, and a rule for what counts as the motion-to-dismiss ruling. RECAP can support that later. v1 cannot, because the entries endpoint refused unauthenticated calls (below) and the IDB does not store those timestamps.

### Split clock

The split uses `FILEDATE`, not termination date. Termination date is an outcome-adjacent fact: settled cases and tried cases have different durations. Details and the party-leakage rule are in `docs/EVALUATION.md`.

## Data sources

### FJC Integrated Database (v1 label and feature source)

Public civil termination files and the codebook are on the FJC page linked above. No API key. The cumulative tab-delimited zip `cv88on.zip` responded to a HEAD request on 7 October 2026 with `content-length` 329,665,474 and `last-modified` 26 August 2026. This spec does not open that zip and does not state how many rows or what share are code 13. Those counts are an output of the build, not an input to this proposal.

v1 uses terminated records only (`STATUSCD = L` where that field is present; it has been captured since October 2000). Pending rows (`STATUSCD = S`, and the pending slice of the cumulative file) have no disposition and are out of the cohort.

The codebook's `FILEDATE` is the actual filing date. `FDATEUSE` is the Administrative Office's statistical-year assignment and will not match published AO tables if ignored. v1 filters and splits on `FILEDATE`, and the evaluation report states both.

Join key, if a later phase attaches RECAP: `DISTRICT` + `OFFICE` + `DOCKET`, which is the key Alexander, Dahlberg, and Tucker used. v1 does not require the join.

### CourtListener opinions (not the v1 source)

The opinion search API answered without a token. The opinions list endpoint did not: `GET /api/rest/v4/opinions/` returned 401, `Authentication credentials were not provided.` Opinions remain the wrong population for settlement, for the reasons in the first section. v1 does not train on them.

### RECAP dockets (not the v1 label source)

Observed without a token on 7 October 2026:

| Request | Result |
| --- | --- |
| `GET /api/rest/v4/dockets/` | 401 |
| `GET /api/rest/v4/parties/` | 401 |
| `GET /api/rest/v4/docket-entries/` | 401 |
| `GET /api/rest/v4/search/?type=r&q=suitNature:"850 Securities/Commodities"` | `count` 67,143, `document_count` 2,218,487. First hit `suitNature` was `850 Securities/Commodities`. |
| `q=suitNature:850` | `count` 68,330, `document_count` 2,319,351. Same suit on the first hit. |
| `q=suitNature:410` | `count` 24,343, `document_count` 1,327,537. First hit `410 Antitrust`. |
| `q=suitNature:160` | `count` 11,178, `document_count` 346,888. First hit `160 Stockholders Suits`. |
| `q=suitNature:190` | `count` 465,671, `document_count` 5,155,669. First hit `190 Contract: Other`. |
| `q=suitNature:"190 Other Contract"` | `count` 399,843, `document_count` 950,204. First hit `190 Other Contract (Diversity)`. |
| `q=nature_of_suit:850` | `count` 0. That field name is the wrong operator. |
| `q=securities` with `type=r` | `count` 6,028,997, `document_count` 16,580,115. This is a word search, not a nature-of-suit census. |

`count` and `document_count` are the JSON fields the search API returned. They are archive hit counts, not the number of federal cases, and the two contract queries do not agree with each other. RECAP is the set of PACER dockets someone has placed in the archive, so coverage is incomplete and uneven across courts.

A search hit can include `party`, `suitNature`, `dateFiled`, and `dateTerminated`. It does not include `DISP`. Entry text, which is where a stipulation of dismissal would actually show settlement, sits behind the entries API. Free Law Project's bulk-data documentation lists high-level docket and opinion tables and says the FJC Integrated Database is imported and merged on request. A 2024 CourtListener issue (freelawproject/courtlistener #4139) records that the PACER archive was not in the public bulk dumps. v1 does not depend on either bulk interpretation.

RECAP is the right place for a later, dated-event model. It is the wrong place to label v1.

## v1 cohort

All of the following:

- Federal district civil terminations in the IDB.
- `FILEDATE` from 1 October 2009 through 30 September 2021 (fiscal years 2010 through 2021). The end date leaves later years out so that slow cases are not silently dropped as "still pending" in a file whose cumulative extract was current as of 30 June 2026. The build measures the filing-to-termination lag on the training years and applies the censoring rule in `docs/EVALUATION.md`.
- `NOS` is 160 (stockholder's suits), 410 (antitrust), or 850 (securities, commodities, exchange). These are the cover-sheet types aimed at corporate litigation rather than the general civil docket.
- Corporate defendant by the rules above.
- `ORIGIN` is 1, 2, 3, 5, 6, or 13 (original, removed, remanded from the court of appeals, transferred, MDL transfer, or MDL originating in the district). Origins 4 and 8 through 12 are reopened matters and are dropped so a reopened docket is not a second copy of an earlier case.
- Label is not `not_a_merits_ending`.

Contract NOS 190, 195, and 196 are out of v1. The unauthenticated `suitNature:190` hit count was 465,671, several times the securities, antitrust, and stockholder hit counts combined, and that code mixes commercial disputes with debt collection and other contract filings. Adding it would let contract base rates dominate the metric. It can be a later cohort.

Courts: all districts present in the file. v1 does not hand-pick SDNY or Delaware. Slice reporting is limited by the sample-size rules in the evaluation doc, so a tiny district will not produce a quoted rate.

This is buildable without `COURTLISTENER_API_KEY`: download the public zip, filter, train, and evaluate locally. The live CourtListener smoke test in the evaluation doc waits for the rotated key and is a separate gate.

## Out of scope for v1

- Any change to the opinion labeler, the review queue, or the court-only charts.
- Training on opinion text, embeddings, or citations.
- Predicting after a motion to dismiss, or using `PROCPROG` as a feature or a filter.
- Buying PACER documents, or calling the RECAP fetch API.
- Treating class-action settlement-approval opinions as the population. Those opinions state the outcome in the text. They are a different project.
- Publishing a settlement rate for "corporate litigation" in general. v1 can only speak about this cohort and this code.

## Decisions needed before a build

1. Primary positive class is IDB `DISP = 13` only. Codes 12 and 5 stay visible and are not called settled. Confirm or replace.
2. Cohort NOS codes are 160, 410, and 850. Contract stays out until a later version. Confirm or add codes.
3. The clock is filing. An after-motion model waits until docket entries are available under a token. Confirm.
4. "Corporate defendant" means the first-listed `DEF` string, plus the diversity incorporation flag. Full party lists wait on RECAP. Confirm.
5. Success is beating the filing-time baselines in `docs/EVALUATION.md`, not a fixed F1 number chosen in advance. Confirm.
