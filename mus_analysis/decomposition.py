"""Additive mono decomposition for the MUS spatial canvas.

The implementation is intentionally a *hypothesis generator*.  Event masks and
NMF components are acoustic components whose sum, together with an explicit
residual, reconstructs the source.  They are not asserted to be historical
physical sources.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class Region:
    region_id: str
    start_seconds: float
    end_seconds: float
    label: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.start_seconds < 0 or self.end_seconds <= self.start_seconds:
            raise ValueError("region bounds are invalid")


@dataclass(frozen=True, slots=True)
class Stem:
    stem_id: str
    label: str
    audio: Any
    start_seconds: float
    source_region: Region | None
    kind: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DecompositionResult:
    source_sample_rate: int
    source_length_samples: int
    stems: tuple[Stem, ...]
    residual: Stem
    closure_rms_error: float
    closure_peak_error: float
    method: str
    parameters: Mapping[str, Any]
    schema: str = "https://sophia-labs.ai/schemas/mus-decomposition-report/1"

    def report_dict(self, *, stem_files: Mapping[str, str] | None = None, residual_file: str | None = None) -> dict[str, Any]:
        files = stem_files or {}
        return {
            "schema": self.schema,
            "method": self.method,
            "sourceSampleRate": self.source_sample_rate,
            "sourceLengthSamples": self.source_length_samples,
            "parameters": dict(self.parameters),
            "closure": {
                "rmsError": self.closure_rms_error,
                "peakError": self.closure_peak_error,
                "claim": "Placed stem clips plus the residual reconstruct the analyzed mono source within numerical tolerance.",
            },
            "stems": [
                {
                    "stemId": stem.stem_id,
                    "label": stem.label,
                    "audio": files.get(stem.stem_id),
                    "startSeconds": stem.start_seconds,
                    "durationSeconds": len(stem.audio) / self.source_sample_rate,
                    "kind": stem.kind,
                    "sourceRegion": asdict(stem.source_region) if stem.source_region else None,
                    "metadata": dict(stem.metadata),
                }
                for stem in self.stems
            ],
            "residual": {
                "stemId": self.residual.stem_id,
                "label": self.residual.label,
                "audio": residual_file,
                "startSeconds": 0.0,
                "durationSeconds": len(self.residual.audio) / self.source_sample_rate,
                "kind": self.residual.kind,
                "metadata": dict(self.residual.metadata),
            },
        }


def read_regions(path: str | Path) -> tuple[Region, ...]:
    """Read Aigua events, generic region rows, or segmentation results."""
    value = json.loads(Path(path).read_text("utf-8"))
    if isinstance(value, dict):
        if isinstance(value.get("events"), list):
            rows = value["events"]
        elif isinstance(value.get("reconciledHypotheses"), list):
            rows = value["reconciledHypotheses"]
        elif isinstance(value.get("segments"), list):
            rows = value["segments"]
        else:
            rows = value.get("regions", value.get("items", []))
    elif isinstance(value, list):
        rows = value
    else:
        raise ValueError("region file must contain a JSON object or array")
    out: list[Region] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            continue
        start = _first_number(row, "startSeconds", "start_seconds", "t0", "start")
        end = _first_number(row, "endSeconds", "end_seconds", "t1", "end")
        if start is None or end is None or end <= start:
            continue
        region_id = str(row.get("eventId", row.get("segmentId", row.get("regionId", row.get("id", index)))))
        label = row.get("label", row.get("family", row.get("shape")))
        out.append(
            Region(
                region_id=region_id,
                start_seconds=float(start),
                end_seconds=float(end),
                label=str(label) if label is not None else None,
                metadata={key: item for key, item in row.items() if key not in {"t0", "t1", "start", "end", "startSeconds", "endSeconds"}},
            )
        )
    if not out:
        raise ValueError("no valid regions found")
    return tuple(sorted(out, key=lambda item: (item.start_seconds, item.end_seconds, item.region_id)))


def propose_regions(signal: Any, sample_rate: int, *, top_db: float = 32.0, minimum_seconds: float = 0.04, merge_gap_seconds: float = 0.03) -> tuple[Region, ...]:
    """Generate generic non-silent event proposals.

    This deliberately returns ``Region`` hypotheses, not ground-truth sources.
    """
    np, _, librosa, _ = _dependencies()
    y = np.asarray(signal, dtype=float).reshape(-1)
    intervals = librosa.effects.split(y, top_db=float(top_db), frame_length=2048, hop_length=256)
    raw = [[int(start), int(end)] for start, end in intervals if (end - start) / sample_rate >= minimum_seconds]
    merged: list[list[int]] = []
    gap = int(round(merge_gap_seconds * sample_rate))
    for row in raw:
        if merged and row[0] - merged[-1][1] <= gap:
            merged[-1][1] = row[1]
        else:
            merged.append(row)
    return tuple(
        Region(
            region_id=f"auto-{index:04d}",
            start_seconds=start / sample_rate,
            end_seconds=end / sample_rate,
            label="event-proposal",
            metadata={"operator": "librosa.effects.split", "topDb": top_db},
        )
        for index, (start, end) in enumerate(merged)
    )


def event_soft_mask_decomposition(
    signal: Any,
    sample_rate: int,
    regions: Sequence[Region],
    *,
    n_fft: int = 2048,
    hop_length: int = 256,
    pad_seconds: float = 0.04,
    context_seconds: float = 0.4,
    residual_weight: float = 0.08,
    profile_floor: float = 0.02,
) -> DecompositionResult:
    """Create one additive, trimmed soft-mask stem per event proposal.

    Each raw mask factorizes into a time support and a foreground-vs-context
    spectral profile.  All masks and the residual are normalized together in
    every time-frequency cell, so overlap cannot duplicate energy.
    """
    np, scipy_signal, librosa, _ = _dependencies()
    y = np.asarray(signal, dtype=np.float64).reshape(-1)
    if y.size == 0:
        raise ValueError("signal is empty")
    if not regions:
        raise ValueError("at least one region is required")
    duration = y.size / sample_rate
    clipped = [
        Region(
            region_id=region.region_id,
            start_seconds=max(0.0, min(duration, region.start_seconds)),
            end_seconds=max(0.0, min(duration, region.end_seconds)),
            label=region.label,
            metadata=region.metadata,
        )
        for region in regions
        if region.start_seconds < duration and region.end_seconds > 0
    ]
    clipped = [region for region in clipped if region.end_seconds > region.start_seconds]
    if not clipped:
        raise ValueError("all regions lie outside the signal")

    stft = librosa.stft(y, n_fft=n_fft, hop_length=hop_length, center=True, window="hann")
    magnitude = np.abs(stft)
    frame_times = librosa.frames_to_time(np.arange(stft.shape[1]), sr=sample_rate, hop_length=hop_length)
    global_floor = np.percentile(magnitude, 20.0, axis=1)
    denominator = np.full_like(magnitude, float(residual_weight), dtype=np.float64)
    factors: list[tuple[Any, Any, Region]] = []

    for region in clipped:
        time_weight = _time_weight(frame_times, region.start_seconds, region.end_seconds, pad_seconds)
        core = (frame_times >= region.start_seconds) & (frame_times <= region.end_seconds)
        local = (frame_times >= max(0.0, region.start_seconds - context_seconds)) & (
            frame_times <= min(duration, region.end_seconds + context_seconds)
        )
        background = local & ~core
        if np.any(core):
            foreground = np.percentile(magnitude[:, core], 70.0, axis=1)
        else:
            foreground = global_floor
        if np.any(background):
            floor = np.percentile(magnitude[:, background], 50.0, axis=1)
        else:
            floor = global_floor
        profile = np.clip((foreground - floor) / np.maximum(foreground, 1e-12), 0.0, 1.0)
        profile = scipy_signal.savgol_filter(profile, min(31, max(5, (len(profile) // 8) * 2 + 1)), 2, mode="interp")
        profile = np.clip(profile, 0.0, 1.0)
        profile = np.maximum(profile, profile_floor * (foreground > global_floor))
        profile = np.sqrt(profile)
        denominator += profile[:, None] * time_weight[None, :]
        factors.append((profile, time_weight, region))

    residual_mask = residual_weight / np.maximum(denominator, 1e-15)
    residual_full = librosa.istft(stft * residual_mask, hop_length=hop_length, length=y.size, center=True)
    claimed = np.zeros_like(y)
    stems: list[Stem] = []

    for index, (profile, time_weight, region) in enumerate(factors):
        mask = (profile[:, None] * time_weight[None, :]) / np.maximum(denominator, 1e-15)
        full = librosa.istft(stft * mask, hop_length=hop_length, length=y.size, center=True)
        claimed += full
        trim_start = max(0, int(math.floor((region.start_seconds - pad_seconds) * sample_rate)))
        trim_end = min(y.size, int(math.ceil((region.end_seconds + pad_seconds) * sample_rate)))
        clip = full[trim_start:trim_end].copy()
        stem_id = _stable_id("event-stem", region.region_id, region.start_seconds, region.end_seconds, index)
        mask_share = float(np.sum((magnitude**2) * mask) / max(float(np.sum(magnitude**2)), 1e-15))
        stems.append(
            Stem(
                stem_id=stem_id,
                label=region.label or f"event {index + 1}",
                audio=clip,
                start_seconds=trim_start / sample_rate,
                source_region=region,
                kind="event-component",
                metadata={
                    "maskEnergyShare": mask_share,
                    "trimPadSeconds": pad_seconds,
                    "interpretation": "Acoustic component generated from an event hypothesis; not asserted to be one physical source.",
                },
            )
        )

    # The frequency-domain masks close before trimming, but persisted event
    # objects are intentionally trimmed.  Recompute the durable residual from
    # the exact clips that will be written so the *published* stems plus the
    # published residual close sample-for-sample.
    durable_claimed = np.zeros_like(y)
    for stem in stems:
        start = max(0, int(round(stem.start_seconds * sample_rate)))
        available = min(len(stem.audio), len(y) - start)
        if available > 0:
            durable_claimed[start : start + available] += stem.audio[:available]
    durable_residual = y - durable_claimed
    correction = durable_residual - residual_full
    reconstructed = durable_claimed + durable_residual
    error = y - reconstructed
    return DecompositionResult(
        source_sample_rate=int(sample_rate),
        source_length_samples=int(y.size),
        stems=tuple(stems),
        residual=Stem(
            stem_id=_stable_id("residual", len(y), sample_rate, len(stems)),
            label="unassigned residual",
            audio=durable_residual,
            start_seconds=0.0,
            source_region=None,
            kind="residual",
            metadata={
                "interpretation": "Exact unassigned remainder after the persisted, trimmed event stems are placed on the source timeline.",
                "trimCorrectionRms": float(np.sqrt(np.mean(correction**2))),
            },
        ),
        closure_rms_error=float(np.sqrt(np.mean(error**2))),
        closure_peak_error=float(np.max(np.abs(error))),
        method="mus.event-soft-mask/1",
        parameters={
            "nFft": n_fft,
            "hopLength": hop_length,
            "padSeconds": pad_seconds,
            "contextSeconds": context_seconds,
            "residualWeight": residual_weight,
            "profileFloor": profile_floor,
        },
    )


def hybrid_decomposition(
    signal: Any,
    sample_rate: int,
    regions: Sequence[Region],
    *,
    components: int = 4,
    event_n_fft: int = 2048,
    event_hop_length: int = 256,
    nmf_n_fft: int = 2048,
    nmf_hop_length: int = 256,
    random_state: int = 0,
) -> DecompositionResult:
    """Objectize discrete regions, then factor the explicit residual as texture.

    The event stage and NMF stage each retain an explicit residual.  The final
    result publishes event clips, full-length texture components, and the NMF
    residual; those published signals close against the original waveform.
    """
    np, _, _, _ = _dependencies()
    y = np.asarray(signal, dtype=np.float64).reshape(-1)
    events = event_soft_mask_decomposition(
        y, sample_rate, regions, n_fft=event_n_fft, hop_length=event_hop_length
    )
    texture = nmf_decomposition(
        events.residual.audio,
        sample_rate,
        components=components,
        n_fft=nmf_n_fft,
        hop_length=nmf_hop_length,
        random_state=random_state,
    )
    texture_stems = tuple(
        Stem(
            stem_id=stem.stem_id,
            label=stem.label,
            audio=stem.audio,
            start_seconds=stem.start_seconds,
            source_region=stem.source_region,
            kind=stem.kind,
            metadata={**stem.metadata, "parentResidual": events.residual.stem_id},
        )
        for stem in texture.stems
    )
    stems = events.stems + texture_stems
    placed = np.zeros_like(y)
    for stem in stems:
        start = max(0, int(round(stem.start_seconds * sample_rate)))
        available = min(len(stem.audio), len(y) - start)
        if available > 0:
            placed[start : start + available] += stem.audio[:available]
    residual = np.asarray(texture.residual.audio, dtype=np.float64)
    reconstructed = placed + residual
    error = y - reconstructed
    return DecompositionResult(
        source_sample_rate=int(sample_rate),
        source_length_samples=int(y.size),
        stems=stems,
        residual=Stem(
            stem_id=texture.residual.stem_id,
            label="hybrid unassigned residual",
            audio=residual,
            start_seconds=0.0,
            source_region=None,
            kind="residual",
            metadata={**texture.residual.metadata, "parentResidual": events.residual.stem_id},
        ),
        closure_rms_error=float(np.sqrt(np.mean(error**2))),
        closure_peak_error=float(np.max(np.abs(error))),
        method="mus.hybrid-event-nmf/1",
        parameters={
            "event": dict(events.parameters),
            "texture": dict(texture.parameters),
            "eventRegions": len(regions),
        },
    )


def nmf_decomposition(
    signal: Any,
    sample_rate: int,
    *,
    components: int = 4,
    n_fft: int = 2048,
    hop_length: int = 256,
    random_state: int = 0,
) -> DecompositionResult:
    """Factor a mono recording into additive NMF texture components."""
    np, _, librosa, _ = _dependencies()
    try:
        from sklearn.decomposition import NMF
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("NMF decomposition requires scikit-learn") from exc
    y = np.asarray(signal, dtype=np.float64).reshape(-1)
    if components < 1:
        raise ValueError("components must be positive")
    stft = librosa.stft(y, n_fft=n_fft, hop_length=hop_length, center=True, window="hann")
    power = np.abs(stft) ** 2
    model = NMF(
        n_components=int(components),
        init="nndsvda",
        solver="mu",
        beta_loss="kullback-leibler",
        max_iter=500,
        random_state=int(random_state),
    )
    activations = model.fit_transform(power.T)
    templates = model.components_
    component_power = np.stack([np.outer(templates[k], activations[:, k]) for k in range(components)], axis=0)
    denominator = np.sum(component_power, axis=0)
    masks = component_power / np.maximum(denominator[None, :, :], 1e-15)
    stems: list[Stem] = []
    reconstructed = np.zeros_like(y)
    for index in range(components):
        full = librosa.istft(stft * np.sqrt(masks[index]), hop_length=hop_length, length=y.size, center=True)
        reconstructed += full
        spectral_center = _component_centroid(templates[index], sample_rate, n_fft)
        stems.append(
            Stem(
                stem_id=_stable_id("nmf-stem", index, components, random_state),
                label=f"texture component {index + 1}",
                audio=full,
                start_seconds=0.0,
                source_region=None,
                kind="texture-component",
                metadata={
                    "componentIndex": index,
                    "spectralCentroidHz": spectral_center,
                    "interpretation": "NMF acoustic component; not asserted to be a source identity.",
                },
            )
        )
    # Square-root Wiener masks are not exactly additive.  Preserve closure with
    # an explicit residual rather than renormalizing or hiding the discrepancy.
    residual = y - reconstructed
    error = y - (reconstructed + residual)
    return DecompositionResult(
        source_sample_rate=int(sample_rate),
        source_length_samples=int(y.size),
        stems=tuple(stems),
        residual=Stem(
            stem_id=_stable_id("nmf-residual", len(y), components, random_state),
            label="NMF reconstruction residual",
            audio=residual,
            start_seconds=0.0,
            source_region=None,
            kind="residual",
            metadata={"interpretation": "Exact time-domain remainder after component reconstruction."},
        ),
        closure_rms_error=float(np.sqrt(np.mean(error**2))),
        closure_peak_error=float(np.max(np.abs(error))),
        method="mus.nmf-texture-decomposition/1",
        parameters={
            "components": components,
            "nFft": n_fft,
            "hopLength": hop_length,
            "randomState": random_state,
            "betaLoss": "kullback-leibler",
        },
    )


def auditory_band_decomposition(
    signal: Any,
    sample_rate: int,
    *,
    bands: int = 8,
    n_fft: int = 2048,
    hop_length: int = 256,
) -> DecompositionResult:
    """Partition a waveform into smooth ERB-rate spectral layers.

    This is a reversible production decomposition inspired by auditory
    frequency spacing, not a claim to reproduce one exact cochlear filterbank.
    The complex STFT masks sum to one at every bin; an explicit time-domain
    residual preserves sample-exact closure after overlap-add reconstruction.
    """
    np, _, librosa, _ = _dependencies()
    y = np.asarray(signal, dtype=np.float64).reshape(-1)
    if y.size == 0:
        raise ValueError("signal is empty")
    if not 2 <= int(bands) <= 32:
        raise ValueError("bands must be between 2 and 32")
    stft = librosa.stft(y, n_fft=n_fft, hop_length=hop_length, center=True, window="hann")
    frequencies = librosa.fft_frequencies(sr=sample_rate, n_fft=n_fft)
    erb = 21.4 * np.log10(1.0 + 0.00437 * frequencies)
    minimum, maximum = float(erb[0]), float(erb[-1])
    edges = np.linspace(minimum, maximum, int(bands) + 1)
    centers = 0.5 * (edges[:-1] + edges[1:])
    spacing = max(float(edges[1] - edges[0]), 1e-9)
    raw = np.exp(-0.5 * ((erb[None, :] - centers[:, None]) / (0.62 * spacing)) ** 2)
    masks = raw / np.maximum(np.sum(raw, axis=0, keepdims=True), 1e-15)

    stems: list[Stem] = []
    reconstructed = np.zeros_like(y)
    for index, mask in enumerate(masks):
        full = librosa.istft(stft * mask[:, None], hop_length=hop_length, length=y.size, center=True)
        reconstructed += full
        low_hz = _erb_to_hz(edges[index])
        center_hz = _erb_to_hz(centers[index])
        high_hz = _erb_to_hz(edges[index + 1])
        stems.append(
            Stem(
                stem_id=_stable_id("auditory-band-stem", index, bands, sample_rate, n_fft),
                label=f"auditory layer {index + 1} · {low_hz:.0f}–{high_hz:.0f} Hz",
                audio=full,
                start_seconds=0.0,
                source_region=None,
                kind="auditory-band-component",
                metadata={
                    "bandIndex": index,
                    "lowerFrequencyHz": low_hz,
                    "centerFrequencyHz": center_hz,
                    "upperFrequencyHz": high_hz,
                    "frequencyScale": "ERB-rate-spaced smooth STFT partition",
                    "interpretation": "Reversible frequency layer for spatial composition; not a standardized auditory-filter output.",
                },
            )
        )
    residual = y - reconstructed
    error = y - (reconstructed + residual)
    return DecompositionResult(
        source_sample_rate=int(sample_rate),
        source_length_samples=int(y.size),
        stems=tuple(stems),
        residual=Stem(
            stem_id=_stable_id("auditory-band-residual", len(y), bands, sample_rate),
            label="auditory-layer reconstruction residual",
            audio=residual,
            start_seconds=0.0,
            source_region=None,
            kind="residual",
            metadata={"interpretation": "Exact remainder after ERB-rate layer reconstruction."},
        ),
        closure_rms_error=float(np.sqrt(np.mean(error**2))),
        closure_peak_error=float(np.max(np.abs(error))),
        method="mus.auditory-band-decomposition/1",
        parameters={"bands": int(bands), "nFft": n_fft, "hopLength": hop_length, "scale": "ERB-rate"},
    )


def hpss_decomposition(
    signal: Any,
    sample_rate: int,
    *,
    n_fft: int = 2048,
    hop_length: int = 256,
    harmonic_margin: float = 1.0,
    percussive_margin: float = 1.0,
) -> DecompositionResult:
    """Create harmonic-like and percussive-like object layers plus residual."""
    np, _, librosa, _ = _dependencies()
    y = np.asarray(signal, dtype=np.float64).reshape(-1)
    if y.size == 0:
        raise ValueError("signal is empty")
    stft = librosa.stft(y, n_fft=n_fft, hop_length=hop_length, center=True, window="hann")
    harmonic_stft, percussive_stft = librosa.decompose.hpss(
        stft,
        margin=(float(harmonic_margin), float(percussive_margin)),
    )
    harmonic = librosa.istft(harmonic_stft, hop_length=hop_length, length=y.size, center=True)
    percussive = librosa.istft(percussive_stft, hop_length=hop_length, length=y.size, center=True)
    reconstructed = harmonic + percussive
    residual = y - reconstructed
    error = y - (reconstructed + residual)
    stems = (
        Stem(
            stem_id=_stable_id("hpss-harmonic", len(y), sample_rate, harmonic_margin),
            label="harmonic-like layer",
            audio=harmonic,
            start_seconds=0.0,
            source_region=None,
            kind="harmonic-component",
            metadata={
                "interpretation": "Median-filter HPSS harmonic-like component; not a physical-source or perceptual-harmonicity assertion.",
            },
        ),
        Stem(
            stem_id=_stable_id("hpss-percussive", len(y), sample_rate, percussive_margin),
            label="percussive-like layer",
            audio=percussive,
            start_seconds=0.0,
            source_region=None,
            kind="percussive-component",
            metadata={
                "interpretation": "Median-filter HPSS percussive-like component; not a physical-source assertion.",
            },
        ),
    )
    return DecompositionResult(
        source_sample_rate=int(sample_rate),
        source_length_samples=int(y.size),
        stems=stems,
        residual=Stem(
            stem_id=_stable_id("hpss-residual", len(y), sample_rate, harmonic_margin, percussive_margin),
            label="HPSS reconstruction residual",
            audio=residual,
            start_seconds=0.0,
            source_region=None,
            kind="residual",
            metadata={"interpretation": "Exact remainder after harmonic/percussive reconstruction."},
        ),
        closure_rms_error=float(np.sqrt(np.mean(error**2))),
        closure_peak_error=float(np.max(np.abs(error))),
        method="mus.hpss-decomposition/1",
        parameters={
            "nFft": n_fft,
            "hopLength": hop_length,
            "harmonicMargin": float(harmonic_margin),
            "percussiveMargin": float(percussive_margin),
        },
    )


def write_decomposition(result: DecompositionResult, output_dir: str | Path) -> tuple[Path, dict[str, str]]:
    """Write stems, residual, and a JSON report."""
    _, _, _, sf = _dependencies()
    root = Path(output_dir)
    stems_dir = root / "stems"
    stems_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    for index, stem in enumerate(result.stems):
        path = stems_dir / f"{index:04d}-{_slug(stem.label)}-{stem.stem_id[-10:]}.wav"
        sf.write(path, stem.audio, result.source_sample_rate, subtype="FLOAT")
        files[stem.stem_id] = path.relative_to(root).as_posix()
    residual_path = root / "residual.wav"
    sf.write(residual_path, result.residual.audio, result.source_sample_rate, subtype="FLOAT")
    report = result.report_dict(stem_files=files, residual_file=residual_path.relative_to(root).as_posix())
    report_path = root / "decomposition.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", "utf-8")
    return report_path, files


def _time_weight(times: Any, start: float, end: float, pad: float) -> Any:
    np, _, _, _ = _dependencies()
    times = np.asarray(times, dtype=float)
    weight = np.zeros_like(times)
    core = (times >= start) & (times <= end)
    weight[core] = 1.0
    if pad > 0:
        left = (times >= start - pad) & (times < start)
        right = (times > end) & (times <= end + pad)
        weight[left] = 0.5 - 0.5 * np.cos(math.pi * (times[left] - (start - pad)) / pad)
        weight[right] = 0.5 + 0.5 * np.cos(math.pi * (times[right] - end) / pad)
    return weight


def _erb_to_hz(rate: float) -> float:
    return float((10 ** (float(rate) / 21.4) - 1.0) / 0.00437)


def _component_centroid(template: Any, sample_rate: int, n_fft: int) -> float:
    np, _, librosa, _ = _dependencies()
    frequencies = librosa.fft_frequencies(sr=sample_rate, n_fft=n_fft)
    template = np.asarray(template, dtype=float)
    return float(np.sum(frequencies * template) / max(float(np.sum(template)), 1e-15))


def _first_number(row: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            return float(value)
    return None


def _stable_id(namespace: str, *parts: Any) -> str:
    payload = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return f"urn:sophia:mus:{namespace}:sha256:{sha256(payload).hexdigest()}"


def _slug(value: str) -> str:
    text = "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")
    return "-".join(piece for piece in text.split("-") if piece)[:48] or "stem"


def _dependencies() -> tuple[Any, Any, Any, Any]:
    try:
        import numpy as np
        from scipy import signal as scipy_signal
        import librosa
        import soundfile as sf
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("decomposition requires the 'audio' optional dependencies") from exc
    return np, scipy_signal, librosa, sf
