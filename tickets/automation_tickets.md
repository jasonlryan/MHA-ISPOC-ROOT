# MHA Document Pipeline Automation Tickets

## AUT-1: Canonical JSON Hashing and State Utilities
- **Goal**: Provide reusable helpers to canonicalize JSON outputs, compute stable content hashes, and maintain `state/vector_state.json` with `{external_id -> {fileId, contentHash, lastSyncedAt}}`.
- **Scope**:
  - Implement canonicalization that sorts keys and removes volatile fields (e.g., `extracted_date`).
  - Create `state/vector_state.json` bootstrap with empty structure.
  - Expose Python helpers (e.g., `scripts/utils/state.py`) to load/update state atomically.
  - Write lightweight unit tests or CLI dry-run validation for hashing function.
- **Acceptance Criteria**:
  - Running helper against existing JSON files yields consistent hash across runs.
  - State file persists to `state/vector_state.json` and survives repeated loads/writes with no corruption.
  - Documentation explains which fields are stripped before hashing.
- **Dependencies**: none.
- **Linked Deliverables**: #4
- **Status**: Approved ✅
- **Verification Notes**:
  - `scripts/utils/state.py` implements canonical hashing and atomic state updates
  - `state/vector_state.json` present with `{ "docs": {} }`
  - Tests in `scripts/tests/test_state_utils.py` pass (`python3 -m unittest`)

## AUT-2: Vector Store Upsert Script
- **Goal**: Implement `scripts/vector_store_upsert.py` to ingest `MHA_Documents_Metadata_Index.json` and upsert documents to the OpenAI Vector Store idempotently.
- **Scope**:
  - Load API key from repo `.env` (fallback `iSPOC/.env`).
  - Resolve policy/guide source JSON paths, compute content hash via AUT-1, and compare to `state`.
  - Upload new/changed files to vector store with metadata `{documentType, title, file, contentHash, extractedDate, policyId/guideNumber}`.
  - Batch uploads, handle retries/backoff, and log structured metrics.
  - Update `state/vector_state.json` only after successful upload; skip unchanged docs.
- **Acceptance Criteria**:
  - Dry-run mode shows pending upserts/deletes without mutating state.
  - Real run uploads new/changed docs once and leaves unchanged docs untouched.
  - Script exits non-zero on unrecoverable errors and emits summary counts.
- **Dependencies**: AUT-1.
- **Linked Deliverables**: #1, #4
- **Status**: Approved ✅
- **Verification Notes**:
  - `scripts/vector_store_upsert.py` present and executable
  - Vector store ID resolution prioritizes test store: `--vector-store-id` → `TEST_VECTOR_STORE_ID` → `VITE_TEST_VECTOR_STORE_ID` → `VECTOR_STORE_ID` → `VITE_OPENAI_VECTOR_STORE_ID` → `VITE_VECTOR_STORE_ID`
  - Emits `vector.config` log with selected `vectorStoreId` and `source` (arg/test-env/prod-env)
  - API key resolution: `VITE_OPENAI_API_KEY` → `OPENAI_API_KEY`
  - Uses canonical content hashing from AUT-1 and updates `state/vector_state.json` only after successful upload

## AUT-3: Vector Store Reconciliation Script
- **Goal**: Build `scripts/reconcile_vector_store.py` to remove vector entries absent from `MHA_Documents_Metadata_Index.json`.
- **Scope**:
  - List current vector store items with `external_id` metadata.
  - Compare against combined index; queue deletions for stale or renamed docs.
  - Update `state/vector_state.json` to drop removed entries.
  - Support dry-run listing of planned deletions; include retries/backoff.
- **Acceptance Criteria**:
  - Removing a JSON file locally and running script removes corresponding vector item and state entry.
  - Script logs per-item actions and totals; non-zero exit on failure.
- **Dependencies**: AUT-1, AUT-2 (state layout, client utilities).
- **Linked Deliverables**: #2, #4

## AUT-4: JSON Schema Definitions and Validation
- **Goal**: Define JSON Schema files for policy, guide, index, and combined index outputs and enforce validation as part of the pipeline.
- **Scope**:
  - Add schema files under `schemas/` (policies, guides, policy index, guide index, combined index).
  - Integrate validation step (Python module or CLI) invoked before AI/question generation and upsert.
  - Fail fast with clear error messaging; log schema violations with file context.
  - Update requirements with `jsonschema` (or chosen validator) and adjust docs.
