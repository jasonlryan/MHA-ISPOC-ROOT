#!/usr/bin/env python3
"""Upsert MHA documents into the OpenAI Vector Store."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv(*_args: Any, **_kwargs: Any) -> bool:  # type: ignore
        return False

try:
    from scripts.utils.state import (  # type: ignore
        VectorState,
        compute_content_hash_from_data,
        ensure_state_file,
    )
except ModuleNotFoundError:
    try:
        # Fallback when running as a file (PYTHONPATH points to scripts/)
        from utils.state import (  # type: ignore
            VectorState,
            compute_content_hash_from_data,
            ensure_state_file,
        )
    except ModuleNotFoundError:
        # Final fallback: import by file path to survive path quirks
        import importlib.util as _importlib_util
        ROOT = Path(__file__).resolve().parents[1]
        _state_path = ROOT / "scripts" / "utils" / "state.py"
        _spec = _importlib_util.spec_from_file_location("state_local", os.fspath(_state_path))
        if _spec is None or _spec.loader is None:
            raise
        _mod = _spec.loader.load_module()  # type: ignore[attr-defined]
        VectorState = getattr(_mod, "VectorState")  # type: ignore
        compute_content_hash_from_data = getattr(_mod, "compute_content_hash_from_data")  # type: ignore
        ensure_state_file = getattr(_mod, "ensure_state_file")  # type: ignore

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMBINED_INDEX = ROOT / "MHA_Documents_Metadata_Index.json"
DEFAULT_STATE_PATH = ROOT / "state/vector_state.json"
POLICY_DIR = ROOT / "VECTOR_JSON"
GUIDE_DIR = ROOT / "VECTOR_GUIDES_JSON"


def log_event(event: str, **payload: Any) -> None:
    """Emit a structured log line."""
    logging.info(json.dumps({"event": event, **payload}, default=str))


@dataclass
class DocumentWorkItem:
    external_id: str
    source_path: Path
    document_type: str
    index_record: Dict[str, Any]
    json_payload: Dict[str, Any]
    content_hash: str
    state_record: Optional[Dict[str, Any]]

    @property
    def title(self) -> str:
        return self.json_payload.get("title") or self.index_record.get("Document") or self.external_id

    @property
    def extracted_date(self) -> Optional[str]:
        return self.json_payload.get("extracted_date")

    @property
    def identity(self) -> Optional[str]:
        return self.json_payload.get("id") or self.json_payload.get("guide_number")


class VectorStoreClient:
    """Wrapper around the OpenAI client for vector store operations."""

    def __init__(self, vector_store_id: str, api_key: Optional[str] = None) -> None:
        if OpenAI is None:  # pragma: no cover
            raise RuntimeError("openai package is not installed. Install requirements before running.")
        self._client = OpenAI(api_key=api_key)
        self.vector_store_id = vector_store_id

    def upload(self, path: Path, *, external_id: str) -> str:
        """Upload ``path`` to the vector store and return the vector store file id.

        SDK does not support passing metadata on upload; we store external_id in local state.
        """
        with path.open("rb") as handle:
            created_file = self._client.files.create(
                file=handle,
                purpose="assistants",
            )
        # Extract created file id safely
        created_file_id = getattr(created_file, "id", None)
        if created_file_id is None:
            try:
                created_file_id = created_file.get("id")  # type: ignore[attr-defined]
            except Exception:
                raise RuntimeError("Could not extract id from created file response")
        # Attach to vector store
        attached = self._client.beta.vector_stores.files.create(  # type: ignore[attr-defined]
            vector_store_id=self.vector_store_id,
            file_id=created_file_id,
        )
        attached_id = getattr(attached, "id", None)
        if attached_id is None:
            try:
                attached_id = attached.get("id")  # type: ignore[attr-defined]
            except Exception:
                raise RuntimeError("Could not extract id from attach response")
        return attached_id

    def delete(self, file_id: str) -> None:
        """Delete ``file_id`` from the vector store."""
        self._client.beta.vector_stores.files.delete(  # type: ignore[attr-defined]
            vector_store_id=self.vector_store_id,
            file_id=file_id,
        )

    def iter_files(self, *, limit: int = 100) -> Iterable[Any]:  # pragma: no cover - simple wrapper
        after: Optional[str] = None
        while True:
            result = self._client.beta.vector_stores.files.list(  # type: ignore[attr-defined]
                vector_store_id=self.vector_store_id,
                limit=limit,
                after=after,
            )
            data = getattr(result, "data", result["data"])
            for item in data:
                yield item

            has_more = bool(getattr(result, "has_more", getattr(result, "hasMore", False)))
            if not has_more:
                break
            after = getattr(result, "last_id", getattr(result, "lastId", None))
            if after is None:
                break


def backoff_sleep(attempt: int, *, base_delay: float) -> None:
    time.sleep(base_delay * (2 ** attempt))


def with_retries(func, *, retries: int = 3, base_delay: float = 1.0, action: str, context: Dict[str, Any]) -> Any:
    for attempt in range(retries + 1):
        try:
            return func()
        except Exception as exc:  # pragma: no cover - network errors hard to unit test
            log_event(
                "operation.retry",
                action=action,
                attempt=attempt,
                error=str(exc),
                context=context,
            )
            if attempt >= retries:
                raise
            backoff_sleep(attempt + 1, base_delay=base_delay)
    raise RuntimeError("unreachable")


def load_env(root: Path) -> None:
    """Load environment variables from .env files."""
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


def load_combined_index_payload(path: Path) -> Dict[str, Any]:
    """Load the full combined index payload from disk."""
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def normalize_combined_index_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of the combined index payload with documents sorted by filename.

    Sorting ensures reordering does not trigger unnecessary uploads.
    """
    documents = payload.get("MHA Documents")
    if not isinstance(documents, list):
        raise ValueError("Combined index payload is missing 'MHA Documents' array")
    # Create a shallow copy to avoid mutating the original structure
    normalized: Dict[str, Any] = dict(payload)
    normalized_docs = sorted(documents, key=lambda d: (d or {}).get("File") or "")
    normalized["MHA Documents"] = normalized_docs
    return normalized


