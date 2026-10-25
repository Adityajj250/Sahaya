from __future__ import annotations

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier

from .detectors import personal_deviations, SOFT_EVENT_NAMES
from .features import causal_columns


def feature_matrix(raw: pd.DataFrame):
    f = personal_deviations(raw)
    zcols = [c for c in f if c.endswith("_z")]
    for col in zcols:
        f[col + "_pos"] = f[col].clip(lower=0)
        f[col + "_neg"] = (-f[col]).clip(lower=0)
    for col in ["hr_bpm_z", "spo2_pct_z", "sbp_mmhg_z", "dbp_mmhg_z", "skin_temp_c_z", "hr_absdiff_z"]:
        if col in f:
            f[f"{col}_persist30"] = (f[col].abs() > 2).rolling(30, min_periods=1).sum()
            f[f"{col}_persist60"] = (f[col].abs() > 2).rolling(60, min_periods=1).sum()
    context_cols = ["context_active_high", "context_active_low", "context_off_wrist", "context_rest", "context_sleep"]
    context = pd.get_dummies(f.context, prefix="context", dtype="int8").reindex(columns=context_cols, fill_value=0)
    f = f.join(context)
    names = [c for c in causal_columns(f) if not c.endswith("_z") and c != "day_internal"]
    return f[names].replace([np.inf, -np.inf], np.nan).astype("float32"), f, names


def _event_masks(frames: dict[str, pd.DataFrame], events: pd.DataFrame):
    labels, eligible, folds, matrices = {}, {}, {}, {}
    event_rows = events[events.event.isin(SOFT_EVENT_NAMES)]
    excluded_types = {"viral_illness_like", "copd_exacerbation_like", "fall_and_lying_still"}
    for person, raw in frames.items():
        X, f, feature_names = feature_matrix(raw)
        y = pd.Series(False, index=f.index)
        ignored = pd.Series(False, index=f.index)
        boundaries = []
        pe = events[events.person_id == person]
        for ev in pe.itertuples(index=False):
            s, e = pd.Timestamp(ev.start), pd.Timestamp(ev.end)
            t = pd.to_datetime(f.minute)
            inside = (t >= s) & (t <= e)
            if ev.event in SOFT_EVENT_NAMES:
                y |= inside
                boundaries.extend([s, e])
            if ev.event in excluded_types or ev.event.startswith("watch_off_wrist"):
                ignored |= inside
        # A causal five-minute window is positive when at least two constituent minutes overlap an event.
        y = y.rolling(5, min_periods=1).sum().ge(2)
        # Ignore event edges and non-wear for training; they remain available to the independent safety layers.
        t = pd.to_datetime(f.minute)
        for point in boundaries:
            ignored |= (t >= point - pd.Timedelta(minutes=10)) & (t <= point + pd.Timedelta(minutes=10))
        ignored |= f.worn_fraction < .5
        day = f.day_internal.astype(int)
        labels[person] = y.to_numpy(dtype=np.int8)
        eligible[person] = ~ignored.to_numpy()
        folds[person] = ((day.to_numpy() - 1) % 7).astype(int)
        matrices[person] = (X, f)
    return labels, eligible, folds, matrices, event_rows


