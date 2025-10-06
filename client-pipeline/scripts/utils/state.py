"""Utilities for canonical JSON hashing and vector store state management."""

from __future__ import annotations

import json
import hashlib
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional, Set

_DEFAULT_VOLATILE_FIELDS: Set[str] = {"extracted_date"}


def _strip_volatile_fields(data: Any, volatile_fields: Set[str]) -> Any:
    """Recursively remove volatile keys from JSON-like data structures."""
    if isinstance(data, Mapping):
        cleaned: Dict[str, Any] = {}
        for key, value in data.items():
            if key in volatile_fields:
                continue
            cleaned[key] = _strip_volatile_fields(value, volatile_fields)
        return cleaned
    if isinstance(data, list):
        return [_strip_volatile_fields(item, volatile_fields) for item in data]
    return data


def canonicalize_json(data: Any, volatile_fields: Optional[Iterable[str]] = None) -> str:
    """Return a canonical JSON string with sorted keys and volatile fields removed."""
    fields = set(volatile_fields) if volatile_fields is not None else _DEFAULT_VOLATILE_FIELDS
    cleaned = _strip_volatile_fields(data, fields)
    return json.dumps(cleaned, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def compute_content_hash_from_data(data: Any, volatile_fields: Optional[Iterable[str]] = None) -> str:
    """Compute a SHA-256 hash for JSON-serializable data after canonicalization."""
    canonical = canonicalize_json(data, volatile_fields)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_content_hash_from_path(path: Path, volatile_fields: Optional[Iterable[str]] = None) -> str:
    """Load JSON from ``path`` and compute its canonical content hash."""
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return compute_content_hash_from_data(data, volatile_fields)


def _atomic_write_json(path: Path, payload: MutableMapping[str, Any]) -> None:
    """Write ``payload`` to ``path`` using an atomic temp-file swap."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(path.parent)) as handle:
        handle.write(serialized)
        temp_name = handle.name
    os.replace(temp_name, path)


class VectorState:
    """Helper for reading and writing ``state/vector_state.json``."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._data: Dict[str, Any] = {"docs": {}}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            with self.path.open("r", encoding="utf-8") as handle:
                loaded = json.load(handle)
                if isinstance(loaded, Mapping):
                    self._data = {"docs": dict(loaded.get("docs", {}))}

    @property
    def docs(self) -> Dict[str, Any]:
        return self._data["docs"]

    def get(self, external_id: str) -> Optional[Dict[str, Any]]:
        return self.docs.get(external_id)

    def upsert(self, external_id: str, *, file_id: str, content_hash: str, last_synced_at: Optional[str] = None, **metadata: Any) -> Dict[str, Any]:
        entry: Dict[str, Any] = {
            "fileId": file_id,
            "contentHash": content_hash,
            "lastSyncedAt": last_synced_at or self._utc_timestamp(),
        }
        entry.update(metadata)
        self.docs[external_id] = entry
        return entry

    def set_metadata(self, external_id: str, **metadata: Any) -> Dict[str, Any]:
        """Merge arbitrary metadata into the stored entry for ``external_id``."""
        entry = dict(self.docs.get(external_id, {}))
        entry.update(metadata)
        self.docs[external_id] = entry
        return entry

    def remove(self, external_id: str) -> None:
        self.docs.pop(external_id, None)

    def to_dict(self) -> Dict[str, Any]:
        return {"docs": dict(self.docs)}

    def save(self) -> None:
        _atomic_write_json(self.path, self.to_dict())

    @staticmethod
    def _utc_timestamp() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ensure_state_file(path: Path) -> None:
    """Ensure a state file exists at ``path`` with the default structure."""
    target = Path(path)
    if target.exists():
        return
    _atomic_write_json(target, {"docs": {}})
