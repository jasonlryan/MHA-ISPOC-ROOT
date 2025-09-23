### Secrets, Permissions, Testing, and Operations

---

### Secrets
- OpenAI
  - `VITE_OPENAI_API_KEY` (preferred)
  - `OPENAI_API_KEY` (fallback)
- Vector Store IDs
  - `TEST_VECTOR_STORE_ID` for non‑prod runs
  - `VECTOR_STORE_ID` for production

Storage of secrets
- Azure Container Apps: set as environment variables, optionally sourced from Key Vault with managed identity
- Azure Automation: variables/credentials mapped to environment variables or written to a temporary `.env`

---

### Permissions
- Power Automate
  - Access to SharePoint library for trigger
- Azure Runner
  - Pull from Container Registry (if using custom image)
  - Access to Storage/File Share for persistent `state/` and artifacts
  - Access to Key Vault (if used) via managed identity
- Graph API (optional if fetching content each run)
  - App registration with Files.Read.All, Sites.Read.All (application permissions)

---

### Testing Matrix
- Dry run, no AI
  - Command: `python run_pipeline.py --dry-run --skip-ai --log-level INFO`
  - Expect: conversion, indexing, validation pass; plan printed; no uploads
- Full test store run
  - Command: `python run_pipeline.py --log-level INFO`
  - Require: `TEST_VECTOR_STORE_ID`
  - Expect: updated JSON, indexes, questions, and vector store
- Regression (no changes)
  - Re-run without modifying DOCX
  - Expect: zero AI calls; zero vector uploads; quick finish

---

### Rollback
- Restore `state/vector_state.json` from last known good snapshot in file share
- Optionally restore `MHA_Documents_Metadata_Index.json` and per‑document JSON
- Re-run pipeline pointing to the same vector store ID

---

### Monitoring & Alerting
- Forward runner logs to Log Analytics or Application Insights
- Configure alerts on non‑zero exit codes or repeated failures
- Power Automate: add failure branches with Teams/email notifications

---

### Cost Controls
- Hash-based change detection reduces AI invocations and uploads
- Use test vector store for non‑prod
- Throttle Power Automate flow concurrency and schedule non‑peak hours
