import unittest

from mus_analysis.clustering import coassignment_matrix, consensus_components, variation_of_information


class ClusteringTests(unittest.TestCase):
    def test_noise_is_not_counted_as_separation(self) -> None:
        result = coassignment_matrix(
            [
                {"a": 0, "b": 0, "c": 1},
                {"a": 2, "b": 2, "c": -1},
                {"a": 3, "b": 4, "c": 5},
            ]
        )
        a = result.item_ids.index("a")
        b = result.item_ids.index("b")
        c = result.item_ids.index("c")
        self.assertAlmostEqual(result.matrix[a][b] or 0, 2 / 3)
        self.assertEqual(result.comparable_run_counts[a][c], 2)

    def test_consensus_components(self) -> None:
        result = coassignment_matrix([
            {"a": 0, "b": 0, "c": 1},
            {"a": 2, "b": 2, "c": 3},
        ])
        self.assertIn(("a", "b"), consensus_components(result, threshold=0.9))

    def test_variation_of_information(self) -> None:
        self.assertAlmostEqual(
            variation_of_information({"a": 0, "b": 0}, {"a": 1, "b": 1}),
            0.0,
        )
        self.assertGreater(
            variation_of_information({"a": 0, "b": 0}, {"a": 0, "b": 1}),
            0.0,
        )


if __name__ == "__main__":
    unittest.main()