def resolve_source_path(document_type: str, file_name: str) -> Path:
    directory = POLICY_DIR if document_type.lower() == "policy" else GUIDE_DIR
    return directory / file_name


def build_work_items(documents: Iterable[Dict[str, Any]], state: VectorState) -> List[DocumentWorkItem]:
    items: List[DocumentWorkItem] = []
    for record in documents:
        file_name = record.get("File")
        if not file_name:
            raise ValueError("Combined index entry missing 'File'")
        document_type = record.get("Document Type", "Policy")
        source_path = resolve_source_path(document_type, file_name)
        if not source_path.exists():
            raise FileNotFoundError(f"Source JSON not found for {file_name} at {source_path}")
        with source_path.open("r", encoding="utf-8") as handle:
            json_payload = json.load(handle)
        content_hash = compute_content_hash_from_data(json_payload)
        external_id = file_name
        state_record = state.get(external_id)
        items.append(
            DocumentWorkItem(
                external_id=external_id,
                source_path=source_path,
                document_type=document_type,
                index_record=record,
                json_payload=json_payload,
                content_hash=content_hash,
                state_record=state_record,
            )
        )
    return items


def build_index_work_item(combined_index_path: Path, state: VectorState) -> DocumentWorkItem:
    """Construct a DocumentWorkItem for the combined metadata index file.

    Uses a normalized view of the payload for hashing to avoid churn from order-only changes.
    """
    payload = load_combined_index_payload(combined_index_path)
    normalized = normalize_combined_index_payload(payload)
    content_hash = compute_content_hash_from_data(normalized)
    external_id = combined_index_path.name
    state_record = state.get(external_id)
    # Minimal index_record to support title resolution
    index_record = {"Document": "MHA Documents Combined Index", "Document Type": "Index"}
    # The upsert upload uses the on-disk file (original order); hashing uses normalized payload
    return DocumentWorkItem(
        external_id=external_id,
        source_path=combined_index_path,
        document_type="Index",
        index_record=index_record,
        json_payload=payload,
        content_hash=content_hash,
        state_record=state_record,
    )


