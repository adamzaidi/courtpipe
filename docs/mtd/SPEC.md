# Spec: motion-to-dismiss outcomes against corporate defendants

Status: proposal. This document does not add code, data, or a model. Build only after this spec and `docs/mtd/EVALUATION.md` are approved.

This is a different track from `docs/SPEC.md`. That document predicts filing-time settlement from the FJC Integrated Database. This one predicts how a district judge rules on a motion to dismiss. The two tracks do not share a label, a clock, or a training file. `docs/SPEC.md` and `docs/EVALUATION.md` are left as they are.

No Granola notes discussed this project. The proposal is from the current courtpipe code, public CourtListener responses collected on 7 October 2026, and the CourtListener docket models those responses line up with.

## What the current pipeline actually does

`etl/transform.py` labels an opinion by searching its text, preferring the tail, for `vacate`, `reverse`, `remand`, `affirm`, and `dismiss`. Confidence rises when those words sit near `opinion`, `judgment`, `order`, or a phrase such as `we affirm`. `analysis/model.py` then trains logistic regression and a random forest on court, opinion year, a word-count bucket, and three fields taken from that same labeling pass: `disposition_zone_found`, `evidence_contains_strong_phrase`, and `evidence_match_position`.

That is extraction of the ruling. The words the labeler matches are the outcome, and several model features are functions of those words. The fine labels the code emits are `affirmed`, `dismissed`, `reversed`, `vacated`, `remanded`, `mixed`, and `other`. None of those is "this Rule 12(b)(6) motion was granted in part." An appellate affirmance of a dismissal is a different event from the district judge's order on the motion.

A search hit for an opinion is also the wrong object. On 7 October 2026, unauthenticated `GET /api/rest/v4/search/?type=o&q=court_id:nysd AND "12(b)(6)" AND "motion to dismiss"` returned `count` 5,104. Those are Southern District of New York opinions whose text contains the phrases. The first hit was `Garner v. Behrman Bros. IV, LLC`, docket `16 Civ. 6968 (PAE)`. A hit of that kind can be the order, a later opinion in the same case, or an opinion that only cites the rule. The count is not the number of motions.

## Prediction question for v1

For one Rule 12(b)(6) motion to dismiss filed by a corporate defendant in a federal district civil case in the cohort below, estimate the probability of each outcome of that motion:

- `granted`
- `granted_in_part`
- `denied`

The information set is material filed before the ruling: the complaint, the motion and briefs, and docket metadata. The ruling is the label. It is not an input.

The binary summary used for ranking and calibration is `y_relief = 1` when the label is `granted` or `granted_in_part`, and `0` when the label is `denied`. "Did the movant get any of the dismissal it asked for" is the binary question. The three-way label stays on every row. A model that only separates full grants from denials, and never separates partial grants, has to say so. The evaluation protocol makes that sentence mandatory when the metrics come out that way.

Leave to amend is stored on the same row. It is not a fourth class. See below.

## Unit of prediction

One row is one motion, linked to the order that first resolves it.

A case with a motion against the original complaint and a later motion against an amended complaint produces two rows. A single order that resolves two motions produces two rows. Both rows share a docket id, and the split in `docs/mtd/EVALUATION.md` keeps a docket on one side.

The row is the corporate defendant's motion. A plaintiff's motion to dismiss a counterclaim is out of the cohort. An order that grants as to the company and denies as to an individual officer is labeled for the company's motion. If the order cannot be tied to the company, the row is `movant_unresolved` and leaves the cohort.

## How a ruling is found

v1 labels from the docket, then uses a written opinion only to fill a gap. Both sources are label stores. The feature builder cannot read them.

### Source 1: the order's docket entry

CourtListener's `DocketEntry.description` is the text of the entry on the PACER docket page. `DocketEntry.date_filed` is the entry's date in the court's timezone. `time_filed` is a nullable time on the same model. `RECAPDocument.is_available` is true when the file is in the RECAP archive. The search serializer for a RECAP document exposes a `snippet` taken from `plain_text` and does not return the full body.

