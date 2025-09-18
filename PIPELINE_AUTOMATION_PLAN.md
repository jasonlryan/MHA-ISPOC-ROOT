### Purpose
A concise, actionable plan to automate the MHA document pipeline end‑to‑end and define a robust update/overwrite strategy for the OpenAI Vector Store.

- **Scope**: Raw DOCX policies/guides → JSON → Indexes → AI Questions → Combined Index → Vector Store upsert/overwrite
- **Environment root**: `/Users/rachelstubbs/Documents/MHA-ISPOC-ROOT`
- **Secrets**: prefer repo root `.env` → `VITE_OPENAI_API_KEY` (fallback: `iSPOC/.env`)


### What this repo does (functional summary)
- **Convert DOCX to JSON (Policies)**: `scripts/convert_to_json.py`
  - Reads DOCX files from `raw policies/`
  - Extracts core properties, full text, and sections via heuristic headers
  - Writes structured JSON to `VECTOR_JSON/`
- **Convert DOCX to JSON (Guides)**: `scripts/convert_guides_to_json.py`
  - Reads DOCX files from `raw_guides/`
  - Extracts guide metadata and common sections
  - Writes JSON to `VECTOR_GUIDES_JSON/`
- **Build Policy Index**: `scripts/build_policy_index.py`
  - Reads `VECTOR_JSON/*.json`
  - Creates/updates `Policy_Documents_Metadata_Index.json` with description + 3 templated questions
  - Auto-backups the index with timestamp before writing
- **Build Guide Index**: `scripts/build_guide_index.py` (present in repo)
  - Reads `VECTOR_GUIDES_JSON/*.json`
  - Creates/updates `Guide_Documents_Metadata_Index.json` (similar to policy index)
- **AI-enrich Questions (Policies)**: `scripts/generate_ai_questions.py`
  - Loads OpenAI API key from `iSPOC/.env`
  - Rewrites "Questions Answered" for each policy in `Policy_Documents_Metadata_Index.json`
  - Saves backups periodically and on completion
- **AI-enrich Questions (Guides)**: `scripts/generate_guide_ai_questions.py`
  - Same flow as policies, targeting guides
- **Combine Indexes**: `scripts/combine_indexes.py`
  - Reads both indexes; normalizes all `File` extensions to `.json`
  - Adds `Document Type` and writes `MHA_Documents_Metadata_Index.json`


### Single-command local run (manual)
From the repo root:
```bash
cd /Users/rachelstubbs/Documents/MHA-ISPOC-ROOT && \
python -m pip install -r scripts/requirements.txt && \
python scripts/convert_to_json.py && \
python scripts/convert_guides_to_json.py && \
python scripts/build_policy_index.py && \
python scripts/build_guide_index.py && \
python scripts/generate_ai_questions.py && \
python scripts/generate_guide_ai_questions.py && \
python scripts/combine_indexes.py
```


### Automation plan (options)
- **Option A: Power Automate → Azure Automation Runbook (Python)**
  - Trigger: file added/updated in SharePoint/OneDrive for `raw policies/` and `raw_guides/`, or a scheduled daily trigger (02:00), or manual button.
  - Steps in Runbook (working directory = repo root):
    1) `python -m pip install -r scripts/requirements.txt`
    2) `python scripts/convert_to_json.py`
    3) `python scripts/convert_guides_to_json.py`
    4) `python scripts/build_policy_index.py`
    5) `python scripts/build_guide_index.py`
    6) `python scripts/generate_ai_questions.py`
    7) `python scripts/generate_guide_ai_questions.py`
    8) `python scripts/combine_indexes.py`
    9) Vector store upsert (see section below)
  - Secrets: Store `VITE_OPENAI_API_KEY` as an Azure Automation variable/credential and export into the process or write to a temporary `.env` the scripts can read.

- **Option B: Power Automate → Self-hosted runner via on-premises data gateway**
  - Execute a shell script on a secure VM or Mac mini that runs the same sequence.

- **Option C: CI (e.g., GitHub Actions or Azure DevOps)**
  - On push or on schedule, run the pipeline. Ensure access to DOCX sources (share or artifact) and secrets.


### Idempotency, safety, and logging
- **Backups**: Index scripts already back up `Policy_Documents_Metadata_Index.json` and `Guide_Documents_Metadata_Index.json` with timestamped files.
- **Change gating (recommended)**: Before AI steps, compute a content digest for each JSON file and skip AI regen when the JSON digest unchanged since previous run (store a small `state/vector_state.json`).
- **Retries/Rate limits**: AI steps include a 1s delay; consider exponential backoff on failures.
- **Logging**: Capture stdout/stderr per step in your automation platform and alert on non-zero exit codes.


### Vector store upsert/overwrite strategy
Goal: Keep the OpenAI Vector Store synchronized with the latest JSON content, updating entries when source policies/guides change.

- **Deterministic identifiers**
  - Use a stable `external_id` per document for vector store items: the JSON filename (e.g., `HR4.13 DBS Policy and Procedure.json`) is sufficient and already present in indexes.
  - Metadata to attach: `{ documentType, policyIdOrGuideNumber, title, file, contentHash, extractedDate }`.

