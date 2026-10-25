# Synthetic replay metrics

These metrics describe only this scripted synthetic dataset. They are not clinical evidence.

## Event recall

| Event type | Detected / total | Recall (exact 95% interval) | Median delay (s) |
|---|---:|---:|---:|
| af_like_episode | 4/4 | 100.0% (39.8%–100.0%) | 450 |
| copd_exacerbation_like | 1/1 | 100.0% (2.5%–100.0%) | 17340 |
| exertional_desaturation | 4/4 | 100.0% (39.8%–100.0%) | 570 |
| fall_and_lying_still | 2/2 | 100.0% (15.8%–100.0%) | 32 |
| hypertensive_surge | 5/5 | 100.0% (47.8%–100.0%) | 720 |
| hypoglycaemia_like_episode | 3/3 | 100.0% (29.2%–100.0%) | 480 |
| nocturnal_desaturation | 14/14 | 100.0% (76.8%–100.0%) | 450 |
| viral_illness_like | 1/1 | 100.0% (2.5%–100.0%) | 45840 |

Overall: **34/34 (100.0%; exact 95% CI 89.7%–100.0%)**.

## Cold start vs mature replay

| Replay period | Detected / total | Recall |
|---|---:|---:|
| Days 1–3 | 6/6 | 100.0% |
| Days 4–14 | 28/28 | 100.0% |

## False alert workload

False incident = outside any scored event plus 10 minutes. Watch off-wrist intervals are excluded from health-event scoring.

- Yellow false incidents: 17 total; 0.243 per person-day
- Orange false incidents: 3 total; 0.043 per person-day
- Red false incidents: 0 total; 0.000 per person-day
- False Orange-or-higher incidents per person-day: 0.043
- False Yellow-or-higher incidents per person-day: 0.286

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
| Population thresholds | 14/34 (41.2%) | 1.600 | 0.50 | 7.93 |
| Personal-deviation layer | 16/34 (47.1%) | 0.000 | 0.00 | 3.21 |
| Acute-pattern rules | 15/34 (44.1%) | 0.057 | 0.64 | 0.14 |
| M3 LightGBM | 26/34 (76.5%) | 0.000 | 0.36 | 1.71 |
| Drift only | 3/34 (8.8%) | 0.000 | 0.00 | 0.50 |
| Full fusion | 34/34 (100.0%) | 0.043 | 1.21 | 2.14 |
