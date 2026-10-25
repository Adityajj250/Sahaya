"""Persistent Vercel-facing dashboard state backed by PostgreSQL.

The existing replay and profile content remains a read-only packaged artifact;
all mutable clock, workflow, inbound-message, report, and audio references live
in managed storage instead of a function's local filesystem or memory.
"""
from __future__ import annotations

import json
import hashlib
import os
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import pandas as pd
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from . import dashboard as demo

PROJECT = Path(__file__).resolve().parents[1]
_DATABASE_READY = False
_DATABASE_INIT_LOCK = threading.Lock()
SCHEMA = """
CREATE TABLE IF NOT EXISTS care_runtime (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    payload JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS care_workflow_log (
    entry_id BIGSERIAL PRIMARY KEY,
    incident_id TEXT NOT NULL,
    status TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS inbound_messages (
    message_id TEXT PRIMARY KEY,
    sender TEXT NOT NULL,
    message_type TEXT NOT NULL,
    mime_type TEXT,
    media_id TEXT,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    processing_status TEXT NOT NULL DEFAULT 'received',
    raw_message JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS voice_reports (
    incident_id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL UNIQUE REFERENCES inbound_messages(message_id),
    sender TEXT NOT NULL,
    person_id TEXT,
    urgency TEXT NOT NULL CHECK (urgency IN ('Yellow', 'Red')),
    report JSONB NOT NULL,
    audio_path TEXT,
    status TEXT NOT NULL DEFAULT 'New',
    notification_sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def database_url() -> str:
    value = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not value:
        raise RuntimeError("Connect a PostgreSQL database and set DATABASE_URL")
    return value


@contextmanager
def connection() -> Iterator[psycopg.Connection]:
    with psycopg.connect(database_url(), connect_timeout=10, row_factory=dict_row) as con:
        yield con


def ensure_ready() -> None:
    # Vercel packages only this prepared minute-level feed and alert replay.
    if demo.FEED is None:
        feed_path = demo.FEED_FILE
        if not feed_path.exists():
            raise RuntimeError("The prepared dashboard replay file is missing")
        demo._load_feed()
    ensure_database()


def ensure_database() -> None:
    global _DATABASE_READY
    if _DATABASE_READY:
        return
    with _DATABASE_INIT_LOCK:
        if _DATABASE_READY:
            return
        with connection() as con:
            for statement in SCHEMA.split(";"):
                if statement.strip():
                    con.execute(statement)
            con.execute("ALTER TABLE voice_reports ADD COLUMN IF NOT EXISTS notification_sent_at TIMESTAMPTZ")
            con.execute(
                "INSERT INTO care_runtime(singleton,payload) VALUES (TRUE,%s) ON CONFLICT(singleton) DO NOTHING",
                (Jsonb({"index": 0, "speed": 3600, "fraction": 0.0, "paused": False,
                             "started": False, "active": {}, "triggered": [],
                             "updated_at": datetime.now(timezone.utc).isoformat()}),),
            )
        _DATABASE_READY = True


def lock_runtime(con: psycopg.Connection) -> dict:
    row = con.execute("SELECT payload FROM care_runtime WHERE singleton=TRUE FOR UPDATE").fetchone()
    if row is None:
        raise RuntimeError("Dashboard state has not been initialized")
    return row["payload"]


def save_runtime(con: psycopg.Connection, payload: dict) -> None:
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    con.execute("UPDATE care_runtime SET payload=%s, updated_at=now() WHERE singleton=TRUE", (Jsonb(payload),))


def tick(payload: dict) -> None:
    now = datetime.now(timezone.utc)
    try:
        previous = datetime.fromisoformat(payload["updated_at"])
        if previous.tzinfo is None:
            previous = previous.replace(tzinfo=timezone.utc)
    except (KeyError, ValueError, TypeError):
        previous = now
    elapsed = max(0.0, (now - previous).total_seconds())
    if payload["started"] and not payload["paused"] and demo.FEED is not None:
        accumulated = elapsed * int(payload["speed"]) / 60 + float(payload.get("fraction", 0))
        count = int(accumulated)
        payload["fraction"] = accumulated - count
        target = min(demo.TOTAL_MINUTES - 1, int(payload["index"]) + count)
        triggered = set(payload.get("triggered", []))
        for index in range(int(payload["index"]) + 1, target + 1):
            new_alerts = [a for a in demo.ALERTS_AT.get(index, []) if a["incident_id"] not in triggered]
            for alert in new_alerts:
                triggered.add(alert["incident_id"])
                payload.setdefault("active", {})[alert["incident_id"]] = {**alert, "status": "New"}
            payload["index"] = index
            if new_alerts:
                payload["paused"] = True
                payload["fraction"] = 0.0
                break
        payload["triggered"] = sorted(triggered)
    payload["updated_at"] = now.isoformat()


def voice_alert(row: dict) -> dict:
    report = row["report"] or {}
    person_id = row["person_id"]
    profile = demo.PEOPLE.get(person_id, {})
    actions = report.get("recommended_actions") or [
        "Call the sender to confirm their current symptoms and location.",
        "Arrange an in-person check if concerns persist or the sender cannot be reached.",
        "Follow the organisation’s urgent escalation process for immediate danger.",
    ]
    contacts = [{"label": "WhatsApp sender", "name": profile.get("name", "Unmatched sender"), "number": row["sender"]}]
    if profile:
        contacts += [
            {"label": "Family contact", "name": profile["family_name"], "number": profile["family_phone"]},
            {"label": "Care centre", "name": profile["care_site"], "number": profile["care_phone"]},
        ]
    return {
        "incident_id": row["incident_id"], "person_id": person_id or "WHATSAPP",
        "client_name": profile.get("name", f"WhatsApp sender +{row['sender']}"),
        "display_tier": row["urgency"], "tier": row["urgency"], "status": row["status"],
        "start_ts": row["created_at"].isoformat(), "summary": report.get("summary", "Voice report received for staff review"),
        "reason_text": report.get("rationale", "Voice report assessed for urgency by the configured language model."),
        "why_flagged": report.get("rationale", "Staff should confirm the information directly with the client."),
        "profile_story": report.get("client_context", "Incoming WhatsApp voice report; client identity requires confirmation."),
        "possible_context": report.get("possible_context", "An audio summary cannot establish a medical cause. Confirm details directly."),
        "transcript": report.get("transcript", ""), "language": report.get("language", ""),
        "similar_cases": [], "similar_case_count": 0,
        "actions": actions, "contacts": contacts, "audio_url": f"/api/audio?id={row['message_id']}",
        "source_label": "WhatsApp voice report", "confidence": report.get("confidence"),
    }


def active_voice_reports(con) -> list[dict]:
    rows = con.execute("SELECT * FROM voice_reports WHERE status <> 'Resolved' ORDER BY created_at DESC").fetchall()
    return [voice_alert(row) for row in rows]


def pending_voice_reports(con) -> list[dict]:
    rows = con.execute("""SELECT m.message_id,m.sender,m.received_at
        FROM inbound_messages m LEFT JOIN voice_reports r ON r.message_id=m.message_id
        WHERE m.message_type='audio' AND m.processing_status IN ('received','queued') AND r.message_id IS NULL
        ORDER BY m.received_at DESC LIMIT 25""").fetchall()
    reports = []
    for row in rows:
        person_id = sender_to_profile(row["sender"])
        profile = demo.PEOPLE.get(person_id or "", {})
        reports.append({
            "incident_id": "pending-" + hashlib.sha256(row["message_id"].encode()).hexdigest()[:20],
            "person_id": person_id or "WHATSAPP", "client_name": profile.get("name", f"WhatsApp sender +{row['sender']}"),
            "display_tier": "Red", "status": "Preparing report", "start_ts": row["received_at"].isoformat(),
            "summary": "Voice note received · urgency review in progress",
            "reason_text": "The recording is being retrieved and reviewed. Staff should confirm the sender’s status directly if there may be immediate danger.",
            "why_flagged": "An unreviewed voice report is temporarily held in the priority queue until the urgency assessment is ready.",
            "profile_story": profile.get("story", "Incoming WhatsApp voice note. Confirm the sender’s identity before using profile-specific context."),
            "possible_context": "Automated review is still in progress; no conclusion about the reported symptoms has been reached.",
            "similar_cases": [], "similar_case_count": 0,
            "actions": ["Call the sender if you are concerned about their immediate safety.", "Wait for the transcript and urgency summary to appear; listen to the original message in WhatsApp if needed."],
            "contacts": [{"label": "WhatsApp sender", "name": profile.get("name", "Unmatched sender"), "number": row["sender"]}],
            "source_label": "WhatsApp voice report", "processing": True,
        })
    return reports


def _num(value):
    return None if pd.isna(value) else round(float(value), 2)


def render_state(con, payload: dict) -> dict:
    ts, vitals = demo._vitals(int(payload["index"]))
    by_person: dict[str, list[dict]] = {}
    active_demo = list(payload.get("active", {}).values())
    for alert in active_demo:
        by_person.setdefault(alert["person_id"], []).append(alert)
    alerts = [demo._decorate_alert(alert) for alert in active_demo]
    voice = active_voice_reports(con)
    pending = pending_voice_reports(con)
    for alert in voice:
        if alert.get("person_id") in demo.PEOPLE:
            by_person.setdefault(alert["person_id"], []).append(alert)
    alerts.extend(voice)
    alerts.extend(pending)
    clients = [{"id": pid, **profile, "vitals": vitals[pid], "alerts": by_person.get(pid, [])}
               for pid, profile in demo.PEOPLE.items()]
    if (voice or pending) and not payload["paused"]:
        payload["paused"] = True
        payload["fraction"] = 0.0
        save_runtime(con, payload)
    return {"now": ts.isoformat(), "speed": payload["speed"], "paused": payload["paused"],
            "started": payload["started"], "complete": int(payload["index"]) >= demo.TOTAL_MINUTES - 1,
            "index": payload["index"], "total": demo.TOTAL_MINUTES, "clients": clients,
            "active_alerts": alerts, "yellow_count": sum(a["display_tier"] == "Yellow" for a in alerts),
            "red_count": sum(a["display_tier"] == "Red" for a in alerts)}


def sender_to_profile(sender: str) -> str | None:
    try:
        mapping = json.loads(os.environ.get("CLIENT_WHATSAPP_MAP_JSON", "{}"))
    except json.JSONDecodeError:
        mapping = {}
    return mapping.get("".join(c for c in sender if c.isdigit()))
