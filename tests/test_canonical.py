from dataclasses import dataclass
from datetime import datetime, timezone
import math
import unittest

from mus_analysis.canonical import CanonicalizationError, canonical_text, content_digest


@dataclass(frozen=True)
class Example:
    z: int
    a: float


class CanonicalTests(unittest.TestCase):
    def test_keys_and_dataclasses_are_stable(self) -> None:
        left = {"b": 2, "a": Example(z=3, a=-0.0)}
        right = {"a": {"a": 0.0, "z": 3}, "b": 2}
        self.assertEqual(canonical_text(left), canonical_text(right))
        self.assertEqual(content_digest(left), content_digest(right))

    def test_non_finite_values_are_rejected(self) -> None:
        with self.assertRaises(CanonicalizationError):
            canonical_text({"bad": math.nan})

    def test_naive_datetimes_are_rejected(self) -> None:
        with self.assertRaises(CanonicalizationError):
            canonical_text(datetime(2026, 8, 8))
        self.assertIn("2026-08-08", canonical_text(datetime(2026, 8, 8, tzinfo=timezone.utc)))


if __name__ == "__main__":
    unittest.main()
