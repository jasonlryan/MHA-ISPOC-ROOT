import json
import tempfile
import unittest
from pathlib import Path

from scripts.utils.state import VectorState, ensure_state_file
from scripts import vector_store_upsert as upsert


class VectorStorePlanningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory(dir=str(upsert.ROOT))
        base_path = Path(self.tmp_dir.name)
        self.policy_dir = base_path / "VECTOR_JSON"
        self.guide_dir = base_path / "VECTOR_GUIDES_JSON"
        self.policy_dir.mkdir()
        self.guide_dir.mkdir()
        self.state_path = base_path / "state" / "vector_state.json"
        ensure_state_file(self.state_path)
        self.state = VectorState(self.state_path)

        self.original_policy_dir = upsert.POLICY_DIR
        self.original_guide_dir = upsert.GUIDE_DIR
        upsert.POLICY_DIR = self.policy_dir
        upsert.GUIDE_DIR = self.guide_dir

    def tearDown(self) -> None:
        upsert.POLICY_DIR = self.original_policy_dir
        upsert.GUIDE_DIR = self.original_guide_dir
        self.tmp_dir.cleanup()

    def test_build_work_items_reads_json(self) -> None:
        sample = {
            "id": "POL-123",
            "title": "Test Policy",
            "filename": "POL-123.docx",
            "extracted_date": "2024-05-01",
            "metadata": {},
            "full_text": "",
            "sections": [],
        }
        json_path = self.policy_dir / "POL-123.json"
        with json_path.open("w", encoding="utf-8") as handle:
            json.dump(sample, handle)

        documents = [
            {
                "File": "POL-123.json",
                "Document Type": "Policy",
                "Document": "Test Policy",
            }
        ]

        items = upsert.build_work_items(documents, self.state)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.external_id, "POL-123.json")
        self.assertEqual(item.identity, "POL-123")
        self.assertEqual(item.document_type, "Policy")
        self.assertTrue(item.content_hash)

    def test_determine_actions_new_skip_update(self) -> None:
        sample = {
            "id": "POL-456",
            "title": "Original Title",
            "filename": "POL-456.docx",
            "extracted_date": "2024-05-01",
            "metadata": {},
            "full_text": "",
            "sections": [],
        }
        json_path = self.policy_dir / "POL-456.json"
        with json_path.open("w", encoding="utf-8") as handle:
            json.dump(sample, handle)

        documents = [
            {
                "File": "POL-456.json",
                "Document Type": "Policy",
            }
        ]

        items = upsert.build_work_items(documents, self.state)
        actions = upsert.determine_actions(items)
        self.assertEqual(len(actions["create"]), 1)

        item = actions["create"][0]
        self.state.upsert(
            item.external_id,
            file_id="file-1",
            content_hash=item.content_hash,
        )
        self.state.save()
        state_again = VectorState(self.state_path)

        items_again = upsert.build_work_items(documents, state_again)
        actions_again = upsert.determine_actions(items_again)
        self.assertEqual(len(actions_again["skip"]), 1)

        sample["title"] = "Updated Title"
        with json_path.open("w", encoding="utf-8") as handle:
            json.dump(sample, handle)

        items_changed = upsert.build_work_items(documents, state_again)
        actions_changed = upsert.determine_actions(items_changed)
        self.assertEqual(len(actions_changed["update"]), 1)


if __name__ == "__main__":
    unittest.main()
