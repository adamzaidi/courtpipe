# Spec: federal securities class actions

Status: proposal. This document does not add code, data, or a model. Build only after this spec and `docs/EVALUATION.md` are approved.

Adam narrowed the target. The plan is federal securities class actions. There are two questions:

1. Will a resolved case be dismissed, or will it settle?
2. If it settles, roughly how large is the settlement?

The earlier plan, which used the Federal Judicial Center's civil Integrated Database and clerk disposition code 13 for a broader set of corporate cases, is Appendix A. It is an alternative if the case list below cannot be obtained. It is not the plan for this model.

No Granola notes discussed this project. The proposal is from the current courtpipe code, the Stanford Securities Class Action Clearinghouse about page, Cornerstone Research's public 2025 reports, NERA's public 2025 review page, the SEC's EDGAR access page, the FJC civil codebook, and public CourtListener responses. Pages were read on 7 October 2026. Counts below are the figures those pages stated, or JSON fields an endpoint returned. This draft did not open a Clearinghouse case page, did not count rows in a spreadsheet, and did not open the FJC zip.

## What the current pipeline actually does

`etl/transform.py` labels an opinion by searching its text, preferring the tail, for `vacate`, `reverse`, `remand`, `affirm`, and `dismiss`. `analysis/model.py` trains on court, opinion year, a word-count bucket, and three fields taken from that same labeling pass: `disposition_zone_found`, `evidence_contains_strong_phrase`, and `evidence_match_position`.

That is outcome extraction. The words the labeler matches are the outcome, and several model features are functions of those words. The fine labels the code emits are `affirmed`, `dismissed`, `reversed`, `vacated`, `remanded`, `mixed`, and `other`. There is no settlement label and no settlement amount. The comment in `data/reference-tables/courtlistener_data_dictionary.csv` that lists Settlement as a fine label does not match the code.

Appellate affirmance is the wrong population. Securities class actions are district-court cases. Many that settle never produce a merits opinion, and an opinion that does discuss the ending states the ending in the text. v1 leaves the opinion labeler, the review queue, and the existing charts as they are.

## Population

v1 follows the Clearinghouse's own population, stated on [About the SCAC](https://securities.stanford.edu/about-the-scac.html):

- Federal securities class actions filed on or after 1 January 1996, after the Private Securities Litigation Reform Act of 1995.
- One record consolidates related complaints that share the same underlying allegations and the same defendant or set of defendants. Later complaints about the same subject become part of that record. The Clearinghouse builds the record before the court consolidates the cases.
- Case summaries generally rely on the first identified complaint. If several complaints are filed at once, the Clearinghouse uses the most detailed one. If it later finds an amended or consolidated complaint, it updates the summary.
- State-court suits with no parallel federal class action are outside the database.
- SEC enforcement proceedings are outside the database. Parallel federal civil class actions are inside it.

The about page states that the filings database contains 6,879 securities class action lawsuits filed since the Act. That is the Clearinghouse's stated count. It is not a row count this repository measured, and it is not the denominator in the Cornerstone or NERA reports below. Those publishers use their own filters. Cornerstone's "core" filings, for example, exclude merger-and-acquisition filings.

v1 keeps one row per Clearinghouse record. It does not split a consolidated record back into the original complaints, and it does not divide the settlement fund across them.