- **Acceptance Criteria**:
  - Validation step catches malformed fixture data in tests.
  - Pipeline halts on invalid JSON and surfaces actionable diagnostics.
  - Schemas checked into repo and referenced in documentation.
- **Dependencies**: none (can run parallel to AUT-1/2 but integrate with orchestrator in AUT-6).
- **Linked Deliverables**: #5, #6

## AUT-5: Change Detection for AI Generation Scripts
- **Goal**: Gate existing AI question generation scripts to skip unchanged documents based on canonical hash metadata.
- **Scope**:
  - Read `state/vector_state.json` and/or dedicated cache to determine if JSON content changed since last AI run.
  - Skip regeneration when content hash matches stored value; regenerate and update state on changes.
  - Ensure backups and logging stay intact.
  - Add CLI options for forcing regeneration or dry-run reporting.
- **Acceptance Criteria**:
  - Re-running pipeline without changes triggers zero AI API calls.
  - Modifying a single JSON results in regeneration only for that file with updated hash stored.
  - Documentation covers bypass/force flags.
- **Dependencies**: AUT-1 (hashing/state), AUT-4 (validation integration point).
- **Linked Deliverables**: supports acceptance criteria (idempotency).

## AUT-6: Orchestration Entry Point
- **Goal**: Deliver `run_pipeline.py` to execute the full DOCX → JSON → Index → AI → Combine → Upsert → Reconcile sequence with robust controls.
- **Scope**:
  - Orchestrate existing scripts plus new validation, upsert, and reconciliation steps.
  - Implement file locking to prevent concurrent executions.
  - Add retry logic with exponential backoff around OpenAI operations.
  - Provide CLI flags for `--dry-run`, `--skip-ai`, `--skip-upload`, etc.
  - Produce structured JSON logs and final summary; exit non-zero on failures.
- **Acceptance Criteria**:
  - Single command completes entire pipeline successfully on happy path.
  - Dry-run mode reports planned work without side effects.
  - Concurrent invocation attempts block/abort with informative message.
- **Dependencies**: AUT-1 through AUT-5.
- **Linked Deliverables**: #3, #4, #5

## AUT-7: Automation Workflow (GitHub Actions)
- **Goal**: Provide `.github/workflows/document-pipeline.yml` to run the orchestrator on schedule and on-demand.
- **Scope**:
  - Set up job to check out repo, install deps, populate `.env` from secrets, and run `python run_pipeline.py`.
  - Include matrix or steps for dry-run vs. full run; schedule nightly execution.
  - Configure artifact/log retention and failure notifications.
- **Acceptance Criteria**:
  - Workflow passes in dry-run mode against current repo state.
  - Documentation explains required secrets and how to trigger manually.
- **Dependencies**: AUT-6 (orchestrator), AUT-2/3 for scripts.
- **Linked Deliverables**: #7

## AUT-8: Documentation and Runbook Updates
- **Goal**: Document pipeline usage, dry-run, rollback, troubleshooting, and CI/automation steps.
- **Scope**:
  - Update existing README or create `docs/pipeline_runbook.md`.
  - Include setup instructions, env variables, manual run steps, failure scenarios, and reconciliation guidance.
  - Document state file semantics and data retention policies.
- **Acceptance Criteria**:
  - New/updated docs reviewed for completeness; references all new scripts and flags.
  - Runbook enumerates rollback procedures and nightly reconciliation steps.
- **Dependencies**: AUT-2 through AUT-7.
- **Linked Deliverables**: #8

## AUT-9: Dependency & Environment Updates
- **Goal**: Ensure `scripts/requirements.txt` and supporting tooling cover new dependencies and environment bootstrap scripts.
- **Scope**:
  - Add `openai`, `python-dotenv`, `jsonschema` (or chosen validator), and any logging/backoff libs.
  - Provide quick verification script (e.g., `scripts/check_env.py`) to confirm API key availability.
  - Pin versions where appropriate and update installation instructions.
- **Acceptance Criteria**:
  - `pip install -r scripts/requirements.txt` succeeds locally and in CI workflow.
  - Running orchestrator without `.env` surfaces clear error with remediation steps.
- **Dependencies**: Supports all other tickets.
- **Linked Deliverables**: #6
