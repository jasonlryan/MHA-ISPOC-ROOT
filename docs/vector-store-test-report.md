## Vector Store Test Report

Date: 2025-10-09

This report confirms successful execution of local tests covering vector store behaviors for policies when they are added, updated, deleted, and when the original source was non-DOCX.

### Summary
- All targeted tests passed.
- Total: 8 tests, 0 failures.

### Scope Covered
- Create/Skip/Update decisioning based on content hash.
- Reconciliation deletes for items not present in the combined index/state.
- Preservation of combined index entry.
- Handling of policy JSONs whose original filename is non-DOCX (e.g., PDF).

### Commands Used
```bash
cd /Users/rachelstubbs/Documents/MHA-ISPOC-ROOT
source .venv/bin/activate
python -m pytest -q scripts/tests/test_vector_store_upsert.py scripts/tests/test_reconcile_vector_store.py
```

### Latest Run Output
```text
........                                                                                             [100%]
8 passed in 0.29s
```

### Key Test Assertions
- Create/Skip/Update outcomes verified in `scripts/tests/test_vector_store_upsert.py`:
  - Ensures new → create; same hash → skip; changed content → update.
- Non-DOCX handling verified in `scripts/tests/test_vector_store_upsert.py`:
  - Accepts JSON where `filename` ends with `.pdf`; item processed as Policy.
- Deletion behavior verified in `scripts/tests/test_reconcile_vector_store.py`:
  - Deletes duplicates and orphans; preserves combined index.

### How To Reproduce Locally
1) Ensure virtual environment and dependencies are installed:
```bash
/usr/bin/python3 -m venv .venv && source .venv/bin/activate
python -m pip install -r scripts/requirements.txt pytest
```
2) Run the tests:
```bash
python -m pytest -q scripts/tests/test_vector_store_upsert.py scripts/tests/test_reconcile_vector_store.py
```


