from __future__ import annotations

import argparse
import json
from pathlib import Path
import joblib
import pandas as pd
import matplotlib.pyplot as plt

from .io import data_dir, load_person, load_events, qa
from .features import minute_features
from .detectors import acute_and_rule_alerts, fall_alerts
from .fusion import incidents
from .evaluate import score_person, write_report, timeline
from .detectors import personal_deviations
from .acute_model import grouped_oof, fit_full_model, predict_full, model_alerts


def process(person: str, root: Path):
    raw = load_person(person, root)
    minute = minute_features(raw)
    scored = acute_and_rule_alerts(minute)
    rows = scored[["minute", "tier", "source", "reason"]].copy()
    rows["alert_ts"] = rows.minute
    fall = pd.DataFrame(fall_alerts(raw))
    if not fall.empty:
        rows = pd.concat([rows, fall[["minute", "tier", "source", "reason", "alert_ts"]]], ignore_index=True)
    return raw, minute, rows


def cmd_qa(args):
    result = qa(args.data)
    print(result.to_string(index=False))
    if not result.row_count_ok.all() or not result.spacing_500ms.all():
        raise SystemExit("Dataset QA failed; see values above")
    print(f"\nEvents: {len(load_events(args.data))}")


def cmd_replay(args):
    root = data_dir(args.data)
    raw, minute, alerts = process(args.person, root)
    falls = fall_alerts(raw)
    if args.day:
        start = pd.Timestamp("2026-10-09") + pd.Timedelta(days=args.day-1)
        end = start + pd.Timedelta(days=1)
        alerts = alerts[(pd.to_datetime(alerts.minute) >= start) & (pd.to_datetime(alerts.minute) < end)]
        falls = [r for r in falls if start <= pd.Timestamp(r["minute"]) < end]
    inc = incidents(alerts, args.person)
    for r in inc.to_dict("records"):
        print(json.dumps({k: (v.isoformat() if isinstance(v, pd.Timestamp) else v) for k,v in r.items()}, ensure_ascii=False))
    print(f"Replay complete: {args.person}; {len(inc)} merged synthetic alert incident(s).")


