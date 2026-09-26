"""Platform-aware, shell-free ICMP ping measurement."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import ipaddress
import math
import re
import shutil
import subprocess
import sys
from typing import Protocol


class PingStatus(StrEnum):
    """Outcome of one low-level ping attempt."""

    SUCCESS = "SUCCESS"
    TIMEOUT = "TIMEOUT"
    TARGET_UNREACHABLE = "TARGET_UNREACHABLE"
    PING_COMMAND_UNAVAILABLE = "PING_COMMAND_UNAVAILABLE"
    INVALID_TARGET = "INVALID_TARGET"
    MALFORMED_OUTPUT = "MALFORMED_OUTPUT"
    COMMAND_ERROR = "COMMAND_ERROR"


@dataclass(frozen=True, slots=True)
class PingResult:
    """One ping outcome with RTT only when a response was parsed."""

    status: PingStatus
    rtt_ms: float | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        if self.status is PingStatus.SUCCESS:
            if self.rtt_ms is None or not math.isfinite(self.rtt_ms) or self.rtt_ms < 0:
                raise ValueError("successful ping results require a finite non-negative RTT")
        elif self.rtt_ms is not None:
            raise ValueError("failed ping results must not include an RTT")


class PingSource(Protocol):
    """Common interface for real and future simulated measurement sources."""

    def ping_once(self, host: str, timeout_seconds: float) -> PingResult:
        """Measure one request/response RTT to a host."""


def validate_target(host: str) -> str:
    """Validate an IP address or DNS hostname before passing it as an argument."""

    if not isinstance(host, str) or not host or len(host) > 253:
        raise ValueError("target must be a non-empty IP address or hostname")
    if host != host.strip() or host.startswith("-"):
        raise ValueError("target contains invalid whitespace or option syntax")
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass

    hostname = host[:-1] if host.endswith(".") else host
    labels = hostname.split(".")
    if not hostname or any(
        not label
        or len(label) > 63
        or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", label)
        for label in labels
    ):
        raise ValueError("target must be a valid IP address or DNS hostname")
    return host


def build_ping_command(
    host: str,
    timeout_seconds: float,
    platform_name: str | None = None,
) -> list[str]:
    """Build an argument vector using the current OS's ping timeout syntax."""

    validate_target(host)
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be finite and positive")
    platform_name = platform_name or sys.platform
    if platform_name == "win32":
        timeout_ms = max(1, math.ceil(timeout_seconds * 1000))
        return ["ping", "-n", "1", "-w", str(timeout_ms), host]
    if platform_name == "darwin":
        timeout_ms = max(1, math.ceil(timeout_seconds * 1000))
        return ["ping", "-n", "-c", "1", "-W", str(timeout_ms), host]
    if platform_name.startswith("linux"):
        timeout_s = max(1, math.ceil(timeout_seconds))
        return ["ping", "-n", "-c", "1", "-W", str(timeout_s), host]
    raise OSError(f"ping arguments are not defined for platform {platform_name!r}")


_RTT_PATTERN = re.compile(r"time[=<]\s*(\d+(?:\.\d+)?)\s*ms", re.IGNORECASE)
_UNREACHABLE_PATTERN = re.compile(
    r"destination (?:host |network )?unreachable|network is unreachable|no route to host",
    re.IGNORECASE,
)
_TIMEOUT_PATTERN = re.compile(
    r"request timed out|100% packet loss|100\.0% packet loss|timed out",
    re.IGNORECASE,
)


def parse_ping_output(stdout: str, stderr: str = "", returncode: int = 0) -> PingResult:
    """Parse common Windows, Linux, and macOS ping response formats."""

    output = f"{stdout}\n{stderr}"
    if _UNREACHABLE_PATTERN.search(output):
        return PingResult(PingStatus.TARGET_UNREACHABLE)
    match = _RTT_PATTERN.search(output)
    if match:
        return PingResult(PingStatus.SUCCESS, float(match.group(1)))
    if _TIMEOUT_PATTERN.search(output):
        return PingResult(PingStatus.TIMEOUT)
    if returncode == 0:
        return PingResult(PingStatus.MALFORMED_OUTPUT)
    return PingResult(PingStatus.COMMAND_ERROR, detail=f"ping exited with status {returncode}")


class RealPingSource:
    """Executes the system ping command without invoking a shell."""

    def __init__(self, platform_name: str | None = None) -> None:
        self._platform_name = platform_name or sys.platform

    def ping_once(self, host: str, timeout_seconds: float) -> PingResult:
        try:
            command = build_ping_command(host, timeout_seconds, self._platform_name)
        except ValueError as exc:
            return PingResult(PingStatus.INVALID_TARGET, detail=str(exc))
        except OSError as exc:
            return PingResult(PingStatus.PING_COMMAND_UNAVAILABLE, detail=str(exc))

        executable = shutil.which(command[0])
        if executable is None:
            return PingResult(PingStatus.PING_COMMAND_UNAVAILABLE, detail="ping executable not found")
        command[0] = executable
        try:
            completed = subprocess.run(
                command,
                shell=False,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_seconds + 1.0,
            )
        except subprocess.TimeoutExpired:
            return PingResult(PingStatus.TIMEOUT)
        except OSError as exc:
            return PingResult(PingStatus.COMMAND_ERROR, detail=str(exc))
        return parse_ping_output(completed.stdout, completed.stderr, completed.returncode)


_default_source = RealPingSource()


def ping_once(host: str, timeout_seconds: float = 2.0) -> PingResult:
    """Perform one real ping using the current platform's system utility."""

    return _default_source.ping_once(host, timeout_seconds)
