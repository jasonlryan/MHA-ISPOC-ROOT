import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

import run_pipeline


class BuildStepsTests(unittest.TestCase):
    def _default_args(self, **overrides):
        tmp_state = Path(tempfile.gettempdir()) / "pipeline_state_test.json"
        args = SimpleNamespace(
            dry_run=False,
            skip_conversion=False,
            skip_index=False,
            skip_ai=False,
            skip_validation=False,
            skip_upload=False,
            skip_reconcile=False,
            state_file=tmp_state,
            lock_path=Path(tempfile.gettempdir()) / "pipeline.lock",
            lock_timeout=1,
            stale_lock_seconds=1,
            max_retries=2,
            retry_base_delay=1.0,
            log_level="INFO",
        )
        for key, value in overrides.items():
            setattr(args, key, value)
        return args

    def test_step_order_starts_with_conversion(self):
        args = self._default_args()
        steps = run_pipeline.build_steps(args, test_vector_store_id="vs_test")
        self.assertEqual(steps[0].name, "convert_policies")
        self.assertIn("vector_store_reconcile", [step.name for step in steps])

    def test_skip_ai_marks_steps_skipped(self):
        args = self._default_args(skip_ai=True)
        steps = run_pipeline.build_steps(args, test_vector_store_id="vs_test")
        policy_step = next(step for step in steps if step.name == "generate_policy_questions")
        self.assertTrue(policy_step.skip)
        self.assertEqual(policy_step.skip_reason, "skip_ai")

    def test_dry_run_propagates_to_upsert(self):
        args = self._default_args(dry_run=True)
        steps = run_pipeline.build_steps(args, test_vector_store_id="vs_test")
        upsert_step = next(step for step in steps if step.name == "vector_store_upsert")
        self.assertIn("--dry-run", upsert_step.command)
        self.assertFalse(upsert_step.skip)

    def test_skip_upload_avoids_upsert_execution(self):
        args = self._default_args(skip_upload=True)
        steps = run_pipeline.build_steps(args, test_vector_store_id="vs_test")
        upsert_step = next(step for step in steps if step.name == "vector_store_upsert")
        self.assertTrue(upsert_step.skip)
        self.assertEqual(upsert_step.skip_reason, "skip_upload")


if __name__ == "__main__":
    unittest.main()
