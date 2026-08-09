#!/usr/bin/env python3
"""Repository-local convenience wrapper for the Aigua v1 fossil import."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mus_analysis.cli import main

if __name__ == "__main__":
    raise SystemExit(
        main(
            [
                "import-aigua-v1",
                "--project-root",
                str(ROOT),
                "--store",
                str(ROOT / "aigua" / "research-object"),
                *sys.argv[1:],
            ]
        )
    )
