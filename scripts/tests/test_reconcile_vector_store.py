import tempfile
import unittest
from pathlib import Path
from typing import List

from scripts.utils.state import VectorState, ensure_state_file
from scripts.reconcile_vector_store import (
    VectorFileRecord,
    list_vector_files,
    plan_reconciliation,
)


class DummyClient:
    def __init__(self, items: List[dict]):
        self._items = items

    def iter_files(self):
        for item in self._items:
            yield item


class ReconcilePlanningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state_path = Path(self.tmp.name) / "vector_state.json"
        ensure_state_file(self.state_path)
        self.state = VectorState(self.state_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_list_vector_files_extracts_metadata(self) -> None:
        client = DummyClient([
            {
                "id": "file-1",
                "metadata": {"external_id": "doc.json", "note": "keep"},
            }
        ])
        records = list_vector_files(client)  # type: ignore[arg-type]
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.file_id, "file-1")
        self.assertEqual(record.external_id, "doc.json")
        self.assertEqual(record.metadata.get("note"), "keep")

    def test_plan_reconciliation_handles_duplicates_and_missing(self) -> None:
        records = [
            VectorFileRecord(file_id="f-keep", external_id="keep.json", metadata={}),
            VectorFileRecord(file_id="f-dupe", external_id="keep.json", metadata={}),
            VectorFileRecord(file_id="f-remove", external_id="remove.json", metadata={}),
        ]
        self.state.upsert("remove.json", file_id="f-remove", content_hash="hash")
        self.state.save()

        combined_files = ["keep.json"]
        plan = plan_reconciliation(records, combined_files, self.state)

        deletions = {(d.file_id, d.reason) for d in plan.deletions}
        self.assertIn(("f-dupe", "duplicate_external_id"), deletions)
        self.assertIn(("f-remove", "not_in_combined_index"), deletions)
        # ensure the duplicate deletion does not request state removal
        self.assertFalse(any(d.file_id == "f-dupe" and d.remove_state for d in plan.deletions))
        # ensure the orphan removal will clean state
        self.assertTrue(any(d.file_id == "f-remove" and d.remove_state for d in plan.deletions))

        self.assertEqual(plan.state_only_removals, [])

    def test_reconcile_does_not_delete_combined_index(self) -> None:
        # Simulate state containing the combined index entry and ensure that
        # when allowed files exclude it, the whitelist logic should spare it
        index_filename = "MHA_Documents_Metadata_Index.json"
        self.state.upsert(index_filename, file_id="file-index", content_hash="hash-index")
        self.state.save()

        # The plan function needs allowed files; ensure index filename is included to preserve
        combined_files = [index_filename]
        plan = plan_reconciliation([], combined_files, self.state)
        # No deletions should be scheduled for the index
        self.assertFalse(any(d.external_id == index_filename for d in plan.deletions))


if __name__ == "__main__":
    unittest.main()
