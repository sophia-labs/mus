"""Write-once research-object storage for MUS analyses."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from hashlib import sha256
import json
import mimetypes
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Iterable

from .canonical import canonical_bytes, normalize
from .model import ArtifactRef, ResearchProjection, RunReceipt


class ResearchObjectError(RuntimeError):
    pass


class ImmutableConflictError(ResearchObjectError):
    """A named write tried to replace different durable bytes."""


class VerificationError(ResearchObjectError):
    pass


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as tmp:
        tmp.write(data)
        tmp.flush()
        os.fsync(tmp.fileno())
        temp_path = Path(tmp.name)
    os.replace(temp_path, path)


def _write_once(path: Path, data: bytes) -> None:
    if path.exists():
        existing = path.read_bytes()
        if existing != data:
            raise ImmutableConflictError(f"refusing to replace immutable object: {path}")
        return
    _atomic_write(path, data)


class ResearchObjectStore:
    """A directory-backed, content-addressed scientific object.

    Objects under ``objects/sha256`` are immutable by digest. Named receipts and
    projections are also write-once: rerunning the exact same materialization is
    idempotent; a different byte sequence at the same name is a hard conflict.
    """

    MANIFEST_SCHEMA = "https://sophia-labs.ai/schemas/mus-analysis/store-manifest/1"

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.objects = self.root / "objects" / "sha256"
        self.runs = self.root / "runs"
        self.projections = self.root / "projections"
        self.root.mkdir(parents=True, exist_ok=True)
        self.objects.mkdir(parents=True, exist_ok=True)
        self.runs.mkdir(parents=True, exist_ok=True)
        self.projections.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def artifact_uri(digest: str) -> str:
        return f"urn:sophia:mus:artifact:sha256:{digest}"

    def object_path(self, digest: str) -> Path:
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("invalid sha256 digest")
        return self.objects / digest[:2] / digest[2:]

    def put_bytes(self, data: bytes, *, media_type: str, role: str | None = None) -> ArtifactRef:
        digest = sha256(data).hexdigest()
        _write_once(self.object_path(digest), data)
        return ArtifactRef(
            uri=self.artifact_uri(digest),
            sha256=digest,
            media_type=media_type,
            byte_length=len(data),
            role=role,
        )

    def put_text(
        self,
        text: str,
        *,
        media_type: str = "text/plain; charset=utf-8",
        role: str | None = None,
    ) -> ArtifactRef:
        return self.put_bytes(text.encode("utf-8"), media_type=media_type, role=role)

    def put_json(self, value: Any, *, role: str | None = None) -> ArtifactRef:
        return self.put_bytes(
            canonical_bytes(value) + b"\n",
            media_type="application/json",
            role=role,
        )

    def put_file(
        self,
        source: str | Path,
        *,
        media_type: str | None = None,
        role: str | None = None,
    ) -> ArtifactRef:
        path = Path(source)
        guessed = mimetypes.guess_type(path.name)[0]
        return self.put_bytes(path.read_bytes(), media_type=media_type or guessed or "application/octet-stream", role=role)

    def read_artifact(self, ref: ArtifactRef) -> bytes:
        data = self.object_path(ref.sha256).read_bytes()
        actual = sha256(data).hexdigest()
        if actual != ref.sha256 or len(data) != ref.byte_length:
            raise VerificationError(f"artifact failed verification: {ref.uri}")
        return data

    def write_run(self, receipt: RunReceipt) -> Path:
        path = self.runs / _safe_name(receipt.run_id) / "receipt.json"
        _write_once(path, canonical_bytes(receipt) + b"\n")
        return path

    def write_projection(self, name: str, projection: ResearchProjection | Any) -> Path:
        path = self.projections / f"{_safe_name(name)}.json"
        _write_once(path, canonical_bytes(projection) + b"\n")
        return path

    def write_named_bytes(self, relative_path: str | Path, data: bytes) -> Path:
        path = self.root / relative_path
        try:
            path.resolve().relative_to(self.root.resolve())
        except ValueError as exc:
            raise ValueError("named path escapes research-object root") from exc
        _write_once(path, data)
        return path

    def write_named_json(self, relative_path: str | Path, value: Any) -> Path:
        return self.write_named_bytes(relative_path, canonical_bytes(value) + b"\n")

    def manifest(self) -> dict[str, Any]:
        object_rows = []
        for path in sorted(p for p in self.objects.rglob("*") if p.is_file()):
            data = path.read_bytes()
            digest = path.parent.name + path.name
            object_rows.append({
                "sha256": digest,
                "byteLength": len(data),
                "verified": sha256(data).hexdigest() == digest,
            })
        run_rows = []
        for path in sorted(self.runs.glob("*/receipt.json")):
            value = json.loads(path.read_text("utf-8"))
            run_rows.append({"runId": value.get("run_id"), "receipt": str(path.relative_to(self.root))})
        projection_rows = [str(path.relative_to(self.root)) for path in sorted(self.projections.glob("*.json"))]
        return {
            "schema": self.MANIFEST_SCHEMA,
            "objects": object_rows,
            "runs": run_rows,
            "projections": projection_rows,
        }

    def write_manifest(self) -> Path:
        # A store manifest is a mutable *index* in ordinary use.  For this first
        # foundation we name snapshots by their own digest and keep a stable
        # pointer out of the immutable core.
        manifest = self.manifest()
        artifact = self.put_json(manifest, role="store-manifest-snapshot")
        pointer = {
            "schema": self.MANIFEST_SCHEMA,
            "manifestArtifact": normalize(artifact),
        }
        path = self.root / "manifest.json"
        _atomic_write(path, canonical_bytes(pointer) + b"\n")
        return path

    def verify(self) -> dict[str, Any]:
        failures: list[str] = []
        checked = 0
        for path in sorted(p for p in self.objects.rglob("*") if p.is_file()):
            digest = path.parent.name + path.name
            data = path.read_bytes()
            checked += 1
            if sha256(data).hexdigest() != digest:
                failures.append(f"digest mismatch: {path.relative_to(self.root)}")
        for path in sorted(self.runs.glob("*/receipt.json")):
            try:
                receipt = json.loads(path.read_text("utf-8"))
            except Exception as exc:  # pragma: no cover - defensive verification path
                failures.append(f"invalid run receipt {path.relative_to(self.root)}: {exc}")
                continue
            for direction in ("inputs", "outputs"):
                for artifact in receipt.get(direction, []):
                    digest = artifact.get("sha256")
                    if not isinstance(digest, str) or not self.object_path(digest).is_file():
                        failures.append(
                            f"missing {direction[:-1]} artifact {digest!r} for {receipt.get('run_id')}"
                        )
        result = {"ok": not failures, "objectsChecked": checked, "failures": failures}
        if failures:
            raise VerificationError("; ".join(failures))
        return result


def _safe_name(value: str) -> str:
    digest = sha256(value.encode("utf-8")).hexdigest()[:16]
    readable = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in value)[-72:]
    return f"{readable}-{digest}"
