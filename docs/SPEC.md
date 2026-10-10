# Spec: federal securities class actions

Status: proposal. This document does not add code, data, or a model. Build only after this spec and `docs/EVALUATION.md` are approved.

Adam narrowed the target. The plan is federal securities class actions. There are two questions:

1. Will a resolved case be dismissed, or will it settle?
2. If it settles, roughly how large is the settlement?

The earlier plan, which used the Federal Judicial Center's civil Integrated Database and clerk disposition code 13 for a broader set of corporate cases, is now its own document at `docs/idb/SPEC.md`. That track is implemented. It is not the plan for the securities model.

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
3. Scraping, webcrawling, and unauthorized reproduction are out. The outage is not a reason to collect the site another way. If the request is refused or unanswered through the restructuring, v1 waits. The Integrated Database classifier in `docs/idb/SPEC.md` is a separate track and has no settlement dollars.

### FJC Integrated Database (coverage cross-check, not the amount source)

The public civil file and codebook are on the [FJC civil cases page](https://www.fjc.gov/research/idb/civil-cases-filed-terminated-and-pending-sy-1988-present). The codebook `Civil Codebook 1988 Forward 10252023.pdf` was retrieved on 7 October 2026. `cv88on.zip` answered a HEAD request that day with `content-length` 329,665,474 and `last-modified` 26 August 2026. The zip was not opened. No row counts are stated.

Nature of suit 850 is Securities, Commodities, Exchange. `CLASSACT = 1` means a class allegation at filing. Together they can, once the zip is opened, be compared with the Clearinghouse list on district, office, and docket number. That comparison is a coverage check. It is not the label source.

`AMTREC` is "dollar amount received (in thousands) when appropriate." The codebook says the field is not used uniformly, is not mandatory, and the Statistics Division advises against using it for analysis. Some courts use 9999 for amounts over $1 million and others use it as a filler. v1 does not use `AMTREC` as a settlement fund.

The Integrated Database design in `docs/idb/SPEC.md` is a filing-time classifier on clerk code 13. It cannot answer the amount question.

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
- A market-wide "corporate litigation" settlement rate. That question is the Integrated Database design in `docs/idb/SPEC.md`, and it has no usable settlement fund.
- Treating a Cornerstone or NERA median as a prediction this model made.

## Decisions needed before a build

1. Confirm the binary target: `dismissed` versus `settled`. Ongoing cases are excluded. Trial and remand are excluded and counted. They are not folded into either class.
2. Confirm the amount target: total settlement fund, natural log, CPI-U adjusted, scored only on settled rows with a stated fund. Partial payments that are not the total fund are excluded from the amount task.
3. Confirm the data path: request the academic Excel under an NDA, and do not scrape. The site banner says the Clearinghouse is unavailable until Winter 2026, so the request may wait. Also confirm who can sign a non-commercial NDA, and whether aggregate metrics may be published in this public repo. The file itself stays local.
4. Confirm the clock: first identified complaint, unless you want the consolidated-complaint clock declared in advance. Lead plaintiff and court-appointed lead counsel are not filing-time features.
5. Confirm features by what the spreadsheet actually contains. Industry, allegation flags, first-complaint counsel, and a dated damages figure are in v1 only when the file has them and the dating rule is satisfied. EDGAR may add total assets and shares outstanding under the SEC fair-access policy. Market cap and a reconstructed stock drop wait on a licensed price source or a compliant column. If those columns are absent, the amount baseline is the training median alone.
6. Confirm success is beating the baselines in `docs/EVALUATION.md` on both tasks, with bootstrap intervals. There is no fixed AUC or dollar-error cutoff.
7. Confirm merger-and-acquisition filings are dropped when the file flags them.
8. The Integrated Database design stays a separate track in `docs/idb/`. It is not the securities plan.

The approved IDB rules and the evaluation that was built against them are in [`docs/idb/SPEC.md`](idb/SPEC.md) and [`docs/idb/EVALUATION.md`](idb/EVALUATION.md).
