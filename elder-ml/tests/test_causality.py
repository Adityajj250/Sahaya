import numpy as np
import pandas as pd

from src.features import minute_features, causal_columns
from src.detectors import personal_deviations, fall_alerts
from src.acute_model import feature_matrix


def raw_stream(minutes=20):
    n = minutes * 120
    ts = pd.date_range("2026-01-01", periods=n, freq="500ms")
    return pd.DataFrame({"timestamp": ts, "day": 1, "t_sec": np.arange(n) / 2,
                         "person_id": "E1", "hr_bpm": 70., "spo2_pct": 96.,
                         "sbp_mmhg": 120., "dbp_mmhg": 75., "skin_temp_c": 33.,
                         "motion_g": .02, "gt_activity": "rest", "gt_state": "normal"})


def test_features_do_not_change_when_future_rows_change():
    raw = raw_stream()
    before = minute_features(raw)
    changed = raw.copy()
    changed.loc[changed.timestamp >= pd.Timestamp("2026-01-01 00:10:00"), "hr_bpm"] = 180.
    after = minute_features(changed)
    cols = causal_columns(before)
    pd.testing.assert_frame_equal(before.loc[:9, cols], after.loc[:9, cols])


def test_personal_baseline_is_past_only():
    f = minute_features(raw_stream(80))
    before = personal_deviations(f)
    changed = f.copy()
    changed.loc[changed.minute >= pd.Timestamp("2026-01-01 01:16:00"), "hr_bpm_mean"] = 180.
    after = personal_deviations(changed)
    pd.testing.assert_series_equal(before.loc[:75, "hr_bpm_baseline"], after.loc[:75, "hr_bpm_baseline"])
    pd.testing.assert_series_equal(before.loc[:75, "hr_bpm_z"], after.loc[:75, "hr_bpm_z"])


def test_model_feature_schema_excludes_ground_truth_and_absolute_time():
    X, _, names = feature_matrix(minute_features(raw_stream(20)))
    assert not any(c.startswith("gt_") for c in names)
    assert "day_internal" not in names
    assert "minute" not in names
    assert "hour_sin" in names and "hour_cos" in names
    assert len(X.columns) == len(names)


def test_fall_detector_rejects_exercise_stop_and_detects_impact_then_stillness():
    n = 300
    motion = np.full(n, .02)
    motion[30:100] = 1.1  # active movement ending in stillness is not enough
    motion[150:154] = .05
    motion[154:157] = [2.9, 3.6, 1.8]
    motion[160:220] = .004
    raw = pd.DataFrame({"timestamp": pd.date_range("2026-01-01", periods=n, freq="500ms"),
                        "motion_g": motion, "hr_bpm": 70.})
    alerts = fall_alerts(raw)
    assert len(alerts) == 1
    assert alerts[0]["tier"] == "Red"
    assert alerts[0]["alert_ts"] - alerts[0]["raw_impact_ts"] <= pd.Timedelta(seconds=90)
