#!/usr/bin/env python3
"""Orchestrate the MHA document automation pipeline."""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

# Ensure local packages are importable on CI
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, os.fspath(ROOT))

# Import helpers with multiple fallbacks to survive CI path quirks
try:
    from scripts.utils.state import ensure_state_file  # type: ignore
    from scripts.vector_store_upsert import load_env  # type: ignore
except ModuleNotFoundError:
    try:
        sys.path.insert(0, os.fspath(ROOT / "scripts"))
        from utils.state import ensure_state_file  # type: ignore
        from vector_store_upsert import load_env  # type: ignore
    except ModuleNotFoundError:
        # Final fallback: import by file path
        state_path = ROOT / "scripts" / "utils" / "state.py"
        upsert_path = ROOT / "scripts" / "vector_store_upsert.py"
        def _import_from_path(name: str, path: Path):
            spec = importlib.util.spec_from_file_location(name, os.fspath(path))
            if spec is None or spec.loader is None:
                raise ModuleNotFoundError(f"Cannot load module {name} from {path}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # type: ignore[attr-defined]
            return module
        state_mod = _import_from_path("state_local", state_path)
        upsert_mod = _import_from_path("upsert_local", upsert_path)
        ensure_state_file = getattr(state_mod, "ensure_state_file")  # type: ignore
        load_env = getattr(upsert_mod, "load_env")  # type: ignore

STATE_DIR = ROOT / "state"
DEFAULT_STATE_FILE = STATE_DIR / "vector_state.json"
DEFAULT_LOCK_PATH = STATE_DIR / "pipeline.lock"
PYTHON_EXEC = sys.executable or "python3"


@dataclass
class Step:
    name: str
    command: List[str]
    retries: int = 0
    retry_delay: float = 2.0
    cwd: Path = ROOT
    env: Dict[str, str] = field(default_factory=dict)
    skip: bool = False
    skip_reason: Optional[str] = None


def log_event(event: str, **payload: object) -> None:
    logging.info(json.dumps({"event": event, **payload}, default=str))


class PipelineLockError(RuntimeError):
    pass


class PipelineLock:
    def __init__(self, lock_path: Path, *, timeout: int, stale_seconds: int) -> None:
        self.lock_path = lock_path
        self.timeout = timeout
        self.stale_seconds = stale_seconds
        self._acquired = False

    def _is_stale(self) -> bool:
        if self.stale_seconds <= 0 or not self.lock_path.exists():
            return False
        age = time.time() - self.lock_path.stat().st_mtime
        return age > self.stale_seconds

    def _try_acquire(self) -> bool:
        path_str = os.fspath(self.lock_path)
        try:
            fd = os.open(path_str, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, f"pid={os.getpid()} time={int(time.time())}\n".encode("utf-8"))
            finally:
                os.close(fd)
            return True
        except FileExistsError:
            return False

    def acquire(self) -> None:
        deadline = time.time() + self.timeout if self.timeout > 0 else None
        while True:
            if self._try_acquire():
                self._acquired = True
                log_event("lock.acquired", path=str(self.lock_path))
                return
            if self._is_stale():
                log_event("lock.stale", path=str(self.lock_path))
                try:
                    self.lock_path.unlink()
                except OSError:
                    time.sleep(1)
                    continue
                continue
            if deadline and time.time() >= deadline:
                raise PipelineLockError(f"Could not acquire lock at {self.lock_path}")
            time.sleep(1)

    def release(self) -> None:
        if self._acquired and self.lock_path.exists():
            try:
                self.lock_path.unlink()
            finally:
                self._acquired = False
                log_event("lock.released", path=str(self.lock_path))

    def __enter__(self) -> "PipelineLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Run network/vector steps in dry-run mode")
    parser.add_argument("--skip-conversion", action="store_true", help="Skip DOCX to JSON conversion")
    parser.add_argument("--skip-index", action="store_true", help="Skip index rebuilds and combination")
    parser.add_argument("--skip-ai", action="store_true", help="Skip AI question regeneration")
    parser.add_argument("--skip-validation", action="store_true", help="Skip JSON schema validation")
    parser.add_argument("--skip-upload", action="store_true", help="Skip vector store upsert")
    parser.add_argument("--skip-reconcile", action="store_true", help="Skip vector store reconciliation")
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    parser.add_argument("--lock-path", type=Path, default=DEFAULT_LOCK_PATH)
    parser.add_argument("--lock-timeout", type=int, default=30, help="Seconds to wait for pipeline lock")
    parser.add_argument("--stale-lock-seconds", type=int, default=3600, help="Treat existing lock older than N seconds as stale")
    parser.add_argument("--max-retries", type=int, default=3, help="Max retries for network-bound steps")
    parser.add_argument("--retry-base-delay", type=float, default=2.0)
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


