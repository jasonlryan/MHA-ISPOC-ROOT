### Client Guide — Power Automate + Azure to Run the MHA iSPOC Pipeline

This guide explains how to automatically run the document pipeline when a policy (or guide) is added to SharePoint, using Power Automate and Azure. The pipeline converts DOCX → JSON, builds indexes, generates AI questions, combines indexes, and syncs to the OpenAI Vector Store.

---

### What You Will Build
- A Power Automate cloud flow that triggers when a file is added/modified in SharePoint.
- The flow invokes an Azure compute target (Container Apps Job, Automation Runbook, or Function) that executes the repository’s single command:
  - `python run_pipeline.py --log-level INFO`
- The compute target has access to the repository, Python dependencies, secrets, and a persistent volume for state.

---

### Prerequisites
- Azure subscription with permission to create resources (Resource Group, Container Apps, Storage/File Share or Automation Account, Key Vault optional).
- SharePoint site and library where users upload DOCX files.
- OpenAI account and vector store, with the following values:
  - `VITE_OPENAI_API_KEY`
  - `TEST_VECTOR_STORE_ID` (or `VECTOR_STORE_ID` for production)
- Access to this repository code (packaged into your compute environment).

---

### Recommended Architecture (Container Apps Job)

- Container Image contains:
  - Python 3.x, `scripts/requirements.txt` installed
  - Repo mounted at `/workspace/app`
  - Working directory `/workspace/app`
- Job environment variables:
  - `VITE_OPENAI_API_KEY`
  - `TEST_VECTOR_STORE_ID` (or `VECTOR_STORE_ID`)
- Volume mount (Azure Files):
  - Mount path `/workspace/app/state` mapped to a persistent file share
  - Optional: mount `/workspace/app/VECTOR_JSON`, `/workspace/app/VECTOR_GUIDES_JSON` for artifact retention
- Command:
  - `python run_pipeline.py --log-level INFO`

Notes:
- The pipeline will detect changes and skip unnecessary AI work and uploads.
- To lower cost or speed up runs, you may pass `--skip-ai` or `--dry-run` in early testing.

---

### Step 1 — Prepare the Runner

Option A: Build your own image
1) Clone the repo locally; add a `Dockerfile` that installs `scripts/requirements.txt` and copies code into `/workspace/app`.
2) Push the image to Azure Container Registry.
3) Create an Azure Container Apps Job using that image.

Option B: Azure Automation Runbook (Python)
1) Create an Automation Account and a Python 3 Runbook.
2) Add a Managed Identity; grant access to Storage and Key Vault (if used).
3) At run start, `git clone` the repo to a temp path, `pip install -r scripts/requirements.txt`, then execute `python run_pipeline.py`.

We recommend Container Apps Job for faster startup and easier dependency management.

---

### Step 2 — Wire up Secrets

- Store `VITE_OPENAI_API_KEY` and vector store IDs as environment variables on the job (or in Key Vault and inject via identities).
- The scripts also support a `.env` file at the repo root if you prefer to materialize secrets into the container at runtime.

Environment variables recognized by the scripts:
- `VITE_OPENAI_API_KEY` or `OPENAI_API_KEY`
- `TEST_VECTOR_STORE_ID` (preferred for test) or `VECTOR_STORE_ID` (production)

---

### Step 3 — SharePoint Integration

Choose one pattern:
- Pattern A: Trigger-only orchestration (simplest)
  - Power Automate triggers on SharePoint file added/modified
  - The flow starts the job, which always runs the full pipeline from the repo workspace
  - The job must have access to the latest source files. Preferred approach: the repo directory already contains the latest `raw policies/` and `raw_guides/` synced via your operational process

- Pattern B: Content fetch per run (richer)
  - Power Automate passes the file info (site, library, path) to the job
  - A small pre-step in the job uses Microsoft Graph to download the changed file(s) into `/workspace/app/raw policies/` (or `raw_guides/`) before calling the pipeline
  - Requires an Azure AD app registration and delegated permissions

For immediate rollout, use Pattern A and ensure that uploads to SharePoint are mirrored to the runner’s workspace via a scheduled sync or a separate integration.

---

### Step 4 — Build the Flow in Power Automate

1) Create a new Cloud Flow
- Trigger: SharePoint — “When a file is created (properties only)”
  - Site Address: your site
  - Library Name: your library (policies)
  - Filter: optional folder path (e.g., `/raw policies`)

2) Add action: Start job (Container Apps) or Start Runbook (Automation)
- Parameters:
  - Environment variables (API key, vector store IDs)
  - Command: `python run_pipeline.py --log-level INFO`
  - Working directory: `/workspace/app`

3) Optional: Add condition to skip if the file is not DOCX.

4) Optional: Add notification actions (Teams/Email) on success/failure.

---

### Step 5 — Test and Validate

- First run with `--dry-run --skip-ai` to validate conversion, indexing, validation, and planning.
- Then run with full AI to generate questions and upsert to the vector store.
- Confirm that:
  - `VECTOR_JSON/` and/or `VECTOR_GUIDES_JSON/` are updated
  - `Policy_Documents_Metadata_Index.json`, `Guide_Documents_Metadata_Index.json`, and `MHA_Documents_Metadata_Index.json` refresh
  - `state/vector_state.json` changes reflect new/updated content
  - Vector store shows new/updated files

---

### Operations

- Nightly cleanup (recommended): run `scripts/reconcile_vector_store.py` to remove stale vector store files.
- Monitoring: send container logs to Log Analytics; add alerts for non‑zero exit codes.
- Rollback: restore the previous `state/vector_state.json` and combined index from the file share, then re‑run.
- Cost control: hash‑based change detection prevents unnecessary AI and uploads; you may also throttle via Power Automate concurrency.

---

### Troubleshooting

- Missing API key: ensure `VITE_OPENAI_API_KEY` is present in the job environment.
- Vector store ID not set: set `TEST_VECTOR_STORE_ID` (or `VECTOR_STORE_ID`).
- Validation errors: run `python scripts/validate_outputs.py` and inspect JSON schema errors.
- Path issues: verify that `raw policies/` and `raw_guides/` exist in the working directory.

---

### One‑Command Reference

Use this for manual runs during testing:

```bash
python -m pip install -r scripts/requirements.txt
python run_pipeline.py --log-level INFO
```

Flags:
- `--dry-run` to plan actions
- `--skip-ai`, `--skip-index`, `--skip-upload`, `--skip-validation` to tune behavior
