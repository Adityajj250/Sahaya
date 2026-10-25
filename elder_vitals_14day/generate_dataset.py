#!/usr/bin/env python3
"""
Synthetic wearable dataset: 5 elderly people x 14 days x 500 ms sampling
(2,419,200 rows per person, 12.1 M rows in total).

Signals   : hr_bpm, spo2_pct, sbp_mmhg, dbp_mmhg, skin_temp_c, motion_g
Truth     : columns starting with gt_ (drop before training).
Watch     : worn day and night (charging does NOT require removal). Removed only for
            bathing (~15-30 min) and the occasional forgotten morning.

Run:  python generate_dataset.py            -> elder_E1..E5.parquet, events.csv, persons.csv
      python generate_dataset.py --csv      -> also one CSV per person per day in ./csv/
"""
import os
import argparse
import numpy as np
import pandas as pd
from scipy.signal import lfilter, lfilter_zi

SEED = 2026
DT = 0.5                          # seconds per sample (500 ms)
DAYS = 14
SPD = int(86400 / DT)             # samples per day = 172,800
N = DAYS * SPD
START = pd.Timestamp("2026-10-09 00:00:00")      # IST local time, day 1
OUT = os.path.dirname(os.path.abspath(__file__))
EVENT_SCALE = 1.0
NOISE_SCALE = 1.0

ORDER = ["sleep", "rest", "light", "walk", "exercise", "meal", "nap", "off_bath", "off_unworn"]
ACT = {n: i for i, n in enumerate(ORDER)}
SLEEP, NAP, OFF_BATH, OFF_UNWORN = ACT["sleep"], ACT["nap"], ACT["off_bath"], ACT["off_unworn"]
#                 sleep rest light walk exer meal nap  bath unworn
HR_LUT = np.array([0,    0,   9,   24,  46,  4,   0,   0,   0], float)
SBP_LUT = np.array([0,   0,   6,   14,  30,  2,   0,   0,   0], float)
AMP_LUT = np.array([0.006, 0.020, 0.12, 0.42, 0.80, 0.05, 0.008, 0.0, 0.0])
TMP_LUT = np.array([0,   0,   0.1, 0.25, 0.35, 0,  0,   0,   0], float)


# ------------------------------------------------------------------ helpers
def sec(hhmm):
    p = [int(x) for x in hhmm.split(":")]
    return p[0] * 3600 + p[1] * 60 + (p[2] if len(p) > 2 else 0)


def at(day, hhmm):
    """Sample index of local time hhmm on 0-based day."""
    return int(round((day * 86400 + sec(hhmm)) / DT))


def stamp(i):
    return (START + pd.Timedelta(seconds=float(i) * DT)).strftime("%Y-%m-%d %H:%M:%S")


def lag(x, tau_s):
    a = np.exp(-DT / tau_s)
    b, aa = [1 - a], [1, -a]
    return lfilter(b, aa, x, zi=lfilter_zi(b, aa) * x[0])[0]


def ar_noise(rng, tau_s, sd, n=N):
    a = np.exp(-DT / tau_s)
    e = rng.standard_normal(n) * NOISE_SCALE
    return lfilter([np.sqrt(1 - a * a) * sd], [1, -a], e)


def env_slice(i0, i1, ramp_s):
    """Smooth 0..1 envelope, returned only for the window it matters in."""
    pad = int(6 * ramp_s / DT)
    lo, hi = max(0, i0 - pad), min(N, i1 + pad)
    env = np.zeros(hi - lo)
    env[i0 - lo:i1 - lo] = 1.0
    return lo, hi, lag(env, ramp_s)


def A(day, s, e, kind, end_day=None, hr=0, sbp=0, dbp=0, spo2=0.0, temp=0.0, motion=0.0,
      ramp=90, note="", act=None):
    """Anomaly spec. act=(start,end,activity) forces that activity on the same day."""
    return dict(day=day, s=s, end_day=day if end_day is None else end_day, e=e, kind=kind,
                hr=hr, sbp=sbp, dbp=dbp, spo2=spo2, temp=temp, motion=motion,
                ramp=ramp, note=note, act=act)


