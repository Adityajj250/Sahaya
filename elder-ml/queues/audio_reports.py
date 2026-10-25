"""Durable audio-to-report processing for WhatsApp voice messages."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from google import genai
from psycopg.types.json import Jsonb
from vercel import blob
from vercel.queue import Message, subscribe

from src import cloud_store as store
from src import dashboard as demo

GRAPH_VERSION = os.environ.get("META_GRAPH_VERSION", "v25.0")
MAX_AUDIO_BYTES = 16 * 1024 * 1024


def _request_json(url: str, token: str, data: dict | None = None) -> dict:
    body = json.dumps(data).encode() if data is not None else None
    req = Request(url, data=body, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urlopen(req, timeout=25) as response:
        return json.loads(response.read())


def _download_audio(media_id: str) -> tuple[bytes, str]:
    token = os.environ.get("META_ACCESS_TOKEN", "")
    if not token:
        raise RuntimeError("META_ACCESS_TOKEN has not been configured")
    base = f"https://graph.facebook.com/{GRAPH_VERSION}/{media_id}"
    metadata = _request_json(base, token)
    size = int(metadata.get("file_size", 0))
    if size and size > MAX_AUDIO_BYTES:
        raise ValueError("The voice message is larger than the configured 16 MB processing limit")
    request = Request(metadata["url"], headers={"Authorization": f"Bearer {token}"})
    with urlopen(request, timeout=40) as response:
        audio = response.read(MAX_AUDIO_BYTES + 1)
        mime = response.headers.get_content_type() or metadata.get("mime_type", "audio/ogg")
    if mime == "application/octet-stream":
        mime = str(metadata.get("mime_type", "audio/ogg")).split(";", 1)[0].strip()
    if len(audio) > MAX_AUDIO_BYTES:
        raise ValueError("The downloaded voice message is larger than the configured 16 MB processing limit")
    return audio, mime


def _profile_context(person_id: str | None) -> dict:
    profile = demo.PEOPLE.get(person_id or "")
    if not profile:
        return {"client_id": None, "client_context": "No client profile is linked to this WhatsApp number. Confirm the sender’s identity before taking action.", "conditions": [], "medications": []}
    return {"client_id": person_id, "client_context": profile["story"],
            "conditions": profile["conditions"], "medications": profile["medications"]}


def _analyse_audio(audio: bytes, mime: str, person_id: str | None) -> dict:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY has not been configured")
    suffix = {"audio/ogg": ".ogg", "audio/mpeg": ".mp3", "audio/mp3": ".mp3",
              "audio/mp4": ".m4a", "audio/aac": ".aac", "audio/webm": ".webm"}.get(mime, ".audio")
    context = _profile_context(person_id)
    prompt = f"""You are preparing a staff-review report from a client WhatsApp voice note.
Transcribe the recording in its original language and provide a concise English summary.
Use profile information as context only; never infer a diagnosis or claim a cause.
Choose urgency Yellow for a concern that needs timely staff follow-up, or Red for
an immediate safety concern such as a reported fall/injury, chest pain, severe
breathing difficulty, loss of consciousness, sudden severe confusion, or similarly
urgent symptoms. When the audio is unclear or urgency cannot be ruled out, choose
Red and explicitly say that a person must listen and verify. This is a routing aid,
not medical advice. Return only valid JSON with keys: language, transcript,
summary, urgency, rationale, possible_context, confidence (0 to 1),
recommended_actions (array of short staff actions). Do not suggest medication
changes. Keep recommendations limited to contacting the client, arranging a
wellbeing check, or following the organisation's escalation procedure.

