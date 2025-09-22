import json
import tempfile
import unittest
from pathlib import Path

from scripts import validate_outputs as validator


@unittest.skipUnless(validator.JSONSCHEMA_AVAILABLE, "jsonschema dependency missing")
class ValidationSchemaTests(unittest.TestCase):
    def _write_json(self, payload):
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as handle:
            json.dump(payload, handle)
            path = Path(handle.name)
        return path

    def test_policy_document_schema_accepts_valid_payload(self) -> None:
        schema = validator.load_schema(validator.DEFAULT_SCHEMAS_DIR, "policy_document.schema.json")
        payload = {
            "id": "POL-1",
            "title": "Policy Title",
            "filename": "POL-1.docx",
            "extracted_date": "2024-05-01",
            "metadata": {"author": "Unit"},
            "full_text": "Example text",
            "sections": {"summary": "text"}
        }
        path = self._write_json(payload)
        try:
            errors = validator.validate_file(path, schema)
            self.assertEqual(errors, [])
        finally:
            path.unlink(missing_ok=True)

    def test_policy_document_schema_requires_id_field(self) -> None:
        schema = validator.load_schema(validator.DEFAULT_SCHEMAS_DIR, "policy_document.schema.json")
        payload = {
            "title": "Policy Title",
            "filename": "POL-1.docx",
            "extracted_date": "2024-05-01",
            "metadata": {},
            "full_text": "Example text",
            "sections": {}
        }
        path = self._write_json(payload)
        try:
            errors = validator.validate_file(path, schema)
            self.assertTrue(errors)
            self.assertIn("'id' is a required property", errors[0]["message"])
        finally:
            path.unlink(missing_ok=True)

    def test_combined_index_enforces_document_type_enum(self) -> None:
        schema = validator.load_schema(validator.DEFAULT_SCHEMAS_DIR, "combined_index.schema.json")
        payload = {
            "MHA Documents": [
                {
                    "Document": "Doc",
                    "File": "Doc.json",
                    "Description": "desc",
                    "Questions Answered": ["Q"],
                    "Document Type": "Manual"
                }
            ]
        }
        path = self._write_json(payload)
        try:
            errors = validator.validate_file(path, schema)
            self.assertTrue(errors)
            self.assertIn("'Manual' is not one of", errors[0]["message"])
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