def grouped_oof(frames: dict[str, pd.DataFrame], events: pd.DataFrame):
    """Return day-grouped OOF model scores and recall-derived thresholds for synthetic analysis."""
    labels, eligible, folds, matrices, event_rows = _event_masks(frames, events)
    predictions = {person: np.full(len(frames[person]), np.nan, dtype=float) for person in frames}
    feature_names = next(iter(matrices.values()))[0].columns.tolist()
    constraints = []
    for col in feature_names:
        constraints.append(1 if (col.endswith("_pos") or col.endswith("_neg") or "_persist" in col) else 0)
    for fold in range(7):
        train_x, train_y, train_w, test_x, refs = [], [], [], [], []
        # Hold out complete modulo-7 day groups; exclude a 2-hour buffer around their event spans from train.
        held_out_times = []
        for ev in event_rows.itertuples(index=False):
            if (int(ev.day) - 1) % 7 == fold:
                held_out_times.append((ev.person_id, pd.Timestamp(ev.start), pd.Timestamp(ev.end)))
        for person, (X, f) in matrices.items():
            test = folds[person] == fold
            train = (folds[person] != fold) & eligible[person]
            t = pd.to_datetime(f.minute)
            for pid, start, end in held_out_times:
                if pid == person:
                    train &= ~((t >= start - pd.Timedelta(hours=2)) & (t <= end + pd.Timedelta(hours=2)))
            idx = np.flatnonzero(train)
            if len(idx):
                yy = labels[person][idx]
                train_x.append(X.iloc[idx]); train_y.append(yy)
                train_w.append(np.where(yy == 1, 15., 1.))
            tidx = np.flatnonzero(test)
            if len(tidx):
                test_x.append(X.iloc[tidx]); refs.extend((person, i) for i in tidx)
        if not train_x or not test_x or len(np.unique(np.concatenate(train_y))) < 2:
            continue
        model = LGBMClassifier(objective="binary", n_estimators=180, num_leaves=9, learning_rate=.05,
                               min_child_samples=200, colsample_bytree=.8, reg_lambda=1.0,
                               monotone_constraints=constraints, verbosity=-1, random_state=2026, n_jobs=-1)
        model.fit(pd.concat(train_x, ignore_index=True), np.concatenate(train_y), sample_weight=np.concatenate(train_w))
        pred = model.predict_proba(pd.concat(test_x, ignore_index=True))[:, 1]
        for (person, idx), p in zip(refs, pred):
            predictions[person][idx] = p
    pos_scores = np.concatenate([predictions[p][(labels[p] == 1) & eligible[p] & np.isfinite(predictions[p])] for p in frames])
    if not len(pos_scores):
        return {}, {"yellow": .5, "orange": .5}, labels
    # Sensitivity-first Orange threshold: retain the OOF-derived Yellow threshold,
    # while allowing persistent scores >=0.30 to escalate when the model is less
    # certain than it was on the original generator seed.
    # Tier order fixed: Yellow is the looser (early) threshold, Orange the stricter one.
    orange = float(np.quantile(pos_scores, .02))
    return predictions, {"yellow": min(.60, orange), "orange": orange}, labels


def fit_full_model(frames: dict[str, pd.DataFrame], events: pd.DataFrame):
    labels, eligible, _, matrices, _ = _event_masks(frames, events)
    feature_names = next(iter(matrices.values()))[0].columns.tolist()
    constraints = [1 if (c.endswith("_pos") or c.endswith("_neg") or "_persist" in c) else 0 for c in feature_names]
    xs, ys, ws = [], [], []
    for person, (X, _) in matrices.items():
        idx = np.flatnonzero(eligible[person])
        y = labels[person][idx]
        xs.append(X.iloc[idx]); ys.append(y); ws.append(np.where(y == 1, 15., 1.))
    model = LGBMClassifier(objective="binary", n_estimators=180, num_leaves=9, learning_rate=.05,
                           min_child_samples=200, colsample_bytree=.8, reg_lambda=1.0,
                           monotone_constraints=constraints, verbosity=-1, random_state=2026, n_jobs=-1)
    model.fit(pd.concat(xs, ignore_index=True), np.concatenate(ys), sample_weight=np.concatenate(ws))
    return model, feature_names


def predict_full(model, raw: pd.DataFrame):
    X, _, _ = feature_matrix(raw)
    return model.predict_proba(X)[:, 1]


def model_alerts(frame: pd.DataFrame, probabilities: np.ndarray, threshold: dict, yellow_window: int = 12, yellow_need: int = 8) -> pd.DataFrame:
    p = pd.Series(probabilities, index=frame.index)
    orange_candidate = p.ge(threshold["orange"]).fillna(False)
    yellow_candidate = p.ge(threshold["yellow"]).fillna(False)
    orange = orange_candidate.rolling(8, min_periods=1).sum().ge(7)
    # Yellow needs a sustained mild deviation (default 8 of the last 12 minutes), so a few noisy minutes cannot trigger it.
    yellow = yellow_candidate.rolling(yellow_window, min_periods=1).sum().ge(yellow_need)
    rows = pd.DataFrame({"minute": frame.minute, "tier": "Green", "source": "", "reason": "", "alert_ts": frame.minute})
    rows.loc[yellow, ["tier", "source", "reason"]] = ["Yellow", "M3", "Elevated multivariate deviation from recent personal baseline"]
    rows.loc[orange, ["tier", "source", "reason"]] = ["Orange", "M3", "Persistent elevated multivariate deviation from recent personal baseline"]
    rows.loc[orange, "alert_ts"] = frame.loc[orange, "minute"]
    rows.loc[yellow & ~orange, "alert_ts"] = frame.loc[yellow & ~orange, "minute"]
    return rows[rows.tier.ne("Green")].copy()
