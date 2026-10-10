# Hand audit rubric for IDB disposition code 13

The sample is `docs/idb/audit_sample.csv`. Two people label independently. Discussion decides the gold label. Write that label in `gold_label` and the reason in `gold_notes`.

This audit is not done. `audit_gate` stays `pending` until the filled sample is scored against the floor in `docs/idb/EVALUATION.md`.

Look up the case on a public docket you can read (district, office, and docket number). Do not buy PACER. If you cannot tie the row to a docket, set `gold_label` to `insufficient record`.

## Labels

- **Settled out of court** if the record says the parties settled, compromised, or stipulated to dismissal because of a settlement, and the ending is not a consent judgment signed as affirmative relief.
- **Consent judgment** if the record shows an agreed judgment that grants relief and is entered by the court.
- **Voluntary dismissal** if the plaintiff withdrew under Rule 41(a) and the record does not say a settlement caused the withdrawal.
- **Judgment for plaintiff** or **judgment for defendant** only when a judgment on the merits, default, or motion is entered for that side.
- **Other** for transfers, remands, statistical closings, and anything that does not fit.
- **Insufficient record** if the row cannot be tied to a docket you can read. These rows stay in the "could we check" count and leave the precision denominator.

## What the floor is

On the code-13 rows that are not `insufficient record`, precision is the share whose gold label is settled out of court. The label is usable only if the lower end of a 95% Wilson interval is above 0.5. If the two auditors assign the same label on at most half of the code-13 rows, stop.

If more than half of the code-13 sample is `insufficient record`, the audit did not happen.

## Strata in the file

| `stratum` | Intended rows |
| --- | --- |
| `disp_13` | 50, spread across nature of suit 160, 410, and 850 when those rows exist |
| `disp_12` | 25 |
| `disp_5` | 25 |
| `judgment` | 25 |
| `other_dismissal` | 25 |

A short stratum is filled with every available row. The report's `audit.shortfalls` field records the gap. That gap is a property of the extract, not a completed audit.