With `COURTLISTENER_API_KEY` set, the build reads:

- `GET /api/rest/v4/dockets/{id}/`
- `GET /api/rest/v4/docket-entries/?docket={id}`
- `GET /api/rest/v4/recap-documents/` for the documents on those entries
- `GET /api/rest/v4/parties/?docket={id}`

The token is sent as `Authorization: Token <value>`, the same header `etl/extract.py` already uses. The value comes from the environment. It is not written into the report, the fixtures, or the repository. `.env` stays gitignored. `.env.example` keeps the placeholder.

On 7 October 2026, without a token, each of `dockets/`, `parties/`, `docket-entries/`, `recap-documents/`, and `opinions/` returned 401 with `Authentication credentials were not provided.` The docket serializer in the CourtListener source also excludes the nested `parties` list, so a docket payload is not a substitute for the parties endpoint.

An entry is a candidate order only if its description matches an order, memorandum, or minute entry, and the description also refers to a motion to dismiss, Rule 12(b)(6), or failure to state a claim. Two exclusions are applied before any verb is read:

- The description contains `proposed order` or `text of proposed order`. On 7 October 2026 a document-search hit whose description contained both `ORDER granting` and `Motion to Dismiss for Failure to State a Claim` was a motion, not an order: "MOTION TO DISMISS FOR FAILURE TO STATE A CLAIM by Defendants International Business Machines Corporation, Red Hat, Inc." with an attached proposed order. A proposed order states the relief the movant wants. It is a party filing.
- The description is a report and recommendation, or a magistrate judge's recommendation. That document is not the district judge's ruling. If the district judge later adopts it, the judge's entry is the candidate.

### Source 2: a written opinion, only if the entry does not state the disposition

Some orders say only "Order on Motion to Dismiss" and put the disposition in a PDF or in a CourtListener opinion cluster linked to the docket. The opinion list endpoint returned 401 without a token. Opinion search is public and can include a `download_url` on the nested opinion. v1 may read that text for the label after the entry is tied to a motion. The same text is then sealed in the label store.

If the entry description has no grant, deny, or partial verb, and neither the order file nor a linked opinion is available, the row is `needs_text`. It is not given a class. It is counted in the funnel and omitted from training.

### Why a public keyword search is not the finder

RECAP document search is public, and it is the wrong tool for building the cohort.

| Query on 7 October 2026 | `type` | `count` | What the first page showed |
| --- | --- | --- | --- |
| `"motion to dismiss" "failure to state a claim"` | `rd` | 1,094,506 | An opposition brief, `is_available` false. Document 52 on docket 70649963, filed 2025-11-06. |
| `short_description:"Order on Motion to Dismiss for Failure to State a Claim"` | `rd` | 86,224 | The `short_description` string repeated. `court_id` was null. |
| that short-description query `AND is_available:true` | `rd` | 27,235 | A memorandum order directing a RICO case statement, dated 28 March 2025 in the description. `page_count` 4. |
| that short-description query `AND is_available:false` | `rd` | 59,458 | Description empty on the first hit. |
| `short_description:"Motion to Dismiss for Failure to State a Claim"` | `rd` | 107,296 | A motion document, `is_available` true, `page_count` 5, description empty, `court_id` null. |
| that motion query `AND is_available:true` | `rd` | 31,726 | Same shape of hit. |
| `short_description:"Complaint"` | `rd` | 5,209,203 | A notice of removal, not a complaint census. |

`count` is the search API's hit count. It is not the number of motions in the cohort. The two `is_available` counts for the order short-description query sum to 86,693, which is 469 above the unfiltered count of 86,224, so those two queries are not a clean partition of the first query. Adding `court_id:nysd` to the order short-description query returned `count` 0. The RECAP-document search serializer drops `court_id`. A zero from that filter is a failed filter, not a finding that the Southern District has no such orders.

