from __future__ import annotations

import numpy as np
import pandas as pd
from .io import SIGNALS


def minute_features(raw: pd.DataFrame) -> pd.DataFrame:
    """Aggregate 500 ms samples into causal minute rows; labels are carried for scoring only."""
    df = raw.copy()
    df["timestamp"] = pd.to_datetime(df.timestamp)
    df["minute"] = df.timestamp.dt.floor("min")
    df["_hr_absdiff"] = df.hr_bpm.diff().abs()
    df["_hr_repeat"] = (df.hr_bpm.eq(df.hr_bpm.shift()) & df.hr_bpm.notna()).astype("float32")
    groups = df.groupby("minute", sort=True)
    out = groups[SIGNALS].agg(["mean", "median", "min", "max", "std"])
    out.columns = [f"{a}_{b}" for a, b in out.columns]
    valid = groups[SIGNALS].count().div(groups.size(), axis=0)
    valid.columns = [f"{c}_valid" for c in valid.columns]
    out = out.join(valid)
    out["held_hr_fraction"] = groups._hr_repeat.mean()
    out["hr_absdiff"] = groups._hr_absdiff.mean()
    out["motion_p95"] = groups.motion_g.quantile(.95)
    out["motion_burst_max"] = groups.motion_g.max()
    # Inference-only wear proxy from sensor availability; never use gt_worn as a feature.
    out["worn_fraction"] = out[["hr_bpm_valid", "spo2_pct_valid"]].max(axis=1)
    out["activity_label"] = groups.gt_activity.first()
    out["state_label"] = groups.gt_state.first()
    out["minute"] = out.index
    out["day_internal"] = groups.day.first().to_numpy()
    # Inference-only context heuristic; labels above remain evaluation metadata.
    motion = out.motion_g_mean
    hour_of_day = out.minute.dt.hour
    # Sleep needs BOTH the night-time window AND low motion, so early-morning exercise or chores
    # (e.g. E2 at 06:00) are never mistaken for sleep.
    sleep_hours = ((hour_of_day >= 22) | (hour_of_day <= 6)) & (motion < .08)
    out["context"] = np.select([out.worn_fraction < .5, sleep_hours, motion > .45, motion > .12],
                                ["off_wrist", "sleep", "active_high", "active_low"], default="rest")
    # Trailing windows include the current minute and never look ahead.
    for col in [f"{s}_mean" for s in SIGNALS] + ["hr_absdiff", "motion_p95"]:
        out[f"{col}_roll5"] = out[col].rolling(5, min_periods=1).mean()
        out[f"{col}_roll15"] = out[col].rolling(15, min_periods=1).mean()
    hour = out.minute.dt.hour + out.minute.dt.minute / 60
    out["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    out["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    return out.reset_index(drop=True)


def causal_columns(frame: pd.DataFrame) -> list[str]:
    blocked = {"minute", "day_internal", "activity_label", "state_label", "context"}
    return [c for c in frame.columns if c not in blocked and pd.api.types.is_numeric_dtype(frame[c])]
