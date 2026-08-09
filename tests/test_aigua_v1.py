import json
from pathlib import Path
import tempfile
import unittest

from mus_analysis.aigua_v1 import import_aigua_v1
from mus_analysis.model import EvidenceKind
from mus_analysis.store import ResearchObjectStore


class AiguaImportTests(unittest.TestCase):
    def test_import_separates_observation_membership_and_curation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "aigua").mkdir()
            events = [
                {
                    "id": 14,
                    "t0": 1.0,
                    "t1": 1.4,
                    "dur": 0.4,
                    "rms_db": -20.0,
                    "peak_db": -3.0,
                    "f_peak": 1500.0,
                    "f_lo": 900.0,
                    "f_hi": 5000.0,
                    "centroid": 2500.0,
                    "bandwidth": 1000.0,
                    "flatness": 0.01,
                    "f0_med": 1000.0,
                    "f0_min": 700.0,
                    "f0_max": 2000.0,
                    "sweep_st": 4.0,
                    "span_st": 18.0,
                    "f0_conf": 4.2,
                    "shape": "arch",
                    "am_rate": 30.0,
                    "am_depth": -0.1,
                    "cluster": 3,
                }
            ]
            instrument = {
                "voices": {
                    "call": {
                        "family": "signature call",
                        "cluster": 3,
                        "population": 1,
                        "samples": [
                            {
                                "file": "samples/call_01.wav",
                                "event": 14,
                                "f0_hz": 1000.0,
                                "note": "B5",
                                "midi": 83,
                                "cents": 21.0,
                            }
                        ],
                    }
                }
            }
            (root / "aigua" / "events.json").write_text(json.dumps(events), "utf-8")
            (root / "aigua" / "events.csv").write_text("id,t0,t1\n14,1,1.4\n", "utf-8")
            (root / "aigua" / "instrument.json").write_text(json.dumps(instrument), "utf-8")
            store_path = root / "research-object"
            projection = import_aigua_v1(root, store_path)

            self.assertEqual(len(projection.events), 1)
            self.assertEqual(len(projection.memberships), 1)
            self.assertTrue(projection.interpretations)
            self.assertIn("vehicle-dominated", projection.events[0].labels)
            property_ids = {item.observed_property for item in projection.observations}
            self.assertIn("envelopeAutocorrelationPeakStrength", property_ids)
            self.assertNotIn("amplitudeModulationDepth", property_ids)
            am = next(
                item
                for item in projection.observations
                if item.observed_property == "envelopeAutocorrelationPeakStrength"
            )
            self.assertEqual(am.value, -0.1)
            self.assertIs(am.evidence_kind, EvidenceKind.DETERMINISTICALLY_COMPUTED)
            self.assertTrue(ResearchObjectStore(store_path).verify()["ok"])
            nt = (store_path / "projections" / "aigua-v1.nt").read_text("utf-8")
            self.assertIn("EvidenceKind-ModelInferred", nt)
            # Import is idempotent; write-once projections receive identical bytes.
            projection2 = import_aigua_v1(root, store_path)
            self.assertEqual(projection.projection_id, projection2.projection_id)


if __name__ == "__main__":
    unittest.main()
