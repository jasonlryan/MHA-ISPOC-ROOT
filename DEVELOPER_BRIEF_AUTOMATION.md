### Developer Brief: Automate MHA Document Pipeline

#### Objective
Automate the end-to-end document pipeline from raw DOCX to OpenAI Vector Store, with reliable updates when source policies/guides change.

#### Repository & Branch
- Repo root: `/Users/rachelstubbs/Documents/MHA-ISPOC-ROOT`
- Working branch: `automate` (already created)

#### Current State (summary)
- DOCX → JSON (Policies): `scripts/convert_to_json.py` reads `raw policies/` → outputs `VECTOR_JSON/`
- DOCX → JSON (Guides): `scripts/convert_guides_to_json.py` reads `raw_guides/` → outputs `VECTOR_GUIDES_JSON/`
- Build Index (Policies): `scripts/build_policy_index.py` → `Policy_Documents_Metadata_Index.json`
- Build Index (Guides): `scripts/build_guide_index.py` → `Guide_Documents_Metadata_Index.json`
- AI Questions (Policies): `scripts/generate_ai_questions.py`
- AI Questions (Guides): `scripts/generate_guide_ai_questions.py`
- Combine: `scripts/combine_indexes.py` → `MHA_Documents_Metadata_Index.json`
- Secrets: scripts now prefer repo root `.env` → `VITE_OPENAI_API_KEY` (fallback: `iSPOC/.env`)

#### Scope
- Automate the full pipeline: DOCX → JSON → Indexes → AI questions → Combined Index → Vector Store upsert
- Implement deterministic, idempotent vector store sync with change detection and reconciliation
- Provide an orchestration entrypoint (one command) and optional CI/runbook

#### Out of Scope (for now)
- Frontend/UI changes
- Model prompt redesign beyond current system prompts

#### Deliverables
1) `scripts/vector_store_upsert.py` — Upsert JSON docs to OpenAI Vector Store
2) `scripts/reconcile_vector_store.py` — Nightly cleanup for removed/renamed docs
3) `run_pipeline.py` (or `run_pipeline.sh`) — Orchestration runner with locking, retries, dry-run
4) `state/vector_state.json` — Persistent state mapping `{ external_id → {fileId, contentHash} }`
5) JSON schema files (policy, guide, indexes) + validation step
6) Updated `scripts/requirements.txt` with required deps
7) Optional automation: GitHub Actions workflow or Azure Automation runbook sample
8) Documentation updates: how to run, dry-run, rollback, troubleshooting
9) Test Vector Store configuration — scripts accept `TEST_VECTOR_STORE_ID` and default to it on the `automate` branch; logs include the target store ID

#### Technical Requirements
- Dependencies: add to `scripts/requirements.txt`
  - `openai`, `python-dotenv`, `jsonschema` (or `pydantic`), and logging utils if used
- Secrets: `VITE_OPENAI_API_KEY` loaded from repo root `.env` (fallback `iSPOC/.env`), compatible with CI/Runbook secrets
- Hashing: canonicalize JSON before hashing (sorted keys; strip volatile fields like `extracted_date`)
- Identifiers: use JSON filename as `external_id` in the vector store; attach metadata: `{ documentType, id/guide_number, title, file, contentHash, extractedDate }`
- Vector Store IDs: support both `VECTOR_STORE_ID` (prod) and `TEST_VECTOR_STORE_ID` (test). The `automate` branch must default to `TEST_VECTOR_STORE_ID` unless overridden by an explicit flag

#### Implementation Details
- Vector upsert
  - For each entry in `MHA_Documents_Metadata_Index.json`, resolve source path:
    - Policy → `VECTOR_JSON/<File>`; Guide → `VECTOR_GUIDES_JSON/<File>`
  - Compute `contentHash` (canonical JSON)
  - Compare against `state/vector_state.json`
    - New: upload; save `fileId` and `contentHash`
    - Unchanged: skip
    - Changed: delete old file from store (if present), upload new, update state
  - Batch operations; respect rate limits; optional parallelism
  - Select target store: if `TEST_VECTOR_STORE_ID` is set (or `--env test` flag), use it; otherwise use `VECTOR_STORE_ID`
