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

    def test_non_docx_original_filename_is_handled(self) -> None:
        # Even if the original source file was not a DOCX (e.g., PDF), the
        # upsert logic only consumes the structured JSON in VECTOR_JSON.
        # This test ensures that a JSON payload whose 'filename' ends with
        # a non-docx extension is still processed normally.
        sample = {
            "id": "POL-PDF-1",
            "title": "Policy From PDF",
            "filename": "POL-PDF-1.pdf",
            "extracted_date": "2024-06-01",
            "metadata": {},
            "full_text": "",
            "sections": [],
        }
        json_path = self.policy_dir / "POL-PDF-1.json"
        with json_path.open("w", encoding="utf-8") as handle:
            json.dump(sample, handle)

        documents = [
            {
                "File": "POL-PDF-1.json",
                "Document Type": "Policy",
                "Document": "Policy From PDF",
            }
        ]

        items = upsert.build_work_items(documents, self.state)
        self.assertEqual(len(items), 1)
        item = items[0]
        # Confirm that the work item is created and treated as a Policy
        self.assertEqual(item.external_id, "POL-PDF-1.json")
        self.assertEqual(item.document_type, "Policy")
        self.assertTrue(item.content_hash)

    def test_index_hash_normalization_prevents_order_churn(self) -> None:
        # Write two documents and a combined index with reversed order
        doc_a = {"id": "A", "title": "A", "extracted_date": "2024-01-01", "full_text": "", "sections": []}
        doc_b = {"id": "B", "title": "B", "extracted_date": "2024-01-02", "full_text": "", "sections": []}
        (self.policy_dir / "A.json").write_text(json.dumps(doc_a), encoding="utf-8")
        (self.policy_dir / "B.json").write_text(json.dumps(doc_b), encoding="utf-8")

        combined_path = Path(self.tmp_dir.name) / "MHA_Documents_Metadata_Index.json"
        payload_desc = {
            "MHA Documents": [
                {"File": "B.json", "Document Type": "Policy", "Document": "B"},
                {"File": "A.json", "Document Type": "Policy", "Document": "A"},
            ]
        }
        combined_path.write_text(json.dumps(payload_desc), encoding="utf-8")

        # Build index item and compute hash
        item_desc = upsert.build_index_work_item(combined_path, self.state)

        # Now flip the order and ensure hash is unchanged
        payload_asc = {
            "MHA Documents": [
                {"File": "A.json", "Document Type": "Policy", "Document": "A"},
                {"File": "B.json", "Document Type": "Policy", "Document": "B"},
            ]
        }
        combined_path.write_text(json.dumps(payload_asc), encoding="utf-8")
        item_asc = upsert.build_index_work_item(combined_path, self.state)

        self.assertEqual(item_desc.content_hash, item_asc.content_hash)

    def test_index_create_skip_update_decision(self) -> None:
        combined_path = Path(self.tmp_dir.name) / "MHA_Documents_Metadata_Index.json"
        payload = {"MHA Documents": []}
        combined_path.write_text(json.dumps(payload), encoding="utf-8")

        index_item = upsert.build_index_work_item(combined_path, self.state)
        # Initially, no state → create
        actions = upsert.determine_actions([index_item])
        self.assertEqual(len(actions["create"]), 1)

        # Upsert into state, then build again → skip
        self.state.upsert(index_item.external_id, file_id="file-x", content_hash=index_item.content_hash)
        self.state.save()
        index_item_again = upsert.build_index_work_item(combined_path, VectorState(self.state_path))
        actions_again = upsert.determine_actions([index_item_again])
        self.assertEqual(len(actions_again["skip"]), 1)

        # Modify payload → update
        payload2 = {"MHA Documents": [{"File": "A.json"}]}
        combined_path.write_text(json.dumps(payload2), encoding="utf-8")
        index_item_changed = upsert.build_index_work_item(combined_path, VectorState(self.state_path))
        actions_changed = upsert.determine_actions([index_item_changed])
        self.assertEqual(len(actions_changed["update"]), 1)


if __name__ == "__main__":
    unittest.main()
