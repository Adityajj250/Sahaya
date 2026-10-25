# Sahaya

This repository contains presentation and development projects from the ELDER workspace.

## Projects

- **elder-ml/** — elder wearable alerting dashboard, model artifacts, presentation replay data, and WhatsApp webhook/deployment prototype.
- **elder_vitals_14day/** — documentation and reproducible generator for the synthetic wearable benchmark.
- **WhatsUp/** — Flutter and Firebase chat application.
- **ibm_bob_proj/** — CareCircle elderly-support service prototype.

## Dataset files

The large raw Parquet and CSV benchmark datasets are not included. The generator and dataset documentation are included in `elder_vitals_14day/`. Regenerate the data locally before training or rebuilding the raw-data replay. Prepared presentation artifacts remain in `elder-ml/deployment_data/`.

## Local configuration

Environment files containing local tokens, webhook verification tokens, private runtime databases, logs, build outputs, and nested Git metadata are intentionally excluded. Use the included `.env.example` files to configure local development. Never commit actual credentials.

These are demonstration projects. Do not use sample profiles or model output for real care decisions.
