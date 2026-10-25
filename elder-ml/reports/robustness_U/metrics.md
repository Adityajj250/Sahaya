# Synthetic replay metrics

These metrics describe only this scripted synthetic dataset. They are not clinical evidence.

## Event recall

| Event type | Detected / total | Recall (exact 95% interval) | Median delay (s) |
|---|---:|---:|---:|
| af_like_episode | 4/4 | 100.0% (39.8%–100.0%) | 600 |
| copd_exacerbation_like | 1/1 | 100.0% (2.5%–100.0%) | 12060 |
| exertional_desaturation | 4/4 | 100.0% (39.8%–100.0%) | 390 |
| fall_and_lying_still | 2/2 | 100.0% (15.8%–100.0%) | 32 |
| hypertensive_surge | 3/5 | 60.0% (14.7%–94.7%) | 1800 |
| hypoglycaemia_like_episode | 2/3 | 66.7% (9.4%–99.2%) | 510 |
| nocturnal_desaturation | 14/14 | 100.0% (76.8%–100.0%) | 300 |
| viral_illness_like | 1/1 | 100.0% (2.5%–100.0%) | 45060 |

Overall: **31/34 (91.2%; exact 95% CI 76.3%–98.1%)**.

## Cold start vs mature replay

| Replay period | Detected / total | Recall |
|---|---:|---:|
| Days 1–3 | 5/6 | 83.3% |
| Days 4–14 | 26/28 | 92.9% |

## False alert workload

False incident = outside any scored event plus 10 minutes. Watch off-wrist intervals are excluded from health-event scoring.

- Yellow false incidents: 10 total; 0.143 per person-day
- Orange false incidents: 6 total; 0.086 per person-day
- Red false incidents: 1 total; 0.014 per person-day
- False Orange-or-higher incidents per person-day: 0.100
- False Yellow-or-higher incidents per person-day: 0.243

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
| Acute-pattern rules | 10/34 (29.4%) | 0.071 | 0.57 | 0.07 |
| M3 LightGBM | 28/34 (82.4%) | 0.014 | 0.29 | 1.86 |
| Drift only | 3/34 (8.8%) | 0.000 | 0.00 | 0.29 |
| Full fusion | 31/34 (91.2%) | 0.100 | 1.00 | 1.93 |
