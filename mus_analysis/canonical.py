"""Deterministic JSON and content identities for MUS analysis objects.

The scientific layer is deliberately conservative: canonicalization accepts
ordinary JSON-compatible values plus dataclasses, enums, Decimal, datetime and
Path, rejects non-finite numbers, normalizes negative zero, and emits UTF-8 JSON
with sorted keys and no insignificant whitespace.

This is not advertised as a full RFC 8785 implementation.  The schema names the
algorithm (`mus-canonical-json/1`) so a future migration can be explicit rather
than silently changing object identities.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

CANONICALIZATION_ID = "mus-canonical-json/1"


class CanonicalizationError(ValueError):
    """Raised when a value cannot be represented by the canonical JSON codec."""


def _datetime_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise CanonicalizationError("naive datetimes are forbidden; supply an explicit timezone")
    utc = value.astimezone(timezone.utc)
    return utc.isoformat(timespec="microseconds").replace("+00:00", "Z")


def normalize(value: Any) -> Any:
    """Return a deterministic, JSON-compatible representation of ``value``."""
    if is_dataclass(value):
        return normalize(asdict(value))
    if isinstance(value, Enum):
        return normalize(value.value)
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, datetime):
        return _datetime_text(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise CanonicalizationError("non-finite Decimal values are forbidden")
        # Preserve exact decimal semantics without introducing a binary float.
        return format(value, "f")
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalizationError("NaN and infinity are forbidden")
        return 0.0 if value == 0.0 else value
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalizationError(f"object keys must be strings, got {type(key).__name__}")
            out[key] = normalize(item)
        return out
    if isinstance(value, (set, frozenset)):
        normalized = [normalize(item) for item in value]
        return sorted(normalized, key=lambda item: canonical_text(item))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [normalize(item) for item in value]
    raise CanonicalizationError(f"unsupported value type: {type(value).__name__}")


def canonical_text(value: Any) -> str:
    """Serialize ``value`` using the MUS canonical JSON v1 codec."""
    return json.dumps(
        normalize(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_bytes(value: Any) -> bytes:
    return canonical_text(value).encode("utf-8")


def digest_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def content_digest(value: Any) -> str:
    return digest_bytes(canonical_bytes(value))


def content_urn(kind: str, value: Any) -> str:
    if not kind or any(ch.isspace() for ch in kind):
        raise CanonicalizationError("content URN kind must be a non-empty token")
    return f"urn:sophia:mus:{kind}:sha256:{content_digest(value)}"