# ------------------------------------------------------------------ people
def people():
    P = {}

    P["E1"] = dict(
        desc="72F, type 2 diabetes + hypertension. Three hypoglycaemia-like dizzy episodes (days 3, 8, 12).",
        age=72, sex="F", hr_day=76, hr_sleep=64, sbp_day=138, dbp_day=84, dip=0.09, spo2=96.5, temp=33.6,
        wake="06:15", bed="22:20", bath="13:30", p_bath=0.6, p_forget=0.03,
        acts=[("06:45", "07:30", "light", .95), ("07:30", "08:00", "meal", .9),
              ("08:00", "08:40", "walk", .85), ("10:00", "10:30", "light", .9),
              ("12:45", "13:20", "meal", 1), ("14:00", "15:00", "nap", .8),
              ("17:00", "17:40", "walk", .8), ("19:30", "20:00", "meal", 1),
              ("20:15", "20:45", "light", .9)],
        anomalies=[
            A(2, "10:20", "11:15", "hypoglycaemia_like_episode", hr=32, sbp=-24, dbp=-10, temp=-0.55, motion=-0.7,
              note="Dizzy, sweaty, tachycardic, BP dips (matches the 'dizzy since morning' demo)"),
            A(7, "09:50", "10:40", "hypoglycaemia_like_episode", hr=26, sbp=-20, dbp=-8, temp=-0.45, motion=-0.6,
              note="Second episode after skipped breakfast"),
            A(11, "10:30", "11:20", "hypoglycaemia_like_episode", hr=36, sbp=-27, dbp=-11, temp=-0.6, motion=-0.7,
              note="Third, slightly stronger episode"),
        ],
        offs=[("sd", dict(hr=1.5, sbp=4.0, temp=0.12, spo2=0.25))],
    )

    P["E2"] = dict(
        desc="68M, healthy reference. Regular exercise (normal) and a viral-illness-like phase on days 9-11.",
        age=68, sex="M", hr_day=66, hr_sleep=56, sbp_day=122, dbp_day=77, dip=0.12, spo2=97.5, temp=34.0,
        wake="05:45", bed="22:45", bath="07:30", p_bath=0.9, p_forget=0.02,
        acts=[("06:00", "06:50", "exercise", .7), ("08:15", "08:45", "meal", 1),
              ("09:30", "10:30", "light", .9), ("12:30", "13:10", "meal", 1),
              ("13:30", "14:20", "nap", .6), ("16:30", "17:15", "walk", .85),
              ("19:15", "19:50", "meal", 1), ("20:00", "20:30", "light", .9)],
        anomalies=[
            A(8, "18:00", "23:59", "viral_illness_like", end_day=10, hr=9, spo2=-0.9, temp=0.9, motion=-0.35, ramp=6 * 3600,
              note="Slow-onset: raised resting HR and skin temp, slightly lower SpO2, less activity (days 9-11)"),
        ],
        offs=[("sd", dict(hr=1.2, sbp=3.0, temp=0.10, spo2=0.2))],
    )

    P["E3"] = dict(
        desc="79F, uncontrolled hypertension, non-dipper. Five evening/daytime BP surges.",
        age=79, sex="F", hr_day=80, hr_sleep=72, sbp_day=152, dbp_day=92, dip=0.02, spo2=96.0, temp=33.4,
        wake="06:30", bed="22:30", bath="16:00", p_bath=0.5, p_forget=0.03,
        acts=[("07:15", "07:45", "meal", 1), ("08:30", "09:30", "light", .9),
              ("10:30", "11:00", "walk", .8), ("12:45", "13:20", "meal", 1),
              ("14:00", "15:00", "nap", .7), ("19:15", "19:50", "meal", 1),
              ("20:00", "20:30", "light", .9)],
        anomalies=[
            A(1, "17:05", "18:35", "hypertensive_surge", hr=14, sbp=36, dbp=16, temp=-0.15, note="Sustained BP surge at rest"),
            A(4, "11:20", "12:40", "hypertensive_surge", hr=12, sbp=32, dbp=14, temp=-0.1, note="Late-morning surge"),
            A(6, "17:30", "18:50", "hypertensive_surge", hr=15, sbp=40, dbp=18, temp=-0.15, note="Strong evening surge"),
            A(10, "20:10", "21:10", "hypertensive_surge", hr=11, sbp=30, dbp=13, temp=-0.1, note="Short surge after dinner"),
            A(13, "16:40", "18:10", "hypertensive_surge", hr=14, sbp=38, dbp=17, temp=-0.15, note="Surge on last day"),
        ],
        offs=[("sd", dict(hr=1.5, sbp=5.0, temp=0.12, spo2=0.25))],
    )

    P["E4"] = dict(
        desc="75M, COPD-like. Low SpO2 baseline, nightly desaturation dips, exertional desaturation, exacerbation-like phase days 11-14.",
        age=75, sex="M", hr_day=82, hr_sleep=70, sbp_day=132, dbp_day=80, dip=0.07, spo2=93.5, temp=33.3,
        wake="06:00", bed="22:00", bath="08:10", p_bath=0.6, p_forget=0.03,
        acts=[("06:30", "07:00", "light", .9), ("07:30", "08:00", "meal", 1),
              ("09:30", "10:00", "walk", .8), ("12:30", "13:10", "meal", 1),
              ("13:30", "14:30", "nap", .7), ("17:30", "18:30", "light", .9),
              ("19:30", "20:05", "meal", 1)],
        anomalies=[
            A(d, "15:03", "15:40", "exertional_desaturation", hr=26, sbp=10, dbp=4, spo2=-6.5, temp=0.1,
              note="SpO2 falls to ~87% after a walk, slow recovery", act=("15:00", "15:25", "walk"))
            for d in (3, 6, 9, 12)
        ] + [
            A(10, "07:00", "23:59", "copd_exacerbation_like", end_day=13, hr=6, spo2=-1.8, temp=0.2, ramp=4 * 3600,
              note="Persistently lower SpO2 and higher resting HR (days 11-14)"),
        ],
        nocturnal=("01:00", "05:00"),
        offs=[("sd", dict(hr=1.5, sbp=4.0, temp=0.12, spo2=0.3))],
    )

    P["E5"] = dict(
        desc="70M. Forgot the watch on day 1. Four AF-like episodes (days 3, 7, 10, 14) and two falls (day 8 evening, day 12 at night).",
        age=70, sex="M", hr_day=72, hr_sleep=62, sbp_day=134, dbp_day=82, dip=0.08, spo2=96.8, temp=33.8,
        wake="06:20", bed="22:30", bath="16:15", p_bath=0.6, p_forget=0.03,
        acts=[("07:00", "07:30", "light", .9), ("09:15", "09:45", "meal", 1),
              ("10:00", "10:40", "walk", .85), ("12:30", "13:15", "meal", 1),
              ("14:00", "15:00", "nap", .7), ("17:30", "18:10", "light", .9),
              ("19:00", "19:35", "meal", 1)],
        forced=[(0, "00:00", "09:15", "off_unworn")],
        anomalies=[
            A(2, "12:08", "12:58", "af_like_episode", hr=42, note="Irregular fast HR; cuffless BP unreliable"),
            A(6, "21:10", "21:55", "af_like_episode", hr=36, note="Evening episode"),
            A(9, "05:40", "06:30", "af_like_episode", hr=40, note="Early-morning episode"),
            A(13, "14:20", "15:40", "af_like_episode", hr=46, note="Longest episode"),
        ],
        falls=[
            dict(day=7, s="19:42:10", e="20:05:00", act=None,
                 note="Impact (~3.6 g) then near-zero motion, elevated HR/BP for ~23 min"),
            dict(day=11, s="03:10:20", e="03:52:00", act=("03:06", "03:10", "walk"),
                 note="Night-time fall on way to bathroom, lying still ~42 min"),
        ],
        offs=[("sd", dict(hr=1.5, sbp=4.0, temp=0.12, spo2=0.25))],
    )
    return P


