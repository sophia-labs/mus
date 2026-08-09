from pathlib import Path
import tempfile
import unittest

from mus_analysis.model import ProfileRef, RunReceipt, RunStatus
from mus_analysis.store import ImmutableConflictError, ResearchObjectStore


class StoreTests(unittest.TestCase):
    def test_content_addressing_and_named_immutability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ResearchObjectStore(tmp)
            a = store.put_text("same")
            b = store.put_text("same")
            self.assertEqual(a.sha256, b.sha256)
            store.write_named_bytes("x/value.txt", b"one")
            store.write_named_bytes("x/value.txt", b"one")
            with self.assertRaises(ImmutableConflictError):
                store.write_named_bytes("x/value.txt", b"two")
            self.assertTrue(store.verify()["ok"])

    def test_run_references_are_verified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ResearchObjectStore(tmp)
            artifact = store.put_json({"ok": True})
            receipt = RunReceipt(
                run_id="urn:test:run",
                run_type="test",
                profile=ProfileRef("test", "1"),
                status=RunStatus.SUCCEEDED,
                producer="tests",
                started_at="2026-08-08T00:00:00Z",
                completed_at="2026-08-08T00:00:00Z",
                outputs=(artifact,),
            )
            store.write_run(receipt)
            self.assertTrue(store.verify()["ok"])


if __name__ == "__main__":
    unittest.main()
