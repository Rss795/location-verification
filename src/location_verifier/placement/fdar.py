"""Verification-aware FDAR and verification-blind baseline placement entry points."""

from __future__ import annotations

from collections import Counter
from typing import Sequence

from ..config import PlacementConfig
from ..models import VerificationStatus
from .crush import crush_select
from .eligibility import decide_eligibility
from .models import (
    EligibilityState,
    PlacementMode,
    PlacementPeer,
    PlacementResult,
    PlacementStatus,
    PeerDecision,
    SelectedReplica,
    verification_scores,
)
from .topology import FailureDomainTopology


def _scored_peer(peer: PlacementPeer, hash_score: float, config: PlacementConfig) -> float:
    confidence, agreement, quality = verification_scores(peer.verification)
    score = (
        config.scoring.confidence_weight * confidence
        + config.scoring.witness_agreement_weight * agreement
        + config.scoring.measurement_quality_weight * quality
    )
    return score + config.scoring.deterministic_hash_weight * hash_score


def _result(
    object_id: str,
    topology: FailureDomainTopology,
    config: PlacementConfig,
    mode: PlacementMode,
    candidates: Sequence[PlacementPeer],
    decisions: Sequence[PeerDecision],
) -> PlacementResult:
    level = config.failure_domain_level
    if level != "peer" and level not in topology.hierarchy_levels:
        raise ValueError(f"unknown failure-domain level: {level}")
    if mode is PlacementMode.BASELINE:
        eligible = [peer for peer in candidates if peer.available]
        excluded = tuple(
            PeerDecision(
                peer.peer_id,
                EligibilityState.INELIGIBLE,
                "peer is unavailable" if not peer.available else "",
                0.0 if not peer.available else 1.0,
                peer.verification_status,
                peer.verification.confidence if peer.verification else None,
                peer.verification.uncertainty if peer.verification else None,
                peer.topology_verification_state,
                peer.witnessing_zone_verification_state,
            )
            for peer in candidates
            if not peer.available
        )
        score_peer = lambda peer, hash_score: hash_score
    else:
        decision_by_peer = {decision.peer_id: decision for decision in decisions}
        eligible = [
            peer
            for peer in candidates
            if decision_by_peer[peer.peer_id].state
            in {EligibilityState.ELIGIBLE, EligibilityState.CONDITIONAL}
        ]
        excluded = tuple(
            sorted(
                (
                    decision
                    for decision in decisions
                    if decision.state in {EligibilityState.INELIGIBLE, EligibilityState.QUARANTINED}
                ),
                key=lambda item: item.peer_id,
            )
        )

        def score_peer(peer: PlacementPeer, hash_score: float) -> float:
            decision = decision_by_peer[peer.peer_id]
            return _scored_peer(peer, hash_score, config) * decision.preference_multiplier

    domains = {topology.failure_domain(peer.peer_id, level) for peer in eligible}
    selected = crush_select(
        object_id,
        eligible,
        topology,
        level,
        config.replication_factor,
        score_peer,
    )
    status = (
        PlacementStatus.SUCCESS
        if len(selected) == config.replication_factor
        else PlacementStatus.NO_ELIGIBLE_PEERS
        if not eligible
        else PlacementStatus.INSUFFICIENT_DOMAINS
    )
    if status is PlacementStatus.SUCCESS:
        reason = (
            f"selected {len(selected)} replicas in distinct {level} failure domains"
        )
    elif status is PlacementStatus.NO_ELIGIBLE_PEERS:
        reason = "no available peers satisfy the configured eligibility policy"
    else:
        reason = (
            f"requested {config.replication_factor} replicas but only "
            f"{len(domains)} distinct eligible {level} domains are available; "
            "placement was not allowed to violate domain diversity"
        )

    decision_by_peer = {decision.peer_id: decision for decision in decisions}
    selected_records: list[SelectedReplica] = []
    for item in selected:
        decision = decision_by_peer.get(item.peer.peer_id)
        verification = item.peer.verification
        selected_records.append(
            SelectedReplica(
                peer_id=item.peer.peer_id,
                failure_domain=item.failure_domain,
                domain_level=level,
                verification_status=item.peer.verification_status,
                confidence=verification.confidence if verification else None,
                uncertainty=verification.uncertainty if verification else None,
                why_eligible=(
                    decision.reason if decision else "baseline trusts topology claim without verification"
                ),
                why_selected=(
                    "highest deterministic evidence-preference rank among remaining domains"
                    if mode is PlacementMode.FDAR
                    else "highest deterministic object/domain/peer hash rank in baseline"
                ),
                preference_score=item.preference_score,
                topology_verification_state=item.peer.topology_verification_state,
                witnessing_zone_verification_state=item.peer.witnessing_zone_verification_state,
            )
        )
    statuses = Counter(peer.verification_status.value for peer in candidates)
    return PlacementResult(
        object_id=object_id,
        requested_replication_factor=config.replication_factor,
        selected_peers=tuple(selected_records),
        selected_failure_domains=tuple(item.failure_domain for item in selected_records),
        failure_domain_level=level,
        excluded_peers=excluded,
        placement_status=status,
        placement_reason=reason,
        mode=mode,
        eligible_peer_count=len(eligible),
        available_distinct_failure_domains=len(domains),
        deterministic_selection_metadata={
            "algorithm": "sha256-ranked hierarchical one-peer-per-domain prototype",
            "hash_input": "object_id NUL failure_domain NUL peer_id",
            "hash": "SHA-256",
            "score_mode": "verification preference plus deterministic hash" if mode is PlacementMode.FDAR else "deterministic hash only",
            "peer_weight": "M1 PeerNode weight multiplies ranking score in both modes",
        },
        verification_summary={status: count for status, count in sorted(statuses.items())},
    )


def place_fdar(
    object_id: str,
    topology: FailureDomainTopology,
    config: PlacementConfig,
    *,
    peers: Sequence[PlacementPeer] | None = None,
    mode: PlacementMode = PlacementMode.FDAR,
) -> PlacementResult:
    """Place replicas in distinct domains; FDAR uses verification, baseline does not."""

    candidates = tuple(peers if peers is not None else topology.peers)
    for peer in candidates:
        if topology.get_peer(peer.peer_id) != peer:
            raise ValueError(f"candidate {peer.peer_id} does not match topology record")
    decisions = tuple(
        decide_eligibility(peer, config.verification_policy)
        for peer in candidates
    ) if mode is PlacementMode.FDAR else ()
    return _result(object_id, topology, config, mode, candidates, decisions)


def place_baseline(
    object_id: str,
    topology: FailureDomainTopology,
    config: PlacementConfig,
    *,
    peers: Sequence[PlacementPeer] | None = None,
) -> PlacementResult:
    """Run the same domain-aware selector over available peers, ignoring verification."""

    return place_fdar(
        object_id,
        topology,
        config,
        peers=peers,
        mode=PlacementMode.BASELINE,
    )
