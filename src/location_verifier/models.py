"""Core data contracts shared by the verifier and its future integrations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
import math


def _require_non_empty(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must not be empty")


@dataclass(frozen=True, slots=True)
class GeoLocation:
    """Latitude and longitude in decimal degrees."""

    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.latitude) or not -90 <= self.latitude <= 90:
            raise ValueError("latitude must be finite and between -90 and 90")
        if not math.isfinite(self.longitude) or not -180 <= self.longitude <= 180:
            raise ValueError("longitude must be finite and between -180 and 180")


@dataclass(frozen=True, slots=True)
class PeerClaim:
    """A peer's asserted location and physical failure-domain identity."""

    peer_id: str
    claimed_location: GeoLocation
    claimed_failure_domain: str

    def __post_init__(self) -> None:
        _require_non_empty(self.peer_id, "peer_id")
        _require_non_empty(self.claimed_failure_domain, "claimed_failure_domain")


class MeasurementFailureReason(StrEnum):
    """Why an individual network measurement did not produce an RTT."""

    TIMEOUT = "TIMEOUT"
    TARGET_UNREACHABLE = "TARGET_UNREACHABLE"
    MALFORMED_OUTPUT = "MALFORMED_OUTPUT"
    COMMAND_ERROR = "COMMAND_ERROR"


@dataclass(frozen=True, slots=True)
class MeasurementObservation:
    """One timestamped RTT observation; timeout observations have no RTT."""

    timestamp: datetime
    rtt_ms: float | None
    timed_out: bool = False
    failure_reason: MeasurementFailureReason | None = None

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        if self.timed_out and self.rtt_ms is not None:
            raise ValueError("timed-out observations must not include an RTT")
        if self.timed_out and self.failure_reason not in (
            None,
            MeasurementFailureReason.TIMEOUT,
        ):
            raise ValueError("timed-out observations must use the TIMEOUT failure reason")
        if (
            self.failure_reason is MeasurementFailureReason.TIMEOUT
            and not self.timed_out
        ):
            raise ValueError("TIMEOUT failure reasons must set timed_out=True")
        if not self.timed_out and self.rtt_ms is None:
            if self.failure_reason is None:
                raise ValueError("failed observations must include a failure reason")
        if self.rtt_ms is not None and self.failure_reason is not None:
            raise ValueError("successful observations must not include a failure reason")
        if self.rtt_ms is not None and (
            not math.isfinite(self.rtt_ms) or self.rtt_ms < 0
        ):
            raise ValueError("rtt_ms must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class Witness:
    """A measurement witness and its current evidence-quality metadata."""

    witness_id: str
    location: GeoLocation
    known_failure_domain: str | None = None
    measurement_history: tuple[MeasurementObservation, ...] = field(default_factory=tuple)
    reliability_score: float = 0.5

    def __post_init__(self) -> None:
        _require_non_empty(self.witness_id, "witness_id")
        if self.known_failure_domain is not None:
            _require_non_empty(self.known_failure_domain, "known_failure_domain")
        if not math.isfinite(self.reliability_score) or not 0 <= self.reliability_score <= 1:
            raise ValueError("reliability_score must be between 0 and 1")


class VerificationStatus(StrEnum):
    """Non-binary outcomes exposed to downstream placement components."""

    PLAUSIBLE = "PLAUSIBLE"
    UNCERTAIN = "UNCERTAIN"
    SUSPICIOUS = "SUSPICIOUS"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Stable result contract for direct calls and future service adapters."""

    peer_id: str
    claimed_failure_domain: str
    status: VerificationStatus
    confidence: float
    uncertainty: float
    witness_agreement: float | None = None
    evidence: tuple[dict[str, object], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _require_non_empty(self.peer_id, "peer_id")
        _require_non_empty(self.claimed_failure_domain, "claimed_failure_domain")
        for name, value in (
            ("confidence", self.confidence),
            ("uncertainty", self.uncertainty),
        ):
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.witness_agreement is not None and (
            not math.isfinite(self.witness_agreement)
            or not 0 <= self.witness_agreement <= 1
        ):
            raise ValueError("witness_agreement must be between 0 and 1")
