#!/usr/bin/env python3
"""Enhance policy metadata with AI-generated questions using change detection."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

try:  # pragma: no cover - optional dependency handling
    import dotenv
except ImportError:  # pragma: no cover
    dotenv = None  # type: ignore

try:  # pragma: no cover - optional dependency handling
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore

from scripts.utils.state import (
    VectorState,
    compute_content_hash_from_data,
    ensure_state_file,
)

ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "Policy_Documents_Metadata_Index.json"
JSON_DIR = ROOT / "VECTOR_JSON"
STATE_PATH = ROOT / "state/vector_state.json"
PRIMARY_ENV = ROOT / ".env"
FALLBACK_ENV = ROOT / "iSPOC" / ".env"
MODEL_NAME = "gpt-4.1-mini"
DEFAULT_SAVE_INTERVAL = 5


@dataclass
class PlanItem:
    entry: Dict[str, Any]
    json_filename: str
    json_path: Path
    payload: Optional[Dict[str, Any]]
    content_hash: Optional[str]
    action: str  # "update" | "skip"
    reason: Optional[str] = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-file", type=Path, default=STATE_PATH)
    parser.add_argument("--dry-run", action="store_true", help="Show planned updates without calling OpenAI or writing files")
    parser.add_argument("--force", action="store_true", help="Regenerate questions even when content hash unchanged")
    parser.add_argument("--only", nargs="+", help="Limit regeneration to matching document titles or filenames")
    parser.add_argument("--sleep", type=float, default=1.0, help="Delay between OpenAI calls (seconds)")
    parser.add_argument("--save-interval", type=int, default=DEFAULT_SAVE_INTERVAL, help="Write index to disk every N updates (default 5)")
    return parser.parse_args()


def current_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def backup_index(index_path: Path) -> Optional[Path]:
    if not index_path.exists():
        return None
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = index_path.with_name(f"{index_path.stem}_{timestamp}.json")
    try:
        shutil.copy2(index_path, backup_path)
        print(f"Created backup at {backup_path}")
        return backup_path
    except Exception as exc:  # pragma: no cover - filesystem errors
        print(f"Warning: unable to create backup: {exc}")
        return None


def load_openai_key() -> str:
    loaded = False
    if dotenv:
        if PRIMARY_ENV.exists():
            loaded = dotenv.load_dotenv(PRIMARY_ENV, override=False)
        if not loaded and FALLBACK_ENV.exists():
            loaded = dotenv.load_dotenv(FALLBACK_ENV, override=False)
        if not loaded:
            try:
                discovered = dotenv.find_dotenv()  # type: ignore[attr-defined]
            except AttributeError:
                discovered = ""
            if discovered:
                dotenv.load_dotenv(discovered, override=False)
    api_key = os.getenv("VITE_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OpenAI API key not found. Set VITE_OPENAI_API_KEY or OPENAI_API_KEY.")
    return api_key


def load_policy_index(index_path: Path) -> Dict[str, Any]:
    if not index_path.exists():
        raise FileNotFoundError(f"Policy index not found: {index_path}")
    with index_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_policy_index(index_data: Dict[str, Any], index_path: Path) -> None:
    with index_path.open("w", encoding="utf-8") as handle:
        json.dump(index_data, handle, indent=4, ensure_ascii=False)


def prepare_content_for_ai(policy_json: Dict[str, Any]) -> str:
    content: List[str] = []
    title = policy_json.get("title", "")
    policy_id = policy_json.get("id", "")
    content.append(f"Policy: {title} (ID: {policy_id})")

    sections = policy_json.get("sections", {}) or {}
    for section_name, section_text in sections.items():
        if section_text:
            text = str(section_text)
            content.append(f"{section_name.upper()}: {text[:1000]}")

    if len(content) < 3 and policy_json.get("full_text"):
        content.append(f"CONTENT EXCERPT: {policy_json['full_text'][:2000]}")
    return "\n\n".join(content)


def generate_questions_with_openai(client: Any, policy_content: str) -> List[str]:
    try:
        response = client.chat.completions.create(  # type: ignore[attr-defined]
            model=MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert in healthcare policy analysis. Identify the"
                        " 3 most important practical questions this policy answers."
                        " Return ONLY a JSON array of 3 questions."
                    ),
                },
                {"role": "user", "content": policy_content},
            ],
            response_format={"type": "json_object"},
            temperature=0.5,
            max_tokens=500,
        )
        result = response.choices[0].message.content  # type: ignore[index]
        if not result:
            raise ValueError("Empty response from OpenAI")
        try:
            payload = json.loads(result)
        except json.JSONDecodeError:
            raise ValueError(f"Failed to parse JSON response: {result}")
        if isinstance(payload, list):
            return [str(item) for item in payload][:3]
        if isinstance(payload, dict):
            if "questions" in payload and isinstance(payload["questions"], list):
                return [str(item) for item in payload["questions"]][:3]
            for value in payload.values():
                if isinstance(value, list) and value:
                    return [str(item) for item in value][:3]
        raise ValueError(f"Unexpected response format: {payload}")
    except Exception as exc:
        print(f"Error calling OpenAI API: {exc}")
        return [
            "What procedures are outlined in this policy?",
            "What responsibilities are assigned in this policy?",
            "How is compliance with this policy monitored?",
        ]


def _matches_filters(json_filename: str, file_field: str, document: str, filters: Optional[Sequence[str]]) -> bool:
    if not filters:
        return True
    lowered = {item.lower() for item in filters}
    return (
        json_filename.lower() in lowered
        or file_field.lower() in lowered
        or document.lower() in lowered
    )


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def collect_plan(
    documents: Iterable[Dict[str, Any]],
    state: VectorState,
    *,
    force: bool,
    filters: Optional[Sequence[str]] = None,
) -> List[PlanItem]:
    plan: List[PlanItem] = []
    for entry in documents:
        file_field = entry.get("File", "")
        document_name = entry.get("Document", "Unknown")
        if not file_field:
            plan.append(
                PlanItem(
                    entry=entry,
                    json_filename="",
                    json_path=Path(),
                    payload=None,
                    content_hash=None,
                    action="skip",
                    reason="missing_file",
                )
            )
            continue

        json_filename = file_field.replace(".txt", ".json") if file_field.endswith(".txt") else file_field
        json_path = JSON_DIR / json_filename

        if not _matches_filters(json_filename, file_field, document_name, filters):
            continue

        if not json_path.exists():
            plan.append(
                PlanItem(
                    entry=entry,
                    json_filename=json_filename,
                    json_path=json_path,
                    payload=None,
                    content_hash=None,
                    action="skip",
                    reason="json_not_found",
                )
            )
            continue

        try:
            payload = _load_json(json_path)
        except Exception as exc:
            plan.append(
                PlanItem(
                    entry=entry,
                    json_filename=json_filename,
                    json_path=json_path,
                    payload=None,
                    content_hash=None,
                    action="skip",
                    reason=f"load_error: {exc}",
                )
            )
            continue

        content_hash = compute_content_hash_from_data(payload)
        state_entry = state.get(json_filename) or {}
        previous_hash = (
            state_entry.get("policyQuestionsHash")
            or state_entry.get("questionsHash")
        )

        if not force and previous_hash == content_hash:
            plan.append(
                PlanItem(
                    entry=entry,
                    json_filename=json_filename,
                    json_path=json_path,
                    payload=payload,
                    content_hash=content_hash,
                    action="skip",
                    reason="unchanged",
                )
            )
            continue

        plan.append(
            PlanItem(
                entry=entry,
                json_filename=json_filename,
                json_path=json_path,
                payload=payload,
                content_hash=content_hash,
                action="update",
                reason=None,
            )
        )
    return plan


def main() -> int:
    args = parse_args()

    ensure_state_file(args.state_file)
    state = VectorState(args.state_file)

    index_data = load_policy_index(INDEX_PATH)
    documents = index_data.get("Policy Documents", [])
    if not documents:
        print("No policies found in index file.")
        return 0

    plan = collect_plan(documents, state, force=args.force, filters=args.only)
    updates = [item for item in plan if item.action == "update"]
    skips = [item for item in plan if item.action == "skip"]

    total_considered = len(plan)
    print(f"Policies considered: {total_considered}; to update: {len(updates)}; skipped: {len(skips)}")

    if not updates:
        if not plan and args.only:
            print("No policies matched the provided filters.")
        else:
            for item in skips:
                doc_title = item.entry.get("Document", item.json_filename or "Unknown")
                reason = item.reason or "skip"
                print(f"Skipping {doc_title} ({item.json_filename}): {reason}")
            print("All policy questions are up to date.")
        return 0

    if args.dry_run:
        for item in updates:
            doc_title = item.entry.get("Document", item.json_filename)
            print(f"[DRY-RUN] Would regenerate questions for {doc_title} ({item.json_filename})")
        return 0

    if OpenAI is None:
        raise RuntimeError("openai package is not installed. Run `pip install -r scripts/requirements.txt`.")

    api_key = load_openai_key()
    client = OpenAI(api_key=api_key)  # type: ignore[call-arg]

    backup_index(INDEX_PATH)

    updated_count = 0
    state_dirty = False

    for idx, item in enumerate(plan, start=1):
        doc_title = item.entry.get("Document", item.json_filename or "Unknown")
        print("\n" + "=" * 80)
        print(f"Processing [{idx}/{len(plan)}]: {doc_title}")
        print("=" * 80)

        if item.action != "update":
            reason = item.reason or "skip"
            print(f"Skipping: {reason}")
            continue

        payload = item.payload or {}
        policy_content = prepare_content_for_ai(payload)
        questions = generate_questions_with_openai(client, policy_content)

        item.entry["Questions Answered"] = questions
        timestamp = current_timestamp()
        state.set_metadata(
            item.json_filename,
            policyQuestionsHash=item.content_hash,
            policyQuestionsUpdatedAt=timestamp,
        )
        state_dirty = True
        updated_count += 1

        print("Generated questions:")
        for i, question in enumerate(questions, start=1):
            print(f"  {i}. {question}")

        if args.save_interval > 0 and updated_count % args.save_interval == 0:
            save_policy_index(index_data, INDEX_PATH)
            print(f"Saved progress after {updated_count} updates")

        if args.sleep > 0 and idx < len(plan):
            time.sleep(args.sleep)

    save_policy_index(index_data, INDEX_PATH)
    if state_dirty:
        state.save()

    print(f"\nUpdated questions for {updated_count} policies.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
