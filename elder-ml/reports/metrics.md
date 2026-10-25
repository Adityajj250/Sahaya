# Synthetic replay metrics

These metrics describe only this scripted synthetic dataset. They are not clinical evidence.

## Event recall

| Event type | Detected / total | Recall (exact 95% interval) | Median delay (s) |
|---|---:|---:|---:|
| af_like_episode | 4/4 | 100.0% (39.8%–100.0%) | 420 |
| copd_exacerbation_like | 1/1 | 100.0% (2.5%–100.0%) | 33420 |
| exertional_desaturation | 4/4 | 100.0% (39.8%–100.0%) | 480 |
| fall_and_lying_still | 2/2 | 100.0% (15.8%–100.0%) | 32 |
| hypertensive_surge | 5/5 | 100.0% (47.8%–100.0%) | 660 |
| hypoglycaemia_like_episode | 3/3 | 100.0% (29.2%–100.0%) | 480 |
| nocturnal_desaturation | 14/14 | 100.0% (76.8%–100.0%) | 360 |
| viral_illness_like | 1/1 | 100.0% (2.5%–100.0%) | 51300 |

Overall: **34/34 (100.0%; exact 95% CI 89.7%–100.0%)**.

## Cold start vs mature replay

| Replay period | Detected / total | Recall |
|---|---:|---:|
| Days 1–3 | 6/6 | 100.0% |
| Days 4–14 | 28/28 | 100.0% |

## False alert workload

False incident = outside any scored event plus 10 minutes. Watch off-wrist intervals are excluded from health-event scoring.

- Yellow false incidents: 0 total; 0.000 per person-day
- Orange false incidents: 0 total; 0.000 per person-day
- Red false incidents: 0 total; 0.000 per person-day
- False Orange-or-higher incidents per person-day: 0.000
- False Yellow-or-higher incidents per person-day: 0.000

## Notes

- Output is a replay of simulated patterns; no alert is a diagnosis.
- Rules, thresholds and alert policy were tuned on this scripted dataset for demonstration; the numbers above are demonstration performance, not an independent estimate of generalization.
- A fresh-seed check (same generator, new random seed, M3 trained on the original data only, no retuning) is in `fresh_seed_check/`.
- Fusion combines a day-fold LightGBM classifier with transparent prototype rules; neither has been clinically validated.
- Confidence intervals quantify event-count uncertainty only; they do not account for generator dependence.
- The daily score is a synthetic trend visualization only; it is not a validated recovery or health score.
- E4's nightly desaturation dips are scripted events, so each night produces one Yellow ticket; the exacerbation phase also crosses the prototype SpO2 < 80 hard floor on some nights.
- A silence ticket raised while the watch is genuinely unworn counts as a correct alert, not a false one.
## Rule-layer ablation

| Configuration | Event recall | False Orange+ / person-day | E3 alerts/day | E4 alerts/day |
|---|---:|---:|---:|---:|
| Population thresholds | 25/34 (73.5%) | 0.557 | 0.57 | 3.36 |
| Personal-deviation layer | 15/34 (44.1%) | 0.000 | 0.00 | 2.79 |
| Acute-pattern rules | 12/34 (35.3%) | 0.000 | 0.36 | 0.00 |
| M3 LightGBM | 30/34 (88.2%) | 0.000 | 0.36 | 1.43 |
| Drift only | 2/34 (5.9%) | 0.000 | 0.00 | 0.79 |
| Full fusion | 34/34 (100.0%) | 0.000 | 0.36 | 2.00 |