# ------------------------------------------------------------------ timeline
def build_timeline(cfg, rng):
    act = np.full(N, ACT["rest"], np.int8)
    wakes = [d * 86400 + sec(cfg["wake"]) + rng.normal(0, 18 * 60) for d in range(DAYS)]
    beds = [d * 86400 + sec(cfg["bed"]) + rng.normal(0, 25 * 60) for d in range(DAYS)]
    prev = 0.0
    for d in range(DAYS):
        act[int(prev / DT):int(wakes[d] / DT)] = SLEEP
        prev = beds[d]
    act[int(prev / DT):] = SLEEP

    forced = list(cfg.get("forced", []))
    for a in cfg["anomalies"] + cfg.get("falls", []):
        if a.get("act"):
            s, e, name = a["act"]
            forced.append((a["day"], s, e, name))

    for d in range(DAYS):
        for s, e, name, p in cfg["acts"]:
            if rng.random() > p:
                continue
            a = d * 86400 + sec(s) + rng.normal(0, 15 * 60)
            b = a + (sec(e) - sec(s)) * rng.uniform(0.8, 1.25)
            a, b = max(a, wakes[d] + 600), min(b, beds[d] - 600)
            if b > a:
                act[int(a / DT):int(b / DT)] = ACT[name]
    for d, s, e, name in forced:
        act[at(d, s):at(d, e)] = ACT[name]
    for d in range(DAYS):                                   # bathing: watch off 15-30 min
        if rng.random() < cfg["p_bath"]:
            a = d * 86400 + sec(cfg["bath"]) + rng.normal(0, 25 * 60)
            act[int(a / DT):int((a + rng.uniform(15, 30) * 60) / DT)] = OFF_BATH
        if rng.random() < cfg["p_forget"]:                  # forgot to put the watch on
            a = wakes[d]
            act[int(a / DT):int((a + rng.uniform(1, 3) * 3600) / DT)] = OFF_UNWORN
    for d, s, e, name in cfg.get("forced", []):             # explicit forced non-wear wins last
        if name.startswith("off"):
            act[at(d, s):at(d, e)] = ACT[name]
    return act


