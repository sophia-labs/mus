"""Historical Aigua-v1 identifiers and exact descriptor semantics."""
from __future__ import annotations

from typing import Any

from .model import EvidenceKind

AIGUA_PROJECT_ID = "urn:sophia:mus:aigua:2026-08-08"
AIGUA_SOURCE_FALLBACK = AIGUA_PROJECT_ID + ":asset:source-recording"
AIGUA_BIRD_VIEW = AIGUA_PROJECT_ID + ":signal-view:bird-band-gated-v1"
AIGUA_BIRD_BAND_RAW_VIEW = AIGUA_PROJECT_ID + ":signal-view:bird-band-raw-v1"
AIGUA_RAW_VIEW = AIGUA_PROJECT_ID + ":signal-view:raw-pcm-v1"
AIGUA_V1_TIME = "2026-08-08T00:00:00.000000Z"
AIGUA_CURATOR = AIGUA_PROJECT_ID + ":agent:historical-curator"

SEGMENTATION_RUN_ID = AIGUA_PROJECT_ID + ":run:segmentation-v1"
OBSERVATION_RUN_ID = AIGUA_PROJECT_ID + ":run:event-observations-v1"
CLUSTER_RUN_ID = AIGUA_PROJECT_ID + ":run:ward-k7-v1"
CURATION_RUN_ID = AIGUA_PROJECT_ID + ":run:instrument-curation-v1"
CLAIM_RUN_ID = AIGUA_PROJECT_ID + ":run:claim-register-v1"
CLUSTER_MODEL_ID = AIGUA_PROJECT_ID + ":cluster-model:ward-k7-v1"

DEFAULT_CONFIG: dict[str, Any] = {
    "sourceCandidates": [
        "aigua/source/aigua-birds-2026-08-08.m4a",
        "aigua/source/New Recording 22.m4a",
        "source/aigua-birds-2026-08-08.m4a",
    ],
    "eventsPath": "aigua/events.json",
    "eventsCsvPath": "aigua/events.csv",
    "instrumentPath": "aigua/instrument.json",
    "vehicleEventIds": [14],
    "historicalProducer": "sophia-labs/mus@aigua-concrete",
}


