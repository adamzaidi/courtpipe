# Appeal-reversal results

These figures are from `courtpipe evaluate-appeal`. They are not Table B-5 and not opinion-pipeline fixture scores.

**Synthetic/small extract.** Training n is below the spec's 50-row circuit backoff floor, so rate baselines collapse toward a constant. Bootstrap intervals on ~12 test rows are wide. Do not quote these numbers as an affirmance or reversal rate. Live bulk-snapshot metrics are pending.

Audit gate: **pending**.
Modeling gate: **fail**.

- Train rows: 16
- Test rows: 12
- Train disturb rate: 0.5
- Test disturb rate: 0.4166666666666667

## Primary scores (`y_disturb`)

- Model ROC-AUC: 0.7714285714285716
- Best rate baseline for AUC (circuit_rate): 0.5
- AUC difference interval: [-0.25, 0.5]
- Model Brier: 0.1576616519210354
- Best rate baseline for Brier (circuit_rate): 0.25
- Brier improvement interval: [-0.016860599842325377, 0.1882265471973152]
- Majority-class accuracy (descriptive): 0.4166666666666667
- Expected calibration error: 0.16339092349609363

## Bars

- roc_auc_beats_best_baseline: fail
- brier_beats_best_baseline: fail
- model_auc_ci_above_0.5: fail

Reasons:
- ROC-AUC does not clear the best circuit/case-type/judge rate baseline with a difference interval above zero.
- Brier score does not improve on the best rate baseline with an interval above zero.
- The model AUC interval does not sit above 0.5.

## Known limitations

- Headline event is y_disturb: reversed/vacated/remanded/mixed versus pure affirmance.
- affirmed_with_remand is excluded from the headline. Sensitivities A and B are printed and are not swapped in after seeing the test score.
- v1 features come from pre-decision fields. Appellate opinion text is the label store.
- A live bulk snapshot is required before treating fixture numbers as corpus results.
- Judge-level outputs are aggregate only.
- On extracts with fewer than 50 training rows, circuit and case-type baselines backoff to a constant; bootstrap intervals on a tiny test set are not a cohort result.
