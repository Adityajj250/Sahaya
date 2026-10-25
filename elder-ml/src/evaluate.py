from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import beta
import matplotlib.pyplot as plt

from .io import load_events
from .fusion import incidents

REQUIRED = {"fall_and_lying_still": "Red", "af_like_episode": "Orange", "hypertensive_surge": "Orange",
            "hypoglycaemia_like_episode": "Orange", "exertional_desaturation": "Orange",
            "nocturnal_desaturation": "Yellow", "viral_illness_like": "Yellow", "copd_exacerbation_like": "Yellow"}
LEVEL = {"Green": 0, "Yellow": 1, "Orange": 2, "Red": 3}


def score_person(person: str, alerts: pd.DataFrame, root: Path) -> tuple[list[dict], pd.DataFrame]:
    events = load_events(root)
    events = events[(events.person_id == person) & events.event.isin(REQUIRED)].copy()
    if events.empty:
        return [], incidents(alerts, person)
    inc = incidents(alerts, person)
    scored = []
    for ev in events.itertuples(index=False):
        start, end = pd.Timestamp(ev.start), pd.Timestamp(ev.end)
        required = REQUIRED[ev.event]
        win = inc[(inc.tier_reached_ts >= start - pd.Timedelta(minutes=5)) & (inc.tier_reached_ts <= end + pd.Timedelta(minutes=10))]
        win = win[win.tier.map(LEVEL).ge(LEVEL[required])]
        hit = not win.empty
        alert_ts = win.tier_reached_ts.min() if hit else pd.NaT
        scored.append({"person_id": person, "event": ev.event, "event_start": start, "event_end": end,
                       "required_tier": required, "detected": hit,
                       "delay_seconds": (alert_ts - start).total_seconds() if hit else np.nan,
                       "alert_ts": alert_ts})
    return scored, inc


def cp_interval(success: int, total: int) -> tuple[float, float]:
    if total == 0: return np.nan, np.nan
    lo = 0. if success == 0 else beta.ppf(.025, success, total-success+1)
    hi = 1. if success == total else beta.ppf(.975, success+1, total-success)
    return float(lo), float(hi)