- **Content hashing to detect changes**
  - Compute SHA-256 of the JSON content (minus volatile fields like `extracted_date`) to produce `contentHash`.
  - Maintain a local `state/vector_state.json` mapping `{ external_id -> lastKnownHash, vectorStoreFileId }`.

- **Upsert algorithm (per document)**
  1) Build combined index: read `MHA_Documents_Metadata_Index.json`.
  2) For each item:
     - Resolve source JSON path:
       - If `Document Type == "Policy"` → `VECTOR_JSON/<File>`
       - If `Document Type == "Guide"` → `VECTOR_GUIDES_JSON/<File>`
     - Compute `contentHash`.
     - Compare with `state/vector_state.json`:
       - If no entry: upload file to vector store, record returned `file_id` under this `external_id` and store `contentHash`.
       - If entry exists and `contentHash` unchanged: skip.
       - If entry exists and `contentHash` changed: replace file contents in vector store (delete old file or update), then update state with new `file_id` (if it changes) and `contentHash`.

- **Overwrite mechanics (OpenAI Vector Stores)**
  - One document → one uploaded file in the vector store (no chunking client-side; let the platform handle chunking).
  - On change:
    - Preferred: delete the existing file by `file_id` from the vector store and re-upload the new JSON under the same `external_id` (metadata retains identity).
    - Alternate: upload new file and detach the old file from the store. Keep only one active file per `external_id`.

- **Atomicity**
  - Upsert in batches and commit after a successful batch to avoid partial states. If your platform supports transactions/commits, use them; otherwise, keep `state/vector_state.json` updates as the commit step (write only after successful upload).

- **Reconciliation job**
  - Nightly job: scan the vector store for items whose `external_id` is no longer present in `MHA_Documents_Metadata_Index.json` and remove them (handles deletions/renames). Also prune any items with duplicate `external_id`s, keeping the one that matches the latest `contentHash`.


### Example pseudo-steps for the vector store upsert
Pseudocode to illustrate the approach (adapt to your SDK/runtime):
```python
from pathlib import Path
import hashlib, json, os

ROOT = Path("/Users/rachelstubbs/Documents/MHA-ISPOC-ROOT")
STATE = ROOT / "state/vector_state.json"
COMBINED = ROOT / "MHA_Documents_Metadata_Index.json"

# 1) Load state
state = {"docs": {}}
if STATE.exists():
    state = json.loads(STATE.read_text())

# 2) Load combined index
data = json.loads(COMBINED.read_text())

def content_hash(p):
    # Hash without volatile fields if needed
    text = Path(p).read_text(encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

uploads = []
for item in data.get("MHA Documents", []):
    file_name = item["File"]
    doc_type = item.get("Document Type", "Policy")
    src = ROOT / ("VECTOR_JSON" if doc_type == "Policy" else "VECTOR_GUIDES_JSON") / file_name
    eid = file_name
    chash = content_hash(src)

    prev = state["docs"].get(eid)
    if prev and prev.get("contentHash") == chash:
        continue  # no change

    # upload to vector store (pseudo)
    # resp = client.vector_stores.files.upload(store_id, file=src, external_id=eid, metadata={...})
    # file_id = resp.id
    file_id = "returned_file_id"  # placeholder

    # optional: if prev exists, delete prev["fileId"] from the store first

    state["docs"][eid] = {"fileId": file_id, "contentHash": chash}
    uploads.append(eid)

# 3) Commit state atomically
STATE.parent.mkdir(parents=True, exist_ok=True)
STATE.write_text(json.dumps(state, indent=2))
print(f"Upserts: {len(uploads)}")
```


### Minimal requirements for implementation
- Python deps for DOCX conversion are already specified: `scripts/requirements.txt` (`python-docx`).
- Add OpenAI SDK dependency to your automation environment for vector upserts.
- Ensure `iSPOC/.env` or platform secrets provide `VITE_OPENAI_API_KEY`.


### Operational runbook
- **Initial full build**
  1) Place DOCX files into `raw policies/` and `raw_guides/`.
  2) Run the single-command pipeline (above).
  3) Run the vector store upsert batch.
- **Incremental updates**
  - Trigger on file additions/updates; re-run conversion + re-index + AI steps only for changed files (optional optimization), then run vector upsert. The content-hash gate prevents unnecessary uploads.
- **Deletions/renames**
  - If a DOCX is removed or renamed, the nightly reconciliation removes obsolete items from the vector store using `external_id` comparison against the combined index.


### Acceptance checklist
- [ ] End-to-end run succeeds locally from the repo root
- [ ] Backups appear adjacent to index files
- [ ] Combined index includes only `.json` extensions and has `Document Type`
- [ ] Vector store contains one file per document with stable `external_id`
- [ ] Re-running with no changes uploads nothing (idempotent)
- [ ] Changing a DOCX propagates to JSON, indexes, AI questions, combined index, and triggers exactly one vector overwrite
