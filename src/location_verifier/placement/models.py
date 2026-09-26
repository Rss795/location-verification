"""Placement-specific immutable records and outcome enums."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import json
import math
from types import MappingProxyType
from typing import Mapping

from ..models import PeerClaim, VerificationResult, VerificationStatus


class VerificationPolicyMode(StrEnum):
    STRICT = "strict"
    BALANCED = "balanced"
    PERMISSIVE = "permissive"


class EligibilityState(StrEnum):
    ACTIVE = "ACTIVE"
    ELIGIBLE = "ELIGIBLE"
    CONDITIONAL = "CONDITIONAL"
    QUARANTINED = "QUARANTINED"
    INELIGIBLE = "INELIGIBLE"


class PlacementMode(StrEnum):
    BASELINE = "BASELINE"
    FDAR = "FDAR"


class PlacementStatus(StrEnum):
    SUCCESS = "SUCCESS"
    INSUFFICIENT_DOMAINS = "INSUFFICIENT_DOMAINS"
    NO_ELIGIBLE_PEERS = "NO_ELIGIBLE_PEERS"


@dataclass(frozen=True, slots=True)
class PlacementPeer:
    """Candidate peer with declared hierarchy, claim, verification, and availability."""

    peer_id: str
    claim: PeerClaim
    failure_domains: Mapping[str, str]
    verification: VerificationResult | None = None
    available: bool = True
    topology_verification_state: str | None = None
    witnessing_zone_verification_state: str | None = None
    topology_verification_states: tuple[str, ...] = ()
    weight: float = 1.0

    def __post_init__(self) -> None:
        if not self.peer_id.strip():
            raise ValueError("peer_id must not be empty")
        if self.claim.peer_id != self.peer_id:
            raise ValueError("claim peer_id must match placement peer_id")
        for level, identifier in self.failure_domains.items():
            if not level.strip() or not identifier.strip():
                raise ValueError("failure-domain levels and identifiers must not be empty")
        object.__setattr__(self, "failure_domains", MappingProxyType(dict(self.failure_domains)))
        if self.verification is not None and self.verification.peer_id != self.peer_id:
            raise ValueError("verification peer_id must match placement peer_id")
        if self.topology_verification_state is not None and not self.topology_verification_state.strip():
            raise ValueError("topology_verification_state must not be empty")
        if self.witnessing_zone_verification_state is not None and not self.witnessing_zone_verification_state.strip():
            raise ValueError("witnessing_zone_verification_state must not be empty")
        if not math.isfinite(self.weight) or self.weight <= 0:
            raise ValueError("peer weight must be finite and positive")

    @property
    def verification_status(self) -> VerificationStatus:
        if self.verification is None:
            return VerificationStatus.INSUFFICIENT_EVIDENCE
        return self.verification.status


@dataclass(frozen=True, slots=True)
class PeerDecision:
    """Placement policy decision retained for selected and excluded peers."""

    peer_id: str
    state: EligibilityState
    reason: str
    preference_multiplier: float
    verification_status: VerificationStatus
    confidence: float | None
    uncertainty: float | None
    topology_verification_state: str | None = None
    witnessing_zone_verification_state: str | None = None


@dataclass(frozen=True, slots=True)
class SelectedReplica:
    """One selected peer with the selection explanation and its domain."""

    peer_id: str
    failure_domain: str
    domain_level: str
    verification_status: VerificationStatus
    confidence: float | None
    uncertainty: float | None
    why_eligible: str
    why_selected: str
    preference_score: float
    topology_verification_state: str | None = None
    witnessing_zone_verification_state: str | None = None


@dataclass(frozen=True, slots=True)
class PlacementResult:
    """Explainable deterministic placement outcome, serializable as JSON."""

    object_id: str
    requested_replication_factor: int
    selected_peers: tuple[SelectedReplica, ...]
    selected_failure_domains: tuple[str, ...]
    failure_domain_level: str
    excluded_peers: tuple[PeerDecision, ...]
    placement_status: PlacementStatus
    placement_reason: str
    mode: PlacementMode
    eligible_peer_count: int
    available_distinct_failure_domains: int
    deterministic_selection_metadata: dict[str, str] = field(default_factory=dict)
    verification_summary: dict[str, int] = field(default_factory=dict)

    @property
    def placement_success(self) -> bool:
        return self.placement_status is PlacementStatus.SUCCESS

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "object_id": self.object_id,
            "requested_replication_factor": self.requested_replication_factor,
            "selected_peers": [
                {
                    "peer_id": replica.peer_id,
                    "failure_domain": replica.failure_domain,
                    "domain_level": replica.domain_level,
                    "verification_status": replica.verification_status.value,
                    "confidence": replica.confidence,
                    "uncertainty": replica.uncertainty,
                    "why_eligible": replica.why_eligible,
                    "why_selected": replica.why_selected,
                    "preference_score": replica.preference_score,
                    "topology_verification_state": replica.topology_verification_state,
                    "witnessing_zone_verification_state": replica.witnessing_zone_verification_state,
                }
                for replica in self.selected_peers
            ],
            "selected_failure_domains": list(self.selected_failure_domains),
            "failure_domain_level": self.failure_domain_level,
            "excluded_peers": [
                {
                    "peer_id": item.peer_id,
                    "state": item.state.value,
                    "reason": item.reason,
                    "verification_status": item.verification_status.value,
                    "confidence": item.confidence,
                    "uncertainty": item.uncertainty,
                    "topology_verification_state": item.topology_verification_state,
                    "witnessing_zone_verification_state": item.witnessing_zone_verification_state,
                }
                for item in self.excluded_peers
            ],
            "placement_status": self.placement_status.value,
            "placement_reason": self.placement_reason,
            "mode": self.mode.value,
            "eligible_peer_count": self.eligible_peer_count,
            "available_distinct_failure_domains": self.available_distinct_failure_domains,
            "deterministic_selection_metadata": self.deterministic_selection_metadata,
            "verification_summary": self.verification_summary,
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True, allow_nan=False)


@dataclass(frozen=True, slots=True)
class PlacementMetrics:
    replica_count: int
    distinct_failure_domains: int
    domain_collision_count: int
    eligible_peer_count: int
    excluded_peer_count: int
    uncertain_peer_count: int
    suspicious_peer_count: int
    placement_success: bool
    reconfiguration_move_count: int = 0

    def __post_init__(self) -> None:
        for name, value in (
            ("replica_count", self.replica_count),
            ("distinct_failure_domains", self.distinct_failure_domains),
            ("domain_collision_count", self.domain_collision_count),
            ("eligible_peer_count", self.eligible_peer_count),
            ("excluded_peer_count", self.excluded_peer_count),
            ("uncertain_peer_count", self.uncertain_peer_count),
            ("suspicious_peer_count", self.suspicious_peer_count),
            ("reconfiguration_move_count", self.reconfiguration_move_count),
        ):
            if value < 0:
                raise ValueError(f"{name} must be non-negative")


def verification_scores(result: VerificationResult | None) -> tuple[float, float, float]:
    """Extract confidence, agreement, and mean witness measurement quality."""

    if result is None:
        return 0.0, 0.0, 0.0
    quality_values = [
        float(record["measurement_quality"])
        for record in result.evidence
        if isinstance(record, dict)
        and isinstance(record.get("measurement_quality"), (int, float))
        and math.isfinite(float(record["measurement_quality"]))
    ]
    quality = sum(quality_values) / len(quality_values) if quality_values else 0.0
    return (
        result.confidence,
        result.witness_agreement or 0.0,
        min(max(quality, 0.0), 1.0),
    )
