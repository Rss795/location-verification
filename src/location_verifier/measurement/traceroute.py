"""Optional path-evidence collection, independent from RTT measurement."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
import shutil
import subprocess
import sys

from .ping import validate_target


class TracerouteStatus(StrEnum):
    SUCCESS = "SUCCESS"
    UNAVAILABLE = "UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    INVALID_TARGET = "INVALID_TARGET"
    COMMAND_ERROR = "COMMAND_ERROR"


@dataclass(frozen=True, slots=True)
class TracerouteResult:
    """Optional supporting path output; hop text is not geographic proof."""

    status: TracerouteStatus
    hops: tuple[str, ...] = ()
    detail: str | None = None


def collect_traceroute(
    host: str,
    timeout_seconds: float = 30.0,
    max_hops: int = 20,
    *,
    platform_name: str | None = None,
) -> TracerouteResult:
    """Run traceroute/tracert if available, returning status instead of raising."""

    try:
        validate_target(host)
    except ValueError as exc:
        return TracerouteResult(TracerouteStatus.INVALID_TARGET, detail=str(exc))
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0 or max_hops < 1:
        return TracerouteResult(TracerouteStatus.COMMAND_ERROR, detail="invalid traceroute settings")

    platform_name = platform_name or sys.platform
    if platform_name == "win32":
        executable = "tracert"
        command = [executable, "-d", "-h", str(max_hops), "-w", str(math.ceil(timeout_seconds * 1000)), host]
    elif platform_name == "darwin" or platform_name.startswith("linux"):
        executable = "traceroute"
        command = [executable, "-n", "-m", str(max_hops), "-w", str(timeout_seconds), "-q", "1", host]
    else:
        return TracerouteResult(TracerouteStatus.UNAVAILABLE, detail="unsupported platform")

    resolved = shutil.which(executable)
    if resolved is None:
        return TracerouteResult(TracerouteStatus.UNAVAILABLE, detail="traceroute executable not found")
    command[0] = resolved
    try:
        completed = subprocess.run(
            command,
            shell=False,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return TracerouteResult(TracerouteStatus.TIMEOUT)
    except OSError as exc:
        return TracerouteResult(TracerouteStatus.COMMAND_ERROR, detail=str(exc))

    hop_lines = tuple(
        line.strip()
        for line in completed.stdout.splitlines()
        if line.strip() and line.lstrip()[:1].isdigit()
    )
    if completed.returncode == 0 or hop_lines:
        return TracerouteResult(TracerouteStatus.SUCCESS, hop_lines)
    return TracerouteResult(
        TracerouteStatus.COMMAND_ERROR,
        hop_lines,
        f"traceroute exited with status {completed.returncode}",
    )
