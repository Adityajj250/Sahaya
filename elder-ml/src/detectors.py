from __future__ import annotations

import numpy as np
import pandas as pd

SOFT_EVENT_NAMES = {"hypoglycaemia_like_episode", "hypertensive_surge", "exertional_desaturation",
                    "nocturnal_desaturation", "af_like_episode"}


def personal_deviations(frame: pd.DataFrame) -> pd.DataFrame:
    """Past-only rolling robust baselines. Context grouping uses inferred context, never labels."""
    out = frame.copy()
    specs = {"hr_bpm": ("hr_bpm_mean", 4.), "spo2_pct": ("spo2_pct_mean", 1.),
             "sbp_mmhg": ("sbp_mmhg_mean", 6.), "dbp_mmhg": ("dbp_mmhg_mean", 5.),
             "skin_temp_c": ("skin_temp_c_mean", .25), "hr_absdiff": ("hr_absdiff", 2.)}
    for name, (col, floor) in specs.items():
        med = out.groupby("context", sort=False)[col].transform(lambda s: s.shift(1).rolling(1440, min_periods=60).median())
        # Rolling standard deviation is a fast scale estimate here; the median center and hard scale floor
        # limit the influence of brief simulated spikes at 1-minute aggregation.
        scale = out.groupby("context", sort=False)[col].transform(lambda s: s.shift(1).rolling(1440, min_periods=60).std())
        fallback = out.groupby("context", sort=False)[col].transform(lambda s: s.shift(1).expanding(min_periods=10).median())
        med = med.fillna(fallback)
        scale = scale.clip(lower=floor)
        # Early cold start uses robust prior samples from this stream; no metadata or future values.
        out[f"{name}_baseline"] = med
        out[f"{name}_z"] = (out[col] - med) / scale
    return out


