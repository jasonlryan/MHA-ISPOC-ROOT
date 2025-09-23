## MHA Document Pipeline Runbook

This runbook explains how to operate the MHA document pipeline safely in local and CI environments. It complements (does not duplicate) these documents:

- Workflow guide: `.github/workflows/README.md`
- Policy conversion usage: `scripts/README.md`

### What the pipeline does

Executed by `run_pipeline.py` (the orchestrator). High‑level steps:

- Convert DOCX → JSON (policies always; guides skip if `raw_guides/` missing)
- Build policy/guide indexes and combine into a master index
- Validate all JSON against `schemas/*.schema.json`
- AI question generation (can be skipped)
- Upsert JSON to the OpenAI test vector store
- Reconcile: remove stale items in the test store

For implementation details, see the workflow guide.

### Environments and secrets

- Required in CI: `OPENAI_API_KEY`, `TEST_VECTOR_STORE_ID`
- The workflow exports `VITE_OPENAI_API_KEY=$OPENAI_API_KEY` and `TEST_VECTOR_STORE_ID` for the run
- Local runs can use a `.env` at the repo root; API key resolution prefers `VITE_OPENAI_API_KEY`, then `OPENAI_API_KEY`

Optional (for future production promotion):

- `VECTOR_STORE_ID` (production) kept separate from the test store

### Running locally

1) Install dependencies
```bash
python3 -m pip install -r scripts/requirements.txt
```

2) Pre‑flight environment check (optional but recommended)
```bash
python3 scripts/check_env.py
# or JSON output
python3 scripts/check_env.py --json
```

3) Set environment
```bash
export OPENAI_API_KEY=...   # or set VITE_OPENAI_API_KEY in a .env at repo root
export TEST_VECTOR_STORE_ID=...
```

4) Dry‑run without AI (safe):
```bash
python3 run_pipeline.py --dry-run --skip-ai --log-level INFO
```

5) Full run against the test store (use with care):
```bash
python3 run_pipeline.py --log-level INFO
```

### Using GitHub Actions (CI)

- Triggers: push to `automate`, nightly 03:00 UTC, or manual dispatch
- Scope: test vector store only; AI skipped by default in CI
- Artifacts: `state/` and index JSON files uploaded for inspection

See `.github/workflows/README.md` for step‑by‑step CI behavior and safeguards.

### Safety controls

- File lock prevents concurrent runs (`state/pipeline.lock`)
- Idempotent hashing avoids unnecessary API calls
- Validation enforces schema correctness
- CI defaults: `--dry-run` and `--skip-ai`

### Rollback and recovery

- Revert problematic changes: `git revert <sha>` and re‑run workflow
- Restore a known‑good `state/` from artifacts if needed
- If vector store contains unwanted files: run reconcile in real mode against the test store

Reconcile example (test store):
```bash
python3 scripts/reconcile_vector_store.py --vector-store-id "$TEST_VECTOR_STORE_ID"
```

### Promotion to production (when ready)

1) Provision a production vector store and store its ID as a separate secret (e.g., `VECTOR_STORE_ID`)
2) Update the workflow (or a separate workflow) to export the production ID instead of the test ID
3) Remove `--dry-run` and optionally remove `--skip-ai`
4) Gate runs to a protected branch and add required approvals

Keep test and production stores distinct at all times.

### Troubleshooting quick reference

- Missing secrets: Workflow exits early; add `OPENAI_API_KEY` and `TEST_VECTOR_STORE_ID`
- Import errors: Ensure dependencies are installed and `PYTHONPATH` includes repo root; CI already sets this
- Schema not found: Verify `schemas/*.schema.json` exist (tracked in repo)
- No guides: Expected; guide conversion skips gracefully if `raw_guides/` is missing
- OpenAI HTTP errors: Pipeline auto‑retries; inspect logs for `step.failure` and re‑run

### Operational checklist (on‑call)

1) Check Actions → latest run → view `pipeline.complete` summary
2) Download artifacts; skim `state/` and combined index
3) If failed: read `step.failure` logs, fix, and re‑run workflow
4) If data drift: run reconcile (dry‑run first), then real if correct
5) Communicate status with link to run and summary

### Ownership

- Orchestrator: `run_pipeline.py`
- Workflow: `.github/workflows/document-pipeline.yml`
- Scripts: `scripts/*.py`
- Schemas: `schemas/*.schema.json`

Change control: Use the `automate` branch and CI to validate changes before promotion.

# MHA Document Pipeline Runbook

This runbook explains how to operate the automated MHA policy & guide pipeline, including prerequisites, execution modes, dry-run behaviour, rollback, and troubleshooting. All commands assume you are in the repository root (`/Users/rachelstubbs/Documents/MHA-ISPOC-ROOT`).

## 1. Prerequisites
- **Python**: 3.10+ (GitHub Actions runs 3.11). Install dependencies once per environment:
  ```bash
  python -m pip install --upgrade pip
  python -m pip install -r scripts/requirements.txt
  ```
- **Environment variables / secrets**:
  - `VITE_OPENAI_API_KEY` (or `OPENAI_API_KEY`) – used by AI question generation and vector store operations.
  - `TEST_VECTOR_STORE_ID` – sandbox vector store ID for dry-run uploads.
  - Optional `VITE_OPENAI_VECTOR_STORE_ID` if you later add a production run; currently everything targets the test store by default.
  - `.env` in the repo root is preferred; scripts fall back to `iSPOC/.env`.
