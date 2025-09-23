import os
import tempfile
import unittest
from pathlib import Path

from scripts import check_env


class CheckEnvTests(unittest.TestCase):
    def test_collect_status_missing_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            status = check_env.collect_status(root=root, env={})
            self.assertFalse(status["openai_key_present"])
            self.assertFalse(status["test_vector_store_id_present"])
            self.assertFalse(status["state_file_exists"])

    def test_collect_status_detects_env_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            state_path = root / "state"
            state_path.mkdir()
            (state_path / "vector_state.json").write_text("{}")

            env = {
                "VITE_OPENAI_API_KEY": "sk-test",
                "TEST_VECTOR_STORE_ID": "vs_test",
                "VITE_OPENAI_VECTOR_STORE_ID": "vs_prod",
            }
            status = check_env.collect_status(root=root, env=env)
            self.assertTrue(status["openai_key_present"])
            self.assertTrue(status["test_vector_store_id_present"])
            self.assertTrue(status["state_file_exists"])
            self.assertIn("modules", status)


if __name__ == "__main__":
    unittest.main()