def acute_and_rule_alerts(frame: pd.DataFrame) -> pd.DataFrame:
    """Non-clinical prototype rules for the dataset's scripted patterns."""
    f = personal_deviations(frame)
    f["tier"] = "Green"
    f["source"] = ""
    f["reason"] = ""
    worn = f.worn_fraction >= .5
    # Conservative hard floor candidates. These remain prototype thresholds, not NEWS2.
    deep_desaturation = worn & (f.spo2_pct_min < 80)
    sbp200 = f.sbp_mmhg_mean.ge(200).rolling(10, min_periods=10).sum().ge(10)
    severe = deep_desaturation | (worn & sbp200)
    f.loc[severe, ["tier", "source", "reason"]] = ["Red", "prototype_rule", "Very abnormal simulated vital reading"]
    sustained_low_o2 = worn & f.spo2_pct_mean.rolling(2, min_periods=2).mean().le(85)
    sustained_high_sbp = worn & f.sbp_mmhg_mean.ge(180).rolling(10, min_periods=10).sum().ge(10)
    tachycardia = worn & (f.hr_bpm_max >= 131)
    low_o2 = sustained_low_o2 & f.context.isin(["sleep", "rest"])
    f.loc[low_o2 & ~severe, ["tier", "source", "reason"]] = ["Orange", "prototype_rule", "Low SpO2 trend in a quiet window"]
    # Personalized acute pattern rules: combined evidence reduces baseline-driven alarms.
    dizzy = worn & (f.hr_bpm_z >= 2) & (f.sbp_mmhg_z <= -1.5) & (f.motion_g_mean < .35)
    # Allow a lower personal-baseline rise when it is sustained in a quiet interval.
    # This favors sensitivity to surges that stay below a population-style cutoff.
    sbp_sustained = f.sbp_mmhg_mean.ge(178).rolling(5, min_periods=5).sum().ge(5)
    bp_surge = (worn & (f.sbp_mmhg_z >= 1.75) & sbp_sustained
                & (f.motion_g_mean < .35) & ((f.dbp_mmhg_z >= 1.2) | (f.hr_bpm_z >= 1.5)))
    exertional = worn & (f.spo2_pct_z <= -3) & (f.motion_g_mean >= .12)
    af_like = worn & (f.hr_bpm_z >= 2) & (f.hr_absdiff_z >= 1.5)
    nightly = worn & (f.context == "sleep") & ((f.spo2_pct_z <= -2) | (f.spo2_pct_min < 90))
    orange = dizzy | bp_surge | exertional | af_like | sustained_high_sbp | tachycardia | low_o2
    f.loc[orange & ~severe, "tier"] = "Orange"
    f.loc[dizzy & ~severe, ["source", "reason"]] = ["acute_pattern", "Heart rate rose while systolic pressure fell at low motion"]
    f.loc[bp_surge & ~severe, ["source", "reason"]] = ["acute_pattern", "Systolic pressure rose above this person's recent baseline"]
    f.loc[exertional & ~severe, ["source", "reason"]] = ["acute_pattern", "SpO2 fell during an active interval"]
    f.loc[af_like & ~severe, ["source", "reason"]] = ["acute_pattern", "Fast and variable heart-rate pattern; simulated signal only"]
    f.loc[tachycardia & ~severe & ~af_like, ["source", "reason"]] = ["prototype_rule", "Fast heart-rate value; prototype threshold only"]
    yellow = nightly & ~orange & ~severe
    f.loc[yellow, ["tier", "source", "reason"]] = ["Yellow", "personal_deviation", "SpO2 below personal sleep baseline"]
    # Slow drift: compare trailing 3-hour quiet-time summaries with earlier observations.
    quiet = worn & f.context.isin(["sleep", "rest"])
    # Exercise recovery and post-episode rebound are not illness: keep them out of the drift windows.
    active_recent = (f.motion_g_mean >= .25).rolling(60, min_periods=1).max().astype(bool)
    acute_recent = (orange | severe).rolling(180, min_periods=1).max().astype(bool)
    quiet = quiet & ~active_recent & ~acute_recent
    for c in ["hr_bpm_mean", "spo2_pct_mean", "skin_temp_c_mean"]:
        smooth = f[c].where(quiet).rolling(180, min_periods=60).mean()
        base = smooth.where(quiet).shift(1).rolling(7 * 1440, min_periods=180).median()
        f[f"{c}_longbase"] = base
        f[f"{c}_3h"] = smooth
    hr_drift = f.hr_bpm_mean_3h - f.hr_bpm_mean_longbase >= 4
    o2_drift = f.spo2_pct_mean_longbase - f.spo2_pct_mean_3h >= 1.2
    temp_drift = f.skin_temp_c_mean_3h - f.skin_temp_c_mean_longbase >= .55
    drift_count = hr_drift.fillna(False).astype(int) + o2_drift.fillna(False).astype(int) + temp_drift.fillna(False).astype(int)
    drift = quiet & (drift_count >= 2)
    drift_orange = quiet & ((drift_count >= 3) | (drift.rolling(1440, min_periods=1440).sum() >= 1440))
    drift_yellow = drift & ~drift_orange
    f.loc[drift_yellow & f.tier.eq("Green"), ["tier", "source", "reason"]] = ["Yellow", "drift", "Multiple resting signals shifted from prior baseline"]
    f.loc[drift_orange & ~f.tier.eq("Red"), ["tier", "source", "reason"]] = ["Orange", "drift", "Persistent resting signal drift"]
    # Silence ticket only after 90 minutes without worn data during waking hours.
    hour = f.minute.dt.hour
    awake = (hour >= 7) & (hour < 22)
    off_awake = (f.worn_fraction < .5) & awake
    run_id = off_awake.ne(off_awake.shift(fill_value=False)).cumsum()
    off_run = off_awake.groupby(run_id).cumcount() + 1
    silence = off_awake & (off_run >= 90)
    f.loc[silence & f.tier.eq("Green"), ["tier", "source", "reason"]] = ["Yellow", "silence", "No worn data for at least 90 minutes during waking hours"]
    # Hysteresis: 3 of 5 minutes for Yellow; acute Orange needs all 8 minutes.
    # Red remains immediate unless the fall signature fails its stillness check.
    orange_candidate = f.tier.eq("Orange")
    yellow_candidate = f.tier.eq("Yellow") | orange_candidate
    orange_ok = orange_candidate.rolling(8, min_periods=1).sum() >= 8
    yellow_ok = yellow_candidate.rolling(5, min_periods=1).sum() >= 3
    original = f.tier.copy()
    # A short acute-pattern spike is not enough to emit a weaker health alert.
    # Keep other Orange candidates as Yellow during confirmation, but suppress
    # unconfirmed multivariate/acute pattern candidates to limit repeat false alarms.
    unconfirmed_acute = original.eq("Orange") & ~orange_ok & f.source.eq("acute_pattern")
    f.loc[original.eq("Orange") & ~orange_ok & ~unconfirmed_acute, "tier"] = "Yellow"
    f.loc[unconfirmed_acute, "tier"] = "Green"
    f.loc[original.eq("Yellow") & ~yellow_ok, "tier"] = "Green"
    f.loc[original.eq("Green") & yellow_ok, "tier"] = "Yellow"
    f.loc[original.eq("Orange") & orange_ok, "tier"] = "Orange"
    # Demo hygiene: an alert must always carry a source and a reason.
    f.loc[f.tier.ne("Green") & f.source.eq(""), "tier"] = "Green"
    return f


def fall_alerts(raw: pd.DataFrame) -> list[dict]:
    """Detect the deliberately scripted impact + stillness signature on raw samples."""
    x = raw.copy()
    x.timestamp = pd.to_datetime(x.timestamp)
    m = x.motion_g.to_numpy(dtype=float)
    alerts = []
    from numpy.lib.stride_tricks import sliding_window_view
    windows = sliding_window_view(m, 3)
    impact = (np.nanmax(windows, axis=1) >= 1.5) & (np.nanmean(windows, axis=1) >= 1.0)
    candidates = np.flatnonzero(impact)
    last_alert = -100
    for start in candidates:
        i = int(start + 2)
        if i - last_alert < 70 or i + 64 >= len(m) or start < 4:
            continue
        # Require an impact out of low pre-impact movement; sustained exercise followed by a rest is not a fall.
        still_window = m[i+4:i+65]
        if (np.nanmean(m[start-4:start]) <= .3 and np.nanmean(still_window) <= .05
                and np.nanquantile(still_window, .95) <= .05):
            detection_ts = x.timestamp.iat[i+64]
            alerts.append({"minute": detection_ts.floor("min"), "alert_ts": detection_ts,
                           "tier": "Red", "source": "fall", "reason": "Impact followed by 30 seconds of stillness",
                           "raw_impact_ts": x.timestamp.iat[i-2]})
            last_alert = i
    return alerts
