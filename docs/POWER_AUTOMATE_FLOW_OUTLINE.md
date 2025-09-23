### Power Automate Flow Outline — SharePoint to Azure Runner

Use this outline to implement the automation quickly; adapt actions to your Azure target (Container Apps Job vs Automation Runbook).

---

### Trigger
- SharePoint — When a file is created (properties only)
  - Site Address: <your site>
  - Library Name: <your library>
  - Folder: `/raw policies` (or `/raw_guides`)
  - Condition: File extension equals `docx`

Optional alternative:
- SharePoint — When a file is created or modified (properties only)
- Recurrence (schedule) for periodic full runs

---

### Actions

1) Initialize Variables (optional)
- `RepoPath` = `/workspace/app`
- `WorkingDir` = `/workspace/app`
- `Command` = `python run_pipeline.py --log-level INFO`

2) Start Azure Job / Runbook
- If Container Apps Job:
  - Action: Invoke Container Apps Job (custom connector or HTTP call to Azure REST)
  - Body parameters:
    - Environment variables: `VITE_OPENAI_API_KEY`, `TEST_VECTOR_STORE_ID`
    - Command override: `python run_pipeline.py --log-level INFO`
    - Working directory: `/workspace/app`
- If Automation Runbook:
  - Action: Create job
  - Parameters:
    - Repo URL or bundle path
    - Script: `python run_pipeline.py --log-level INFO`
    - Variables/credentials mapped to env vars

3) Optional: Pass file metadata to the runner
- Inputs: Site URL, Library ID, File Path, File Name
- Runner pre-step downloads file into `raw policies/` or `raw_guides/` using Graph API

4) Wait for Completion (optional)
- Poll job status until Succeeded/Failed

5) Notifications
- On Success: Post message to Teams channel
- On Failure: Send email/Teams with logs link and error summary

---

### Error Handling
- Add a parallel branch for `hasFailed` conditions
- Provide run details: document name, site, library, job ID, time

---

### Security & Governance
- Restrict flow ownership to the platform team
- Use Managed Identities or Key Vault for secrets
- Limit concurrency to avoid duplicate runs (Power Automate → Settings → Concurrency control)

---

### Quick Test Variant
- Temporarily set Command to `python run_pipeline.py --dry-run --skip-ai --log-level INFO`
- Validate outputs and indexes update without vector store writes