Known profile context: {json.dumps(context, ensure_ascii=False)}"""
    client = genai.Client(api_key=api_key)
    with tempfile.NamedTemporaryFile(suffix=suffix) as audio_file:
        audio_file.write(audio)
        audio_file.flush()
        uploaded = client.files.upload(file=audio_file.name, config={"mime_type": mime})
        result = client.models.generate_content(model=os.environ.get("GEMINI_MODEL", "gemini-3.8-flash"),
            contents=[prompt, uploaded], config={"response_mime_type": "application/json"})
    text = (result.text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    try:
        report = json.loads(text)
    except json.JSONDecodeError:
        # An unparseable assessment is kept in the urgent human-review pathway.
        report = {"language": "Unknown", "transcript": "", "summary": "Audio needs immediate staff review",
                  "urgency": "Red", "rationale": "The automated report could not be read. Listen to the recording and verify the client’s current status.",
                  "possible_context": "Automated assessment unavailable; the recording has not been medically interpreted.",
                  "confidence": 0.0, "recommended_actions": ["Listen to the recording and call the sender to confirm current status.", "Follow the organisation’s urgent escalation procedure if immediate danger is possible."]}
    tier = str(report.get("urgency", "Red")).strip().lower()
    report["urgency"] = tier.title() if tier in {"red", "yellow"} else "Red"
    report["confidence"] = max(0.0, min(1.0, float(report.get("confidence", 0))))
    report.setdefault("transcript", "")
    report.setdefault("summary", "Voice report received for staff review")
    report.setdefault("rationale", "Staff review is required to confirm reported details.")
    report.setdefault("possible_context", "An audio report cannot establish a medical cause.")
    report.setdefault("recommended_actions", ["Call the sender to confirm current symptoms.", "Follow the organisation’s escalation procedure if concerns are urgent."])
    if not isinstance(report["recommended_actions"], list):
        report["recommended_actions"] = [str(report["recommended_actions"])]
    report.update({k: context[k] for k in ("client_id", "client_context")})
    return report


def _send_notification(sender: str, report: dict, incident_id: str) -> None:
    token = os.environ.get("META_ACCESS_TOKEN", "")
    phone_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
    recipient = os.environ.get("ALERT_WHATSAPP_TO", "")
    template_name = os.environ.get("ALERT_TEMPLATE_NAME", "")
    template_language = os.environ.get("ALERT_TEMPLATE_LANGUAGE", "en_US")
    if not token or not phone_id or not recipient or not template_name:
        raise RuntimeError("Configure the Meta credentials, ALERT_WHATSAPP_TO, and an approved alert template")
    tier = report["urgency"].upper()
    text = f"{tier} voice report needs staff review. {report['summary']} Open the CareSignal dashboard to review the transcript and recording. Reference: {incident_id[-12:]}"
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{phone_id}/messages"
    _request_json(url, token, {"messaging_product": "whatsapp", "to": recipient,
                               "type": "template", "template": {
                                   "name": template_name,
                                   "language": {"code": template_language},
                                   "components": [{"type": "body", "parameters": [
                                       {"type": "text", "text": text[:1024]}
                                   ]}],
                               }})


@subscribe(topic="whatsapp-audio", max_attempts=8)
async def process_audio(message: Message[dict[str, str]]) -> None:
    job = message.payload
    store.ensure_database()
    message_id = job["message_id"]
    with store.connection() as con:
        inbound = con.execute("SELECT * FROM inbound_messages WHERE message_id=%s", (message_id,)).fetchone()
        if inbound is None:
            raise RuntimeError("The queued WhatsApp message is not in the database")
        existing = con.execute("SELECT * FROM voice_reports WHERE message_id=%s", (message_id,)).fetchone()
    if existing:
        if not existing["notification_sent_at"]:
            _send_notification(existing["sender"], existing["report"], existing["incident_id"])
            with store.connection() as con:
                con.execute("UPDATE voice_reports SET notification_sent_at=now() WHERE message_id=%s", (message_id,))
        return

    person_id = store.sender_to_profile(job["sender"])
    audio, mime, report, audio_path = None, job.get("mime_type", "audio/ogg"), None, None
    try:
        audio, mime = await asyncio.to_thread(_download_audio, job["media_id"])
        report = await asyncio.to_thread(_analyse_audio, audio, mime, person_id)
        suffix = mime.split("/", 1)[-1].split(";", 1)[0].replace("+", "-")
        pathname = "voice-reports/" + hashlib.sha256(message_id.encode()).hexdigest() + "." + suffix
        uploaded = await blob.put_blob(pathname, audio, access="private", content_type=mime, add_random_suffix=False)
        audio_path = uploaded.pathname
    except Exception as exc:
        attempt = getattr(getattr(message, "metadata", None), "delivery_count", 1)
        if attempt < 2:
            raise
        print(f"Audio report fallback: {type(exc).__name__}")
        report = {
            "language": "Unknown", "transcript": "", "summary": "Voice note needs immediate staff review",
            "urgency": "Red", "rationale": "The recording could not be fully processed. Contact the sender promptly and verify their current status.",
            "possible_context": "Automated audio review was unavailable; no medical cause has been determined.",
            "confidence": 0.0,
            "recommended_actions": ["Call the sender promptly to confirm current symptoms and location.",
                                    "Ask staff to listen to the recording if it is available in the incoming message.",
                                    "Follow the organisation’s urgent escalation procedure if immediate danger is possible."],
            **_profile_context(person_id),
        }
        if audio is not None and audio_path is None:
            try:
                suffix = mime.split("/", 1)[-1].split(";", 1)[0].replace("+", "-")
                pathname = "voice-reports/" + hashlib.sha256(message_id.encode()).hexdigest() + "." + suffix
                uploaded = await blob.put_blob(pathname, audio, access="private", content_type=mime, add_random_suffix=False)
                audio_path = uploaded.pathname
            except Exception as blob_error:
                print(f"Private audio storage unavailable: {type(blob_error).__name__}")
    incident_id = "voice-" + hashlib.sha256(message_id.encode()).hexdigest()[:24]
    with store.connection() as con:
        con.execute("""INSERT INTO voice_reports
          (incident_id,message_id,sender,person_id,urgency,report,audio_path)
          VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(message_id) DO NOTHING""",
          (incident_id, message_id, job["sender"], person_id, report["urgency"], Jsonb(report), audio_path))
        con.execute("UPDATE inbound_messages SET processing_status='processed' WHERE message_id=%s", (message_id,))
        runtime = con.execute("SELECT payload FROM care_runtime WHERE singleton=TRUE FOR UPDATE").fetchone()
        if runtime:
            payload = runtime["payload"]
            payload.update(paused=True, fraction=0.0, updated_at=datetime.now(timezone.utc).isoformat())
            con.execute("UPDATE care_runtime SET payload=%s,updated_at=now() WHERE singleton=TRUE", (Jsonb(payload),))
    _send_notification(job["sender"], report, incident_id)
    with store.connection() as con:
        con.execute("UPDATE voice_reports SET notification_sent_at=now() WHERE message_id=%s", (message_id,))
