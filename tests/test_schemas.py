from pathlib import Path
import json
import unittest

from jsonschema import Draft202012Validator

from mus_analysis.canonical import normalize
from mus_analysis.model import ProfileRef, RunReceipt, RunStatus


ROOT = Path(__file__).resolve().parents[1]


class SchemaTests(unittest.TestCase):
    def test_run_receipt_schema_accepts_model_output(self) -> None:
        schema = json.loads((ROOT / "schemas" / "run-receipt.schema.json").read_text("utf-8"))
        receipt = RunReceipt(
            run_id="urn:test:run",
            run_type="test",
            profile=ProfileRef("test.profile", "1"),
            status=RunStatus.SUCCEEDED,
            producer="tests",
            started_at="2026-08-08T00:00:00Z",
            completed_at="2026-08-08T00:00:00Z",
        )
        errors = list(Draft202012Validator(schema).iter_errors(normalize(receipt)))
        self.assertEqual(errors, [], "\n".join(error.message for error in errors))

    def test_profile_registry_conforms(self) -> None:
        schema = json.loads((ROOT / "schemas" / "analysis-profile.schema.json").read_text("utf-8"))
        registry = json.loads((ROOT / "aigua" / "research" / "profile-registry.json").read_text("utf-8"))
        validator = Draft202012Validator(schema)
        errors = [error for profile in registry["profiles"] for error in validator.iter_errors(profile)]
        self.assertEqual(errors, [], "\n".join(error.message for error in errors))


if __name__ == "__main__":
    unittest.main()
