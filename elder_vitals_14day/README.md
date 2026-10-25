# Synthetic elder wearable dataset, 14 days (hackathon prototype)

5 elderly people x 14 days x 500 ms sampling = 2,419,200 rows each (12.1 M total). Timestamps are IST local time, 2026-10-09 00:00 to 2026-10-22 23:59:59.5.
**Entirely synthetic. Not clinical data. Not for diagnosis.** Seeded generator included; edit and regenerate freely.

## Files
- `elder_E1.parquet` ... `elder_E5.parquet` : signals + ground truth (zstd Parquet, ~25 MB each)
- `events.csv` : every labelled anomaly and non-wear interval with start/end timestamps
- `persons.csv` : baselines, worn %, description
- `sample_E1_day3_1000-1130.csv` : 90-minute CSV preview around a dizzy episode
- `generate_dataset.py` : generator (`--csv` writes one CSV per person per day)

The generator also accepts `--seed`, `--event-scale`, `--noise-scale`, and `--out` for reproducible robustness sets. These options write to the requested output folder; the defaults retain the original seed and output location.

```python
import pandas as pd
df = pd.read_parquet("elder_E1.parquet")
X = df.drop(columns=[c for c in df.columns if c.startswith("gt_")])   # what a device would send
```

## Signal columns
`hr_bpm, spo2_pct, sbp_mmhg, dbp_mmhg, skin_temp_c, motion_g` (+ `timestamp`, `day` 1-14, `t_sec`). NaN = no reading.
## Ground truth (drop before training)
`gt_worn`, `gt_activity` (sleep, rest, light, walk, exercise, meal, nap, off_bath, off_unworn), `gt_state` (normal or the event name)

## Wear model
Watch is worn day and night; charging does not require removal. Removed only for bathing (15-30 min on most days) and occasional forgotten mornings. Worn 95.5-99.3% of the time.

## People and events (day numbers are 1-based)
| ID | Story |
|---|---|
| E1 | 72F, diabetes + hypertension. Hypoglycaemia-like dizzy episodes on days 3, 8, 12. |
| E2 | 68M healthy reference. Regular exercise (normal). Viral-illness-like phase days 9-11: higher resting HR and skin temp, lower SpO2. |
| E3 | 79F uncontrolled hypertension, non-dipper. BP surges on days 2, 5, 7, 11, 14. |
| E4 | 75M COPD-like. Nightly SpO2 dips, exertional desaturation days 4, 7, 10, 13, exacerbation-like phase days 11-14 (lower SpO2, higher resting HR, worse dips). |
| E5 | 70M. AF-like episodes days 3, 7, 10, 14. Falls on day 8 (19:42, lying ~23 min) and day 12 (03:10, lying ~42 min). Forgot watch on day 1 morning. |

## Realism features
Circadian HR/BP dip, activity-driven HR/BP with lag, day-to-day baseline drift, whole-number readings, motion dropouts (blank or stale held values), SpO2 motion glitches,
frequent cuffless-BP gaps, off-wrist periods where skin temp decays to room temp and recovers on re-wear.

## Caveats
- Real wearables rarely output SpO2, BP or skin temp at 2 Hz and cuffless BP is a trend estimate. For modelling, resample to 1-5 minute windows.
- HRV (core of Whoop-style recovery) needs beat-to-beat RR intervals, which 2 Hz HR cannot provide.
- Labels are scripted, so models will find them easier than real-world data. Report results with that caveat.