The first page of the looser phrase query `"Order on Motion to Dismiss for Failure to State a Claim"` was later filings that quote an order's title: motions for reconsideration, notices of appeal, judgments, and certificates of service. Fifteen of those twenty hits had `is_available` false. That page is the first page the API returned, not a random sample, and it is enough to show that a phrase search harvests references to orders.

v1 therefore finds orders by walking docket entries on in-cohort dockets. Search is used to list candidate dockets. It is not used as the label.

## How the order is mapped to the motion

CM/ECF descriptions can name the document number they resolve. The parser looks for those patterns and is tested against them. The patterns are hypotheses, not a claim that they cover the archive:

- `granting 15 Motion to Dismiss for Failure to State a Claim`
- `denying 15 Motion to Dismiss`
- `granting in part and denying in part 15 Motion to Dismiss`
- a minute entry that names the motion and uses `granted`, `denied`, or `granted in part`

The integer is the motion's document number. The entry with that document number is the motion only if its own description is a motion to dismiss. If the order names several document numbers, each linked motion becomes its own row, and each row takes the verb attached to its own number.

If the order says "the motion to dismiss" and does not give a number, the link is kept only when exactly one candidate motion is pending on that docket on the order date. Two pending motions and no number yields `link_ambiguous`, and the row leaves the cohort.

The motion is in the 12(b)(6) cohort when the motion entry, or the order entry, identifies Rule 12(b)(6) or failure to state a claim. A motion that also raises Rule 12(b)(1) or Rule 12(b)(2) stays in. The row is flagged `also_12b1` or `also_12b2`. If the order states separate dispositions for the separate rules, the label is the disposition of the 12(b)(6) request. If the order uses one verb for the whole motion, the label is that verb and the row is flagged `grounds_not_separated`.

Motions that raise only 12(b)(1), only 12(b)(2), or only another 12(b) subsection are counted in the funnel and excluded. Jurisdiction and venue are different questions from plausibility. They can be a later cohort. They are not folded into v1 to enlarge it.

### Dispositions that are not a ruling on the motion

These leave the cohort. They are not coded as `denied`.

| Situation | Rule |
| --- | --- |
| Withdrawn, stipulated, or voluntarily dismissed before an order | The motion was not ruled on. |
| Denied or granted as moot, including mootness after an amended complaint | No merits ruling on the motion. |
| Converted to a summary-judgment motion under Rule 12(d) | The court looked outside the pleadings. Different procedure. |
| Magistrate recommendation with no district-judge order yet | Not yet a ruling. |
| Appellate opinion about a dismissal | Out. Appellate affirmance is the current pipeline's task. |
| Order on reconsideration | Not the first resolution. The first order is the label. A later reconsideration is ignored. |

The first resolving order is the label even if a later order changes it. Predicting reconsideration is a different task.

## The three classes, and leave to amend

| Label | Rule |
| --- | --- |
| `granted` | The 12(b)(6) request is granted as to every claim it attacks, or the complaint is dismissed in full on 12(b)(6). Leave to amend does not move this row to another class. |
| `granted_in_part` | At least one attacked claim is dismissed on 12(b)(6) and at least one attacked claim survives. The same rule applies across defendants when the order splits them and the row is the corporate movant: dismissal as to the company and survival as to the company are what count. |
| `denied` | The 12(b)(6) request is denied in full. "Denied without prejudice" is still `denied`. |

One row receives one of these three, or it leaves the cohort under the rules above.

Leave to amend is a modifier, not a class:

| Modifier | Rule |
| --- | --- |
| `leave_granted` | The order grants leave to amend, or it directs the plaintiff to file an amended complaint by a date. |
| `leave_denied` | The order says with prejudice, without leave to amend, or otherwise denies leave. |
| `leave_not_stated` | The order does not say. "Without prejudice," standing alone, is recorded in the audit notes and coded `leave_not_stated`. It is not treated as leave to amend. Courts use that phrase for more than one idea. |

