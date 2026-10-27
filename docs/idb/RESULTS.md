# IDB settlement results

These figures are from one run of `courtpipe evaluate-settlement` on the public FJC civil file. They are not the 20-row opinion fixture in the README.

Audit gate: **pending**. The 150-row sample is `docs/idb/audit_sample.csv`. The rubric is `docs/idb/AUDIT_RUBRIC.md`. The project is not done while this gate is pending.

Modeling gate: **fail**.

## Cohort

- Nature-of-suit 160/410/850 rows read: 29038
- Cohort after filters and de-duplication: 8952
- Train rows scored: 4864
- Test rows scored: 1196
- Test rows dropped because the defendant name was in training: 401
- Test rows dropped by the duration rule: 2491. These rows are already terminated. A case lasting as long as the training 95th percentile (2573.7 days) would not have been observable by the extract as-of date, so the filing is left out of the score.
- Train settlement rate (code 13): 0.22594572368421054
- Test settlement rate (code 13): 0.13377926421404682

## Primary scores

- Model ROC-AUC: 0.7036739864864865
- Model AUC 95% interval: [0.6630210670916094, 0.7435224704147543]
- Best rate baseline for AUC (nos_court_rate): 0.7138664333976835
- AUC difference interval (model minus that baseline): [-0.047368498820290685, 0.02618002048262949]
- Model Brier: 0.11084030895038599
- Best rate baseline for Brier (nos_court_rate): 0.1120375565299572
- Brier improvement interval (baseline minus model): [-0.004074789726750783, 0.0061374313704518615]

A bar passes only when the model is better than that baseline and the interval's lower end is above zero. The model's own AUC interval must also sit above 0.5.

## Bars

- roc_auc_beats_best_baseline: fail
- brier_beats_best_baseline: fail
- model_auc_ci_above_0.5: pass

Reasons:
- ROC-AUC does not clear the best filing-time rate baseline with a difference interval above zero.
- Brier score does not improve on the best filing-time rate baseline with an interval above zero.
- The AUC difference changes sign when a training fiscal year is dropped: 2013, 2015. That blocks a stability claim. It does not by itself fail the modeling gate.

Macro-F1 on the six-way label is reported in the JSON and is not a binding bar.

File SHA-256: `74405231a9a3c246c7090d471a1525924fa5afb513ff22b4dc0f4babbac7223d`
Bytes: 329665474
As-of date used for censoring: 2026-08-26
