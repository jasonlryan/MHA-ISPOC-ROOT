### MHA iSPOC Pipeline — Refactor and Automation Plan

#### Objectives
- Reduce orchestration to a single callable entrypoint for automation.
- Ensure idempotent runs with change detection and minimal cost.
- Make Power Automate → Azure execution straightforward and supportable.

---

### Current State (summary)
- Orchestrator: `run_pipeline.py` handles conversion, indexing, validation, AI question generation, combining indexes, vector store upsert, and reconciliation.
- Scripts:
  - Conversion: `scripts/convert_to_json.py` (policies), `scripts/convert_guides_to_json.py` (guides)
  - Indexing: `scripts/build_policy_index.py`, `scripts/build_guide_index.py`, `scripts/combine_indexes.py`
  - AI: `scripts/generate_ai_questions.py`, `scripts/generate_guide_ai_questions.py`
  - Validation: `scripts/validate_outputs.py`
  - Vector Store: `scripts/vector_store_upsert.py`, `scripts/reconcile_vector_store.py`
- Change detection: Implemented for AI generation and vector store upserts via `state/vector_state.json`.

---

### Refactor Recommendations (keep steps minimal)

1) Keep a Single Entry Command
- Use `python run_pipeline.py` as the only command Power Automate/Azure needs to call.
- Rely on existing flags to tune behavior:
  - `--dry-run` to plan without side effects.
  - `--skip-ai`, `--skip-index`, `--skip-upload`, `--skip-validation` as needed.

2) Optional Consolidation (nice-to-have; not required for Azure rollout)
- Merge conversions into one script `scripts/convert_all.py` that detects the presence of `raw policies/` and `raw_guides/` and processes both.
- Merge AI generation into one script `scripts/generate_all_questions.py` to reduce two invocations.
- Outcome: `run_pipeline.py` remains the orchestrator; consolidation simply shortens logs and step count.

3) Make Environments Portable
- Continue resolving secrets via environment variables with `.env` support at repo root.
- Standardize on `VITE_OPENAI_API_KEY` and `TEST_VECTOR_STORE_ID` (and optionally `VECTOR_STORE_ID` for production).
- Keep all outputs and `state/` under the repo to allow a persistent volume in Azure.

4) Containerize the Runner (recommended for Power Automate)
- Provide a container image with:
  - Python 3.x + `scripts/requirements.txt` installed
  - The repository included at a fixed path (e.g., `/workspace/app`)
  - Entry point: `python run_pipeline.py --log-level INFO`
- Benefits: deterministic environment, fast cold-starts, simple scaling, easier permissioning.

5) Persistence and Artifacts
- Mount a persistent volume to keep `state/vector_state.json` between runs.
- Optionally persist the combined index and per-document JSON for audit/logging and debugging.

6) Observability & Controls
- Keep structured JSON logs already present in the scripts.
- In Azure, forward container logs to Log Analytics / Application Insights.
- Add a nightly reconciliation job calling `scripts/reconcile_vector_store.py` to remove stale vector files.

7) Naming and Folders
- Retain `raw policies/` (with a space) for compatibility with existing scripts.
- In Azure storage, prefer dash/underscore names (e.g., `raw-policies`, `raw-guides`); the container job maps these to the local folder names used by scripts.

---

### Minimal Azure Execution Model (recommended)

- Orchestration: Power Automate triggers an Azure Container Apps Job (or Azure Container Instance) to run `python run_pipeline.py`.
- Input: Files are synced into the container’s working directory before invocation (see Client Guide for options).
- Secrets: Passed as environment variables to the job.
- Persistence: Azure Files or Azure Managed Disk mounted at `/workspace/data` mapped to repo `state/` and output directories.

---

### Implementation Phases

- Phase A (Now):
  - Use `run_pipeline.py` as the single command.
  - Provision the containerized runner and persistent volume.
  - Wire Power Automate → Container Apps Job with secrets.

- Phase B (Optional Enhancements):
  - Consolidate conversion and AI steps into single scripts (no behavior change).
  - Add a `--changed-only` flag in `run_pipeline.py` to skip early steps when no DOCX changes are detected.

- Phase C (Operational Hardening):
  - Application Insights dashboards, alerting on failures.
  - Nightly vector store reconciliation.
  - Backups of `state/` and combined index to Storage.

---

### Required Secrets and Config
- `VITE_OPENAI_API_KEY`: OpenAI API key for model and vector store.
- `TEST_VECTOR_STORE_ID`: Target test vector store ID (production uses `VECTOR_STORE_ID`).
- Optional SharePoint access method (choose one):
  - Files provided by the trigger payload and written to the container volume.
  - Or an Azure Function/Runbook that uses Microsoft Graph to fetch changed files.

---

### Success Criteria
- One-click/one-command automation via Power Automate.
- Idempotent runs: unchanged files cause zero AI calls and zero vector uploads.
- Clear logs and exit codes for operations and support teams.
