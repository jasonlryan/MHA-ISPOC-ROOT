import json
import tempfile
import unittest
from pathlib import Path

from scripts.utils.state import (
    VectorState,
    canonicalize_json,
    compute_content_hash_from_data,
    ensure_state_file,
)


class StateUtilsTests(unittest.TestCase):
    def test_hash_ignores_extracted_date_fields(self) -> None:
        base = {
            "title": "Policy Title",
            "extracted_date": "2024-01-01",
            "sections": [
                {
                    "name": "summary",
                    "content": "Example text",
                    "extracted_date": "2023-02-02",
                }
            ],
        }
        changed = json.loads(json.dumps(base))
        changed["extracted_date"] = "2024-05-05"
        changed["sections"][0]["extracted_date"] = "2023-06-06"

        hash_a = compute_content_hash_from_data(base)
        hash_b = compute_content_hash_from_data(changed)

        self.assertEqual(hash_a, hash_b)

    def test_canonicalize_json_sorts_keys(self) -> None:
        data = {"b": 1, "a": {"d": 2, "c": 3}}
        canonical = canonicalize_json(data, volatile_fields=())
        self.assertEqual(canonical, '{"a":{"c":3,"d":2},"b":1}')

    def test_vector_state_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_path = Path(tmp_dir) / "vector_state.json"

            ensure_state_file(state_path)
            state = VectorState(state_path)
            self.assertEqual(state.to_dict(), {"docs": {}})

            state.upsert("doc-1", file_id="file-123", content_hash="hash-abc")
            state.save()

            loaded = VectorState(state_path)
            doc = loaded.get("doc-1")
            self.assertIsNotNone(doc)
            assert doc is not None
            self.assertEqual(doc["fileId"], "file-123")
            self.assertEqual(doc["contentHash"], "hash-abc")
            self.assertIn("lastSyncedAt", doc)

            loaded.remove("doc-1")
            loaded.save()
            reloaded = VectorState(state_path)
            self.assertIsNone(reloaded.get("doc-1"))

    def test_set_metadata_merges_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_path = Path(tmp_dir) / "vector_state.json"
            ensure_state_file(state_path)
            state = VectorState(state_path)

            state.upsert("doc-1", file_id="file-123", content_hash="hash-abc")
            state.set_metadata("doc-1", policyQuestionsHash="hash-abc", note="test")

            entry = state.get("doc-1")
            assert entry is not None
            self.assertEqual(entry["fileId"], "file-123")
            self.assertEqual(entry["policyQuestionsHash"], "hash-abc")
            self.assertEqual(entry["note"], "test")

            state.set_metadata("doc-2", policyQuestionsHash="hash-def")
            entry2 = state.get("doc-2")
            assert entry2 is not None
            self.assertEqual(entry2["policyQuestionsHash"], "hash-def")


if __name__ == "__main__":
    unittest.main()
