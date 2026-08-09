"""Content-addressed dense numeric artifacts.

RDF and run receipts describe arrays; they do not contain every frame/bin.  NPY
is the first lossless on-disk lane because it is simple, deterministic for a
fixed ndarray, and already available wherever the Aigua analysis runs.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Any

from .model import ArtifactRef
from .store import ResearchObjectStore


@dataclass(frozen=True, slots=True)
class DenseArrayRef:
    artifact: ArtifactRef
    shape: tuple[int, ...]
    dtype: str
    array_format: str = "npy/1"
    order: str = "C"
    missing_value_semantics: str | None = None


def put_array(
    store: ResearchObjectStore,
    array: "object",
    *,
    role: str | None = None,
    missing_value_semantics: str | None = None,
) -> DenseArrayRef:
    import numpy as np

    value = np.asarray(array)
    if value.dtype.hasobject:
        raise ValueError("object arrays are forbidden; encode structured metadata separately")
    contiguous = np.ascontiguousarray(value)
    buffer = BytesIO()
    np.save(buffer, contiguous, allow_pickle=False)
    artifact = store.put_bytes(
        buffer.getvalue(),
        media_type="application/x-npy",
        role=role,
    )
    return DenseArrayRef(
        artifact=artifact,
        shape=tuple(int(item) for item in contiguous.shape),
        dtype=contiguous.dtype.str,
        order="C",
        missing_value_semantics=missing_value_semantics,
    )


def read_array(store: ResearchObjectStore, ref: DenseArrayRef) -> "object":
    import numpy as np

    data = store.read_artifact(ref.artifact)
    value = np.load(BytesIO(data), allow_pickle=False)
    if tuple(value.shape) != ref.shape or value.dtype.str != ref.dtype:
        raise ValueError("dense-array metadata does not match artifact bytes")
    return value