_PROPERTY_MAP: dict[str, dict[str, Any]] = {
    "dur": {
        "property": "eventDurationSeconds",
        "unit": "s",
        "operator": "aigua.hysteresis-segment",
        "version": "1",
        "evidence": EvidenceKind.STATISTICALLY_ESTIMATED,
        "view": AIGUA_BIRD_VIEW,
    },
    "rms_db": {
        "property": "bandLimitedDenoisedRmsDbfs",
        "unit": "dBFS",
        "operator": "aigua.event-level",
        "version": "1",
        "evidence": EvidenceKind.DETERMINISTICALLY_COMPUTED,
        "view": AIGUA_BIRD_VIEW,
    },
    "peak_db": {
        "property": "bandLimitedDenoisedPeakDbfs",
        "unit": "dBFS",
        "operator": "aigua.event-level",
        "version": "1",
        "evidence": EvidenceKind.DETERMINISTICALLY_COMPUTED,
        "view": AIGUA_BIRD_VIEW,
    },
    "f_peak": {
        "property": "meanMagnitudePeakFrequencyHz",
        "unit": "Hz",
        "operator": "aigua.event-spectrum",
        "version": "1",
        "evidence": EvidenceKind.DETERMINISTICALLY_COMPUTED,
        "view": AIGUA_BIRD_VIEW,
    },
    "f_lo": {
        "property": "meanMagnitudeQuantile05FrequencyHz",
        "unit": "Hz",
        "operator": "aigua.event-spectrum",
        "version": "1",
        "evidence": EvidenceKind.DETERMINISTICALLY_COMPUTED,
        "view": AIGUA_BIRD_VIEW,
    },
    "f_hi": {
        "property": "meanMagnitudeQuantile95FrequencyHz",
        "unit": "Hz",
        "operator": "aigua.event-spectrum",
        "version": "1",
        "evidence": EvidenceKind.DETERMINISTICALLY_COMPUTED,
        "view": AIGUA_BIRD_VIEW,
    },
    "centroid": {
        "property": "meanMagnitudeSpectralCentroidHz",
        "unit": "Hz",
        "operator": "aigua.event-spectrum",
        "version": "1",
        "evidence": EvidenceKind.DETERMINISTICALLY_COMPUTED,
        "view": AIGUA_BIRD_VIEW,
    },
    "bandwidth": {
        "property": "meanMagnitudeSpectralBandwidthHz",
        "unit": "Hz",
        "operator": "aigua.event-spectrum",
        "version": "1",
        "evidence": EvidenceKind.DETERMINISTICALLY_COMPUTED,
        "view": AIGUA_BIRD_VIEW,
    },
    "flatness": {
        "property": "meanFrameSpectralFlatness",
        "unit": "ratio",
        "operator": "librosa.feature.spectral_flatness",
        "version": "historical",
        "evidence": EvidenceKind.DETERMINISTICALLY_COMPUTED,
        "view": AIGUA_BIRD_VIEW,
    },
    "f0_med": {
        "property": "shsMedianFrequencyHz",
        "unit": "Hz",
        "operator": "aigua.shs-f0",
        "version": "1",
        "evidence": EvidenceKind.STATISTICALLY_ESTIMATED,
        "view": AIGUA_BIRD_VIEW,
        "scoreField": "f0_conf",
    },
    "f0_min": {
        "property": "shsMinimumFrequencyHz",
        "unit": "Hz",
        "operator": "aigua.shs-f0",
        "version": "1",
        "evidence": EvidenceKind.STATISTICALLY_ESTIMATED,
        "view": AIGUA_BIRD_VIEW,
        "scoreField": "f0_conf",
    },
    "f0_max": {
        "property": "shsMaximumFrequencyHz",
        "unit": "Hz",
        "operator": "aigua.shs-f0",
        "version": "1",
        "evidence": EvidenceKind.STATISTICALLY_ESTIMATED,
        "view": AIGUA_BIRD_VIEW,
        "scoreField": "f0_conf",
    },
    "sweep_st": {
        "property": "shsStartEndSweepSemitones",
        "unit": "semitone",
        "operator": "aigua.shs-f0-summary",
        "version": "1",
        "evidence": EvidenceKind.STATISTICALLY_ESTIMATED,
        "view": AIGUA_BIRD_VIEW,
        "scoreField": "f0_conf",
    },
    "span_st": {
        "property": "shsRangeSemitones",
        "unit": "semitone",
        "operator": "aigua.shs-f0-summary",
        "version": "1",
        "evidence": EvidenceKind.STATISTICALLY_ESTIMATED,
        "view": AIGUA_BIRD_VIEW,
        "scoreField": "f0_conf",
    },
    "f0_conf": {
        "property": "shsPeakToMeanScore",
        "unit": "ratio",
        "operator": "aigua.shs-f0",
        "version": "1",
        "evidence": EvidenceKind.DETERMINISTICALLY_COMPUTED,
        "view": AIGUA_BIRD_VIEW,
    },
    "shape": {
        "property": "contourClassEstimate",
        "unit": None,
        "operator": "aigua.contour-classify",
        "version": "1",
        "evidence": EvidenceKind.MODEL_INFERRED,
        "view": AIGUA_BIRD_VIEW,
    },
    "am_rate": {
        "property": "envelopePeriodicityRateHz",
        "unit": "Hz",
        "operator": "aigua.envelope-autocorrelation",
        "version": "1",
        "evidence": EvidenceKind.STATISTICALLY_ESTIMATED,
        "view": AIGUA_BIRD_BAND_RAW_VIEW,
    },
    # Historical field name was `am_depth`, but the implementation returns the
    # selected normalized autocorrelation value.  Negative historical values
    # make clear that it is not a conventional modulation depth.
    "am_depth": {
        "property": "envelopeAutocorrelationPeakStrength",
        "unit": "normalized-autocorrelation",
        "operator": "aigua.envelope-autocorrelation",
        "version": "1",
        "evidence": EvidenceKind.DETERMINISTICALLY_COMPUTED,
        "view": AIGUA_BIRD_BAND_RAW_VIEW,
        "legacyMisnomer": "am_depth",
    },
}
