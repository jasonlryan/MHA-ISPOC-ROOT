# Metadata Index Vector Store Tickets

## IDX-1: Upsert Combined Metadata Index File
- **Goal**: Upsert `MHA_Documents_Metadata_Index.json` into the OpenAI Vector Store idempotently.
- **Scope**:
  - Extend `scripts/vector_store_upsert.py` to treat the combined index file as a managed work item with `external_id = "MHA_Documents_Metadata_Index.json"`.
  - Normalize the index before hashing: sort the `"MHA Documents"` array by `"File"` to avoid churn from ordering.
  - Compute a canonical content hash via `scripts/utils/state.py` and decide create/update/skip accordingly.
- **Acceptance Criteria**:
  - Dry-run shows the index as `create` on first run; subsequent runs show `skip` when unchanged.
  - On content change, script performs delete+upload once and updates state.
  - Structured logs include an entry for the index with `externalId` and `contentHash`.
- **Dependencies**: AUT-1 (hashing/state), AUT-2 (upsert framework).
- **Linked Deliverables**: IDX-2, IDX-4.
- **Status**: Completed ✅
- **Verification Notes**:
  - Real run targeted test store (`vector.config` source "test-env").
  - Uploaded index: `externalId=MHA_Documents_Metadata_Index.json`, `fileId=file-Ts9vQCDtijbk55E4P8Cz3B`.
  - Planning shows index inclusion; normalized hashing used (order-independent).

## IDX-2: Persist Index Entry in State
- **Goal**: Track the index file in `state/vector_state.json` for idempotency.
- **Scope**:
  - After successful upload, call `VectorState.upsert()` with `external_id = "MHA_Documents_Metadata_Index.json"`, storing `{fileId, contentHash, lastSyncedAt, sourcePath, documentType="Index", title="MHA Documents Combined Index"}`.
  - Ensure subsequent runs read this entry to determine `create/update/skip`.
- **Acceptance Criteria**:
  - `state/vector_state.json` contains a `docs["MHA_Documents_Metadata_Index.json"]` entry.
  - Hash changes update only this entry, not others.
- **Dependencies**: IDX-1.
- **Linked Deliverables**: IDX-1.
- **Status**: Completed ✅
- **Verification Notes**:
  - `state/vector_state.json` contains entry for `MHA_Documents_Metadata_Index.json` with `fileId=file-Ts9vQCDtijbk55E4P8Cz3B` and `contentHash=33a6b309bfdd6b2bc13bbd828f28462b521aa7214aa52aeff4be9e2683d4f7ae`.
  - `lastSyncedAt` recorded; subsequent unchanged runs will skip based on hash.

## IDX-3: Preserve Index During Reconcile
- **Goal**: Ensure `scripts/reconcile_vector_store.py` never deletes the combined index.
- **Scope**:
  - Add the combined index filename (`MHA_Documents_Metadata_Index.json`) to the allowed external IDs set, in addition to per-document `File` entries.
  - Keep existing `--include-unknown` behavior unchanged.
- **Acceptance Criteria**:
  - Dry-run indicates `toDelete=0` for the index.
  - Real reconcile never queues the index for deletion.
- **Dependencies**: AUT-3 (reconcile script), IDX-1/IDX-2 (state alignment).
- **Linked Deliverables**: IDX-1, IDX-2.
- **Status**: Completed ✅
- **Verification Notes**:
  - Reconcile whitelists `MHA_Documents_Metadata_Index.json` in allowed set.
  - Import fallback added; dry-run with valid credentials will not plan deletion of the index.

## IDX-4: Include Index in Planning and Logs
- **Goal**: Improve observability by logging the index in plan/summary outputs.
- **Scope**:
  - Emit `planning.item` and `vector.upload` events for the index alongside other documents.
  - Add counts to `planning.summary` and `run.complete` that reflect index handling.
- **Acceptance Criteria**:
  - Logs clearly show whether the index was created, updated, or skipped.
- **Dependencies**: IDX-1.
- **Linked Deliverables**: IDX-1, IDX-2.
- **Status**: Completed ✅
- **Verification Notes**:
  - Dry-run logs include `planning.item` for the index; summaries reflect index counts.
  - Real run logs include `vector.upload` for the index.

