import json
import tempfile
import unittest
from pathlib import Path

from scripts import generate_ai_questions as policy_mod
from scripts import generate_guide_ai_questions as guide_mod
from scripts.utils.state import VectorState, ensure_state_file


class PolicyChangeDetectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.policy_dir = self.tmp_path / "VECTOR_JSON"
        self.policy_dir.mkdir()
        self.state_path = self.tmp_path / "state.json"
        ensure_state_file(self.state_path)
        self.state = VectorState(self.state_path)

        self.original_policy_dir = policy_mod.JSON_DIR
        policy_mod.JSON_DIR = self.policy_dir

        payload = {
            "id": "POL-1",
            "title": "Policy",
            "filename": "policy.docx",
            "extracted_date": "2024-05-01",
            "metadata": {},
            "full_text": "Example text",
            "sections": {"summary": "Example section"},
        }
        self.json_path = self.policy_dir / "policy.json"
        self.json_path.write_text(json.dumps(payload))
        self.documents = [
            {"Document": "Policy", "File": "policy.json"}
        ]

    def tearDown(self) -> None:
        policy_mod.JSON_DIR = self.original_policy_dir
        self.tmp.cleanup()

    def test_collect_plan_detects_unchanged_documents(self) -> None:
        plan = policy_mod.collect_plan(self.documents, self.state, force=False)
        updates = [item for item in plan if item.action == "update"]
        self.assertEqual(len(updates), 1)
        content_hash = updates[0].content_hash
        self.assertIsNotNone(content_hash)

        self.state.set_metadata("policy.json", policyQuestionsHash=content_hash)
        plan_again = policy_mod.collect_plan(self.documents, self.state, force=False)
        skips = [item for item in plan_again if item.action == "skip" and item.reason == "unchanged"]
        self.assertEqual(len(skips), 1)


class GuideFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.guide_dir = self.tmp_path / "VECTOR_GUIDES_JSON"
        self.guide_dir.mkdir()
        self.state_path = self.tmp_path / "state.json"
        ensure_state_file(self.state_path)
        self.state = VectorState(self.state_path)

        self.original_guide_dir = guide_mod.JSON_DIR
        guide_mod.JSON_DIR = self.guide_dir

        payload_one = {
            "guide_number": "1",
            "title": "Guide One",
            "filename": "guide1.docx",
            "extracted_date": "2024-05-01",
            "metadata": {},
            "full_text": "Text",
            "sections": {"overview": "Overview"},
        }
        payload_two = {
            "guide_number": "2",
            "title": "Guide Two",
            "filename": "guide2.docx",
            "extracted_date": "2024-05-01",
            "metadata": {},
            "full_text": "Text",
            "sections": {"overview": "Overview"},
        }
        (self.guide_dir / "guide-one.json").write_text(json.dumps(payload_one))
        (self.guide_dir / "guide-two.json").write_text(json.dumps(payload_two))
        self.documents = [
            {"Document": "Guide One", "File": "guide-one.json"},
            {"Document": "Guide Two", "File": "guide-two.json"},
        ]

    def tearDown(self) -> None:
        guide_mod.JSON_DIR = self.original_guide_dir
        self.tmp.cleanup()

    def test_collect_plan_filters_documents(self) -> None:
        plan = guide_mod.collect_plan(self.documents, self.state, force=False, filters=["guide-two.json"])
        self.assertTrue(all(item.json_filename == "guide-two.json" for item in plan))
        self.assertGreater(len(plan), 0)


if __name__ == "__main__":
    unittest.main()