def write_report(event_rows: list[dict], incidents_by_person: list[pd.DataFrame], ablation_rows: list[dict], root: Path, report_dir: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    ev = pd.DataFrame(event_rows)
    ev.to_csv(report_dir / "event_metrics.csv", index=False)
    inc = pd.concat(incidents_by_person, ignore_index=True) if incidents_by_person else pd.DataFrame()
    events = load_events(root)
    # A silence ticket raised while the watch really is unworn is a CORRECT alert, not a false one.
    valid_events = events[events.event.isin(REQUIRED) | events.event.eq("watch_off_wrist:unworn")]
    false_mask = []
    for row in inc.itertuples(index=False):
        person_events = valid_events[valid_events.person_id == row.person_id]
        ts = pd.Timestamp(row.start_ts)
        overlaps = ((person_events.start <= ts + pd.Timedelta(minutes=10)) &
                    (person_events.end >= ts - pd.Timedelta(minutes=10))).any()
        false_mask.append(not overlaps)
    if not inc.empty:
        inc["is_false_alert"] = false_mask
    inc.to_json(report_dir / "alerts.jsonl", orient="records", lines=True, date_format="iso")
    lines = ["# Synthetic replay metrics", "", "These metrics describe only this scripted synthetic dataset. They are not clinical evidence.", "",
             "## Event recall", "", "| Event type | Detected / total | Recall (exact 95% interval) | Median delay (s) |", "|---|---:|---:|---:|"]
    for name, grp in ev.groupby("event", sort=True):
        hits, total = int(grp.detected.sum()), len(grp); lo, hi = cp_interval(hits, total)
        recall = hits / total if total else 0
        delay = grp.loc[grp.detected, "delay_seconds"].median()
        lines.append(f"| {name} | {hits}/{total} | {recall:.1%} ({lo:.1%}–{hi:.1%}) | {delay:.0f} |")
    if not ev.empty:
        hits, total = int(ev.detected.sum()), len(ev); lo, hi = cp_interval(hits, total)
        lines += ["", f"Overall: **{hits}/{total} ({hits/total:.1%}; exact 95% CI {lo:.1%}–{hi:.1%})**."]
        ev["event_day"] = (pd.to_datetime(ev.event_start).dt.normalize() - pd.Timestamp("2026-10-09")).dt.days + 1
        lines += ["", "## Cold start vs mature replay", "", "| Replay period | Detected / total | Recall |", "|---|---:|---:|"]
        for label, mask in [("Days 1–3", ev.event_day <= 3), ("Days 4–14", ev.event_day >= 4)]:
            subset = ev[mask]
            lines.append(f"| {label} | {int(subset.detected.sum())}/{len(subset)} | {subset.detected.mean():.1%} |" if len(subset) else f"| {label} | 0/0 | n/a |")
    lines += ["", "## False alert workload", "", "False incident = outside any scored event plus 10 minutes. Watch off-wrist intervals are excluded from health-event scoring.", ""]
    if not inc.empty:
        d = inc.copy(); d["date"] = pd.to_datetime(d.start_ts).dt.date
        for tier in ["Yellow", "Orange", "Red"]:
            f = d[(d.tier == tier) & d.is_false_alert]
            lines.append(f"- {tier} false incidents: {len(f)} total; {len(f)/70:.3f} per person-day")
        lines.append(f"- False Orange-or-higher incidents per person-day: {int((d.is_false_alert & d.tier.isin(['Orange','Red'])).sum())/70:.3f}")
        lines.append(f"- False Yellow-or-higher incidents per person-day: {int(d.is_false_alert.sum())/70:.3f}")
    else:
        lines.append("No incidents were produced.")
    lines += ["", "## Notes", "", "- Output is a replay of simulated patterns; no alert is a diagnosis.",
              "- Rules, thresholds and alert policy were tuned on this scripted dataset for demonstration; the numbers above are demonstration performance, not an independent estimate of generalization.",
              "- A fresh-seed check (same generator, new random seed, M3 trained on the original data only, no retuning) is in `fresh_seed_check/`.",
              "- Fusion combines a day-fold LightGBM classifier with transparent prototype rules; neither has been clinically validated.",
              "- Confidence intervals quantify event-count uncertainty only; they do not account for generator dependence.",
              "- The daily score is a synthetic trend visualization only; it is not a validated recovery or health score.",
              "- E4's nightly desaturation dips are scripted events, so each night produces one Yellow ticket; the exacerbation phase also crosses the prototype SpO2 < 80 hard floor on some nights.",
              "- A silence ticket raised while the watch is genuinely unworn counts as a correct alert, not a false one."]
    (report_dir / "metrics.md").write_text("\n".join(lines), encoding="utf-8")
    # Compact alert-rate chart for the synthetic replay.
    if not inc.empty:
        rates = [int((inc.is_false_alert & inc.tier.eq(t)).sum()) / 70 for t in ["Yellow", "Orange", "Red"]]
        fig, ax = plt.subplots(figsize=(6, 3.5)); ax.bar(["Yellow", "Orange", "Red"], rates, color=["#d8a500", "#ef7800", "#c62828"])
        ax.set_ylabel("False incidents / person-day"); ax.set_title("Synthetic replay false-alert workload")
        ax.grid(axis="y", alpha=.25); fig.tight_layout(); fig.savefig(report_dir / "false_alert_rates.png", dpi=140); plt.close(fig)

    if ablation_rows:
        ab = pd.DataFrame(ablation_rows)
        ab.to_csv(report_dir / "ablation_metrics.csv", index=False)
        with (report_dir / "metrics.md").open("a", encoding="utf-8") as report:
            report.write("\n## Rule-layer ablation\n\n| Configuration | Event recall | False Orange+ / person-day | E3 alerts/day | E4 alerts/day |\n|---|---:|---:|---:|---:|\n")
            for r in ablation_rows:
                report.write(f"| {r['configuration']} | {r['event_hits']}/{r['event_total']} ({r['event_recall']:.1%}) | {r['false_orange_plus_per_person_day']:.3f} | {r['E3_alerts_per_day']:.2f} | {r['E4_alerts_per_day']:.2f} |\n")
        fig, axs = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
        x = np.arange(len(ab))
        axs[0].bar(x, ab.event_recall * 100, color="#3977a8")
        axs[0].set_ylabel("Event recall (%)"); axs[0].set_ylim(0, 105); axs[0].grid(axis="y", alpha=.2)
        axs[1].bar(x, ab.false_orange_plus_per_person_day, color="#ef7800")
        axs[1].set_ylabel("False Orange+ / person-day"); axs[1].grid(axis="y", alpha=.2)
        axs[1].set_xticks(x, ab.configuration, rotation=15, ha="right")
        fig.suptitle("Rule-layer ablation on the original synthetic data")
        fig.tight_layout(); fig.savefig(report_dir / "ablation.png", dpi=150); plt.close(fig)


def timeline(person: str, frame: pd.DataFrame, inc: pd.DataFrame, events: pd.DataFrame, report_dir: Path) -> None:
    fig, axs = plt.subplots(3, 1, figsize=(15, 8), sharex=True)
    t = pd.to_datetime(frame.minute)
    for ax, col, title in zip(axs, ["hr_bpm_mean", "spo2_pct_mean", "sbp_mmhg_mean"], ["Heart rate (bpm)", "SpO₂ (%)", "Systolic BP (mmHg)"]):
        ax.plot(t, frame[col], linewidth=.55)
        ax.set_ylabel(title); ax.grid(alpha=.2)
    person_events = events[(events.person_id == person) & ~events.event.str.startswith("watch_off_wrist")]
    for ev in person_events.itertuples(index=False):
        for ax in axs: ax.axvspan(pd.Timestamp(ev.start), pd.Timestamp(ev.end), color="orange", alpha=.12)
    for row in inc.itertuples(index=False):
        axs[0].axvline(pd.Timestamp(row.start_ts), color={"Yellow":"#d8a500","Orange":"#ef7800","Red":"#c62828"}.get(row.tier,"#555"), alpha=.7, linewidth=.8)
    axs[-1].set_xlabel("Timestamp (dataset local time)")
    fig.suptitle(f"{person} — synthetic signal replay and alerts")
    fig.tight_layout(); fig.savefig(report_dir / f"timeline_{person}.png", dpi=140); plt.close(fig)