A six-way label (three dispositions crossed with leave) would split an already uneven problem into cells the audit cannot support. The cross-tab of disposition by leave is reported. A denial almost never carries leave. "Granted with leave" is still a grant of the motion: the complaint, as it stood, failed. Whether the plaintiff may replead is the modifier.

The hand-audit rubric, the sample size, and the accuracy bar are in `docs/mtd/EVALUATION.md`. The label is usable for training only if that bar is met. The known ways the automatic label goes wrong, which the audit is built to catch, are:

- An entry that quotes another document's title, so a later brief looks like an order.
- A proposed order attached to the motion.
- One order resolving several motions or several defendants with different verbs.
- A 12(b)(6) request and a jurisdictional request disposed of in one sentence.
- "Without prejudice" read as leave, or "with leave" read as a denial because the case continues.
- A generic "Order on Motion to Dismiss" with no PDF in RECAP, which must stay `needs_text` rather than being guessed.
- The current opinion labeler seeing the word `dismissed` in a complaint, a brief, or an appellate opinion.

## What the model may see, and how it is fetched

The prediction instant is the order's filing time. Every feature comes from a docket entry strictly before that instant.

The RECAP search hits inspected on 7 October 2026 carried `entry_date_filed` as a calendar date. The docket-entry model also has nullable `time_filed`. The cutoff is:

- If the order and the other entry both have `time_filed`, the other entry is allowed when its timestamp is strictly earlier.
- If either time is null, the other entry is allowed only when its `date_filed` is strictly earlier. A brief filed the same calendar day as the order is dropped and counted. Same-day order is not proof that the brief was on file when the judge ruled.

Allowed materials, when their entry passes that cutoff:

| Material | Where it comes from |
| --- | --- |
| Operative complaint | The latest complaint or amended complaint among allowed entries. |
| The motion and its memorandum, exhibits, and proposed order | The motion entry the order cites, plus attachments on that entry. The proposed order is a party filing. It is allowed as text of the ask. It is never a label. |
| Opposition, reply, and any sur-reply | Party entries before the cutoff. |
| Docket metadata | Court, nature of suit, cause, jurisdiction type, jury demand, dates of allowed entries, party and counsel records tied to the movant. |
| Judge | `assigned_to` on the docket, and only with the limitation in the judge paragraph below. |
| Counts | Prior amended complaints, number of defendants, number of corporate defendants, whether an opposition was filed. |

The operative complaint is the latest complaint-like entry that passes the cutoff. If the plaintiff amends while the motion is pending, and that amended complaint still passes the cutoff, it is the operative complaint and the row is flagged `complaint_amended_while_pending`. The order may later call the motion moot because of that amendment. Mootness is a label-time exclusion, applied from the order, which the feature builder does not see. The flag itself does not state the outcome.

### Documents that are listed and not in the archive

`is_available` false means the docket index knows about the filing and RECAP does not have the file. v1 does not buy it from PACER and does not call a fetch that purchases it.

On 7 October 2026 the first hit for terminated securities dockets filed in the first half of 2018 was `Tennenbaum v. Gamble, Jr.`, Northern District of Georgia, `1:18-cv-00967`, filed 2018-03-05, terminated 2021-03-22. The search hit's `meta.more_docs` was true. The embedded `recap_documents` list had three items, all `is_available` false. The first was the verified shareholder derivative complaint. The query that returned this hit, `suitNature:"850 Securities/Commodities" AND dateFiled:[2018-01-01 TO 2018-06-30] AND dateTerminated:[2018-01-01 TO 2024-12-31]`, had `count` 732 and `document_count` 41,169. Those two fields are archive totals for the query. They are not a count of purchasable PDFs, and the three embedded rows are not the whole docket.

