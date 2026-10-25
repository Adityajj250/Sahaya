"""Small, isolated Meta WhatsApp webhook receiver for local demonstrations.

Expose only this service through a tunnel. It stores incoming message metadata
locally; Meta sends a media ID for audio, which must be downloaded separately
using a WhatsApp access token before transcription/analysis can run.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PROJECT = Path(__file__).resolve().parents[1]
REPORTS = PROJECT / "reports"
DB = REPORTS / "whatsapp_inbox.sqlite"
TOKEN_FILE = REPORTS / "whatsapp_verify_token.txt"
PORT = int(os.environ.get("WHATSAPP_WEBHOOK_PORT", "8766"))


def _verify_token() -> str:
    REPORTS.mkdir(exist_ok=True)
    if not TOKEN_FILE.exists():
        TOKEN_FILE.write_text(secrets.token_urlsafe(32), encoding="utf-8")
    return TOKEN_FILE.read_text(encoding="utf-8").strip()


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS inbound_messages (
        message_id TEXT PRIMARY KEY, sender TEXT NOT NULL, message_type TEXT NOT NULL,
        received_at TEXT NOT NULL, text_body TEXT, media_id TEXT, mime_type TEXT,
        raw_json TEXT NOT NULL, processing_status TEXT NOT NULL DEFAULT 'received'
    )""")
    return con


def _signature_ok(body: bytes, signature: str | None) -> bool:
    app_secret = os.environ.get("META_APP_SECRET", "")
    if not app_secret or not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _save_webhook(payload: dict) -> int:
    count = 0
    con = _db()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for message in value.get("messages", []):
                kind = message.get("type", "unknown")
                content = message.get(kind, {}) if isinstance(message.get(kind), dict) else {}
                text_body = content.get("body") if kind == "text" else None
                con.execute("""INSERT OR IGNORE INTO inbound_messages
                    (message_id,sender,message_type,received_at,text_body,media_id,mime_type,raw_json)
                    VALUES (?,?,?,?,?,?,?,?)""", (
                    message.get("id", secrets.token_hex(12)), message.get("from", "unknown"),
                    kind, now, text_body, content.get("id"), content.get("mime_type"),
                    json.dumps(message, ensure_ascii=False),
                ))
                count += con.execute("SELECT changes()").fetchone()[0]
    con.commit()
    con.close()
    return count


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def _reply(self, status: int, body: bytes, content_type: str = "text/plain; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/webhook/whatsapp":
            return self._reply(404, b"Not found")
        args = parse_qs(parsed.query)
        mode = args.get("hub.mode", [""])[0]
        token = args.get("hub.verify_token", [""])[0]
        challenge = args.get("hub.challenge", [""])[0]
        if mode == "subscribe" and hmac.compare_digest(token, _verify_token()) and challenge:
            return self._reply(200, challenge.encode())
        return self._reply(403, b"Webhook verification failed")

    def do_POST(self):
        if urlparse(self.path).path != "/webhook/whatsapp":
            return self._reply(404, b"Not found")
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 2_000_000:
            return self._reply(413, b"Payload size invalid")
        body = self.rfile.read(length)
        if not _signature_ok(body, self.headers.get("X-Hub-Signature-256")):
            return self._reply(401, b"Webhook signature not configured or invalid")
        try:
            payload = json.loads(body)
            count = _save_webhook(payload)
        except (ValueError, TypeError, sqlite3.Error):
            return self._reply(400, b"Invalid webhook payload")
        return self._reply(200, json.dumps({"received": True, "new_messages": count}).encode(), "application/json")


def main():
    _verify_token()
    _db().close()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"WhatsApp webhook receiver listening on http://127.0.0.1:{PORT}/webhook/whatsapp")
    server.serve_forever()


if __name__ == "__main__":
    main()