Merger-and-acquisition filings (Section 14 claims without Rule 10b-5, Section 11, or Section 12(a) claims, which is Cornerstone's description) are a different settlement process. If the spreadsheet flags them, v1 drops them and reports the drop. If it does not flag them, they stay in, and the report says the cohort is broader than Cornerstone's core filings. That choice is one of the decisions at the end.

## Labels

The spreadsheet's status vocabulary is unknown until the file arrives. The build writes a crosswalk from those values onto the labels below, and the audit in `docs/EVALUATION.md` checks the crosswalk. The labels are the ones Cornerstone uses for core federal filings in its 2025 year-in-review page: dismissed, settled, remanded, continuing, and trial.

| Label | Rule | Role |
| --- | --- | --- |
| `dismissed` | The case ended by dismissal, and the record does not describe a settlement. | Class 0 in the binary task. |
| `settled` | The parties settled, and a settlement was reached for the class case. | Class 1 in the binary task. Amount task uses these rows when a total fund is stated. |
| `trial` | The case reached trial. | Excluded from both scores. Counted in the report. |
| `remanded` | The case was remanded and has no later dismissal or settlement in the record. | Excluded from both scores. Counted in the report. |
| `ongoing` | The case is still open, or the file has no terminal status. | Excluded from both scores. This is right-censoring, not a third class and not a dismissal. |
| `unmapped` | The status value has no row in the crosswalk. | Excluded. The values are listed. They are not folded into dismissed or settled. |

A row receives one label. A settled case stays `settled` even if an earlier motion to dismiss was denied. A dismissal after a settlement agreement is `settled`, because the ending the model is asked to predict is the settlement.

### Why ongoing cases are excluded

Cornerstone's [Securities Class Action Filings—2025 Year in Review](https://www.cornerstone.com/insights/reports/securities-class-action-filings-2025-year-in-review/) page states two facts that drive the split:

- From 1997 to 2025, 46% of core federal filings were settled, 45% were dismissed, 0.5% were remanded, and 8% are continuing. During that period, 0.4% of core federal filings (22 filings) reached trial.
- In the first few years after filing, dismissals outnumber settlements. Later, settlements outnumber dismissals. From 2015 to 2022, 54% of core federal filings have been dismissed, 39% have settled, and 5% are ongoing. Of core federal filings that are ongoing, 81% were filed between 2023 and 2025.

Those are Cornerstone's aggregates for its core-federal definition. They are sanity checks. They are not labels, and they are not this cohort's measured rates.

Scoring recent filings as if the still-open ones did not exist would bias the test set toward early dismissals. v1 drops `ongoing` rows from both tasks, counts them, and refuses a test window that is still mostly unresolved. The rule is in `docs/EVALUATION.md`.

`trial` and `remanded` stay out of the binary task. Folding 22 trials into "dismissed" or "settled" would invent a class for a rare ending. The report prints their counts.

### Settlement amount

The amount target is the total settlement fund for the record, in dollars, before attorneys' fees.

- The model predicts the natural log of the inflation-adjusted fund.
- Dollars are adjusted with the CPI-U annual average (not seasonally adjusted) into the last complete calendar year covered by the extract. Cornerstone states that its published settlement dollars are inflation-adjusted and that its 2025 figures are 2025 dollar equivalents. v1 uses the same index family and records the base year.
- The settlement year is the year of the settlement hearing when the file has that date. Cornerstone assigns the settlement year that way. If the file has a settlement year and no hearing date, v1 uses the file's year and says so.
- A settled row with no stated fund, a zero fund, or only a partial payment that is not the total fund is `amount_incomplete`. It remains in the classification task. It leaves the amount task. v1 does not impute an amount.
- The amount is never a feature. It is a label, and only for rows already labeled `settled`.

"Roughly" is an evaluation statement, not a label. `docs/EVALUATION.md` scores log error and the share of predictions within a factor of two of the fund.

## Prediction time and leakage

The default clock is the filing date of the first identified complaint. That matches the Clearinghouse's summary rule: the first complaint stands in for the related complaints.

A second clock is allowed only if it is chosen before any test score is computed: the date of the consolidated complaint. Every feature under that clock has to be dated on or before that complaint. The report names which clock was used. Switching clocks after a test score invalidates the run.

### Known at the first complaint

| Feature | Where it can come from |
| --- | --- |
| Court and circuit | Clearinghouse spreadsheet, if present. FJC `DISTRICT` and `CIRCUIT` as a cross-check. A RECAP search hit's `court_id`, once a token exists. |
| Filing year and filing month | Spreadsheet filing date. FJC `FILEDATE`. RECAP `dateFiled`. |
| Industry or sector | Spreadsheet, if coded. Otherwise the SIC on the issuer's latest EDGAR filing dated on or before the prediction date, for a CIK that matches. Cornerstone's GICS sector is a published aggregate, not a case-level field this project has. |
| Issuer size | Total assets, and shares outstanding, from an EDGAR filing dated on or before the prediction date. Market capitalization needs a price. EDGAR does not provide a daily price. |
| Allegation flags that are in the first complaint | Rule 10b-5, Section 11, Section 12, a stated accounting restatement, a stated SEC investigation or action. Source: spreadsheet flags, if the file says they were taken from the first complaint, or the complaint text itself. |
| Counsel on the first complaint | The firm that filed that complaint. This is filing-time counsel. |

### Known only at a later, declared clock

These are real predictors in the settlement literature. They are not filing-time facts.

| Feature | When it becomes known |
| --- | --- |
| Lead plaintiff, institutional or individual | After the PSLRA notice and appointment. Cornerstone's 2025 settlement review reports that institutional lead or co-lead plaintiffs sit on larger cases. The appointment order can be a feature only at a clock on or after that order, and the order has to predate the outcome. |
| Court-appointed lead counsel | After appointment. Distinct from counsel on the first complaint. |
| Consolidated-complaint allegations | When that complaint is filed. Allowed under the second clock. An allegation that appears only in a later amendment is excluded at the first-complaint clock. |
| Parallel derivative suit | On the date that derivative case is filed, and only if that date is on or before the prediction instant. A flag that means "a derivative case was eventually filed" leaks the future. |
| SEC enforcement action filed after the class complaint | Only if its filing date is on or before the prediction instant. The Clearinghouse does not track SEC proceedings as cases. A parallel action is usable only when its date is in the file. |

### Excluded from the feature set

These reveal the outcome or the path after the prediction instant:

- Settlement amount, plan of allocation, attorneys' fee award, and any text that states them.
- The dismissal order, the settlement-approval order, and opinion disposition words from the current courtpipe labeler.
- Termination date, RECAP `dateTerminated`, FJC `TERMDATE`, `DISP`, `JUDGMENT`, `PROCPROG`, `TRCLACT`, `NOJ`.
- Docket-entry counts measured through settlement. Cornerstone uses the median number of docket entries as a complexity proxy on cases that have already settled. That count is accumulated up to the ending. It is leakage here.
- Class-certification ruling, denial of a motion to dismiss, and any event dated after the prediction instant. Cornerstone reports that in 2025, 8% of settlements happened before a motion to dismiss was filed and 54% before a motion for class certification. Those stage facts are descriptions of settled cases, not inputs.
- Judge identity from the public-use FJC files. `FILEJUDG` and `FILEMAG` are blank there.
- A disclosure-dollar-loss or plaintiff-style-damages figure whose price inputs run past the prediction date. Cornerstone defines disclosure dollar loss with the market-cap change around the end of the class period, and it says the figure includes information unrelated to the litigation. CRSP is not a public source. v1 does not scrape a quote site. A damages number already in the spreadsheet is allowed only when the file's documentation dates every input on or before the prediction instant. Otherwise the column is excluded and the report says so.
- The issuer's later returns, a restatement announced after filing, and a bankruptcy or delisting after filing.

`PROCPROG` in the FJC file is procedural progress at termination. Using it, or filtering on it, tells the model how far the case got before it ended.

## Data sources

### Stanford Securities Class Action Clearinghouse (primary case list)

Primary page: [About the SCAC](https://securities.stanford.edu/about-the-scac.html), read on 7 October 2026.

What the page states:

- The database contains complaints, briefs, dispositive orders, and other litigation materials. Most posted documents can be downloaded and printed for free. The Clearinghouse does not mail paper copies.
- When the site is operating, the filings database is updated each business day.
- Sign-up creates an account "to access all features." Email notices are a separate registration. Questions about sign-up go to scac@law.stanford.edu.
- FAQ 7: Excel spreadsheets are provided to academic researchers for non-commercial empirical research, under a Non-Disclosure Agreement. The Terms of Service prohibit commercial use, unauthorized reproduction, and the use of scraping tools or webcrawlers to access, process, and/or index the data. The content-manager address on that answer is obfuscated. The page's published address for methodology and sign-up questions is scac@law.stanford.edu.
- The terms paragraph that follows says users accept the terms by using the site and by agreeing at registration. The fetched text ends at "The User ID may be used by you to gain access to the SCAC only for so long as you are authorized..." The rest of the click-through terms was not retrieved. This spec relies on the prohibitions FAQ 7 states, and it does not invent further clauses.
- A banner on the about page and on the sign-up page says the Clearinghouse is under construction and temporarily unavailable, expected to return as part of the Stanford Rock Center for Corporate Governance in Winter 2026. During that period, updates and new filings will not be available. Urgent contact: rockprograms@law.stanford.edu. The sign-up page, fetched the same day, showed that banner and no registration form.

Access from this environment on 7 October 2026:

- `robots.txt` returned HTTP 200. It disallows six specific PDFs under `/filings-documents/`. It does not disallow the rest of the site. A short robots file is not permission to bulk-collect. FAQ 7 is the rule that governs.
- A direct request to the about page and to the filings page from this environment returned a Cloudflare block. A case page and a filings table were not opened. This draft therefore has no observed column list, no observed status vocabulary, and no observed per-case settlement amounts.

Compliant path for v1:

1. Request the academic Excel from scac@law.stanford.edu, with a copy to rockprograms@law.stanford.edu while the site is down. Use is non-commercial research under the NDA. The spreadsheet stays on the operator's machine. It is gitignored. It is not committed to this public repository. Aggregate metrics go in the report only if the NDA allows publication. That is a decision for Adam, because this repo is public.
2. The hand audit may read individual documents the terms allow an authorized user to download. The audit sample is small and is specified in the evaluation doc. It is not a back door to reconstructing the database.
3. Scraping, webcrawling, and unauthorized reproduction are out. The outage is not a reason to collect the site another way. If the request is refused or unanswered through the restructuring, v1 waits, or the project uses the Appendix A design for a classifier without settlement dollars.

### FJC Integrated Database (coverage cross-check, not the amount source)

The public civil file and codebook are on the [FJC civil cases page](https://www.fjc.gov/research/idb/civil-cases-filed-terminated-and-pending-sy-1988-present). The codebook `Civil Codebook 1988 Forward 10252023.pdf` was retrieved on 7 October 2026. `cv88on.zip` answered a HEAD request that day with `content-length` 329,665,474 and `last-modified` 26 August 2026. The zip was not opened. No row counts are stated.

Nature of suit 850 is Securities, Commodities, Exchange. `CLASSACT = 1` means a class allegation at filing. Together they can, once the zip is opened, be compared with the Clearinghouse list on district, office, and docket number. That comparison is a coverage check. It is not the label source.

`AMTREC` is "dollar amount received (in thousands) when appropriate." The codebook says the field is not used uniformly, is not mandatory, and the Statistics Division advises against using it for analysis. Some courts use 9999 for amounts over $1 million and others use it as a filler. v1 does not use `AMTREC` as a settlement fund.

The Appendix A design remains the written alternative for a filing-time classifier on clerk code 13. It cannot answer the amount question.

### CourtListener RECAP (later, and only with a token)

Observed without a token on 7 October 2026:

| Request | Result |
| --- | --- |
| `GET /api/rest/v4/dockets/`, `/parties/`, `/docket-entries/` | 401, authentication credentials were not provided. |
| `GET /api/rest/v4/search/?type=r&q=suitNature:"850 Securities/Commodities"` | `count` 67,143, `document_count` 2,218,487. |
| `q=suitNature:850` | `count` 68,330, `document_count` 2,319,351. |
| `q=nature_of_suit:850` | `count` 0. That field name is the wrong operator. |
| `q=securities` with `type=r` | `count` 6,028,997. This is a word search, not a nature-of-suit census. |

`count` and `document_count` are archive hit counts. RECAP is the set of PACER dockets someone has placed in the archive. A search hit can include `party`, `suitNature`, `dateFiled`, and `dateTerminated`. It does not include the disposition code or the settlement fund. `dateTerminated` is excluded from features.

A token will arrive later as an environment variable, `COURTLISTENER_API_KEY`. v1 does not call the PACER purchase API. RECAP is how a later phase would attach a dated complaint or a lead-plaintiff order. It is not how v1 labels the cohort.

### SEC EDGAR (issuer size, under the fair-access policy)

The SEC's [Accessing EDGAR Data](https://www.sec.gov/os/accessing-edgar-data) page, last reviewed 26 June 2024, states:

- Filing indexes and the JSON APIs on data.sec.gov are public and free.
- The current maximum request rate is 10 requests per second. Callers declare a User-Agent with a contact. The SEC does not allow botnets or automated tools outside that policy, and it may limit rates. Download only what is needed. There is no technical support for scripts.
- EDGAR starts in 1994/1995. Indexes run from 1994Q3. A CIK is stable and is not recycled.
- `company_tickers.json` and `company_tickers_exchange.json` exist. The SEC does not guarantee their accuracy.

v1 may attach total assets and shares outstanding from the latest filing dated on or before the prediction date, for issuers that match a CIK. The match rate is reported. Unmatched issuers get a missingness indicator, not an imputed size. Market cap and disclosure dollar loss still need a price. Those wait on a field already in the NDA spreadsheet or on a price source Adam is licensed to use.

### Cornerstone Research and NERA (sanity checks, not training data)

These are published aggregates. They are not case-level tables, and the two publishers do not agree with each other. After a real extract exists, the evaluation compares the extract's dismissal share, settlement share, and median fund with the figures below for overlapping years. A difference is reported. It is not "corrected" by editing labels.

Cornerstone, [Securities Class Action Settlements—2025 Review and Analysis](https://www.cornerstone.com/wp-content/uploads/2026/02/Securities-Class-Action-Settlements-2025-Review-and-Analysis.pdf), text read on 7 October 2026:

- 74 settlements in 2025 totaling $3.0 billion, compared with 88 settlements totaling $3.8 billion in 2024. The table lists 2025 total dollars as $3,006.5 million and 2024 as $3,833.8 million, in millions, inflation-adjusted, 2025 dollar equivalents.
- Median settlement $17.3 million, the highest since 1997, up 20% from 2024. Average settlement $40.6 million, down 7% from 2024.
- Median for cases with only 1933 Act claims: $32.5 million. Excluding those cases, the median was $16.0 million.
- Median duration from filing to the settlement hearing: 3.5 years. The 2024 median was 3.2 years. The 2023 peak was 3.7 years. This is a median among settled cases. It is not a censoring rule by itself, and it is not a feature.
- Nearly 40% of 2025 settlements were in the Ninth Circuit.
- Institutional investors as lead or co-lead plaintiff are associated with larger cases (higher plaintiff-style damages and higher issuer assets). The median settlement with an institutional lead or co-lead was 4.8 times the median without one.
- An accompanying derivative action was present in 49% of 2025 cases. The median settlement for those cases was $16.0 million.
- The share of settled cases with GAAP allegations, and with financial restatements, was lower in 2021–2025 than in 2016–2020 (GAAP 37% versus 50%; restatements 14% versus 24%).

NERA, [Recent Trends in Securities Class Action Litigation: 2025 Full-Year Review](https://www.nera.com/insights/publications/2026/recent-trends-in-securities-class-action-litigation--2025-full-y.html), the public highlights page read the same day:

- 234 resolutions in 2025, up from 210 in 2024: 155 dismissals and 79 settlements.
- Aggregate settlement value $2.9 billion, down 25% from an inflation-adjusted $3.9 billion in 2024.
- Median settlement $17 million, up 21%, described as a 10-year high.

NERA's 79 settlements, $2.9 billion, and $17 million median are not Cornerstone's 74, $3.0 billion, and $17.3 million. Both stay in the report as external checks. Neither overwrites the spreadsheet.

## v1 scope

v1 is buildable once the NDA spreadsheet is on disk. It is verifiable with the protocol in `docs/EVALUATION.md`. It is deliberately small.

- Cohort: Clearinghouse federal securities class actions, merger filings dropped only when a flag exists, `ongoing` / `trial` / `remanded` / `unmapped` removed from the scores, binary label `dismissed` versus `settled`.
- Years: filings from 1996 through a test window that has had time to resolve. The evaluation doc sets the window from the extract's last complete year. Recent filings are held out and unscored.
- Features: the filing-time fields in the table above that are actually in the spreadsheet, plus EDGAR total assets and shares outstanding when a CIK matches. A column that fails the dating rule is dropped, not repaired.
- Models: logistic regression for the probability of settlement, and ordinary linear regression for the log fund. The point of v1 is the labels, the clock, and the baselines. A more flexible model is a later experiment and does not change the success rule.
- Complaint text, embeddings, and opinion text stay out of v1.
- One local command, specified in the evaluation doc, reads a path the operator supplies. It does not download the Clearinghouse.

Until the spreadsheet arrives, there is nothing to train. The build does not fill the gap with a crawl, with Cornerstone's medians, or with `AMTREC`.

## Out of scope for v1

- Changes to the opinion labeler, the review queue, or the court charts.
- Scraping securities.stanford.edu, or reproducing the spreadsheet in this repo.
- Buying PACER documents.
- Predicting from docket progress, settlement stage, or entry counts.
- A market-wide "corporate litigation" settlement rate. That question is the Appendix A design, and it has no usable settlement fund.
- Treating a Cornerstone or NERA median as a prediction this model made.

## Decisions needed before a build

1. Confirm the binary target: `dismissed` versus `settled`. Ongoing cases are excluded. Trial and remand are excluded and counted. They are not folded into either class.
2. Confirm the amount target: total settlement fund, natural log, CPI-U adjusted, scored only on settled rows with a stated fund. Partial payments that are not the total fund are excluded from the amount task.
3. Confirm the data path: request the academic Excel under an NDA, and do not scrape. The site banner says the Clearinghouse is unavailable until Winter 2026, so the request may wait. Also confirm who can sign a non-commercial NDA, and whether aggregate metrics may be published in this public repo. The file itself stays local.
4. Confirm the clock: first identified complaint, unless you want the consolidated-complaint clock declared in advance. Lead plaintiff and court-appointed lead counsel are not filing-time features.
5. Confirm features by what the spreadsheet actually contains. Industry, allegation flags, first-complaint counsel, and a dated damages figure are in v1 only when the file has them and the dating rule is satisfied. EDGAR may add total assets and shares outstanding under the SEC fair-access policy. Market cap and a reconstructed stock drop wait on a licensed price source or a compliant column. If those columns are absent, the amount baseline is the training median alone.
6. Confirm success is beating the baselines in `docs/EVALUATION.md` on both tasks, with bootstrap intervals. There is no fixed AUC or dollar-error cutoff.
7. Confirm merger-and-acquisition filings are dropped when the file flags them.
8. Confirm Appendix A stays an alternative. It is the path for a classifier without settlement dollars if the spreadsheet cannot be obtained. It is not the main plan.

---

# Appendix A. Set-aside plan: filing-time IDB settlement for corporate civil cases

The sections below are the previous draft, from commit `c5119dd`. They specify a filing-time classifier for clerk disposition code 13 on a corporate-defendant cohort in the FJC civil file. That design cannot support a settlement-amount model: `AMTREC` is not a usable fund. Where this appendix says "v1," it means the IDB design, not the securities class-action design above. The matching evaluation protocol is Appendix A of `docs/EVALUATION.md`.

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
