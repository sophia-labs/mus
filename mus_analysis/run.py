"""Execution seam for capturing real analysis commands as immutable runs."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any, Mapping, Sequence

from .canonical import content_urn
from .model import Diagnostic, OperatorRef, ProfileRef, RunReceipt, RunStatus
from .store import ResearchObjectStore


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class CommandSpec:
    run_type: str
    profile: ProfileRef
    operators: tuple[OperatorRef, ...]
    command: tuple[str, ...]
    cwd: Path
    input_paths: tuple[Path, ...] = ()
    output_paths: tuple[Path, ...] = ()
    parameters: Mapping[str, Any] = field(default_factory=dict)
    env: Mapping[str, str] = field(default_factory=dict)
    timeout_seconds: float | None = None


class CommandRunError(RuntimeError):
    def __init__(self, receipt: RunReceipt):
        super().__init__(f"analysis command failed: {receipt.run_id}")
        self.receipt = receipt


def run_command(store: ResearchObjectStore, spec: CommandSpec, *, raise_on_failure: bool = True) -> RunReceipt:
    """Execute a real command and capture its material boundary.

    Inputs are snapshotted before execution. Outputs, stdout and stderr are
    content-addressed after execution. Missing declared outputs are diagnostics,
    never silently ignored. The work directory itself may be mutable; the
    resulting research object is not.
    """
    started = utc_now()
    inputs = tuple(
        store.put_file(spec.cwd / path if not path.is_absolute() else path, role=f"input:{path}")
        for path in spec.input_paths
    )
    process_env = os.environ.copy()
    process_env.update(spec.env)
    command = tuple(str(item) for item in spec.command)
    proc = subprocess.run(
        command,
        cwd=spec.cwd,
        env=process_env,
        capture_output=True,
        timeout=spec.timeout_seconds,
        check=False,
    )
    stdout_ref = store.put_bytes(proc.stdout, media_type="text/plain; charset=utf-8", role="stdout")
    stderr_ref = store.put_bytes(proc.stderr, media_type="text/plain; charset=utf-8", role="stderr")
    outputs = [stdout_ref, stderr_ref]
    diagnostics: list[Diagnostic] = []
    for path in spec.output_paths:
        full = spec.cwd / path if not path.is_absolute() else path
        if not full.is_file():
            diagnostics.append(
                Diagnostic(
                    code="MUSA-RUN-OUTPUT-MISSING",
                    message=f"declared output was not produced: {path}",
                    anchor=str(path),
                )
            )
            continue
        outputs.append(store.put_file(full, role=f"output:{path}"))
    if proc.returncode != 0:
        diagnostics.append(
            Diagnostic(
                code="MUSA-RUN-NONZERO-EXIT",
                message=f"command exited with status {proc.returncode}",
                detail={"returnCode": proc.returncode},
            )
        )
    status = RunStatus.SUCCEEDED if not diagnostics else RunStatus.FAILED
    completed = utc_now()
    seed = {
        "run_type": spec.run_type,
        "profile": spec.profile,
        "status": status,
        "producer": "mus-analysis-command-runner/1",
        "started_at": started,
        "completed_at": completed,
        "inputs": inputs,
        "outputs": tuple(outputs),
        "operators": spec.operators,
        "parameters": {**spec.parameters, "command": command},
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "executable": sys.executable,
            "declaredEnvironment": dict(spec.env),
        },
        "diagnostics": tuple(diagnostics),
    }
    # Run identity includes the actual temporal execution and output artifacts;
    # two repeated executions remain distinguishable even when byte-identical.
    receipt = RunReceipt(run_id=content_urn("run", seed), **seed)
    store.write_run(receipt)
    if status is RunStatus.FAILED and raise_on_failure:
        raise CommandRunError(receipt)
    return receipt
