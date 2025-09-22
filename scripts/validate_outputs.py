#!/usr/bin/env python3
"""Validate generated JSON outputs and indexes against repository schemas."""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

try:
    from jsonschema import Draft202012Validator, ValidationError
    JSONSCHEMA_AVAILABLE = True
except ImportError:  # pragma: no cover
    Draft202012Validator = None  # type: ignore
    ValidationError = Exception  # type: ignore
    JSONSCHEMA_AVAILABLE = False

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMAS_DIR = ROOT / "schemas"
DEFAULT_POLICY_DIR = ROOT / "VECTOR_JSON"
DEFAULT_GUIDE_DIR = ROOT / "VECTOR_GUIDES_JSON"
DEFAULT_POLICY_INDEX = ROOT / "Policy_Documents_Metadata_Index.json"
DEFAULT_GUIDE_INDEX = ROOT / "Guide_Documents_Metadata_Index.json"
DEFAULT_COMBINED_INDEX = ROOT / "MHA_Documents_Metadata_Index.json"


@dataclass
class Dataset:
    label: str
    files: Iterable[Path]
    schema_name: str
    optional: bool = False


def log_event(event: str, **payload: Any) -> None:
    logging.info(json.dumps({"event": event, **payload}, default=str))


def load_schema(schema_dir: Path, schema_name: str) -> Draft202012Validator:
    if not JSONSCHEMA_AVAILABLE:
        raise RuntimeError("jsonschema not installed. Install requirements to use validation.")
    path = schema_dir / schema_name
    if not path.exists():
        raise FileNotFoundError(f"Schema not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)
    return Draft202012Validator(schema)


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def format_error(error: ValidationError) -> Dict[str, Any]:
    location = ".".join(str(part) for part in error.absolute_path)
    return {
        "message": error.message,
        "path": location,
        "validator": error.validator,
    }


def validate_file(path: Path, validator: Draft202012Validator) -> List[Dict[str, Any]]:
    data = read_json(path)
    if not JSONSCHEMA_AVAILABLE:
        raise RuntimeError("jsonschema not installed. Install requirements to use validation.")
    errors = [format_error(err) for err in validator.iter_errors(data)]
    return errors


def gather_files(directory: Path) -> List[Path]:
    if not directory.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")
    return sorted(p for p in directory.glob("*.json") if p.is_file())


def build_datasets(args: argparse.Namespace) -> List[Dataset]:
    datasets: List[Dataset] = [
        Dataset(
            label="policy_documents",
            files=gather_files(args.policy_dir),
            schema_name="policy_document.schema.json",
        ),
        Dataset(
            label="guide_documents",
            files=gather_files(args.guide_dir),
            schema_name="guide_document.schema.json",
        ),
        Dataset(
            label="policy_index",
            files=[args.policy_index],
            schema_name="policy_index.schema.json",
        ),
        Dataset(
            label="guide_index",
            files=[args.guide_index],
            schema_name="guide_index.schema.json",
        ),
        Dataset(
            label="combined_index",
            files=[args.combined_index],
            schema_name="combined_index.schema.json",
        ),
    ]
    return datasets


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schemas-dir", type=Path, default=DEFAULT_SCHEMAS_DIR)
    parser.add_argument("--policy-dir", type=Path, default=DEFAULT_POLICY_DIR)
    parser.add_argument("--guide-dir", type=Path, default=DEFAULT_GUIDE_DIR)
    parser.add_argument("--policy-index", type=Path, default=DEFAULT_POLICY_INDEX)
    parser.add_argument("--guide-index", type=Path, default=DEFAULT_GUIDE_INDEX)
    parser.add_argument("--combined-index", type=Path, default=DEFAULT_COMBINED_INDEX)
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=args.log_level.upper(), format="%(message)s")

    if not JSONSCHEMA_AVAILABLE:
        log_event("run.failed", error="jsonschema dependency not installed")
        return 1

    datasets = build_datasets(args)
    validators: Dict[str, Draft202012Validator] = {}
    errors_found = False

    for dataset in datasets:
        validator = validators.get(dataset.schema_name)
        if validator is None:
            validator = load_schema(args.schemas_dir, dataset.schema_name)
            validators[dataset.schema_name] = validator

        file_list = list(dataset.files)
        if not file_list:
            log_event("dataset.skip", label=dataset.label, reason="no_files")
            continue

        log_event("dataset.start", label=dataset.label, count=len(file_list))
        for path in file_list:
            try:
                validations = validate_file(path, validator)
            except FileNotFoundError:
                errors_found = True
                log_event("validation.error", label=dataset.label, file=str(path), error="file_not_found")
                continue
            if validations:
                errors_found = True
                log_event("validation.fail", label=dataset.label, file=str(path), errors=validations)
            else:
                log_event("validation.pass", label=dataset.label, file=str(path))

    if errors_found:
        log_event("run.complete", status="failed")
        return 1

    log_event("run.complete", status="passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