- **State directory**: `state/vector_state.json` stores canonical hashes and vector file IDs. It is auto-created on first use.
- **Source material**: DOCX sources in `raw policies/` and `raw_guides/`.
- **Quick environment check**: `python scripts/check_env.py --json` confirms secrets, modules, and state file readiness.

## 2. Pipeline entry point (`run_pipeline.py`)
`run_pipeline.py` orchestrates the full flow:
1. `scripts/convert_to_json.py`
2. `scripts/convert_guides_to_json.py`
3. `scripts/build_policy_index.py`
4. `scripts/build_guide_index.py`
5. `scripts/validate_outputs.py`
6. `scripts/generate_ai_questions.py`
7. `scripts/generate_guide_ai_questions.py`
8. `scripts/combine_indexes.py`
9. `scripts/validate_outputs.py` (second pass)
10. `scripts/vector_store_upsert.py`
11. `scripts/reconcile_vector_store.py`

### 2.1 Common invocations
- Dry-run (no uploads/deletes; AI skipped by default in GitHub Actions):
  ```bash
  python run_pipeline.py --dry-run
  ```
- Full run (test store):
  ```bash
  python run_pipeline.py
  ```
- Partial run examples:
  - Skip conversions but refresh questions/upserts: `python run_pipeline.py --skip-conversion`
  - Dry-run without AI calls (e.g., for schema validation only): `python run_pipeline.py --dry-run --skip-ai`
  - Skip vector store operations if you only need regenerated indexes: `python run_pipeline.py --skip-upload --skip-reconcile`

### 2.2 Flags & behaviour
- `--dry-run`: propagates to AI generation, upsert, and reconcile scripts.
- `--state-file`: defaults to `state/vector_state.json`; override for experiments.
- `--lock-path`: defaults to `state/pipeline.lock`. The runner prevents concurrent executions; remove the lock file only if you are sure the previous run is dead (`--stale-lock-seconds` controls automatic cleanup of stale locks).
- `--max-retries` / `--retry-base-delay`: control exponential backoff for OpenAI-backed steps.

## 3. Supporting scripts
- `scripts/validate_outputs.py`: Validates JSON outputs against `schemas/*.schema.json`.
  ```bash
  python scripts/validate_outputs.py
  ```
- `scripts/vector_store_upsert.py`: Idempotent upsert to the OpenAI test vector store. Respects `--dry-run` and hashes stored in `state/vector_state.json`.
- `scripts/reconcile_vector_store.py`: Deletes entries not present in the combined index (test store only by default).
- `scripts/check_env.py`: Sanity-checks required environment variables and Python dependencies.
- AI generation scripts (`generate_ai_questions.py`, `generate_guide_ai_questions.py`) now skip unchanged documents using canonical content hashes stored in the state file.

## 4. GitHub Actions workflow
- Workflow file: `.github/workflows/document-pipeline.yml`.
- Schedule: nightly at 03:00 UTC; manual `workflow_dispatch` available with a `dry_run_only` knob (defaults to `true`).
- Steps: checkout → install dependencies → unit tests → `python run_pipeline.py --dry-run --skip-ai` → upload `state/` as an artifact.
- Required repository secrets:
  - `OPENAI_API_KEY` (mirrors to `VITE_OPENAI_API_KEY`)
  - `TEST_VECTOR_STORE_ID`

## 5. Rollback & recovery
1. **Index files**: Conversion and AI scripts create timestamped backups (`*_YYYYMMDD_HHMMSS.json`). To roll back, copy the desired backup over the active file, then rerun `run_pipeline.py --skip-conversion --skip-ai --dry-run` to rebuild metadata and confirm schema compliance.
2. **Vector store state**: Restore `state/vector_state.json` from the latest artifact or commit, then rerun `python run_pipeline.py --skip-conversion --skip-index --skip-ai` to reconcile the state with the vector store without reprocessing DOCX files.
3. **Vector store content**: Because we target the test store, re-running `run_pipeline.py` automatically re-uploads missing entries. For production usage, ensure a manual backup process before switching identifiers.
4. **Lock file stuck**: Delete `state/pipeline.lock` only after verifying no other pipeline process is active (check CI jobs or local terminals).

## 6. Troubleshooting
- **`jsonschema` missing**: Install dependencies (`pip install -r scripts/requirements.txt`). Tests will skip validation if the module is absent, but the pipeline expects it.
- **`TEST_VECTOR_STORE_ID` unset**: Upsert and reconcile will fail fast. Set it in `.env` or session: `export TEST_VECTOR_STORE_ID=vs_...`.
- **Schema validation failures**: Inspect the logged `validation.fail` entries. Correct the offending JSON (often conversion edge cases) and rerun `python scripts/validate_outputs.py`.
- **OpenAI API errors**: The pipeline retries automatically. Persistent 401/429 errors usually mean expired keys or rate limits; confirm the key and consider raising `--retry-base-delay`.

## 7. Verification checklist
- `python -m unittest discover scripts/tests`
- `python scripts/validate_outputs.py`
- `python scripts/check_env.py --json`
- `python run_pipeline.py --dry-run` before a full run
- Confirm `state/vector_state.json` updated (new hashes/timestamps) after successful runs
- Review GitHub Action artifacts (`pipeline-logs`) after nightly executions

## 8. Contacts & ownership
- Primary automation scripts live under `scripts/`.
- Pipeline orchestration & workflows: owned by the automation team maintaining the `automate` branch.
- For OpenAI quota or secret management, coordinate with whoever manages the environment variables in GitHub Secrets / `.env` files.

---
_Last updated: 2025-09-22_
