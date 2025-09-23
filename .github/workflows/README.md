## Document Pipeline Workflow (GitHub Actions)

### Purpose

Automate the end‑to‑end document pipeline for MHA on a safe, isolated test vector store. The workflow ensures the pipeline runs consistently on schedule and on demand, producing validated outputs, uploading artifacts, and surfacing errors early without impacting production.

### What it does

On each run, the workflow executes the orchestrator (`run_pipeline.py`) which performs:

- **Convert policies**: DOCX → JSON under `VECTOR_JSON/`.
- **Convert guides**: DOCX → JSON under `VECTOR_GUIDES_JSON/` (skips gracefully if `raw_guides/` is absent).
- **Build indexes**: `Policy_Documents_Metadata_Index.json` and `Guide_Documents_Metadata_Index.json`.
- **Validate outputs**: Validates all JSON against `schemas/*.schema.json`.
- **AI questions**: Currently skipped in CI (guarded via `--skip-ai`).
- **Combine indexes**: Produces `MHA_Documents_Metadata_Index.json`.
- **Upsert to vector store**: Targets the test store only.
- **Reconcile vector store**: Removes stale entries (dry‑run by default per orchestrator flags if configured).

All steps emit structured logs and a final summary event `{"event":"pipeline.complete", ...}`.

### Why we need it

- **Reliability**: Automated, repeatable runs reduce manual effort and mistakes.
- **Safety**: Runs on a dedicated test vector store; never touches production.
- **Integrity**: Schema validation and stateful upserts enforce data quality and idempotency.
- **Visibility**: Artifacts and structured logs enable quick debugging and auditing.
- **Guardrails**: `scripts/check_env.py` runs before tests to confirm required secrets and modules are present.

### Triggers

- **Push**: Only when pushing to the `automate` branch.
- **Schedule**: Nightly at 03:00 UTC.
- **Manual**: `workflow_dispatch` from the Actions tab.

Workflow file: `.github/workflows/document-pipeline.yml`

### Secrets and environment

- **Required repository secrets**:
  - `OPENAI_API_KEY`: API key for OpenAI (mirrored to `VITE_OPENAI_API_KEY` in the job env).
  - `TEST_VECTOR_STORE_ID`: The OpenAI vector store ID for testing.

The workflow exports:

- `VITE_OPENAI_API_KEY=$OPENAI_API_KEY`
- `TEST_VECTOR_STORE_ID=$TEST_VECTOR_STORE_ID`

The orchestrator reads `TEST_VECTOR_STORE_ID` and fails fast if it’s missing. API key resolution prefers `VITE_OPENAI_API_KEY`, then `OPENAI_API_KEY`.

### Safety controls in CI

- Scoped to the `automate` branch with `if: github.ref == 'refs/heads/automate'`.
- Uses the test vector store ID only.
- Runs orchestrator with `--dry-run` and `--skip-ai` by default in CI.
- Guides conversion skips cleanly if `raw_guides/` does not exist (no failure).

### Artifacts and logs

- Artifacts uploaded:
  - `state/` (pipeline and vector state)
  - `Policy_Documents_Metadata_Index.json`
  - `Guide_Documents_Metadata_Index.json`
  - `MHA_Documents_Metadata_Index.json`

- Logs are structured JSON lines. Useful markers:
  - `lock.acquired` / `lock.released`
  - `step.success` / `step.failure`
  - `pipeline.abort` / `pipeline.complete`
  - `vector.config` (selected vector store ID and source)

### How to run locally

1. Install dependencies:
```bash
python3 -m pip install -r scripts/requirements.txt
```
2. Pre‑flight check (optional):
```bash
python3 scripts/check_env.py
```
3. Set environment (prefer a `.env` at repo root for local runs):
```bash
export OPENAI_API_KEY=... 
export TEST_VECTOR_STORE_ID=...
```
4. Execute a dry‑run without AI:
```bash
python3 run_pipeline.py --dry-run --skip-ai --log-level INFO
```
5. Full run against the test store (use with care):
```bash
python3 run_pipeline.py --log-level INFO
```

### How to trigger/re‑run in GitHub

- Navigate to the Actions tab → `Document Pipeline` → `Run workflow`.
- Pick the `automate` branch and click `Run workflow`.
- To re‑run a failed job, open the run → `Re-run jobs`.

### Common issues and fixes

- **Missing secrets**: The job fails early with a clear message. Add `OPENAI_API_KEY` and `TEST_VECTOR_STORE_ID` in repo Settings → Secrets and variables → Actions → New repository secret.
- **Import errors**: The orchestrator includes robust import fallbacks and the workflow sets `PYTHONPATH`. Ensure `.github/workflows/document-pipeline.yml` step `Install dependencies` runs before tests.
- **Schema not found**: Ensure `schemas/*.schema.json` are present (they are committed in this repo).
- **No guides present**: This is acceptable; the guides conversion step now skips gracefully.

### Adapting for production

- Keep CI pointed at the test store until you explicitly promote.
- For production runs:
  - Provide a production vector store ID via a separate secret (e.g., `VECTOR_STORE_ID`).
  - Update the workflow to export `VECTOR_STORE_ID` (and avoid using the test ID).
  - Remove `--dry-run` and, when ready, remove `--skip-ai` to enable AI question regeneration.
  - Restrict triggers to your release branch and add approvals as needed.

### Ownership

- Primary entrypoint: `run_pipeline.py` (orchestrator)
- Supporting scripts: `scripts/*.py`
- Workflow definition: `.github/workflows/document-pipeline.yml`

For questions or incidents, check the latest run logs and artifacts in Actions first, then open an issue with the failing run link and the `pipeline.complete` summary.