def determine_actions(items: Iterable[DocumentWorkItem]) -> Dict[str, List[DocumentWorkItem]]:
    actions = {"create": [], "update": [], "skip": []}
    for item in items:
        if not item.state_record:
            actions["create"].append(item)
        elif item.state_record.get("contentHash") != item.content_hash:
            actions["update"].append(item)
        else:
            actions["skip"].append(item)
    return actions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--combined-index", type=Path, default=DEFAULT_COMBINED_INDEX)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--vector-store-id", type=str, default=None)
    parser.add_argument("--dry-run", action="store_true", help="Plan actions without uploading or mutating state")
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--retry-base-delay", type=float, default=1.5)
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of uploads (create+update) for debugging")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=args.log_level.upper(), format="%(message)s")
    load_env(ROOT)

    ensure_state_file(args.state_file)
    state = VectorState(args.state_file)

    documents = load_combined_index(args.combined_index)
    items = build_work_items(documents, state)
    # Prepend combined index as its own managed work item
    try:
        index_item = build_index_work_item(args.combined_index, state)
        items.insert(0, index_item)
    except Exception as exc:
        log_event("planning.index.error", error=str(exc), combinedIndex=str(args.combined_index))
    actions = determine_actions(items)

    log_event(
        "planning.summary",
        totals={k: len(v) for k, v in actions.items()},
        combinedIndex=str(args.combined_index),
        stateFile=str(args.state_file),
    )

    if args.dry_run:
        for action, bucket in actions.items():
            for item in bucket:
                log_event(
                    "planning.item",
                    action=action,
                    externalId=item.external_id,
                    documentType=item.document_type,
                    contentHash=item.content_hash,
                    stateHash=item.state_record.get("contentHash") if item.state_record else None,
                )
        log_event("run.complete", dryRun=True)
        return 0

    # Resolve vector store id with test-first precedence and broad env support
    env_test_ids = [
        os.getenv("TEST_VECTOR_STORE_ID"),
        os.getenv("VITE_TEST_VECTOR_STORE_ID"),
    ]
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
        "arg" if args.vector_store_id
        else ("test-env" if next((v for v in env_test_ids if v), None) else "prod-env")
    )
    if not vector_store_id:
        raise RuntimeError(
            "Vector store id not provided. Use --vector-store-id or set TEST_VECTOR_STORE_ID (preferred) "
            "or VECTOR_STORE_ID (fallback)."
        )

    # Log which store is targeted
    log_event("vector.config", vectorStoreId=vector_store_id, source=source)

    api_key = os.getenv("VITE_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OpenAI API key not found in environment. Set VITE_OPENAI_API_KEY or OPENAI_API_KEY.")

    client = VectorStoreClient(vector_store_id=vector_store_id, api_key=api_key)

    state_dirty = False
    failures: List[Dict[str, Any]] = []

    processed = 0
    limit = max(0, args.limit)

    def perform_upload(item: DocumentWorkItem) -> str:
        return client.upload(
            item.source_path,
            external_id=item.external_id,
        )

    for action_name in ("create", "update"):
        for item in actions[action_name]:
            if limit and processed >= limit:
                break
            context = {
                "externalId": item.external_id,
                "documentType": item.document_type,
            }
            old_file_id = item.state_record.get("fileId") if item.state_record else None
            try:
                if action_name == "update" and old_file_id:
                    with_retries(
                        lambda: client.delete(old_file_id),
                        retries=args.max_retries,
                        base_delay=args.retry_base_delay,
                        action="delete",
                        context=context,
                    )
                    log_event("vector.delete", externalId=item.external_id, fileId=old_file_id)

                file_id = with_retries(
                    lambda: perform_upload(item),
                    retries=args.max_retries,
                    base_delay=args.retry_base_delay,
                    action="upload",
                    context=context,
                )
                log_event("vector.upload", externalId=item.external_id, fileId=file_id, action=action_name)
                state.upsert(
                    item.external_id,
                    file_id=file_id,
                    content_hash=item.content_hash,
                    documentType=item.document_type,
                    sourcePath=str(item.source_path.relative_to(ROOT)),
                    title=item.title,
                )
                state_dirty = True
                processed += 1
            except Exception as exc:  # pragma: no cover - network errors
                failures.append({"externalId": item.external_id, "error": str(exc)})
                log_event("vector.error", externalId=item.external_id, error=str(exc))
        if limit and processed >= limit:
            break

    if state_dirty:
        state.save()

    if failures:
        log_event("run.complete", dryRun=False, failures=failures)
        return 1

    log_event("run.complete", dryRun=False, totals={k: len(v) for k, v in actions.items()})
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as err:
        logging.basicConfig(level=logging.ERROR, format="%(message)s")
        log_event("run.failed", error=str(err))
        sys.exit(1)