def build_steps(args: argparse.Namespace, *, test_vector_store_id: str) -> List[Step]:
    steps: List[Step] = []

    def add_step(name: str, script: str, extra_args: Optional[Iterable[str]] = None, *,
                 retries: int = 0, retry_delay: float = None, skip: bool = False,
                 skip_reason: Optional[str] = None) -> None:
        cmd = [PYTHON_EXEC, script]
        if extra_args:
            cmd.extend(extra_args)
        steps.append(
            Step(
                name=name,
                command=cmd,
                retries=retries,
                retry_delay=retry_delay if retry_delay is not None else args.retry_base_delay,
                skip=skip,
                skip_reason=skip_reason,
            )
        )

    state_arg = ["--state-file", str(args.state_file)]

    if not args.skip_conversion:
        add_step("convert_policies", "scripts/convert_to_json.py")
        add_step("convert_guides", "scripts/convert_guides_to_json.py")
    else:
        add_step("convert_policies", "scripts/convert_to_json.py", skip=True, skip_reason="skip_conversion")
        add_step("convert_guides", "scripts/convert_guides_to_json.py", skip=True, skip_reason="skip_conversion")

    if not args.skip_index:
        add_step("build_policy_index", "scripts/build_policy_index.py")
        add_step("build_guide_index", "scripts/build_guide_index.py")
    else:
        add_step("build_policy_index", "scripts/build_policy_index.py", skip=True, skip_reason="skip_index")
        add_step("build_guide_index", "scripts/build_guide_index.py", skip=True, skip_reason="skip_index")

    if not args.skip_validation:
        add_step("validate_outputs_initial", "scripts/validate_outputs.py")
    else:
        add_step("validate_outputs_initial", "scripts/validate_outputs.py", skip=True, skip_reason="skip_validation")

    policy_ai_args = list(state_arg)
    if args.dry_run:
        policy_ai_args.append("--dry-run")
    if not args.skip_ai:
        add_step(
            "generate_policy_questions",
            "scripts/generate_ai_questions.py",
            policy_ai_args,
            retries=args.max_retries,
        )
    else:
        add_step(
            "generate_policy_questions",
            "scripts/generate_ai_questions.py",
            policy_ai_args,
            skip=True,
            skip_reason="skip_ai",
        )

    guide_ai_args = list(state_arg)
    if args.dry_run:
        guide_ai_args.append("--dry-run")
    if not args.skip_ai:
        add_step(
            "generate_guide_questions",
            "scripts/generate_guide_ai_questions.py",
            guide_ai_args,
            retries=args.max_retries,
        )
    else:
        add_step(
            "generate_guide_questions",
            "scripts/generate_guide_ai_questions.py",
            guide_ai_args,
            skip=True,
            skip_reason="skip_ai",
        )

    if not args.skip_index:
        add_step("combine_indexes", "scripts/combine_indexes.py")
    else:
        add_step("combine_indexes", "scripts/combine_indexes.py", skip=True, skip_reason="skip_index")

    if not args.skip_validation:
        add_step("validate_outputs_final", "scripts/validate_outputs.py")
    else:
        add_step("validate_outputs_final", "scripts/validate_outputs.py", skip=True, skip_reason="skip_validation")

    upsert_args = ["--vector-store-id", test_vector_store_id, "--state-file", str(args.state_file)]
    if args.dry_run:
        upsert_args.append("--dry-run")
    if not args.skip_upload:
        add_step(
            "vector_store_upsert",
            "scripts/vector_store_upsert.py",
            upsert_args,
            retries=args.max_retries,
        )
    else:
        add_step(
            "vector_store_upsert",
            "scripts/vector_store_upsert.py",
            upsert_args,
            skip=True,
            skip_reason="skip_upload",
        )

    reconcile_args = ["--vector-store-id", test_vector_store_id, "--state-file", str(args.state_file)]
    if args.dry_run:
        reconcile_args.append("--dry-run")
    if not args.skip_reconcile:
        add_step(
            "vector_store_reconcile",
            "scripts/reconcile_vector_store.py",
            reconcile_args,
            retries=args.max_retries,
        )
    else:
        add_step(
            "vector_store_reconcile",
            "scripts/reconcile_vector_store.py",
            reconcile_args,
            skip=True,
            skip_reason="skip_reconcile",
        )

    return steps


def execute_step(step: Step, *, base_env: Dict[str, str]) -> str:
    if step.skip:
        log_event("step.skip", name=step.name, reason=step.skip_reason)
        return "skipped"

    env = dict(base_env)
    env.update(step.env)

    attempts = step.retries + 1
    for attempt in range(1, attempts + 1):
        start = time.perf_counter()
        try:
            subprocess.run(step.command, cwd=str(step.cwd), env=env, check=True)
            duration = time.perf_counter() - start
            log_event("step.success", name=step.name, attempt=attempt, duration=round(duration, 3))
            return "success"
        except subprocess.CalledProcessError as exc:
            duration = time.perf_counter() - start
            log_event(
                "step.failure",
                name=step.name,
                attempt=attempt,
                returncode=exc.returncode,
                duration=round(duration, 3),
            )
            if attempt >= attempts:
                raise
            time.sleep(step.retry_delay * attempt)
    return "failed"


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=args.log_level.upper(), format="%(message)s")

    load_env(ROOT)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ensure_state_file(args.state_file)
    args.lock_path.parent.mkdir(parents=True, exist_ok=True)

    test_vector_store_id = os.getenv("TEST_VECTOR_STORE_ID")
    if not test_vector_store_id:
        log_event("pipeline.error", error="TEST_VECTOR_STORE_ID not configured")
        return 1

    base_env = dict(os.environ)

    steps = build_steps(args, test_vector_store_id=test_vector_store_id)

    lock = PipelineLock(args.lock_path, timeout=args.lock_timeout, stale_seconds=args.stale_lock_seconds)

    results: Dict[str, str] = {}
    overall_status = "success"

    try:
        with lock:
            for step in steps:
                try:
                    status = execute_step(step, base_env=base_env)
                    results[step.name] = status
                except subprocess.CalledProcessError:
                    results[step.name] = "failed"
                    overall_status = "failed"
                    log_event("pipeline.abort", failed_step=step.name)
                    break
    except PipelineLockError as exc:
        log_event("pipeline.error", error=str(exc))
        return 1
    except Exception as exc:  # pragma: no cover
        log_event("pipeline.error", error=str(exc))
        overall_status = "failed"
    finally:
        summary = {"status": overall_status, "steps": results}
        log_event("pipeline.complete", **summary)

    return 0 if overall_status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
