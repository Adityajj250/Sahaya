"""Local presentation dashboard for the synthetic elder wearable replay."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import pandas as pd

from .features import minute_features
from .io import data_dir, load_person

PROJECT = Path(__file__).resolve().parents[1]
WEB = PROJECT / "web"
REPORTS = PROJECT / "reports"
ASSET_DIR = PROJECT / "deployment_data" if os.environ.get("VERCEL") else REPORTS
FEED_FILE = ASSET_DIR / "dashboard_vitals.csv"
DB_FILE = REPORTS / "dashboard_demo.sqlite"
PEOPLE = {
    "E1": {"name": "Maya Chen", "age": 72, "conditions": ["Type 2 diabetes", "Hypertension"], "medications": ["Metformin · example entry", "Losartan · example entry"], "symptoms": ["Dizziness", "Low energy"], "baseline": "HR 76 bpm · SpO₂ 96.5% · BP 138/84", "monitoring_focus": "A dizziness-like episode with a heart-rate rise and systolic pressure drop is highlighted for staff review.", "story": "The profile includes diabetes and hypertension. In this training record, dizziness is paired with a changing heart-rate and blood-pressure pattern.", "possible_context": "A dizziness episode can have many causes. This record shows a personal heart-rate and blood-pressure shift; wearable readings alone cannot confirm low glucose or explain why it occurred.", "client_phone": "+1 (202) 555-0101", "family_name": "Riya Chen · daughter", "family_phone": "+1 (202) 555-0102", "care_site": "Northstar Care Centre · directory example", "care_phone": "+1 (202) 555-0151", "history_examples": [{"date":"2026-10-02 09:20","summary":"Dizziness with lower-than-usual blood pressure","tier":"Yellow","outcome":"Family check-in completed; symptoms settled in the example record."},{"date":"2026-10-05 14:10","summary":"Brief light-headed episode","tier":"Yellow","outcome":"Wellbeing call logged; no further change noted in the example record."}]},
    "E2": {"name": "Arthur Reed", "age": 68, "conditions": ["No chronic condition listed"], "medications": ["No medication listed"], "symptoms": ["Fatigue during illness-like phase"], "baseline": "HR 66 bpm · SpO₂ 97.5% · BP 122/77", "monitoring_focus": "The illness-like phase is shown through changes in resting heart rate, temperature and oxygen relative to baseline.", "possible_context": "A gradual resting heart-rate, temperature or oxygen change may have several explanations, including an illness, activity recovery or sensor variation. This record cannot determine the cause.", "story": "The example record has no chronic condition listed. A gradual resting-pattern shift is used to demonstrate trend review.", "client_phone": "+1 (202) 555-0103", "family_name": "Nina Reed · daughter", "family_phone": "+1 (202) 555-0104", "care_site": "Northstar Care Centre · directory example", "care_phone": "+1 (202) 555-0151", "history_examples": [{"date":"2026-10-03 08:30","summary":"Resting heart-rate trend above baseline","tier":"Yellow","outcome":"Wellbeing call completed; record closed after follow-up."},{"date":"2026-10-06 19:05","summary":"Fatigue and temperature trend review","tier":"Yellow","outcome":"Home check requested; no escalation in the example record."}]},
    "E3": {"name": "Leena Kapoor", "age": 79, "conditions": ["Hypertension"], "medications": ["Amlodipine · example entry", "Lisinopril · example entry"], "symptoms": ["Headache during pressure surges"], "baseline": "HR 80 bpm · SpO₂ 96% · BP 152/92", "monitoring_focus": "Sustained blood-pressure changes are compared with this profile’s higher baseline.", "possible_context": "The report reflects a sustained rise from this profile’s usual pressure. Activity, stress, symptoms, measurement variation and other factors can affect a reading; the alert does not establish a cause.", "story": "The profile includes hypertension and a higher usual blood-pressure range. Sustained changes from the personal baseline are highlighted.", "client_phone": "+1 (202) 555-0105", "family_name": "Arjun Kapoor · son", "family_phone": "+1 (202) 555-0106", "care_site": "Northstar Care Centre · directory example", "care_phone": "+1 (202) 555-0151", "history_examples": [{"date":"2026-10-01 16:40","summary":"Sustained pressure above personal baseline","tier":"Yellow","outcome":"Nurse review arranged; follow-up reading recorded."},{"date":"2026-10-06 17:15","summary":"Evening pressure rise with headache reported","tier":"Red","outcome":"Urgent review initiated in the example record; status later closed."}]},
    "E4": {"name": "Samuel Brooks", "age": 75, "conditions": ["COPD profile"], "medications": ["Inhaler · example entry", "Tiotropium · example entry"], "symptoms": ["Breathlessness", "Night-time oxygen dips"], "baseline": "HR 82 bpm · SpO₂ 93.5% · BP 132/80", "monitoring_focus": "Night-time and activity-related oxygen changes are highlighted against this profile’s lower baseline.", "possible_context": "Oxygen changes may relate to activity, sleep, respiratory symptoms or sensor fit. The pattern is for staff review and does not identify the underlying cause.", "story": "The profile includes COPD and a lower usual oxygen reading. Overnight and activity-related changes are highlighted for staff review.", "client_phone": "+1 (202) 555-0107", "family_name": "Helen Brooks · spouse", "family_phone": "+1 (202) 555-0108", "care_site": "Northstar Care Centre · directory example", "care_phone": "+1 (202) 555-0151", "history_examples": [{"date":"2026-10-02 02:15","summary":"Night-time oxygen change from usual pattern","tier":"Yellow","outcome":"Morning wellbeing call documented in the example record."},{"date":"2026-10-06 11:25","summary":"Breathlessness and oxygen trend during activity","tier":"Red","outcome":"Home assessment requested; later marked resolved in the example record."}]},
    "E5": {"name": "Owen Patel", "age": 70, "conditions": ["AF-like episodes in training record"], "medications": ["No medication listed"], "symptoms": ["Palpitations", "Fall events in record"], "baseline": "HR 72 bpm · SpO₂ 96.8% · BP 134/82", "monitoring_focus": "Irregular-rate patterns and an impact followed by stillness are highlighted for staff review.", "possible_context": "Impact followed by stillness may indicate a fall, but a device impact or removal can look similar. A person should verify the client’s status.", "story": "The profile includes intermittent irregular-rate episodes and prior falls in the training record. An impact followed by stillness is routed to the highest alert tier.", "client_phone": "+1 (202) 555-0109", "family_name": "Dev Patel · son", "family_phone": "+1 (202) 555-0110", "care_site": "Northstar Care Centre · directory example", "care_phone": "+1 (202) 555-0151", "history_examples": [{"date":"2026-10-03 13:20","summary":"Palpitations and irregular-rate pattern","tier":"Yellow","outcome":"Family contacted; check-in completed in the example record."},{"date":"2026-10-07 19:40","summary":"Possible fall pattern followed by stillness","tier":"Red","outcome":"In-person wellbeing check arranged; case later closed in the example record."}]},
}
LOCK = threading.RLock()
STATE = {"index": 0, "speed": 3600, "fraction": 0.0, "paused": False, "last_tick": time.monotonic(), "active": {}, "triggered": set(), "started": False}
FEED: pd.DataFrame | None = None
ALERTS: list[dict] = []
ALERTS_AT: dict[int, list[dict]] = {}
TIME_AXIS: list[pd.Timestamp] = []
TOTAL_MINUTES = 0


def _db():
    con = sqlite3.connect(DB_FILE)
    con.execute("CREATE TABLE IF NOT EXISTS snapshots (minute TEXT NOT NULL, person_id TEXT NOT NULL, hr REAL, spo2 REAL, sbp REAL, dbp REAL, temp REAL, motion REAL, PRIMARY KEY(minute, person_id))")
    con.execute("CREATE TABLE IF NOT EXISTS workflow (incident_id TEXT PRIMARY KEY, status TEXT NOT NULL, updated TEXT NOT NULL, note TEXT NOT NULL DEFAULT '')")
    con.execute("CREATE TABLE IF NOT EXISTS workflow_log (entry_id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id TEXT NOT NULL, status TEXT NOT NULL, updated TEXT NOT NULL)")
    return con


def _load_feed():
    global FEED, ALERTS, ALERTS_AT, TIME_AXIS, TOTAL_MINUTES
    if not os.environ.get("VERCEL"):
        REPORTS.mkdir(exist_ok=True)
    if FEED_FILE.exists():
        FEED = pd.read_csv(FEED_FILE, parse_dates=["minute"])
    else:
        parts = []
        root = data_dir()
        for person in PEOPLE:
            raw = load_person(person, root)
            mins = minute_features(raw)
            keep = mins[["minute", "hr_bpm_mean", "spo2_pct_mean", "sbp_mmhg_mean", "dbp_mmhg_mean", "skin_temp_c_mean", "motion_g_mean"]].copy()
            keep.insert(1, "person_id", person)
            keep.columns = ["minute", "person_id", "hr", "spo2", "sbp", "dbp", "temp", "motion"]
            parts.append(keep)
            del raw, mins
        FEED = pd.concat(parts, ignore_index=True)
        FEED.to_csv(FEED_FILE, index=False)
    FEED["minute"] = pd.to_datetime(FEED.minute)
    FEED = FEED.sort_values(["minute", "person_id"]).reset_index(drop=True)
    TIME_AXIS = [pd.Timestamp(ts) for ts in FEED.minute.drop_duplicates()]
    TOTAL_MINUTES = len(TIME_AXIS)
    id_to_index = {ts: i for i, ts in enumerate(TIME_AXIS)}
    alert_file = ASSET_DIR / "alerts.jsonl"
    if alert_file.exists():
        for line in alert_file.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                row["_index"] = id_to_index.get(pd.Timestamp(row["start_ts"]).floor("min"), 0)
                # The dashboard has two urgency zones: Orange model/rule escalations are shown as Red.
                row["display_tier"] = "Red" if row.get("tier") in {"Red", "Orange"} else "Yellow"
                row["summary"] = _summary(row)
                ALERTS.append(row)
                ALERTS_AT.setdefault(row["_index"], []).append(row)
            except (ValueError, KeyError, TypeError):
                continue
    ALERTS.sort(key=lambda a: (a["_index"], a["person_id"]))


def _summary(alert):
    source = alert.get("sources", "")
    text = alert.get("reason_text", "")
    if "fall" in source.lower() or "fall" in text.lower():
        return "Possible fall detected · impact followed by sustained stillness"
    if "spo2" in text.lower() or "oxygen" in text.lower() or "desaturation" in text.lower():
        return "Oxygen trend moved outside this profile’s recent pattern"
    if "pressure" in text.lower() or "bp" in source.lower():
        return "Blood pressure pattern moved outside this profile’s recent pattern"
    if "heart" in text.lower() or "af" in source.lower():
        return "Heart-rate pattern moved outside this profile’s recent pattern"
    return "Multiple signals changed from this profile’s recent pattern"


def _category(alert):
    source = alert.get("sources", "").lower()
    summary = alert.get("summary", "").lower()
    if "fall" in source or "fall" in summary: return "fall"
    if "oxygen" in summary or "spo2" in summary or "desaturation" in source: return "oxygen"
    if "pressure" in summary or "hypertens" in source: return "pressure"
    if "heart" in summary or "af" in source: return "rhythm"
    return "general"


def _decorate_alert(alert):
    profile = PEOPLE[alert["person_id"]]
    category = _category(alert)
    previous = [a for a in ALERTS if a["person_id"] == alert["person_id"] and a["_index"] < alert["_index"] and _category(a) == category]
    similar = list(profile.get("history_examples", [])) + [{"date": a["start_ts"], "summary": a["summary"], "tier": a["display_tier"], "outcome": "Example outcome: staff check-in completed and case marked resolved in the training record."} for a in previous[-3:]]
    red = alert["display_tier"] == "Red"
    if red:
        actions = ["Confirm the client’s immediate status using the organisation’s on-call process.", "Request help at home or an in-person check if the client cannot be reached.", "Contact the hospital through the organisation-approved pathway; follow local emergency procedures if there may be immediate danger."]
    else:
        actions = ["Arrange a wellbeing call and ask about current symptoms.", "Ask staff to review the latest readings and repeat the measurement if appropriate.", "Consider a home check if the change persists or the client feels worse."]
    if category == "fall":
        actions = ["Try the client contact and request an immediate in-person wellbeing check.", "If the client is injured or cannot be reached, use the organisation’s urgent escalation procedure.", "Record who accepted the response and when."]
    return {**alert, "client_name": profile["name"], "profile_story": profile["story"],
            "why_flagged": alert.get("reason_text") or alert["summary"], "similar_cases": similar[-4:],
            "similar_case_count": len(profile.get("history_examples", [])) + len(previous), "actions": actions,
            "contacts": [{"label": "Client", "name": profile["name"], "number": profile["client_phone"]},
                         {"label": "Family contact", "name": profile["family_name"], "number": profile["family_phone"]},
                         {"label": "Hospital / care centre", "name": profile["care_site"], "number": profile["care_phone"]}]}


def _snapshot_rows(index):
    assert FEED is not None
    start = index * len(PEOPLE)
    rows = FEED.iloc[start:start + len(PEOPLE)]
    ts = rows.minute.iloc[0]
    return ts, {r.person_id: r for r in rows.itertuples(index=False)}


def _store_snapshot(index):
    ts, rows = _snapshot_rows(index)
    con = _db()
    con.executemany("INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?,?,?,?)", [
        (ts.isoformat(), p, _num(r.hr), _num(r.spo2), _num(r.sbp), _num(r.dbp), _num(r.temp), _num(r.motion)) for p, r in rows.items()
    ])
    con.commit(); con.close()


def _tick_locked():
    now = time.monotonic()
    if not STATE["started"]:
        STATE["last_tick"] = now
        return
    elapsed = max(0, now - STATE["last_tick"])
    STATE["last_tick"] = now
    if STATE["paused"] or FEED is None:
        return
    # Playback speed follows normal clock speed: 60 simulated minutes per real hour at 1×.
    accumulated = elapsed * STATE["speed"] / 60 + STATE["fraction"]
    total = int(accumulated)
    STATE["fraction"] = accumulated - total
    if total <= 0:
        return
    last = TOTAL_MINUTES - 1
    target = min(last, STATE["index"] + total)
    con = _db()
    for idx in range(STATE["index"] + 1, target + 1):
        ts, rows = _snapshot_rows(idx)
        con.executemany("INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?,?,?,?)", [
            (ts.isoformat(), p, _num(r.hr), _num(r.spo2), _num(r.sbp), _num(r.dbp), _num(r.temp), _num(r.motion)) for p, r in rows.items()
        ])
        new_alerts = [a for a in ALERTS_AT.get(idx, []) if a["incident_id"] not in STATE["triggered"]]
        for alert in new_alerts:
            STATE["triggered"].add(alert["incident_id"])
            STATE["active"][alert["incident_id"]] = {**alert, "status": "New"}
        STATE["index"] = idx
        if new_alerts:
            STATE["paused"] = True
            STATE["fraction"] = 0.0
            STATE["last_tick"] = time.monotonic()
            break
    con.commit()
    con.close()
    if STATE["index"] >= last:
        STATE["paused"] = True


def _num(v):
    return None if pd.isna(v) else round(float(v), 2)


def _vitals(index):
    ts, rows = _snapshot_rows(index)
    result = {}
    for pid in PEOPLE:
        r = rows.get(pid)
        result[pid] = {"hr": _num(r.hr) if r else None, "spo2": _num(r.spo2) if r else None,
                       "sbp": _num(r.sbp) if r else None, "dbp": _num(r.dbp) if r else None,
                       "temp": _num(r.temp) if r else None, "motion": _num(r.motion) if r else None}
    return ts, result


def _state():
    _tick_locked()
    ts, vitals = _vitals(STATE["index"])
    alert_by_person = {}
    for alert in STATE["active"].values():
        alert_by_person.setdefault(alert["person_id"], []).append(alert)
    clients = []
    for pid, profile in PEOPLE.items():
        clients.append({"id": pid, **profile, "vitals": vitals[pid], "alerts": alert_by_person.get(pid, [])})
    current_active = [_decorate_alert(a) for a in STATE["active"].values()]
    return {"now": ts.isoformat(), "speed": STATE["speed"], "paused": STATE["paused"], "started": STATE["started"],
            "complete": STATE["index"] >= TOTAL_MINUTES - 1, "index": STATE["index"], "total": TOTAL_MINUTES,
            "clients": clients, "active_alerts": current_active,
            "yellow_count": sum(a["display_tier"] == "Yellow" for a in current_active),
            "red_count": sum(a["display_tier"] == "Red" for a in current_active)}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def _send(self, body, code=200, mime="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else (json.dumps(body, ensure_ascii=False, default=str).encode("utf-8") if mime.startswith("application/json") else body.encode("utf-8"))
        self.send_response(code); self.send_header("Content-Type", mime); self.send_header("Content-Length", str(len(data))); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/" or path == "/index.html":
            return self._send((WEB / "index.html").read_bytes(), mime="text/html; charset=utf-8")
        if path in {"/styles.css", "/app.js"}:
            return self._send((WEB / path[1:]).read_bytes(), mime="text/css; charset=utf-8" if path.endswith("css") else "text/javascript; charset=utf-8")
        with LOCK:
            if path == "/api/state": return self._send(_state())
            if path == "/api/profile":
                pid = parse_qs(urlparse(self.path).query).get("id", [""])[0]
                if pid not in PEOPLE: return self._send({"error": "Unknown profile"}, 404)
                ts, vitals = _vitals(STATE["index"])
                con = _db()
                history = con.execute("SELECT minute,hr,spo2,sbp,dbp FROM snapshots WHERE person_id=? ORDER BY minute DESC LIMIT 180", (pid,)).fetchall()
                actions = con.execute("SELECT incident_id,status,updated FROM workflow_log WHERE incident_id IN (SELECT incident_id FROM workflow WHERE incident_id LIKE ?) ORDER BY entry_id DESC LIMIT 20", (f"{pid}-%",)).fetchall()
                con.close()
                history.reverse()
                return self._send({"id": pid, **PEOPLE[pid], "vitals": vitals[pid], "now": ts.isoformat(), "history": [{"minute": r[0], "hr": r[1], "spo2": r[2], "sbp": r[3], "dbp": r[4]} for r in history], "workflow_history": [{"incident_id": r[0], "status": r[1], "updated": r[2]} for r in actions], "alerts": [_decorate_alert(a) for a in ALERTS if a["person_id"] == pid and a["_index"] <= STATE["index"]]})
        return self._send({"error": "Not found"}, 404)

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
        with LOCK:
            if self.path == "/api/control":
                action = data.get("action")
                if action == "start": STATE["started"] = True; STATE["paused"] = False; _store_snapshot(STATE["index"])
                elif action == "pause": STATE["paused"] = True
                elif action == "resume" and not STATE["active"]: STATE["paused"] = False; STATE["started"] = True
                elif action == "reset":
                    STATE.update(index=0, speed=3600, fraction=0.0, paused=False, last_tick=time.monotonic(), active={}, triggered=set(), started=False)
                    con = _db(); con.execute("DELETE FROM snapshots"); con.execute("DELETE FROM workflow"); con.execute("DELETE FROM workflow_log"); con.commit(); con.close()
                STATE["last_tick"] = time.monotonic()
                return self._send(_state())
            if self.path == "/api/speed":
                STATE["speed"] = int(data.get("speed", 3600)); STATE["last_tick"] = time.monotonic()
                return self._send(_state())
            if self.path == "/api/workflow":
                incident_id, action = data.get("incident_id"), data.get("action")
                alert = STATE["active"].get(incident_id)
                if alert:
                    allowed = {"New": "Action initiated", "Action initiated": "Help reached", "Help reached": "Resolved"}
                    if allowed.get(alert["status"]) == action:
                        alert["status"] = action
                        updated = datetime.now().isoformat(timespec="seconds")
                        con = _db(); con.execute("INSERT OR REPLACE INTO workflow(incident_id,status,updated,note) VALUES (?,?,?,?)", (incident_id, action, updated, action)); con.execute("INSERT INTO workflow_log(incident_id,status,updated) VALUES (?,?,?)", (incident_id, action, updated)); con.commit(); con.close()
                        if action == "Resolved": del STATE["active"][incident_id]
                        if not STATE["active"]:
                            STATE["paused"] = False; STATE["started"] = True; STATE["last_tick"] = time.monotonic()
                return self._send(_state())
        return self._send({"error": "Not found"}, 404)


def main():
    _load_feed()
    print("Synthetic presentation dashboard: http://127.0.0.1:8765")
    print("Building / loading the minute-by-minute synthetic replay may take a few minutes on first launch.")
    ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()


if __name__ == "__main__": main()