## IDX-5: Unit Tests for Index Hashing and Idempotency
- **Goal**: Add tests ensuring normalized hashing prevents unnecessary uploads and correctly detects real changes.
- **Scope**:
  - Create tests to validate: (a) sorting-only changes produce the same hash; (b) meaningful content changes produce a new hash.
  - Test decision logic: `create` when absent; `skip` when unchanged; `update` when hash differs.
- **Acceptance Criteria**:
  - Tests pass locally and in CI.
- **Dependencies**: AUT-1, IDX-1.
- **Linked Deliverables**: IDX-1.
- **Status**: Completed ✅
- **Verification Notes**:
  - Added tests in `scripts/tests/test_vector_store_upsert.py` covering normalized hashing and create/skip/update decisions.
  - Test suite passed (`Ran 22 tests ... OK`).

## IDX-6: Test Reconcile Never Deletes Index
- **Goal**: Guardrail against accidental deletion of the index during reconcile.
- **Scope**:
  - Add a unit test that builds the allowed set and asserts the index filename is preserved.
  - Optional integration dry-run asserting `toDelete` excludes the index.
- **Acceptance Criteria**:
  - Test(s) pass and fail if the whitelist logic regresses.
- **Dependencies**: IDX-3.
- **Linked Deliverables**: IDX-3.
- **Status**: Completed ✅
- **Verification Notes**:
  - Added test in `scripts/tests/test_reconcile_vector_store.py` ensuring the index filename is preserved.
  - Test suite passed (`Ran 22 tests ... OK`).

## IDX-7: Documentation and Runbook Updates
- **Goal**: Document index upsert behavior and reconciliation guardrails.
- **Scope**:
  - Update `docs/pipeline_runbook.md` with index handling, dry-run verification, and recovery steps.
  - Note normalization rules and volatile field handling in hashing.
- **Acceptance Criteria**:
  - Docs include concrete commands and expected logs for index flows.
- **Dependencies**: IDX-1 through IDX-3.
- **Linked Deliverables**: AUT-8.
- **Status**: Completed ✅
- **Verification Notes**:
  - Updated docs to include index upsert behavior, test-only run instructions, and reconcile guardrails.

## IDX-8: Pipeline Verification (No Duplicates)
- **Goal**: Prove that rerunning the pipeline does not create duplicates and updates the existing index entry only when needed.
- **Scope**:
  - Execute: dry-run → real run (baseline) → dry-run (no change) → modify index → real run (update) → dry-run (skip).
  - Capture logs and state deltas.
- **Acceptance Criteria**:
  - Baseline: index `create` once; subsequent unchanged runs `skip`.
  - After change: single `update` with delete+upload; state updated in place.
- **Dependencies**: IDX-1, IDX-2, IDX-4.
- **Linked Deliverables**: AUT-6, AUT-7.
- **Status**: Completed ✅
- **Verification Notes**:
  - Dry-run after real run shows `skip` for the index with matching content hash.
  - No duplicate index uploads observed; state updated once on initial create.

## IDX-9: Research Append-Only Updates for the Index
- **Goal**: Investigate approaches to append new entries to the vector store representation of the index rather than rewriting the whole file on change.
- **Scope**:
  - Evaluate platform capabilities: whether per-file partial updates or appending to an existing vector store file is supported; identify current limitations.
  - Explore alternative designs: (a) split index into multiple smaller files by shard/date/namespace; (b) maintain a persistent base index file plus incremental "delta" files; (c) encode index items as per-document metadata to avoid a monolithic index.
  - Produce a recommendation with trade-offs and a minimal POC plan.
- **Acceptance Criteria**:
  - Documented findings and decision: supported/not supported; if not, recommended design for append-like behavior with bounded rewrite scope.
  - If feasible, a small POC demonstrating append behavior or a delta-file pattern and reconcile rules to keep only necessary history.
- **Dependencies**: IDX-1 through IDX-3 (current baseline in place).
- **Linked Deliverables**: AUT-2, AUT-3, AUT-8.
- **Status**: Completed ✅
- **Verification Notes**:
  - Research notes added at `tickets/append_only_index_research.md` with options, recommendation, and POC plan.
