# Elder wearable alerting prototype

## Presentation dashboard

Run `run_dashboard.bat` from Windows, or run `python -m src.dashboard` from this folder. Open `http://127.0.0.1:8765` in a browser. On the first launch the dashboard creates a minute-by-minute vital replay from the adjacent `elder_vitals_14day` Parquet files; this preparation may take a few minutes. Later launches reuse the local replay cache.

The dashboard uses the model-and-rule fusion replay saved in `reports/alerts.jsonl`. The alert dashboard opens first; use **Client directory** for the roster and individual profiles. Profile reports include example case history, profile context, contact-directory placeholders and suggested team actions. In the two-zone presentation UI, model/rule `Orange` escalation is displayed as `Red`; falls and other `Red` detections also appear in the red zone. Any reached alert pauses both the simulated clock and new profile snapshots. Progress each alert through **Action initiated → Help reached → Resolved**; after all active alerts are resolved, the replay resumes automatically. Playback defaults to 3,600× for a short presentation and can be changed to 2×, 4×, 60×, or 240×.

The dashboard stores replayed vital snapshots and workflow updates locally in `reports/dashboard_demo.sqlite`. Use the reset button in the header to restart the presentation. Names, case histories, medication examples and contact details are demonstration-only; the contact numbers are reserved placeholders and this is not clinical evidence or a live care system.

## Temporary WhatsApp webhook (Meta Cloud API)

For a local test only, start the isolated receiver with `run_whatsapp_webhook.bat`, then expose **port 8766 only** using a temporary HTTPS tunnel. Set the Meta callback URL to `https://<your-tunnel-host>/webhook/whatsapp`; use the verification token in `reports/whatsapp_verify_token.txt` when Meta asks for it. Subscribe the app to the `messages` webhook field. Do not expose dashboard port 8765 through the tunnel.

The receiver verifies Meta POST signatures using `META_APP_SECRET` and stores incoming message metadata in `reports/whatsapp_inbox.sqlite`. WhatsApp audio arrives as a media ID; downloading the recording and producing a Gemini report also require a WhatsApp access token and Gemini API key and are not active until configured. Keep this temporary endpoint to test data. It does not provide authentication for dashboard users or production safeguards for real client health information.

## Vercel deployment

The Vercel entry point is `api/index.py`; the static dashboard remains in `web/`. Its mutable timeline and workflow are stored in PostgreSQL instead of process memory or local SQLite. The packaged `deployment_data/` files are the prepared presentation replay and alert schedule. WhatsApp POSTs are signature checked, audio jobs are placed on Vercel Queues, private recordings go to Vercel Blob, and a queue worker uses Gemini to return a transcript, short report and Yellow/Red routing suggestion. A signed eight-hour staff session protects dashboard APIs and private audio playback. The callback stays public so Meta can verify it and send messages.

To deploy, install and sign into the Vercel CLI, run `vercel link` in this folder, connect a PostgreSQL Marketplace integration and a **private** Blob store, enable Vercel Queues, then run `vercel --prod`. Add the variables listed in `.env.example` in Project Settings → Environment Variables. Use a long random `SESSION_SIGNING_SECRET` (at least 32 characters) and a strong `DASHBOARD_ACCESS_PASSWORD`. Add the Meta app secret, webhook verify token, WhatsApp access token, business phone-number ID and Gemini API key as protected environment variables; never commit them to files.

After deployment, set Meta’s callback to `https://<your-vercel-domain>/webhook/whatsapp`, enter the same `META_WEBHOOK_VERIFY_TOKEN` in Meta, and subscribe the app to `messages`. `CLIENT_WHATSAPP_MAP_JSON` maps sender phone digits to a profile ID, for example `{"919876543210":"E1"}`. Set `ALERT_WHATSAPP_TO` to the staff phone that should receive alerts. Also set `ALERT_TEMPLATE_NAME` and `ALERT_TEMPLATE_LANGUAGE` to an approved WhatsApp message template whose body contains one text placeholder (`{{1}}`); Meta requires an approved template for business-initiated notifications outside an active customer-service window. The system will not send reports back to the client who submitted the recording. Keep `META_GRAPH_VERSION` aligned with the version enabled for your Meta app. Audio is retained in private Blob storage; reports and transcripts are retained in Postgres.

The Vercel setup is for presentation/testing with the sample profiles. Do not put real client health information into this deployment until the organisation has approved the data handling, retention, access and consent arrangements. Gemini’s transcription/report and the urgency tier are AI-generated suggestions for staff review, not a diagnosis or emergency service.

Offline demonstration using the adjacent `elder_vitals_14day` synthetic dataset. This is a software prototype, not a medical device; its alerts and scores are not clinical advice. No clinical claims are made from these scripted signals.

## Run

From this directory, install the packages in `requirements.txt`, then run:

```powershell
python -m src.cli qa
python -m src.cli replay --person E5 --day 8
python -m src.cli evaluate
pytest
```

The default data path is `../elder_vitals_14day`. Outputs are written under `reports/`.

The implementation uses `events.csv` for event-level scoring because the single-valued `gt_state` field can mask overlapping event labels. Ground-truth columns, timestamps, day number and person identifiers are excluded from detector inputs; identifiers are used only to select a stream and join evaluation results. Wear is estimated from sensor availability, not `gt_worn`. Activity and state labels are carried only as reporting metadata. All rolling features are trailing and causal.

Generate and score a separate synthetic robustness set with:

```powershell
python ..\elder_vitals_14day\generate_dataset.py --seed 7 --event-scale 0.6 --noise-scale 1.5 --out data\R
python -m src.cli --data data\R evaluate --out reports\robustness_R
```

The evaluation includes a day-grouped out-of-fold M3 LightGBM classifier, a simple rule-layer ablation, and fixed-model runs on separate synthetic data. Running `evaluate` trains and saves `models/m3_lightgbm.joblib`; the quick `replay` command uses the causal rule and fall layers, while model predictions are produced by `evaluate`. M3 thresholds are not sigmoid-calibrated. The sensitivity-first Orange threshold is capped at 0.30 and requires 7 of 8 minutes; personal BP alerts use a corroborating signal and require 8 of 8 minutes, while a fall requires consistently quiet motion after impact. Sets R, S, T and U informed tuning; seed V was generated after the policy was frozen and is the held-out synthetic check. These are not clinical validation. Baselines use trailing medians and a rolling standard-deviation scale estimate; the prototype does not yet implement the planned per-context MAD baseline, SHAP explanations, an isolation-forest backstop, or clinician-reviewed rules.

## Limits

The source contains five simulated people and a single scripted generator. Robustness results from a changed seed remain synthetic stress tests, not external validation. At 2 Hz, heart rate cannot establish atrial fibrillation or provide beat-to-beat HRV. “AF-like”, “dizzy-like”, illness-like, and desaturation alerts refer only to scripted patterns. NEWS2-inspired inputs are incomplete and rules require clinician review before any clinical interpretation.
