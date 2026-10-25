"""Vercel HTTP entry point for the dashboard API and Meta webhook."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlparse

from psycopg.types.json import Jsonb

from src import dashboard as demo
from src import cloud_store as store


def _token_ok(headers, body: bytes) -> bool:
    secret = os.environ.get("META_APP_SECRET", "")
    signature = headers.get("X-Hub-Signature-256", "")
    if not secret or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _publish_audio(payload: dict, message_id: str) -> None:
    from vercel.queue import send
    asyncio.run(send("whatsapp-audio", payload, idempotency_key=message_id))


def _session_value() -> str:
    expires = int(datetime.now(timezone.utc).timestamp()) + 8 * 60 * 60
    payload = f"{expires}.{secrets.token_urlsafe(24)}"
    signature = hmac.new(os.environ["SESSION_SIGNING_SECRET"].encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def _valid_session(cookie_header: str) -> bool:
    secret = os.environ.get("SESSION_SIGNING_SECRET", "")
    if not secret:
        return False
    cookies = SimpleCookie()
    try:
        cookies.load(cookie_header or "")
        value = cookies.get("care_session").value if cookies.get("care_session") else ""
        expires, nonce, signature = value.split(".", 2)
        payload = f"{expires}.{nonce}"
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return int(expires) > int(datetime.now(timezone.utc).timestamp()) and hmac.compare_digest(signature, expected)
    except (ValueError, AttributeError):
        return False


def _handle_webhook_get(handler) -> None:
    query = parse_qs(urlparse(handler.path).query)
    mode = query.get("hub.mode", [""])[0]
    token = query.get("hub.verify_token", [""])[0]
    challenge = query.get("hub.challenge", [""])[0]
    expected = os.environ.get("META_WEBHOOK_VERIFY_TOKEN", "")
    if mode == "subscribe" and expected and hmac.compare_digest(token, expected) and challenge:
        handler._send(challenge.encode(), 200, "text/plain; charset=utf-8")
    else:
        handler._send(b"Webhook verification failed", 403, "text/plain; charset=utf-8")


def _handle_webhook_post(handler, body: bytes) -> None:
    if not _token_ok(handler.headers, body):
        return handler._json({"error": "Webhook signature is missing or invalid"}, 401)
    try:
        event = json.loads(body)
    except (ValueError, TypeError):
        return handler._json({"error": "Invalid JSON payload"}, 400)

    jobs = []
    try:
        store.ensure_database()
        with store.connection() as con:
            for entry in event.get("entry", []):
                for change in entry.get("changes", []):
                    for message in change.get("value", {}).get("messages", []):
                        message_id = message.get("id")
                        sender = message.get("from")
                        kind = message.get("type", "unknown")
                        media = message.get("audio", {}) if kind == "audio" else {}
                        if not message_id or not sender:
                            continue
                        con.execute("""INSERT INTO inbound_messages
                          (message_id,sender,message_type,mime_type,media_id,raw_message)
                          VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(message_id) DO NOTHING""",
                          (message_id, sender, kind, media.get("mime_type"), media.get("id"), Jsonb(message)))
                        if kind == "audio" and media.get("id"):
                            current = con.execute("SELECT processing_status FROM inbound_messages WHERE message_id=%s", (message_id,)).fetchone()
                            if current and current["processing_status"] != "processed":
                                jobs.append({"message_id": message_id, "sender": sender,
                                             "media_id": media["id"], "mime_type": media.get("mime_type", "audio/ogg")})
            if jobs:
                runtime = con.execute("SELECT payload FROM care_runtime WHERE singleton=TRUE FOR UPDATE").fetchone()
                if runtime:
                    payload = runtime["payload"]
                    payload.update(paused=True, fraction=0.0, updated_at=datetime.now(timezone.utc).isoformat())
                    con.execute("UPDATE care_runtime SET payload=%s,updated_at=now() WHERE singleton=TRUE", (Jsonb(payload),))
        for job in jobs:
            _publish_audio(job, job["message_id"])
            with store.connection() as con:
                con.execute("UPDATE inbound_messages SET processing_status='queued' WHERE message_id=%s", (job["message_id"],))
    except Exception as exc:
        # Return a failure so Meta retries if durable enqueueing did not complete.
        print(f"WhatsApp intake failed: {type(exc).__name__}")
        handler._json({"error": "Message could not be queued"}, 503)
        return
    handler._json({"received": True, "audio_queued": len(jobs)})


class handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def _send(self, body: bytes, status=200, content_type="application/json; charset=utf-8", headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, status=200, headers=None):
        self._send(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"), status, headers=headers)

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > 1_000_000:
            raise ValueError("Request body is too large")
        return self.rfile.read(length)

    def _route(self) -> str:
        path = urlparse(self.path).path
        if path == "/webhook/whatsapp":
            return "webhook/whatsapp"
        return parse_qs(urlparse(self.path).query).get("route", [""])[0].strip("/")

    def _require_operator(self, route: str) -> bool:
        if route in {"login", "webhook/whatsapp", "health"}:
            return True
        if _valid_session(self.headers.get("Cookie", "")):
            return True
        self._json({"error": "Sign in to view this organisation dashboard"}, 401)
        return False

    def do_GET(self):
        route = self._route()
        if route == "webhook/whatsapp":
            return _handle_webhook_get(self)
        if not self._require_operator(route):
            return
        try:
            if route == "health":
                return self._json({"ok": True, "service": "CareSignal"})
            store.ensure_ready()
            if route == "state":
                with store.connection() as con:
                    payload = store.lock_runtime(con)
                    store.tick(payload)
                    store.save_runtime(con, payload)
                    return self._json(store.render_state(con, payload))
            if route == "profile":
                pid = parse_qs(urlparse(self.path).query).get("id", [""])[0]
                if pid not in demo.PEOPLE:
                    return self._json({"error": "Unknown profile"}, 404)
                with store.connection() as con:
                    payload = store.lock_runtime(con)
                    store.tick(payload)
                    store.save_runtime(con, payload)
                    ts, vitals = demo._vitals(int(payload["index"]))
                    rows = demo.FEED[demo.FEED.person_id == pid].iloc[max(0, int(payload["index"]) - 180):int(payload["index"]) + 1]
                    history = [{"minute": str(r.minute), "hr": store._num(r.hr), "spo2": store._num(r.spo2),
                                "sbp": store._num(r.sbp), "dbp": store._num(r.dbp)} for r in rows.itertuples(index=False)]
                    alerts = [demo._decorate_alert(a) for a in demo.ALERTS if a["person_id"] == pid and a["_index"] <= int(payload["index"])]
                    voices = con.execute("SELECT * FROM voice_reports WHERE person_id=%s ORDER BY created_at DESC LIMIT 30", (pid,)).fetchall()
                    alerts.extend(store.voice_alert(v) for v in voices)
                    log = con.execute("SELECT incident_id,status,updated_at FROM care_workflow_log WHERE incident_id LIKE %s ORDER BY entry_id DESC LIMIT 20", (f"{pid}-%",)).fetchall()
                    result = {"id": pid, **demo.PEOPLE[pid], "vitals": vitals[pid], "now": ts.isoformat(),
                              "history": history, "workflow_history": [{"incident_id": x["incident_id"], "status": x["status"], "updated": x["updated_at"].isoformat()} for x in log], "alerts": alerts}
                    return self._json(result)
            if route == "audio":
                message_id = parse_qs(urlparse(self.path).query).get("id", [""])[0]
                with store.connection() as con:
                    record = con.execute("SELECT audio_path FROM voice_reports WHERE message_id=%s", (message_id,)).fetchone()
                if not record or not record["audio_path"]:
                    return self._send(b"Audio not found", 404, "text/plain; charset=utf-8")
                from vercel import blob
                audio = asyncio.run(blob.get_blob(record["audio_path"], access="private"))
                mime = audio.metadata.content_type or "application/octet-stream"
                return self._send(audio.body, 200, mime)
            return self._json({"error": "Not found"}, 404)
        except RuntimeError as exc:
            return self._json({"error": str(exc)}, 503)
        except Exception:
            return self._json({"error": "Dashboard request failed"}, 500)

    def do_POST(self):
        route = self._route()
        if route == "webhook/whatsapp":
            try:
                body = self._body()
            except ValueError as exc:
                return self._json({"error": str(exc)}, 413)
            return _handle_webhook_post(self, body)
        try:
            data = json.loads(self._body() or b"{}")
        except (ValueError, TypeError):
            return self._json({"error": "Invalid request body"}, 400)
        if route == "login":
            password = os.environ.get("DASHBOARD_ACCESS_PASSWORD", "")
            signing_secret = os.environ.get("SESSION_SIGNING_SECRET", "")
            if not password or len(signing_secret) < 32:
                return self._json({"error": "Dashboard sign-in is not configured"}, 503)
            if not hmac.compare_digest(str(data.get("password", "")), password):
                return self._json({"error": "Password did not match"}, 401)
            secure = "; Secure" if os.environ.get("VERCEL") or self.headers.get("X-Forwarded-Proto") == "https" else ""
            return self._json({"ok": True}, headers={"Set-Cookie": f"care_session={_session_value()}; HttpOnly{secure}; SameSite=Strict; Path=/; Max-Age=28800"})
        if not self._require_operator(route):
            return
        try:
            store.ensure_ready()
            with store.connection() as con:
                payload = store.lock_runtime(con)
                store.tick(payload)
                if route == "control":
                    action = data.get("action")
                    if action == "start":
                        payload.update(started=True, paused=False)
                    elif action == "pause":
                        payload["paused"] = True
                    elif action == "resume":
                        if not payload.get("active") and not store.active_voice_reports(con):
                            payload.update(paused=False, started=True)
                    elif action == "reset":
                        payload.update(index=0, speed=3600, fraction=0.0, paused=False,
                                       active={}, triggered=[], started=False)
                elif route == "speed":
                    speed = int(data.get("speed", 3600))
                    if speed not in {2, 4, 60, 240, 3600}:
                        return self._json({"error": "Unsupported playback speed"}, 400)
                    payload["speed"] = speed
                elif route == "workflow":
                    incident_id, action = data.get("incident_id"), data.get("action")
                    voice = con.execute("SELECT status FROM voice_reports WHERE incident_id=%s FOR UPDATE", (incident_id,)).fetchone()
                    allowed = {"New": "Action initiated", "Action initiated": "Help reached", "Help reached": "Resolved"}
                    if voice and allowed.get(voice["status"]) == action:
                        con.execute("UPDATE voice_reports SET status=%s,updated_at=now() WHERE incident_id=%s", (action, incident_id))
                        con.execute("INSERT INTO care_workflow_log(incident_id,status) VALUES (%s,%s)", (incident_id, action))
                    elif incident_id in payload.get("active", {}) and allowed.get(payload["active"][incident_id]["status"]) == action:
                        payload["active"][incident_id]["status"] = action
                        con.execute("INSERT INTO care_workflow_log(incident_id,status) VALUES (%s,%s)", (incident_id, action))
                        if action == "Resolved":
                            del payload["active"][incident_id]
                    if action == "Resolved" and not payload.get("active") and not store.active_voice_reports(con):
                        payload.update(paused=False, started=True)
                else:
                    return self._json({"error": "Not found"}, 404)
                store.save_runtime(con, payload)
                return self._json(store.render_state(con, payload))
        except RuntimeError as exc:
            return self._json({"error": str(exc)}, 503)
        except Exception:
            return self._json({"error": "Dashboard update failed"}, 500)
