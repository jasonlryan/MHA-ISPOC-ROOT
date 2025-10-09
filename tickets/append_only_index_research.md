# IDX-9: Research Notes — Append-Only Updates for the Combined Index

## Summary
Goal: avoid rewriting the entire `MHA_Documents_Metadata_Index.json` on each change by exploring append-like strategies compatible with OpenAI Vector Store constraints.

## Current Constraints
- OpenAI Vector Store treats each uploaded file as immutable; partial in-place append is not supported.
- Metadata attachment at upload is limited via SDK; we maintain `external_id` mapping locally in `state/vector_state.json`.

## Options Considered
1) Sharded index files
- Split the combined index into multiple files (e.g., by first letter, date, or namespace: `index-A.json`, `index-B.json`, ...).
- Only shards with changes are re-uploaded.
- Reconcile needs to include all shard filenames in the allowed set.
- Pros: smaller uploads, localized updates; Cons: coordination/aggregation when consuming.

2) Delta files (base + increments)
- Keep a stable base index file; append new/changed entries in timestamped delta files (e.g., `index-delta-2025-10-09.json`).
- Periodically compact: merge deltas back into a new base; delete older deltas via reconcile.
- Pros: append-like semantics and smaller updates; Cons: compaction logic and multi-file resolution during retrieval.

3) Per-document metadata-centric approach
- Rely more on per-document JSON files and their metadata; minimize the role of the combined index in retrieval.
- Use the combined index only as a navigational map (thin), not as a source of truth.
- Pros: avoids large index churn; Cons: shifts complexity to retrieval/query layer.

## Recommendation
- Start with sharded index files by initial character of `File` (26–36 shards depending on charset).
- Update upsert/reconcile to handle shard enumeration; hashing is per-shard.
- Evaluate delta approach later if change frequency is high within the same shard.

## Minimal POC Plan
- Produce `index-shards/` with files like `index-A.json`, `index-B.json`, etc., each containing an `MHA Documents` array subset.
- Extend upsert to:
  - Build normalized hash per shard; upsert create/update/skip per shard.
  - Track shard entries in `state/vector_state.json`.
- Extend reconcile to allow shard filenames in addition to per-document files.
- Validate with a dry-run and one real run in test store.

## Rollout Notes
- Backward compatible: keep the monolithic index until shards stabilize.
- Consumers can prefer shards if present, else fall back to monolithic.
- Add a compaction tool later to merge deltas or rebalance shards.