The authenticated RECAP document record includes `plain_text`, the extracted text stored on CourtListener's PDF model. Search returns a `snippet` from that field and does not return the field itself. When `plain_text` is blank, the text features are missing. v1 does not OCR the file to fill them. They are not filled with zero, and they are not filled from the order. Page count is used only when the document record has one. The headline test scores every labeled motion, including motions whose complaint file is absent. A second score, defined in the evaluation doc, uses only rows where the complaint and the motion memorandum are both `is_available`. That score is not the headline. That same Georgia hit's `party` array had 17 names, and the embedded complaint was `is_available` false. One docket is not a rate.

### Judge

The feature is `assigned_to_id` from the docket. On 7 October 2026 the Georgia securities hit had `assignedTo` "Thomas W. Thrash Jr." The first hit of `suitNature:"850 Securities/Commodities"`, `CT Healthcare Holdings, LLC v. Sek`, Western District of Texas, `1:26-cv-02750`, filed 2026-09-29, had `assignedTo` null and empty attorney and firm lists. The field is the assignment CourtListener stores, not a history of assignments. v1 uses it only when the build can show the assignment was already on the docket on or before the motion date. Otherwise the judge feature is `unknown`, and the judge baseline uses the court rate for that row.

The signature block inside the order ("Signed by Judge …") is part of the ruling text. It is not copied into the feature table to fill an unknown judge.

### What is forbidden

The feature table is built by a function that receives pre-order party entries and docket metadata. It does not receive the order, later entries, or opinions. A test in the evaluation doc feeds it those objects and requires them to be absent from the matrix.

Forbidden, even if a field would be easy to join:

- The order entry's description, the order PDF, the order's `plain_text`, and any opinion that is the ruling or that cites the ruling.
- Any entry that does not pass the cutoff, including amended complaints, answers, and settlement filings after the order.
- `dateTerminated`, termination reason, and every FJC disposition field (`DISP`, `JUDGMENT`, `PROCPROG`, `TERMDATE`). `PROCPROG` records how far the case had gone when it ended. The settlement spec already bars it. It is not a motion-to-dismiss label and not a feature.
- The current courtpipe outcome columns: `outcome_code`, `outcome_label_fine`, evidence snippets, confidence, `disposition_zone_found`, `evidence_contains_strong_phrase`, `evidence_match_position`.
- Opinion `citeCount`, `posture`, `procedural_history`, and `syllabus`. Search hits for opinions include those fields. Citations accumulate because of the outcome and after it.
- A report and recommendation, and any entry description that states a recommended disposition.
- Days from the motion to the order. That interval uses the order date. Days from the complaint to the motion are allowed. They are known when the motion is filed.
- Counsel who are not tied to the movant. The docket-level `attorney` and `firm` arrays on a search hit are not role-tagged. On the Georgia hit they mixed firms. Using the whole list treats plaintiff's counsel and later appearances as features. Counsel features use attorneys linked to the corporate movant. If the payload has no appearance date, the row is flagged `counsel_as_of_unknown` and the model still may use the movant's counsel list, because those lawyers filed the motion. Lawyers who show up only on entries on or after the order date are out.
- The fact that a later amended complaint was accepted, that leave was taken, or that the case settled. Those are consequences.

## Corporate defendant

A case is in the cohort when the motion's movant is a corporate defendant. The name rules follow the settlement spec so the two tracks describe a company the same way. The role rule is stricter here, because this track can see parties and the settlement track cannot.

The parties endpoint is what carries the role. A public docket search hit has a `party` array of names and no role. On the Georgia hit that array included `Equifax, Inc.` and a list of individuals. The short case name was `Tennenbaum v. Gamble, Jr.`, which does not show Equifax. On the Western District of Texas hit the parties were `CT Healthcare Holdings, LLC` and `Sek`, and the LLC is the plaintiff in the case name. A suffix rule applied to every name in `party` would call both cases corporate for the wrong reason.

v1 therefore does not decide the cohort from the search `party` array.

Once the parties payload is available, a party is a defendant when a party-type string on that party is `Defendant`, `Respondent`, or `Cross Defendant`, compared case-insensitively. If the authenticated payload has no party-type field, the build stops. It does not fall back to the caption. The smoke test records the keys the payload actually contains.

