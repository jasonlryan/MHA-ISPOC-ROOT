# iSPoC working session with Danny

Thu, 02 Oct 25

### Progress on automating the pipeline

- Decided to run the full pipeline in Azure Functions against a SharePoint library (not local folders)
- Function will authenticate to Microsoft Graph, enumerate the whole library, and process all files while skipping unchanged ones (hash/etag/state)
- Initial trigger likely via Power Automate (per-file or HTTP), but each run processes the entire library; timer trigger is also an option
- Identified code changes needed to use Graph instead of local I/O

### What we set up live

Progress on automating the pipeline

- Decided to run the full pipeline in Azure Functions against a SharePoint library (not local folders)
- Agreed the function will authenticate to Microsoft Graph, enumerate the whole library, and process all files while skipping unchanged ones (via hashing/etag/state)
- Chose to trigger via Power Automate (per-file or manual/HTTP) initially, but the function will process the entire library each run; a timer trigger is also an option
- Identified that scripts must be modified to use Graph (not local I/O)

What we set up live

- Azure Function App created
- Azure Functions tooling installed (Visual Studio/Code extension)
- Function App application settings configured:
  - Tenant ID
  - Client ID
  - Client Secret (from new app registration)
  - SharePoint site name/URL
  - SharePoint library name (“iceberg”)
- SharePoint library created with required folder structure (Raw Policies, Output JSON)
- requirements.txt updated to include: azure-functions, msal, requests
- Began scaffolding function files (host.json, local.settings.json, function.json, **init**.py) and discussed where Graph auth and enumeration code will live (in **init**.py and orchestrator/run_pipeline.py)
- New Entra ID app registration created:
  - App ID and client secret generated
  - Granted Microsoft Graph Sites.Read.Write.All with admin consent

Immediate next steps For Rachel

- Review the Gemini/Copilot notes Danny pasted into Teams (Nodes) to understand the code structure and Graph approach
- Prepare proposed code changes to:
  - Move file enumeration from local directories to Graph (SharePoint library)
  - Add authentication call (MSAL or Managed Identity) in orchestrator/run_pipeline.py and/or the function **init**.py
  - Adjust convert_to_json to accept file streams/bytes from Graph rather than local paths
- Confirm dependencies and version pins needed in requirements.txt (decide if msal/requests need specific versions)

For Danny

- Finish scaffolding the Azure Function project files (host.json, function.json, **init**.py) and verify they build
- Decide and implement trigger type for first test (HTTP trigger called by Power Automate is fine)
- Finalize Function App configuration:
  - Ensure all app settings are present and named consistently with code
  - Consider enabling System-Assigned Managed Identity if moving away from client secret
- Validate Entra app setup (permissions, consent); confirm site/library IDs or use Sites.Selected if tightening scope

Other next steps

- Implement Graph integration:
  - Choose auth method: ManagedIdentityCredential (preferred, secretless) or MSAL client credentials (current)
  - Write helper to acquire token and call Graph endpoints to:
    - List files/folders in the target library
    - Download file content for processing
- Add change detection/state:
  - Store processed file hashes/etags or last-processed timestamps (e.g., in Azure Table/Blob/Files.json) to skip unchanged items
- Integrate pipeline:
  - Wrap existing processing steps so they accept in-memory content or temporary files
  - Ensure outputs are written back to SharePoint (via Graph) or to Azure Blob Storage (preferred for outputs)
- Deployment and test:
  - Deploy via Azure CLI: func azure functionapp publish
  - Smoke test with a tiny subset of files; verify auth, enumeration, and output
- Governance and security:
  - If using client secrets, consider moving to Managed Identity + Sites.Selected with site-level grants
  - Optionally store secrets in Key Vault and reference from Function App settings
- Meetings:
  - Monday: 20‑minute status update to Jonathan (no demo required)
  - Tuesday: 2‑hour working session to implement Graph enumeration and first end‑to‑end run

---

Chat with meeting transcript: [https://notes.granola.ai/d/b79f96c3-d554-4e58-8a13-e028a1366fc6](https://notes.granola.ai/d/b79f96c3-d554-4e58-8a13-e028a1366fc6)