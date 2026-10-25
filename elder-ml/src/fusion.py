from __future__ import annotations

import pandas as pd

LEVEL = {"Green": 0, "Yellow": 1, "Orange": 2, "Red": 3}


def incidents(alert_rows: pd.DataFrame, person: str) -> pd.DataFrame:
    a = alert_rows[alert_rows.tier.ne("Green")].sort_values("minute")
    if a.empty:
        return pd.DataFrame(columns=["person_id", "start_ts", "tier_reached_ts", "end_ts", "tier", "sources", "reason_text"])
    groups, current, last = [], [], None
    for row in a.to_dict("records"):
        ts = pd.Timestamp(row["minute"])
        if last is not None and (ts - last).total_seconds() > 1800:
            groups.append(current); current = []
        current.append(row); last = ts
    if current: groups.append(current)
    result = []
    for n, rows in enumerate(groups, 1):
        best = max(rows, key=lambda r: LEVEL[r["tier"]])
        reasons = list(dict.fromkeys(r["reason"] for r in rows if r.get("reason")))
        result.append({"incident_id": f"{person}-{n:04d}", "person_id": person,
                       "start_ts": min(r.get("alert_ts", r["minute"]) for r in rows),
                       "tier_reached_ts": best.get("alert_ts", best["minute"]),
                       "end_ts": max(r.get("alert_ts", r["minute"]) for r in rows),
                       "tier": best["tier"], "sources": ",".join(dict.fromkeys(r["source"] for r in rows if r.get("source"))),
                       "reason_text": "; ".join(reasons[:3]), "suggested_action": "Human review of simulated alert"})
    return pd.DataFrame(result)