A defendant is governmental, and not corporate, if the normalized name contains any of: `UNITED STATES`, the token sequence `U S`, `STATE OF`, `COMMONWEALTH`, `CITY OF`, `COUNTY OF`, `DEPARTMENT`, `SECRETARY`, `COMMISSION`, `DISTRICT ATTORNEY`. The government rule runs first, so a government name that also contains a company word is still governmental.

Otherwise a defendant is corporate when the normalized tokens include one of: `INC`, `INCORPORATED`, `CORP`, `CORPORATION`, `LLC`, `LLP`, `LP`, `LTD`, `LIMITED`, `PLC`, `BANCORP`, `HOLDINGS`, `COMPANY`, or the token sequences `L L C`, `L L P`, `L P`, `P L C`, `N A`, `NATIONAL ASSOCIATION`.

`CO`, `BANK`, `GROUP`, `ASSOCIATION`, and bare `PC` are not suffixes. They match too many non-companies. The cost is missing some banks, associations, and professional corporations. That cost is accepted in v1.

The movant is the party named as the filer on the motion entry ("filed by …") when that string matches a defendant. If the entry does not name the filer, the movant is the defendant whose linked attorney matches an attorney on the motion entry. If neither match works, the row is `movant_unknown` and leaves the cohort. It is not assumed to be the company's motion.

An individual officer as the only movant is out, even when the company is a co-defendant. The company's own motion is in. A motion filed jointly by the company and its officers is in, and the label follows the company's result when the order splits them.

## Cohort: case type, court, and year

All of the following:

- Federal district court. The public courts endpoint on 7 October 2026 returned `count` 3,359 courts in total. `GET /api/rest/v4/courts/?jurisdiction=FD` returned `count` 125, of which 105 had `in_use` true and 20 had `in_use` false. v1 keeps `jurisdiction` FD and `in_use` true, and drops `usdistct`. That id is the generic parent: `GET /api/rest/v4/courts/nysd/` returned `parent_court` pointing at `usdistct`, `jurisdiction` FD, `in_use` true, and `appeals_to` as an empty list. Circuit is not read from `appeals_to`. It comes from a checked-in map of district `court_id` to circuit, which is a fact about the court, knowable at filing.
- Nature of suit, from the docket's `suitNature`, is one of:
  - `160` stockholder's suits
  - `410` antitrust
  - `480` consumer credit
  - `850` securities, commodities, exchange
- The motion's `date_filed` is from 1 January 2016 through 31 December 2023.
- The movant is a corporate defendant under the rules above.
- The motion is a 12(b)(6) motion under the rules above, and it has a resolving order that yields one of the three labels.

Nature-of-suit search on 7 October 2026, `type=r`, returned these archive hit counts. They are not cohort sizes. They restate the live API so the scope can be checked without a token:

| Query | `count` | `document_count` |
| --- | --- | --- |
| `suitNature:160` | 11,178 | 346,888 |
| `suitNature:410` | 24,343 | 1,327,537 |
| `suitNature:480` | 136,118 | 2,373,552 |
| `suitNature:"850 Securities/Commodities"` | 67,143 | 2,218,487 |
| `suitNature:"190 Other Contract"` | 399,843 | 950,204 |
| `court_id:nysd` | 595,400 | 11,111,820 |
| `court_id:nysd AND suitNature:850` | 13,415 | 539,360 |

Contract NOS 190 is out of v1. The quoted query is several times the securities count, and that code mixes commercial disputes with a large mass of other contract filings. Adding it would let contract base rates dominate the metric. It can be a later cohort.

"Consumer class action" is not a nature-of-suit code. v1 uses NOS 480 as the consumer slice. A class allegation is a feature when the complaint text or a pre-order entry says so. It is not required for inclusion. Securities and stockholder cases in this list include many class and derivative complaints. The docket's `suitNature` is the case type even when the complaint reads like a different one. The Georgia hit was a shareholder derivative complaint and its `suitNature` was `850 Securities/Commodities`. v1 does not relabel that docket as NOS 160.

