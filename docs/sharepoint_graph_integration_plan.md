## SharePoint Graph Integration Plan

**Audience**: Danny + Azure Function owners  
**Goal**: Run the full iSPoC pipeline against a SharePoint library via Microsoft Graph, triggered from Power Automate. Provide both Plan A (client secret with MSAL) and Plan B (Managed Identity) so the team can start quickly and then harden.

---

## 1. Repo & Packaging Prep

1. Treat `client-pipeline` as a package (add `client_pipeline/__init__.py`, optional `pyproject.toml`).  
2. Update imports to use `client_pipeline.scripts...` so Azure Functions can import shared code cleanly.  
3. Create `client_pipeline/docs/` if needed for this plan and future runbooks.

---

## 2. Configuration & Secrets

| Setting | Description | Applies to |
| --- | --- | --- |
| `GRAPH_TENANT_ID` | Entra tenant (GUID) | Plan A only |
| `GRAPH_CLIENT_ID` | App registration client ID | Plan A only |
| `GRAPH_CLIENT_SECRET` | Client secret; store in Key Vault or Function App configuration | Plan A only |
| `SHAREPOINT_SITE_ID` | ID from `GET /sites?search={site}` | Both |
| `SHAREPOINT_DRIVE_ID` | Library drive ID from `GET /sites/{siteId}/drives` | Both |
| `STATE_STORAGE_CONNECTION` | Connection string for Blob/Table used for change tracking | Both |
| `STATE_CONTAINER`/`STATE_TABLE` | Storage container/table name | Both |
| `USE_LOCAL_STATE` | Optional toggle for local dev (file-based state) | Dev only |

Document for Danny how to obtain `siteId` and `driveId`:
1. `GET https://graph.microsoft.com/v1.0/sites?search={siteName}` → `site.id`.
2. `GET https://graph.microsoft.com/v1.0/sites/{siteId}/drives` → identify `drive.id` for “iceberg” library.

---

## 3. Graph Utilities

Create `client_pipeline/scripts/utils/graph_client.py` with:

- Token acquisition (Plan A: MSAL client credentials; Plan B: `ManagedIdentityCredential`).
- `list_files(folder_path)` enumerating `Raw Policies` / `Raw Guides`, handling `@odata.nextLink` and optional recursion for subfolders.
- `download_file(item_id)` with retry/backoff for 429/5xx and one retry on 401/403.
- `upload_output(target_path, bytes, content_type="application/json")` with the same resiliency.
- Shared header builder so every call sets `Authorization` (+ `Content-Type` for uploads).

---

## 4. Durable Change Tracking

Implement `client_pipeline/scripts/utils/state_backend.py`:

- Interface `load_state(name) -> dict`, `should_process(name, etag, content_hash) -> bool`, `record_processed(name, etag, content_hash)`.
- Default backend: Azure Blob (JSON per run) or Azure Table (rows keyed by file).  
- Local dev fallback: JSON file when `USE_LOCAL_STATE=true`.

---

## 5. Pipeline Contract Changes

1. Define `PipelineResult` dataclass:
   ```python
   @dataclass
   class PipelineResult:
       name: str
       content: bytes
       metadata: dict
   ```