def cmd_evaluate(args):
    root = data_dir(args.data)
    outdir = Path(args.out) if args.out else Path(__file__).resolve().parents[1] / "reports"
    outdir.mkdir(parents=True, exist_ok=True)
    events = load_events(root)
    all_events, all_incidents, daily_scores = [], [], []
    minutes_by_person, rules_by_person = {}, {}
    for person in ["E1", "E2", "E3", "E4", "E5"]:
        print(f"Processing {person}…", flush=True)
        raw, minute, alerts = process(person, root)
        minutes_by_person[person] = minute
        rules_by_person[person] = alerts
        dev = personal_deviations(minute)
        # Transparent non-clinical composite of four available trend signals.
        adverse = (dev.hr_bpm_z.clip(lower=0, upper=3) / 3 * .35 +
                   (-dev.spo2_pct_z).clip(lower=0, upper=3) / 3 * .30 +
                   dev.skin_temp_c_z.clip(lower=0, upper=3) / 3 * .20 +
                   dev.sbp_mmhg_z.clip(lower=0, upper=3) / 3 * .15)
        dev["daily_score"] = (100 * (1 - adverse)).clip(0, 100)
        for day, g in dev.groupby("day_internal"):
            daily_scores.append({"person_id": person, "day": int(day), "score": float(g.daily_score.median())})
    # Original data: day-grouped out-of-fold M3. Robustness set: train on original and apply without retuning.
    if root.resolve() != data_dir(None).resolve():
        train_root = data_dir(None)
        train_events = load_events(train_root)
        train_frames = {person: minute_features(load_person(person, train_root)) for person in minutes_by_person}
        _, thresholds, _ = grouped_oof(train_frames, train_events)
        model, _ = fit_full_model(train_frames, train_events)
        probabilities = {person: predict_full(model, minutes_by_person[person]) for person in minutes_by_person}
        model_protocol = "M3 trained on original synthetic set; thresholds selected from original grouped OOF predictions"
    else:
        probabilities, thresholds, labels = grouped_oof(minutes_by_person, events)
        model_protocol = "M3 grouped out-of-fold by dataset day; thresholds derived from OOF positive-window scores"
        pred_rows = []
        for person, probs in probabilities.items():
            target = labels[person]
            for i, (minute, prob) in enumerate(zip(minutes_by_person[person].minute, probs)):
                pred_rows.append({"person_id": person, "minute": minute, "target_window": int(target[i]), "oof_probability": prob})
        pd.DataFrame(pred_rows).to_csv(outdir / "m3_oof_scores.csv", index=False)
    (outdir / "m3_thresholds.json").write_text(json.dumps({**thresholds, "protocol": model_protocol}, indent=2), encoding="utf-8")
    if root.resolve() == data_dir(None).resolve():
        trained_model, feature_names = fit_full_model(minutes_by_person, events)
        model_dir = Path(__file__).resolve().parents[1] / "models"
        model_dir.mkdir(parents=True, exist_ok=True)
        joblib.dump({"model": trained_model, "feature_names": feature_names,
                     "thresholds": thresholds, "training_data": "elder_vitals_14day synthetic seed 2026",
                     "policy": "yellow = min(0.60, OOF q02) 8-of-12 minutes; orange = OOF q02 7-of-8 minutes"},
                    model_dir / "m3_lightgbm.joblib")

    all_events, all_incidents = [], []
    ablation_alerts = {"Population thresholds": [], "Personal-deviation layer": [], "Acute-pattern rules": [],
                       "M3 LightGBM": [], "Drift only": [], "Full fusion": []}
    for person, minute in minutes_by_person.items():
        rules = rules_by_person[person]
        m3 = model_alerts(minute, probabilities[person], thresholds)
        combined = pd.concat([rules, m3], ignore_index=True)
        scored, inc = score_person(person, combined, root)
        all_events.extend(scored); all_incidents.append(inc)
        ablation_alerts["Personal-deviation layer"].append(rules[rules.source.eq("personal_deviation")].copy())
        ablation_alerts["Acute-pattern rules"].append(rules[rules.source.eq("acute_pattern")].copy())
        ablation_alerts["M3 LightGBM"].append(m3)
        ablation_alerts["Drift only"].append(rules[rules.source.eq("drift")].copy())
        ablation_alerts["Full fusion"].append(combined)
        pop = minute[(minute.worn_fraction >= .5) & ((minute.hr_bpm_max >= 131) | (minute.spo2_pct_min <= 91) | (minute.sbp_mmhg_mean >= 180))].copy()
        pop_alerts = pd.DataFrame({"minute": pop.minute, "tier": "Orange", "source": "population_threshold", "reason": "Fixed population threshold"})
        pop_alerts.loc[pop.spo2_pct_min < 80, "tier"] = "Red"
        pop_alerts["alert_ts"] = pop_alerts.minute
        ablation_alerts["Population thresholds"].append(pop_alerts)
        timeline(person, minute, inc, events, outdir)
    ablation_rows = []
    for config, per_person in ablation_alerts.items():
        rows = []; incident_sets = []
        for person, a in zip(["E1", "E2", "E3", "E4", "E5"], per_person):
            scored, ix = score_person(person, a, root); rows.extend(scored); incident_sets.append(ix)
        hits, total = sum(int(r["detected"]) for r in rows), len(rows)
        false_count = 0
        for ix in incident_sets:
            for row in ix.itertuples(index=False):
                pe = events[(events.person_id == row.person_id) & events.event.isin({"fall_and_lying_still", "af_like_episode", "hypertensive_surge", "hypoglycaemia_like_episode", "exertional_desaturation", "nocturnal_desaturation", "viral_illness_like", "copd_exacerbation_like", "watch_off_wrist:unworn"})]
                ts = pd.Timestamp(row.start_ts)
                if not ((pe.start <= ts + pd.Timedelta(minutes=10)) & (pe.end >= ts - pd.Timedelta(minutes=10))).any() and row.tier in ("Orange", "Red"):
                    false_count += 1
        ablation_rows.append({"configuration": config, "event_hits": hits, "event_total": total,
                              "event_recall": hits/total if total else 0,
                              "false_orange_plus_per_person_day": false_count/70,
                              "E3_alerts_per_day": len(incident_sets[2])/14,
                              "E4_alerts_per_day": len(incident_sets[3])/14})
    write_report(all_events, all_incidents, ablation_rows, root, outdir)
    score_frame = pd.DataFrame(daily_scores)
    score_frame.to_csv(outdir / "daily_health_score.csv", index=False)
    fig, ax = plt.subplots(figsize=(9, 4))
    for person, g in score_frame.groupby("person_id"):
        ax.plot(g.day, g.score, marker=".", label=person)
    ax.set(xlabel="Dataset day", ylabel="Prototype score (0–100)", title="Synthetic daily trend score — not clinically validated", ylim=(0, 100))
    ax.grid(alpha=.2); ax.legend(ncol=5); fig.tight_layout(); fig.savefig(outdir / "daily_health_score.png", dpi=140)
    plt.close(fig)
    if root.resolve() == data_dir(None).resolve():
        with (outdir / "metrics.md").open("a", encoding="utf-8") as report:
            tuning_metrics = outdir / "robustness_R" / "event_metrics.csv"
            if tuning_metrics.exists():
                tuning = pd.read_csv(tuning_metrics)
                report.write("\n## Synthetic tuning set R\n\n")
                report.write(f"Events detected: {int(tuning.detected.sum())}/{len(tuning)} ({tuning.detected.mean():.1%}). R informed alert-policy tuning, so treat these results as tuning performance, not independent validation. See `robustness_R/metrics.md`.\n")
            heldout_metrics = outdir / "robustness_V" / "event_metrics.csv"
            if heldout_metrics.exists():
                heldout = pd.read_csv(heldout_metrics)
                report.write("\n## Untouched synthetic seed V\n\n")
                report.write(f"Events detected: {int(heldout.detected.sum())}/{len(heldout)} ({heldout.detected.mean():.1%}). The alert policy was frozen before V was generated; this is a synthetic held-out check, not clinical validation. See `robustness_V/metrics.md`.\n")
    print(f"Wrote metrics, event table, alerts and timelines to {outdir}")


def main():
    p = argparse.ArgumentParser(description="Synthetic elder wearable alerting prototype")
    p.add_argument("--data", help="Dataset directory (default: adjacent elder_vitals_14day)")
    sub = p.add_subparsers(dest="command", required=True)
    q = sub.add_parser("qa"); q.set_defaults(func=cmd_qa)
    r = sub.add_parser("replay"); r.add_argument("--person", required=True, choices=["E1","E2","E3","E4","E5"]); r.add_argument("--day", type=int); r.set_defaults(func=cmd_replay)
    e = sub.add_parser("evaluate"); e.add_argument("--out"); e.set_defaults(func=cmd_evaluate)
    args = p.parse_args(); args.func(args)


if __name__ == "__main__": main()
