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

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv(*_args: Any, **_kwargs: Any) -> bool:  # type: ignore
        return False

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore

from scripts.utils.state import VectorState, ensure_state_file

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMBINED_INDEX = ROOT / "MHA_Documents_Metadata_Index.json"
DEFAULT_STATE_PATH = ROOT / "state/vector_state.json"


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


def list_vector_store_files(client: Any, vector_store_id: str) -> List[Dict[str, Any]]:
    files: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    while True:
        result = client.beta.vector_stores.files.list(  # type: ignore[attr-defined]
            vector_store_id=vector_store_id,
            after=cursor,
            limit=100,
        )
        # Support attr and dict access
        data = getattr(result, "data", None) or result.get("data", [])
        for file_obj in data:
            file_id = getattr(file_obj, "id", None) or file_obj.get("id")
            metadata = getattr(file_obj, "metadata", None) or file_obj.get("metadata", {})
            external_id = None
            if isinstance(metadata, dict):
                external_id = metadata.get("external_id")
            files.append({"id": file_id, "external_id": external_id, "raw": file_obj})
        # Pagination
        has_more = getattr(result, "has_more", None)
        if has_more is None:
            has_more = result.get("has_more", False)
        if not has_more:
            break
        # Determine next cursor if available
        cursor = getattr(result, "last_id", None) or result.get("last_id")
        if not cursor:  # no cursor available
            break
    return files


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=args.log_level.upper(), format="%(message)s")
    load_env(ROOT)

    ensure_state_file(args.state_file)
    state = VectorState(args.state_file)

    vector_store_id, source = resolve_vector_store_id(args)
    log_event("reconcile.config", vectorStoreId=vector_store_id, source=source)

    # API key
    api_key = os.getenv("VITE_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if OpenAI is None:
        raise RuntimeError("openai package is not installed. Install requirements before running.")
    if not api_key:
        raise RuntimeError("OpenAI API key not found. Set VITE_OPENAI_API_KEY or OPENAI_API_KEY.")

    client = OpenAI(api_key=api_key)

    # Load combined index and derive allowed external_ids
    index_docs = load_combined_index(args.combined_index)
    allowed_external_ids = {doc.get("File") for doc in index_docs if doc.get("File")}

    # List vector store files
    files = list_vector_store_files(client, vector_store_id)
    log_event("reconcile.list", counts={"vectorFiles": len(files), "allowedExternalIds": len(allowed_external_ids)})

    # Determine deletions
    to_delete: List[Dict[str, Any]] = []
    for f in files:
        eid = f.get("external_id")
        if eid is None and not args.include_unknown:
            continue
        if (eid is None) or (eid not in allowed_external_ids):
            to_delete.append(f)

    log_event("reconcile.plan", toDelete=len(to_delete))
    for f in to_delete[:50]:  # cap listing
        log_event("reconcile.item", externalId=f.get("external_id"), fileId=f.get("id"))

    if args.dry_run:
        log_event("reconcile.complete", dryRun=True)
        return 0

    # Perform deletions
    failures: List[Dict[str, Any]] = []
    for f in to_delete:
        file_id = f.get("id")
        eid = f.get("external_id")
        try:
            with_retries(
                lambda: client.beta.vector_stores.files.delete(vector_store_id=vector_store_id, file_id=file_id),  # type: ignore[attr-defined]
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
        state.save()  # save any successful removals
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
