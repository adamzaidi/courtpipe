# Motion-to-dismiss results

These figures are from `courtpipe evaluate-mtd`. They are not opinion-pipeline fixture scores and not a national grant rate.

**Synthetic/small extract.** Training n is below the spec's 40-row backoff floor, so court and judge rate baselines collapse toward a constant. Do not quote these numbers as a motion-to-dismiss grant rate. Live CourtListener metrics are pending.

Audit gate: **pending**. The two-reader 120-row audit has not been completed.

Modeling gate: **pass**.

Extract: `local extract`
- Train rows: 16
- Test rows: 12
- Train any-relief rate: 0.5
- Test any-relief rate: 0.5

## Primary scores (`y_relief`)

- Model ROC-AUC: 1.0
- Model AUC 95% interval: [0.9999999999999999, 1.0]
- Best rate baseline for AUC (nos_rate): 0.5
- AUC difference interval: [0.4999999999999999, 0.5]
- Model Brier: 2.445631238575507e-05
- Best rate baseline for Brier (nos_rate): 0.25
- Brier improvement interval: [0.24997097425251708, 0.24998056337250565]
- Majority-class accuracy (descriptive): 0.5
- Expected calibration error: 0.004853810088817989

## Bars

- roc_auc_beats_best_baseline: pass
- brier_beats_best_baseline: pass
- model_auc_ci_above_0.5: pass

## Known limitations

- Headline is metadata plus pre-order text on every labeled test row.
- Judge-level outputs are aggregate bootstrap numbers only.
- Audit gate is pending until two readers complete the 120-row sample.
- A live CourtListener extract is required before treating these numbers as cohort results.
- Unresolved motions are excluded, not coded as denials.
- On extracts with fewer than 40 training rows, court and judge baselines backoff to a constant; a modeling-gate pass on a fixture is not a cohort result.
