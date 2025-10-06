#!/usr/bin/env python3
"""Reconcile OpenAI Vector Store with local combined index by removing stale entries.

- Lists files in the target vector store and compares their external_id to the
  set of filenames in MHA_Documents_Metadata_Index.json
- Plans deletions for items not present in the combined index
- Supports --dry-run, retries, and updates local state on successful deletion
- Prefers TEST_VECTOR_STORE_ID when selecting the store id
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from dataclasses import dataclass
from typing import NamedTuple

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv(*_args: Any, **_kwargs: Any) -> bool:  # type: ignore
        return False

import httpx

from scripts.utils.state import VectorState, ensure_state_file

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMBINED_INDEX = ROOT / "MHA_Documents_Metadata_Index.json"
DEFAULT_STATE_PATH = ROOT / "state/vector_state.json"
OPENAI_BASE_URL = "https://api.openai.com/v1"


def log_event(event: str, **payload: Any) -> None:
    logging.info(json.dumps({"event": event, **payload}, default=str))


def load_env(root: Path) -> None:
    primary = root / ".env"
    fallback = root / "iSPOC" / ".env"
    if primary.exists():
        load_dotenv(primary, override=False)
    if fallback.exists():
        load_dotenv(fallback, override=False)


def load_combined_index(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    documents = payload.get("MHA Documents")
    if not isinstance(documents, list):
        raise ValueError(f"Combined index {path} is missing 'MHA Documents' array")
    return documents


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--combined-index", type=Path, default=DEFAULT_COMBINED_INDEX)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--vector-store-id", type=str, default=None)
    parser.add_argument("--dry-run", action="store_true", help="Plan deletions without mutating vector store or state")
    parser.add_argument("--include-unknown", action="store_true", help="Also delete items missing external_id metadata")
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--retry-base-delay", type=float, default=1.5)
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


def backoff_sleep(attempt: int, *, base_delay: float) -> None:
    time.sleep(base_delay * (2 ** attempt))


def with_retries(func, *, retries: int, base_delay: float, action: str, context: Dict[str, Any]) -> Any:
    for attempt in range(retries + 1):
        try:
            return func()
        except Exception as exc:  # pragma: no cover
            log_event("operation.retry", action=action, attempt=attempt, error=str(exc), context=context)
            if attempt >= retries:
                raise
            backoff_sleep(attempt + 1, base_delay=base_delay)
    raise RuntimeError("unreachable")


def resolve_vector_store_id(args: argparse.Namespace) -> Tuple[str, str]:
    env_test_ids = [os.getenv("TEST_VECTOR_STORE_ID"), os.getenv("VITE_TEST_VECTOR_STORE_ID")]
    env_prod_ids = [
        os.getenv("VECTOR_STORE_ID"),
        os.getenv("VITE_OPENAI_VECTOR_STORE_ID"),
        os.getenv("VITE_VECTOR_STORE_ID"),
    ]
    vector_store_id = (
        args.vector_store_id
        or next((v for v in env_test_ids if v), None)
        or next((v for v in env_prod_ids if v), None)
    )
    source = (
        "arg" if args.vector_store_id else ("test-env" if next((v for v in env_test_ids if v), None) else "prod-env")
    )
    if not vector_store_id:
        raise RuntimeError(
            "Vector store id not provided. Use --vector-store-id or set TEST_VECTOR_STORE_ID (preferred) "
            "or VECTOR_STORE_ID (fallback)."
        )
    return vector_store_id, source


def http_client(api_key: str) -> httpx.Client:
    return httpx.Client(
        base_url=OPENAI_BASE_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout=30.0,
    )


# Exported for tests
@dataclass
class VectorFileRecord:
    file_id: str
    external_id: Optional[str]
    metadata: Dict[str, Any]
    reason: Optional[str] = None
    remove_state: bool = False

class ReconcilePlan(NamedTuple):
    deletions: List[VectorFileRecord]
    state_only_removals: List[str]

# Test helper: accept a dummy client that yields dict items
def list_vector_files(client_like: Any) -> List[VectorFileRecord]:
    records: List[VectorFileRecord] = []
    # Expect an iterator over dicts with id/metadata
    iterator = getattr(client_like, "iter_files", None)
    if callable(iterator):
        for item in iterator():
            fid = item.get("id")
            meta = item.get("metadata") or {}
            eid = meta.get("external_id") if isinstance(meta, dict) else None
            records.append(VectorFileRecord(file_id=fid, external_id=eid, metadata=meta))
    return records

# Test helper: compute reconciliation plan from records + combined index
def plan_reconciliation(records: List[VectorFileRecord], allowed_files: List[str], state: VectorState) -> ReconcilePlan:
    deletions: List[VectorFileRecord] = []
    state_only_removals: List[str] = []

    # Track duplicates by external_id
    seen: Dict[str, str] = {}
    for rec in records:
        if not rec.external_id:
            continue
        if rec.external_id in seen:
            # duplicate file for same external_id → delete the newer one
            deletions.append(VectorFileRecord(file_id=rec.file_id, external_id=rec.external_id, metadata={}, reason="duplicate_external_id", remove_state=False))
        else:
            seen[rec.external_id] = rec.file_id

    # Orphans: in state but not allowed anymore
    for eid, entry in state.docs.items():
        if eid not in allowed_files:
            deletions.append(VectorFileRecord(file_id=entry.get("fileId", ""), external_id=eid, metadata={}, reason="not_in_combined_index", remove_state=True))

    return ReconcilePlan(deletions=deletions, state_only_removals=state_only_removals)


def list_vector_store_files_httpx(client: httpx.Client, vector_store_id: str) -> List[Dict[str, Any]]:
    files: List[Dict[str, Any]] = []
    after: Optional[str] = None
    while True:
        params = {"limit": 100}
        if after:
            params["after"] = after
        resp = client.get(f"/vector_stores/{vector_store_id}/files", params=params)
        resp.raise_for_status()
        payload = resp.json()
        data = payload.get("data", [])
        for item in data:
            file_id = item.get("id")
            metadata = item.get("metadata") or {}
            external_id = metadata.get("external_id") if isinstance(metadata, dict) else None
            files.append({"id": file_id, "external_id": external_id})
        if not payload.get("has_more"):
            break
        after = payload.get("last_id")
        if not after:
            break
    return files


def delete_vector_store_file_httpx(client: httpx.Client, vector_store_id: str, file_id: str) -> None:
    resp = client.delete(f"/vector_stores/{vector_store_id}/files/{file_id}")
    resp.raise_for_status()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=args.log_level.upper(), format="%(message)s")
    load_env(ROOT)

    ensure_state_file(args.state_file)
    state = VectorState(args.state_file)

    vector_store_id, source = resolve_vector_store_id(args)
    log_event("reconcile.config", vectorStoreId=vector_store_id, source=source)

    api_key = os.getenv("VITE_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OpenAI API key not found. Set VITE_OPENAI_API_KEY or OPENAI_API_KEY.")

    client = http_client(api_key)

    index_docs = load_combined_index(args.combined_index)
    allowed_external_ids = {doc.get("File") for doc in index_docs if doc.get("File")}

    # Determine deletions from local state first (authoritative)
    stale_external_ids = [eid for eid in state.docs.keys() if eid not in allowed_external_ids]
    to_delete: List[Dict[str, Any]] = []
    for eid in stale_external_ids:
        entry = state.get(eid) or {}
        file_id = entry.get("fileId")
        if file_id:
            to_delete.append({"id": file_id, "external_id": eid, "source": "state"})

    # Optionally list vector store files to find unknowns not tracked in state
    unknowns: List[Dict[str, Any]] = []
    files = list_vector_store_files_httpx(client, vector_store_id)
    for f in files:
        eid = f.get("external_id")
        if not eid and args.include_unknown:
            unknowns.append({"id": f.get("id"), "external_id": None, "source": "unknown"})
            continue
        if eid and eid not in allowed_external_ids and eid not in state.docs:
            if args.include_unknown:
                unknowns.append({"id": f.get("id"), "external_id": eid, "source": "unknown"})

    log_event(
        "reconcile.list",
        counts={
            "vectorFiles": len(files),
            "allowedExternalIds": len(allowed_external_ids),
            "staleByState": len(stale_external_ids),
            "unknownFiles": len(unknowns),
        },
    )

    if args.include_unknown:
        to_delete.extend(unknowns)

    log_event("reconcile.plan", toDelete=len(to_delete))
    for f in to_delete[:50]:
        log_event("reconcile.item", externalId=f.get("external_id"), fileId=f.get("id"), source=f.get("source"))

    if args.dry_run:
        log_event("reconcile.complete", dryRun=True)
        return 0

    failures: List[Dict[str, Any]] = []
    for f in to_delete:
        file_id = f.get("id")
        eid = f.get("external_id")
        try:
            with_retries(
                lambda: delete_vector_store_file_httpx(client, vector_store_id, file_id),
                retries=args.max_retries,
                base_delay=args.retry_base_delay,
                action="delete",
                context={"externalId": eid, "fileId": file_id},
            )
            log_event("reconcile.deleted", externalId=eid, fileId=file_id)
            if eid and state.get(eid):
                state.remove(eid)
        except Exception as exc:  # pragma: no cover
            failures.append({"externalId": eid, "fileId": file_id, "error": str(exc)})
            log_event("reconcile.error", externalId=eid, fileId=file_id, error=str(exc))

    if failures:
        state.save()
        log_event("reconcile.complete", dryRun=False, failures=failures)
        return 1

    state.save()
    log_event("reconcile.complete", dryRun=False)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as err:
        logging.basicConfig(level=logging.ERROR, format="%(message)s")
        log_event("reconcile.failed", error=str(err))
        sys.exit(1)
