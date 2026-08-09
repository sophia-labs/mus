import unittest

from mus_analysis.segmentation import RelationType, Segment, reconcile_segmentations, relate


class SegmentationTests(unittest.TestCase):
    def test_relation_vocabulary(self) -> None:
        a = Segment("a", "run-a", 1.0, 2.0)
        b = Segment("b", "run-b", 1.01, 2.01)
        self.assertIs(relate(a, b, boundary_tolerance_seconds=0.02).relation, RelationType.APPROXIMATELY_CORRESPONDS)
        c = Segment("c", "run-b", 1.2, 1.8)
        self.assertIs(relate(a, c).relation, RelationType.CONTAINS)

    def test_split_merge_ambiguity_is_preserved(self) -> None:
        hypotheses, relations = reconcile_segmentations(
            {
                "phrase": [Segment("p", "phrase", 0.0, 1.0)],
                "syllable": [
                    Segment("s1", "syllable", 0.0, 0.48),
                    Segment("s2", "syllable", 0.5, 1.0),
                ],
            },
            minimum_link_iou=0.2,
        )
        self.assertEqual(len(hypotheses), 1)
        self.assertTrue(hypotheses[0].ambiguous_split_or_merge)
        self.assertEqual(set(hypotheses[0].supporting_run_ids), {"phrase", "syllable"})
        self.assertTrue(relations)


if __name__ == "__main__":
    unittest.main()
