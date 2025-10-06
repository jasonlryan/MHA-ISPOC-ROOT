#!/usr/bin/env python3
"""Quick environment checker for the MHA automation pipeline."""

from __future__ import annotations

import argparse
import json
import os
from importlib import util as importlib_util
from pathlib import Path
from typing import Dict, Mapping, MutableMapping

try:  # pragma: no cover - optional dependency
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "state/vector_state.json"
PRIMARY_ENV = ROOT / ".env"
FALLBACK_ENV = ROOT / "iSPOC/.env"
REQUIRED_MODULES = ["openai", "jsonschema", "httpx"]


def load_env_files() -> None:
    if load_dotenv is None:
        return
    if PRIMARY_ENV.exists():
        load_dotenv(PRIMARY_ENV, override=False)
    if FALLBACK_ENV.exists():
        load_dotenv(FALLBACK_ENV, override=False)


def _module_available(name: str) -> bool:
    return importlib_util.find_spec(name) is not None


def collect_status(*, root: Path, env: Mapping[str, str]) -> Dict[str, object]:
    openai_key = env.get("VITE_OPENAI_API_KEY") or env.get("OPENAI_API_KEY")
    test_store_id = env.get("TEST_VECTOR_STORE_ID")
    prod_store_id = env.get("VITE_OPENAI_VECTOR_STORE_ID") or env.get("VECTOR_STORE_ID")

    modules_status = {name: _module_available(name) for name in REQUIRED_MODULES}
    missing_modules = [name for name, available in modules_status.items() if not available]

    state_path = root / "state/vector_state.json"
    state_exists = state_path.exists()

    return {
        "openai_key_present": bool(openai_key),
        "test_vector_store_id_present": bool(test_store_id),
        "production_vector_store_id_present": bool(prod_store_id),
        "state_file_exists": state_exists,
        "state_file_path": str(state_path),
        "modules": modules_status,
        "missing_modules": missing_modules,
    }


def format_human(status: Mapping[str, object]) -> str:
    lines = []
    lines.append("Environment check summary:\n")
    lines.append(f"- OpenAI API key present: {'yes' if status['openai_key_present'] else 'no'}")
    lines.append(
        f"- TEST_VECTOR_STORE_ID present: {'yes' if status['test_vector_store_id_present'] else 'no'}"
    )
    lines.append(
        f"- Production vector store id present: {'yes' if status['production_vector_store_id_present'] else 'no'}"
    )
    state_exists = status.get("state_file_exists", False)
    lines.append(
        f"- State file exists ({status['state_file_path']}): {'yes' if state_exists else 'no'}"
    )
    missing_modules = status.get("missing_modules", [])
    lines.append(
        "- Required modules installed: "
        + ("yes" if not missing_modules else f"missing {', '.join(missing_modules)}")
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_env_files()
    status = collect_status(root=ROOT, env=os.environ)

    if args.json:
        print(json.dumps(status, indent=2))
    else:
        print(format_human(status))

    ok = (
        status["openai_key_present"]
        and status["test_vector_store_id_present"]
        and not status["missing_modules"]
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