- Reconciliation
  - Remove vector items whose `external_id` no longer appears in combined index
  - Handle renames by mapping old→new when detectable
- Orchestration
  - One entrypoint to run all steps; add file lock to prevent overlap
  - Retries with exponential backoff (OpenAI/network steps)
  - Dry-run mode: produce a diff (to-upload/to-delete) but do not write
- Validation
  - Validate JSON outputs and indexes against schema; fail fast with clear error
- Logging/Observability
  - Structured logs (JSON) per stage with durations, counts, and errors
  - Final summary with totals and exit code
  - Always log the vector store ID used for the run

#### Tasks (phased)
- Phase 1: Foundations
  - Implement `vector_store_upsert.py`
  - Update `scripts/requirements.txt` with `openai`, `python-dotenv`, `jsonschema`
  - Create `state/vector_state.json` and helpers
  - Add `reconcile_vector_store.py`
  - Wire up test vector store: add `TEST_VECTOR_STORE_ID` support and default to it on the `automate` branch; log store ID at start
- Phase 2: Orchestration
  - Add `run_pipeline.py` (or `.sh`) that calls existing scripts in order and then upsert/reconcile
  - Add content hashing + change detection to skip unnecessary AI regeneration and uploads
  - Add file locking, retries, and structured logging
- Phase 3: Automation (choose one)
  - GitHub Actions workflow (`.github/workflows/document-pipeline.yml`) — schedule and on-change
  - OR Azure Automation runbook — schedule and file-change triggers
- Phase 4: Testing & Docs
  - Fixture DOCX set; smoke test and dry-run mode
  - Operational docs: rollback, troubleshooting, and nightly reconciliation
  - Test run on the test vector store and attach run logs/screenshots of item counts

#### Acceptance Criteria
- End-to-end run from repo root succeeds via a single command (no manual steps)
- Idempotent: Re-running without changes performs zero vector uploads/deletes
- Change propagation: Editing a DOCX leads to updated JSON, indexes, AI questions, combined index, and exactly one vector overwrite
- Combined index strictly uses `.json` file extensions and includes `Document Type`
- State is persisted in `state/vector_state.json` and correctly reflects uploads
- Reconciliation removes vector entries not present in the combined index
- JSON outputs and indexes pass schema validation; pipeline fails fast on invalid data
- Logs provide per-stage metrics and a final summary; non-zero exit on critical failure
- `automate` branch writes only to the test vector store (uses `TEST_VECTOR_STORE_ID`); logs clearly show the test store ID; a smoke test ingests N documents into the test store and validates counts

#### How to Run (local)
```bash
cd /Users/rachelstubbs/Documents/MHA-ISPOC-ROOT
python -m pip install -r scripts/requirements.txt
python scripts/convert_to_json.py
python scripts/convert_guides_to_json.py
python scripts/build_policy_index.py
python scripts/build_guide_index.py
python scripts/generate_ai_questions.py
python scripts/generate_guide_ai_questions.py
python scripts/combine_indexes.py
# test store run
env TEST_VECTOR_STORE_ID=vs_test_123 python scripts/vector_store_upsert.py  # new
python scripts/reconcile_vector_store.py  # optional nightly
```

#### Risks & Mitigations
- OpenAI availability/rate limits → retries, backoff, and resumable runs
- Malformed DOCX → validation and per-file error isolation
- Secret handling → prefer env/CI secrets; no secrets checked into repo

#### Definition of Done
- All acceptance criteria met on the `automate` branch
- Documentation updated; PR with passing checks and code review
- Optional: CI/runbook enabled and verified