Courts are every in-use federal district, not a hand-picked set of SDNY, Delaware, and the Northern District of California. Slice reporting in the evaluation doc suppresses tiny courts. A small district does not get a quoted win.

Years start in 2016 so the whole window is after *Iqbal* (2009). The pleading standard is the same rule across the split. That is not a claim about RECAP coverage by year. Coverage by year is unmeasured here and is an output of the build.

The scored split, defined in the evaluation doc, uses motion dates 2016–2019 for training and 2020–2022 for test. Motions filed in 2023 are extracted and quarantined. They are not scored and not used to choose features. They exist so the build can see how many recent motions still have no order.

### Funnel the build must print

This proposal does not fill these cells. The build counts them from the extract and puts them in the report:

1. Dockets in the court, nature-of-suit, and year scope.
2. Entries that look like a 12(b)(6) motion.
3. Of those, motions linked to a first resolving order.
4. Of those, motions whose movant is a corporate defendant.
5. Of those, motions with a complaint file in RECAP, and motions with a motion memorandum in RECAP.
6. The labeled cohort, by nature of suit and by motion year.

Until those cells are filled from an authenticated extract, there is no cohort size to defend.

## Candidate features

The first model uses only fields that can be filled for every labeled row, with an explicit missing value where the archive has a hole. The second model adds text features and missingness indicators. The headline test is the second model scored on every labeled test row. A win limited to rows where the complaint and the motion memorandum are both `is_available` is reported separately. Details are in the evaluation doc.

| Feature | Known before the order? | Notes |
| --- | --- | --- |
| `court_id`, circuit from the checked-in map | Yes | Court of filing. |
| `assigned_to_id` | Only under the judge rule above | Unknown stays unknown. |
| Nature of suit, cause string, jurisdiction type, jury demand | Yes, as stored on the docket | Cause on the Georgia hit was `15:78m(a) Securities Exchange Act`. The string is used as a category, not parsed into a private taxonomy in v1. |
| Days from the operative complaint's filing date to the motion | Yes | Days from motion to order are forbidden. |
| Count of amended complaints filed before the motion | Yes | Same-day complaints count only when `time_filed` shows they were earlier. |
| `complaint_amended_while_pending` | Yes, from pre-order entries | Does not encode mootness. |
| Number of defendants, number of corporate defendants | Yes, from the parties payload | Roles required. |
| Movant counsel and firm, linked to the movant | Yes, with the counsel rule above | The untagged docket-level firm list is forbidden. |
| Opposition filed, reply filed | Yes | Presence and pre-order page counts. |
| Complaint page count or word count | When the file or `page_count` is present | Missing is its own value. |
| Complaint structure | When `plain_text` is present | Count of claim or count headings. A missing file is not "zero claims." |
| Class-allegation flag | When pre-order text says so | Not a cohort filter. |
| Motion length, and flags for citations to *Twombly*, *Iqbal*, Rule 9(b), and the PSLRA | When the motion text is present | These are the pleading-standard cases and rules a 12(b)(6) brief usually argues. The flags are string matches in the motion, not in the order. |
| Exhibit attached to the motion | Yes, from attachments | A proxy for a Rule 12(d) risk. The row is already excluded if the court converted the motion. The flag is still allowed, because the attachment exists at filing. |
| Text of the complaint, the motion, the opposition, and the reply | When `plain_text` exists and the entry passes the cutoff | Bag of words or a simple linear model. No embeddings in v1. No text from the order. |

`assigned_to_id` with only a handful of training motions is a memorization risk. The baseline and the slice rules handle that. The model may still include the judge. It has to beat the judge baseline, not merely rediscover it.

## Feasibility

### Measurable without a token, and already measured

Public search and the public courts list answer the questions in the tables above. They support a scope decision: which nature-of-suit codes, which courts, and which document fields exist on a search hit. They do not support a label.