# ------------------------------------------------------------------ generator
def generate(pid, cfg, rng):
    act = build_timeline(cfg, rng)
    is_sleep = (act == SLEEP) | (act == NAP)
    is_off = act >= OFF_BATH
    sleep_smooth = lag(is_sleep.astype(float), 1800)

    # day-to-day baseline drift (smooth, so no steps at midnight)
    sd = cfg["offs"][0][1]

    def day_off(s):
        return lag(np.repeat(rng.normal(0, s * NOISE_SCALE, DAYS), SPD), 3 * 3600)
    hr_off, sbp_off, temp_off, spo2_off = day_off(sd["hr"]), day_off(sd["sbp"]), day_off(sd["temp"]), day_off(sd["spo2"])

    # ---- true underlying signals
    hr_target = cfg["hr_day"] + HR_LUT[act] - (cfg["hr_day"] - cfg["hr_sleep"]) * sleep_smooth + hr_off
    hr = lag(hr_target, 25) + ar_noise(rng, 300, 2.0) + rng.standard_normal(N) * np.where(is_sleep, 1.6, 1.0) * NOISE_SCALE

    sbp_circ = (cfg["sbp_day"] + sbp_off) * (1 - cfg["dip"] * sleep_smooth)
    dbp_circ = (cfg["dbp_day"] + 0.4 * sbp_off) * (1 - cfg["dip"] * 1.1 * sleep_smooth)
    sbp = lag(sbp_circ + SBP_LUT[act], 60) + ar_noise(rng, 600, 3.0)
    dbp = lag(dbp_circ, 60) + 0.40 * (sbp - lag(sbp_circ, 60)) + ar_noise(rng, 600, 1.5)

    spo2 = cfg["spo2"] + spo2_off + ar_noise(rng, 900, 0.35)
    spo2 -= np.where(act == ACT["exercise"], 0.8, 0) + np.where(act == ACT["walk"], 0.3, 0)
    temp = cfg["temp"] + temp_off + 0.7 * sleep_smooth + lag(TMP_LUT[act], 150) + ar_noise(rng, 1800, 0.12)

    motion = AMP_LUT[act] * np.abs(rng.standard_normal(N) * NOISE_SCALE) * (0.6 + 0.8 * rng.random(N))
    for i in np.flatnonzero((rng.random(N) < 0.0006) & is_sleep):       # turning in bed
        motion[i:i + 6] = np.maximum(motion[i:i + 6], 0.25 + 0.2 * rng.random())

    state = np.zeros(N, np.int16)
    state_names = ["normal"]

    def code(name):
        if name not in state_names:
            state_names.append(name)
        return state_names.index(name)

    events = []

    def log(day, i0, i1, kind, note):
        events.append((pid, day + 1, stamp(i0), stamp(i1), kind, note))

    # ---- scheduled anomalies
    for a in cfg["anomalies"]:
        i0, i1 = at(a["day"], a["s"]), at(a["end_day"], a["e"])
        lo, hi, env = env_slice(i0, i1, a["ramp"])
        hr[lo:hi] += a["hr"] * EVENT_SCALE * env
        sbp[lo:hi] += a["sbp"] * EVENT_SCALE * env
        dbp[lo:hi] += a["dbp"] * EVENT_SCALE * env
        spo2[lo:hi] += a["spo2"] * EVENT_SCALE * env
        temp[lo:hi] += a["temp"] * EVENT_SCALE * env
        motion[lo:hi] *= (1 + a["motion"] * EVENT_SCALE * env)
        seg = state[i0:i1]
        seg[seg == 0] = code(a["kind"])
        if a["kind"] == "af_like_episode":
            n = i1 - i0
            hr[i0:i1] += rng.standard_normal(n) * 9 * NOISE_SCALE + ar_noise(rng, 20, 6, n)
            sbp[i0:i1] += rng.standard_normal(n) * 9 * NOISE_SCALE
            dbp[i0:i1] += rng.standard_normal(n) * 5 * NOISE_SCALE
            spo2[i0:i1] += rng.standard_normal(n) * 1.0 * NOISE_SCALE
        log(a["day"], i0, i1, a["kind"], a["note"])

    # ---- nocturnal desaturation dips (COPD-like)
    if cfg.get("nocturnal"):
        for d in range(DAYS):
            mult = 1.4 if d >= 10 else 1.0                      # worse during exacerbation days
            t, t_end, cnt = at(d, cfg["nocturnal"][0]), at(d, cfg["nocturnal"][1]), 0
            while t < t_end:
                dur = int(rng.integers(60, 200) / DT)
                depth = min(15.0, rng.uniform(5.0, 11.0) * mult * EVENT_SCALE)
                spo2[t:t + dur] -= depth * np.sin(np.linspace(0, np.pi, dur)) ** 0.7
                k = int(40 / DT)
                hr[t + dur:t + dur + k] += 14 * np.exp(-np.linspace(0, 3, k))     # arousal tachycardia
                motion[t + dur:t + dur + 8] = np.maximum(motion[t + dur:t + dur + 8], 0.3)
                seg = state[t:t + dur]
                seg[seg == 0] = code("nocturnal_desaturation")
                t += dur + int(rng.integers(240, 700) / DT)
                cnt += 1
            log(d, at(d, cfg["nocturnal"][0]), t_end, "nocturnal_desaturation",
                f"{cnt} SpO2 dips of {5 * mult:.0f}-{min(15, 11 * mult):.0f} points")

    # ---- falls
    for f in cfg.get("falls", []):
        i0, i1 = at(f["day"], f["s"]), at(f["day"], f["e"])
        k = int(60 / DT)
        motion[i0 - 4:i0] = 0.05
        motion[i0:i0 + 3] = 1.0 + (np.array([2.9, 3.6, 1.8]) - 1.0) * EVENT_SCALE
        motion[i0 + 6:i1] = np.abs(rng.standard_normal(i1 - i0 - 6) * NOISE_SCALE) * 0.004
        lo, hi = max(0, i0 - int(1500 / DT)), min(N, i1 + int(1500 / DT))
        env = np.zeros(hi - lo)
        env[i0 - lo:i1 - lo] = 1.0
        env = lag(env, 240)
        hr[lo:hi] += 38 * EVENT_SCALE * env
        sbp[lo:hi] += 24 * EVENT_SCALE * env
        dbp[lo:hi] += 10 * EVENT_SCALE * env
        spo2[i0:i0 + int(180 / DT)] -= 1.2 * EVENT_SCALE
        hr[i0 + 2:i0 + 2 + k] += 18 * EVENT_SCALE * np.exp(-np.linspace(0, 3, k))
        motion[i1:i1 + k] = np.abs(rng.standard_normal(k) * NOISE_SCALE) * 0.25
        state[i0:i0 + 6] = code("fall_impact")
        state[i0 + 6:i1] = code("post_fall_lying")
        log(f["day"], i0, i1, "fall_and_lying_still", f["note"])

    # ---- physiological limits
    hr = np.clip(hr, 38, 190)
    sbp = np.clip(sbp, 70, 230)
    dbp = np.minimum(np.clip(dbp, 40, 135), sbp - 20)
    spo2 = np.clip(spo2 + rng.standard_normal(N) * 0.35 * NOISE_SCALE, 68, 100)
    temp = temp + rng.standard_normal(N) * 0.03 * NOISE_SCALE

    # ---- measurement artefacts while worn
    p_start = 0.0004 + 0.003 * np.clip(motion / 0.4, 0, 1.5)
    drop_nan = np.zeros(N, bool)
    drop_hold = np.zeros(N, bool)
    for i in np.flatnonzero(rng.random(N) < p_start):
        d = int(rng.integers(2, 25))
        if rng.random() < 0.5:
            drop_nan[i:i + d] = True
        else:
            drop_hold[i:i + d] = True
        if rng.random() < 0.35 and motion[i] > 0.15:
            spo2[i:i + 3] -= rng.uniform(3, 8)
    bp_gap = np.zeros(N, bool)
    for i in np.flatnonzero(rng.random(N) < 0.0006):
        bp_gap[i:i + int(rng.integers(20, 160))] = True

    def hold(x, mask):
        return np.array(pd.Series(np.where(mask, np.nan, x)).ffill().bfill().to_numpy(), dtype=float)

    hr_o, spo2_o = hold(hr, drop_hold), hold(spo2, drop_hold)
    hr_o[drop_nan] = np.nan
    spo2_o[drop_nan] = np.nan
    sbp_o, dbp_o = sbp.copy(), dbp.copy()
    sbp_o[drop_nan | bp_gap] = np.nan
    dbp_o[drop_nan | bp_gap] = np.nan
    temp_o = temp.copy()

    # ---- off-wrist: vitals missing, skin temp drifts to room temp, then recovers
    ambient = 27.5 + 2.0 * np.sin(2 * np.pi * (np.arange(N) * DT / 3600 - 9) / 24)
    edges = np.diff(np.r_[0, is_off.astype(np.int8), 0])
    for s, e in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
        L = e - s
        hr_o[s:e] = spo2_o[s:e] = sbp_o[s:e] = dbp_o[s:e] = np.nan
        t0 = temp[s - 1] if s > 0 else temp[s]
        temp_o[s:e] = ambient[s:e] + (t0 - ambient[s:e]) * np.exp(-np.arange(L) * DT / 420.0) + rng.standard_normal(L) * 0.02 * NOISE_SCALE
        motion[s:e] = np.abs(rng.standard_normal(L) * NOISE_SCALE) * 0.0015
        motion[s:s + 5] = 0.9
        if e + 5 <= N:
            motion[e - 5:e] = 0.9
        kk = min(int(600 / DT), N - e)
        if kk > 0 and e > 0:
            ramp = 1 - np.exp(-np.arange(kk) * DT / 120.0)
            temp_o[e:e + kk] = temp_o[e - 1] + (temp[e:e + kk] - temp_o[e - 1]) * ramp
        seg = state[s:e]
        seg[seg == 0] = code("watch_off_wrist")
        events.append((pid, int(s // SPD) + 1, stamp(s), stamp(e), "watch_off_wrist:" + ORDER[act[s]].replace("off_", ""),
                       "Not worn: HR/SpO2/BP missing, skin temp drifts to room temperature"))

    # ---- quantise like a device
    df = pd.DataFrame({
        "person_id": pd.Categorical.from_codes(np.zeros(N, np.int8), [pid]),
        "timestamp": pd.date_range(START, periods=N, freq="500ms"),
        "day": (np.arange(N) // SPD + 1).astype(np.int8),
        "t_sec": (np.arange(N) * DT).astype(np.float32),
        "hr_bpm": np.round(hr_o).astype(np.float32),
        "spo2_pct": np.round(spo2_o).astype(np.float32),
        "sbp_mmhg": np.round(sbp_o).astype(np.float32),
        "dbp_mmhg": np.round(dbp_o).astype(np.float32),
        "skin_temp_c": np.round(temp_o, 2).astype(np.float32),
        "motion_g": np.round(motion, 4).astype(np.float32),
        "gt_worn": (~is_off).astype(np.int8),
        "gt_activity": pd.Categorical.from_codes(act, ORDER),
        "gt_state": pd.Categorical.from_codes(state, state_names),
    })
    return df, events


def main():
    global OUT, EVENT_SCALE, NOISE_SCALE
    parser = argparse.ArgumentParser(description="Generate the synthetic wearable dataset")
    parser.add_argument("--csv", action="store_true", help="also export one CSV per person/day")
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--event-scale", type=float, default=1.0)
    parser.add_argument("--noise-scale", type=float, default=1.0)
    parser.add_argument("--out", default=OUT, help="output folder (default: this script's folder)")
    args = parser.parse_args()
    if args.event_scale < 0 or args.noise_scale < 0:
        parser.error("event-scale and noise-scale must be non-negative")
    EVENT_SCALE, NOISE_SCALE = args.event_scale, args.noise_scale
    OUT = os.path.abspath(args.out)
    os.makedirs(OUT, exist_ok=True)
    master = np.random.default_rng(args.seed)
    all_events, profiles = [], []
    for pid, cfg in people().items():
        rng = np.random.default_rng(master.integers(1 << 31))
        df, events = generate(pid, cfg, rng)
        df.to_parquet(os.path.join(OUT, f"elder_{pid}.parquet"), compression="zstd", index=False)
        if args.csv:
            os.makedirs(os.path.join(OUT, "csv"), exist_ok=True)
            for d, g in df.groupby("day", observed=True):
                g.to_csv(os.path.join(OUT, "csv", f"elder_{pid}_day{d:02d}.csv"), index=False)
        if pid == "E1":                                   # small sample around the first dizzy episode
            s, e = at(2, "10:00"), at(2, "11:30")
            df.iloc[s:e].to_csv(os.path.join(OUT, "sample_E1_day3_1000-1130.csv"), index=False)
        all_events += events
        profiles.append(dict(person_id=pid, age=cfg["age"], sex=cfg["sex"],
                             baseline_hr_day=cfg["hr_day"], baseline_hr_sleep=cfg["hr_sleep"],
                             baseline_sbp=cfg["sbp_day"], baseline_dbp=cfg["dbp_day"],
                             baseline_spo2=cfg["spo2"], baseline_skin_temp=cfg["temp"],
                             worn_pct=round(100 * df.gt_worn.mean(), 1), description=cfg["desc"]))
        print(pid, df.shape, f"worn {df.gt_worn.mean():.1%}", f"HR missing {df.hr_bpm.isna().mean():.1%}", flush=True)
        del df
    ev = pd.DataFrame(all_events, columns=["person_id", "day", "start", "end", "event", "note"])
    ev.sort_values(["person_id", "start"]).to_csv(os.path.join(OUT, "events.csv"), index=False)
    pd.DataFrame(profiles).to_csv(os.path.join(OUT, "persons.csv"), index=False)


if __name__ == "__main__":
    main()
