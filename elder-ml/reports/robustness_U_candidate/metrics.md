# Synthetic replay metrics

These metrics describe only this scripted synthetic dataset. They are not clinical evidence.

## Event recall

| Event type | Detected / total | Recall (exact 95% interval) | Median delay (s) |
|---|---:|---:|---:|
| af_like_episode | 4/4 | 100.0% (39.8%–100.0%) | 570 |
| copd_exacerbation_like | 1/1 | 100.0% (2.5%–100.0%) | 3300 |
| exertional_desaturation | 4/4 | 100.0% (39.8%–100.0%) | 330 |
| fall_and_lying_still | 2/2 | 100.0% (15.8%–100.0%) | 32 |
| hypertensive_surge | 4/5 | 80.0% (28.4%–99.5%) | 1590 |
| hypoglycaemia_like_episode | 3/3 | 100.0% (29.2%–100.0%) | 540 |
| nocturnal_desaturation | 14/14 | 100.0% (76.8%–100.0%) | 240 |
| viral_illness_like | 1/1 | 100.0% (2.5%–100.0%) | 45060 |

Overall: **33/34 (97.1%; exact 95% CI 84.7%–99.9%)**.

## Cold start vs mature replay

| Replay period | Detected / total | Recall |
|---|---:|---:|
| Days 1–3 | 6/6 | 100.0% |
| Days 4–14 | 27/28 | 96.4% |

## False alert workload

False incident = outside any scored event plus 10 minutes. Watch off-wrist intervals are excluded from health-event scoring.

- Yellow false incidents: 11 total; 0.157 per person-day
- Orange false incidents: 24 total; 0.343 per person-day
- Red false incidents: 1 total; 0.014 per person-day
- False Orange-or-higher incidents per person-day: 0.357
- False Yellow-or-higher incidents per person-day: 0.514

## Notes

- Output is a replay of simulated patterns; no alert is a diagnosis.
- Fusion combines a day-fold LightGBM classifier with transparent prototype rules; neither has been clinically validated.
- M3 thresholds are selected from the same OOF scores used for the original-set metrics; those metrics are not an independent estimate of generalization.
- Confidence intervals quantify event-count uncertainty only; they do not account for generator dependence.
- The daily score is a synthetic trend visualization only; it is not a validated recovery or health score.
- The E4 exacerbation phase overlaps deep nocturnal dips; some values cross the prototype SpO₂ <80 hard floor. Therefore the planned acceptance item requiring drift detection with no hard floor crossed is incompatible with this generated trace.
- The ablation reduces E3/E4 alerts only modestly versus fixed thresholds; review incident grouping and personalize recurring nightly dips before claiming a large workload reduction.
## Rule-layer ablation

| Configuration | Event recall | False Orange+ / person-day | E3 alerts/day | E4 alerts/day |
|---|---:|---:|---:|---:|
| Population thresholds | 15/34 (44.1%) | 1.100 | 1.07 | 4.93 |
| Personal-deviation layer | 15/34 (44.1%) | 0.000 | 0.00 | 3.07 |
| Acute-pattern rules | 11/34 (32.4%) | 0.114 | 0.86 | 0.07 |
| M3 LightGBM | 30/34 (88.2%) | 0.357 | 1.14 | 2.64 |
| Drift only | 3/34 (8.8%) | 0.000 | 0.00 | 0.29 |
| Full fusion | 33/34 (97.1%) | 0.357 | 1.50 | 2.71 |