Update converters (convert_to_json.py, convert_guides_to_json.py) to accept BytesIO + metadata (filename, path hints) and return PipelineResult.
Adjust orchestrator in client_pipeline/run_pipeline.py to expose run_document_pipeline(name, stream, doc_type, etag) → returns PipelineResult plus any metrics.
Ensure downstream scripts (indexes, AI steps) consume in-memory content or known temp paths (if a temp file is unavoidable, wrap inside the orchestrator with cleanup).
## 6. Azure Function Entry Point
File: function/__init__.py.
Signature:
```python
import azure.functions as func
import logging
from client_pipeline... import graph_client, state_backend, run_document_pipeline

def main(req: func.HttpRequest) -> func.HttpResponse:
    logger = logging.getLogger("azure")
    # enumerate files, run pipeline, upload outputs, record metrics
    return func.HttpResponse("Processed X, skipped Y, failed Z", status_code=200)
```
Ensure function/function.json defines:
```json
{
  "bindings": [
    {
      "authLevel": "function",
      "type": "httpTrigger",
      "direction": "in",
      "methods": ["post"],
      "route": "sharepoint-sync",
      "name": "req"
    },
    {
      "type": "http",
      "direction": "out",
      "name": "$return"
    }
  ]
}
```
## 7. Plan A — MSAL Client Credential Flow
App Registration: Confirm the new Entra app has Sites.ReadWrite.All with admin consent.
App Settings: Populate tenant/client/secret values in Azure Functions configuration; store secret in Key Vault if possible and reference it.
Token Helper:
```python
import msal, os

_app = msal.ConfidentialClientApplication(
    os.environ["GRAPH_CLIENT_ID"],
    authority=f"https://login.microsoftonline.com/{os.environ['GRAPH_TENANT_ID']}",
    client_credential=os.environ["GRAPH_CLIENT_SECRET"],
)
def get_token():
    result = _app.acquire_token_silent(["https://graph.microsoft.com/.default"], account=None)
    if not result:
        result = _app.acquire_token_for_client(["https://graph.microsoft.com/.default"])
    if "access_token" not in result:
        raise RuntimeError(result.get("error_description"))
    return result["access_token"]
```
Function Flow:
Enumerate Raw Policies, Raw Guides.
Skip unchanged files (state backend).
Convert with pipeline.
Upload to Output JSON folder with Content-Type set.
Write processed state.
Log per-file status and final counts.
Testing: func start with sample files; curl or Power Automate test using function URL + x-functions-key.
Deployment: func azure functionapp publish <app>; monitor in Application Insights.
## 8. Plan B — Managed Identity (Preferred)
Enable MI: Turn on system-assigned managed identity in Function App.
Permissions:
Tenant admin grants Sites.Selected to Microsoft Graph application.
Execute (with Graph PowerShell):
```powershell
Connect-MgGraph -Scopes "Sites.Selected"
$mi = Get-MgServicePrincipal -Filter "appId eq '<Function App clientId>'"
Grant-MgSitePermission -SiteId "<SITE_ID>" -Roles @("read","write") `
  -GrantedToIdentities @(@{application=@{id=$mi.Id; displayName=$mi.DisplayName}})
```
Alternatively POST https://graph.microsoft.com/v1.0/sites/{siteId}/permissions with grantedToIdentities.
Token Helper:
```python
from azure.identity import ManagedIdentityCredential

credential = ManagedIdentityCredential()
def get_token():
    return credential.get_token("https://graph.microsoft.com/.default").token
```
Config Cleanup: Remove GRAPH_CLIENT_SECRET (and optional GRAPH_CLIENT_ID if unused) once MI path is validated; update documentation to reflect secretless deployment.
Function Flow: identical to Plan A aside from token acquisition.
Validation: Live HTTP trigger test to confirm read/write to SharePoint; monitor Application Insights.
## 9. Requirements & Environments
function/requirements.txt (Plan A):
```text
azure-functions==1.20.0
requests==2.32.3
msal==1.28.0
```
function/requirements.txt (Plan B):
```text
azure-functions==1.20.0
requests==2.32.3
azure-identity==1.17.0
```
Keep client-pipeline/scripts/requirements.txt aligned (add requests, msal or azure-identity as appropriate).
Re-run local install tests after adjusting requirements.

## 10. Logging & Monitoring
Use logging.getLogger("azure") for all logs; include per-file entries and final summary (processed, skipped, failed).
Add optional custom_dimensions for Application Insights queries.
Consider capturing elapsed time per file to spot bottlenecks.
## 11. Power Automate Trigger
HTTP action configured with POST to <function-url>/api/sharepoint-sync.
Header x-functions-key = Function key stored securely in Power Automate (environment variable/secret).
No Graph credentials in Power Automate; all auth handled within Azure Function.
## 12. Testing & Deployment Checklist
Local smoke test (func start) using sample documents.
Deploy to Azure via func azure functionapp publish.
Confirm configuration values in Function App (site/drive IDs, storage connection, secrets or MI).
Trigger via Power Automate/manual HTTP.
Verify uploaded JSON outputs in SharePoint Output JSON folder.
Review Application Insights logs & metrics.
Remove client secret (Plan B) once MI path validated.
## 13. Security & Governance
Prefer Managed Identity in production (Plan B); keep Plan A only for initial demos or fallback.
Store secrets (if any) in Key Vault and reference them via Function App settings.
Limit app permissions to the specific site with Sites.Selected.
Ensure logging avoids sensitive data; monitor for repeated failures (alerting in Power Automate or Azure Monitor).
## 14. Next Actions Before Tuesday Session
Package client_pipeline and add new Graph/state modules.
Implement converters’ stream interface and PipelineResult.
Choose state backend (Blob vs Table) and provision storage.
Prepare Azure Function scaffolding (host.json, function.json, requirements, init.py).
Run local smoke tests; capture notes for Monday status update.