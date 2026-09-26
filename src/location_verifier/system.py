"""End-to-end orchestration over existing measurement, verification, and FDAR APIs."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Mapping, Sequence

from .config import InferenceConfig, PlacementConfig
from .inference.verifier import verify
from .measurement.collector import WitnessEvidence
from .models import PeerClaim, VerificationResult, VerificationStatus
from .placement.fdar import place_baseline, place_fdar
from .placement.models import PlacementResult
from .placement.reconfiguration import ReconfigurationPlan, plan_reconfiguration
from .placement.topology import FailureDomainTopology


class SystemRunStatus(StrEnum):
    PLANNED = "PLANNED"
    PLACEMENT_FAILED = "PLACEMENT_FAILED"
    RECONFIGURATION_PLANNED = "RECONFIGURATION_PLANNED"
    RECONFIGURATION_FAILED = "RECONFIGURATION_FAILED"


@dataclass(frozen=True, slots=True)
class SystemRunResult:
    """System-level view that references existing Phase 3/4 results without copying them."""

    object_id: str
    claims: tuple[PeerClaim, ...]
    verification_results: tuple[VerificationResult, ...]
    baseline_placement: PlacementResult | None
    fdar_placement: PlacementResult
    reconfiguration: ReconfigurationPlan | None
    status: SystemRunStatus
    reasons: tuple[str, ...]
    metadata: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible system summary using underlying result serializers."""

        return {
            "object_id": self.object_id,
            "claims": [
                {
                    "peer_id": claim.peer_id,
                    "claimed_location": {
                        "latitude": claim.claimed_location.latitude,
                        "longitude": claim.claimed_location.longitude,
                    },
                    "claimed_failure_domain": claim.claimed_failure_domain,
                }
                for claim in self.claims
            ],
            "verification_results": [
                {
                    "peer_id": item.peer_id,
                    "claimed_failure_domain": item.claimed_failure_domain,
                    "status": item.status.value,
                    "confidence": item.confidence,
                    "uncertainty": item.uncertainty,
                    "witness_agreement": item.witness_agreement,
                    "evidence": item.evidence,
                }
                for item in self.verification_results
            ],
            "baseline_placement": (
                self.baseline_placement.to_dict() if self.baseline_placement else None
            ),
            "fdar_placement": self.fdar_placement.to_dict(),
            "reconfiguration": (
                {
                    "object_id": self.reconfiguration.object_id,
                    "affected_objects": list(self.reconfiguration.affected_objects),
                    "invalidated_peer_ids": list(self.reconfiguration.invalidated_peer_ids),
                    "replacement_candidates": list(self.reconfiguration.replacement_candidates),
                    "required_moves": self.reconfiguration.required_moves,
                    "success": self.reconfiguration.success,
                    "reason": self.reconfiguration.reason,
                    "proposed_placement": self.reconfiguration.proposed_placement.to_dict(),
                }
                if self.reconfiguration
                else None
            ),
            "status": self.status.value,
            "reasons": list(self.reasons),
            "metadata": dict(self.metadata),
            "research_boundary": "RTT plausibility is not cryptographic proof of physical location",
        }


class SystemOrchestrator:
    """Connect Phase 2 evidence to Phase 3 verification and Phase 4 placement."""

    def __init__(
        self,
        inference_config: InferenceConfig,
        placement_config: PlacementConfig,
    ) -> None:
        self.inference_config = inference_config
        self.placement_config = placement_config

    def run(
        self,
        object_id: str,
        topology: FailureDomainTopology,
        claims: Sequence[PeerClaim],
        witness_evidence: Mapping[str, Sequence[WitnessEvidence]],
        *,
        include_baseline: bool = True,
        metadata: Mapping[str, object] | None = None,
    ) -> SystemRunResult:
        """Verify each claim from supplied Phase 2 evidence, then place via FDAR."""

        if not object_id.strip():
            raise ValueError("object_id must not be empty")
        claim_by_id = {claim.peer_id: claim for claim in claims}
        if len(claim_by_id) != len(claims):
            raise ValueError("duplicate peer claims are not allowed")
        if set(claim_by_id) != {peer.peer_id for peer in topology.peers}:
            raise ValueError("claims must exactly match the topology peer set")

        verified_topology = FailureDomainTopology(topology.hierarchy_levels)
        verification_results: list[VerificationResult] = []
        for peer in topology.peers:
            claim = claim_by_id[peer.peer_id]
            evidence = tuple(witness_evidence.get(peer.peer_id, ()))
            verification = verify(claim, evidence, self.inference_config)
            if peer.claim != claim:
                raise ValueError(f"claim for {peer.peer_id} differs from its topology peer record")
            verified_peer = replace(peer, verification=verification)
            verified_topology.add_peer(verified_peer)
            verification_results.append(verification)

        base_result = (
            place_baseline(object_id, verified_topology, self.placement_config)
            if include_baseline
            else None
        )
        fdar_result = place_fdar(object_id, verified_topology, self.placement_config)
        status = (
            SystemRunStatus.PLANNED
            if fdar_result.placement_success
            else SystemRunStatus.PLACEMENT_FAILED
        )
        reasons = (fdar_result.placement_reason,)
        return SystemRunResult(
            object_id=object_id,
            claims=tuple(claim_by_id[key] for key in sorted(claim_by_id)),
            verification_results=tuple(verification_results),
            baseline_placement=base_result,
            fdar_placement=fdar_result,
            reconfiguration=None,
            status=status,
            reasons=reasons,
            metadata=dict(metadata or {}),
        )

    def plan_verification_change(
        self,
        result: SystemRunResult,
        topology: FailureDomainTopology,
        peer_id: str,
        new_status: VerificationStatus,
    ) -> SystemRunResult:
        """Plan reconfiguration after an explicit status change; no data is moved."""

        if not isinstance(new_status, VerificationStatus):
            raise ValueError("new_status must be a VerificationStatus")
        changed_peer = topology.get_peer(peer_id)
        prior_result = next(
            (item for item in result.verification_results if item.peer_id == peer_id),
            changed_peer.verification,
        )
        if prior_result is None:
            raise ValueError(f"no verification result available for peer {peer_id}")
        changed_peer = replace(
            changed_peer,
            verification=replace(prior_result, status=new_status),
        )
        changed_topology = FailureDomainTopology(topology.hierarchy_levels)
        for peer in topology.peers:
            changed_topology.add_peer(changed_peer if peer.peer_id == peer_id else peer)
        plan = plan_reconfiguration(
            result.fdar_placement,
            changed_topology,
            self.placement_config,
        )
        updated_verifications = tuple(
            replace(item, status=new_status) if item.peer_id == peer_id else item
            for item in result.verification_results
        )
        return replace(
            result,
            verification_results=updated_verifications,
            reconfiguration=plan,
            status=(
                SystemRunStatus.RECONFIGURATION_PLANNED
                if plan.success
                else SystemRunStatus.RECONFIGURATION_FAILED
            ),
            reasons=result.reasons + (plan.reason,),
            metadata={
                **result.metadata,
                "verification_status_change": {
                    "peer_id": peer_id,
                    "from": prior_result.status.value,
                    "to": new_status.value,
                },
            },
        )