A search hit for a docket can include `party`, `suitNature`, `cause`, `dateFiled`, `dateTerminated`, `assignedTo`, `attorney`, `firm`, and a partial `recap_documents` list. `dateTerminated` is forbidden as a feature even though it is present. `meta.more_docs` true means the embedded document list is incomplete. The Georgia hit is the concrete case.

### Requires the rotated key

Linking a motion to an order, reading party roles, listing every entry, and reading `plain_text` where RECAP has it. The environment variable is `COURTLISTENER_API_KEY`. Until it is set, the label audit and the model are blocked. Fixture tests of the labeler can still be written against hand-written entries. Those tests do not pass the accuracy gate.

The key does not create PDFs. `is_available` false stays false unless someone has already placed the file in RECAP. v1 does not purchase the rest.

There is no FJC substitute. The Integrated Database can say how a case ended. It does not say how a particular 12(b)(6) motion was decided, and it does not separate a grant with leave from a grant with prejudice. The settlement track's `DISP` codes stay on that track.

### Coverage risks, with no invented rates

RECAP is the set of PACER dockets and documents someone uploaded or bought. It is denser in matters people cared to fetch. The build must show the cohort's court and nature-of-suit mix. It must not describe that mix as the national mix of corporate motions. A comparison to FJC filing counts for the same codes and years is allowed as a descriptive table when a local IDB file is provided. v1 does not reweight to the IDB. If no IDB file is provided, the comparison is omitted rather than approximated.

Missing documents will cut text features down to a subset. That subset can differ in court and nature of suit from the full labeled cohort. The evaluation doc requires both scores, and the subset score is a coverage result. This proposal states no percentage for how often the complaint, the motion, or the order is in RECAP. Those percentages are funnel outputs.

Opinion text is a poor backfill for missing orders. The 5,104-hit Southern District query shows that the phrases occur in opinions. It does not show that each hit is the motion's ruling, and the opinion endpoint that would return a stable opinion record was 401 without a token.

## Out of scope for v1

- Any change to the opinion labeler, the review queue, the charts, or the settlement spec.
- Training a model in this change. This document is the proposal.
- Buying PACER documents or calling a RECAP purchase endpoint.
- Appellate outcomes, remand, or affirmance.
- Rule 12(b) motions that do not raise 12(b)(6).
- Rule 56 motions, class certification, and settlement approval.
- Contract NOS 190, bankruptcy courts, and state courts.
- Embeddings, large language models, and citation-network features.
- A published "grant rate for motions to dismiss against corporations." v1 can speak only about the labeled cohort and the three classes.

## Decisions needed before a build

1. The classes are `granted`, `granted_in_part`, and `denied`. Leave to amend is a modifier with values `leave_granted`, `leave_denied`, and `leave_not_stated`. "Without prejudice" alone is `leave_not_stated`. Confirm or promote leave to a class.
2. v1 keeps motions that raise 12(b)(6) even when they also raise 12(b)(1) or 12(b)(2), and drops purely jurisdictional motions. Confirm or include the jurisdictional motions as their own label.
3. Nature-of-suit codes are 160, 410, 480, and 850. Contract 190 stays out. Confirm or add codes.
4. Courts are in-use federal districts except `usdistct`. Motion dates 2016–2023 are extracted. Training is 2016–2019, test is 2020–2022, and 2023 is quarantined. Confirm or narrow to a short list of courts.
5. The cutoff is strictly before the order, so opposition and reply briefs are inputs when they were filed in time. A motion-day model that ignores the opposition is a later sensitivity, not v1. Confirm.
6. An unknown judge stays unknown. The order's signature block is not a feature. Confirm.
7. Corporate status requires a party-type role from the authenticated parties payload. The search `party` list is not enough. Confirm.
8. The model has to beat the best of the judge, court, and nature-of-suit baselines in `docs/mtd/EVALUATION.md` on the full labeled test set. A win only on rows where the complaint and the motion are both in RECAP is not a cohort result. Confirm.
