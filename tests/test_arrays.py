import tempfile
import unittest

import numpy as np

from mus_analysis.arrays import put_array, read_array
from mus_analysis.store import ResearchObjectStore


class ArrayArtifactTests(unittest.TestCase):
    def test_npy_artifact_is_deterministic_and_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ResearchObjectStore(tmp)
            value = np.array([[1.0, np.nan], [3.0, 4.0]], dtype=np.float32)
            first = put_array(store, value, role="trajectory", missing_value_semantics="unresolved")
            second = put_array(store, value.copy(), role="trajectory", missing_value_semantics="unresolved")
            self.assertEqual(first.artifact.sha256, second.artifact.sha256)
            actual = read_array(store, first)
            np.testing.assert_equal(actual, value)
            self.assertEqual(first.shape, (2, 2))
            self.assertEqual(first.missing_value_semantics, "unresolved")

    def test_object_arrays_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ResearchObjectStore(tmp)
            with self.assertRaises(ValueError):
                put_array(store, np.array([{"not": "numeric"}], dtype=object))


if __name__ == "__main__":
    unittest.main()
