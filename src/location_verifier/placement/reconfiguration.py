"""Deterministic minimal-movement repair planning after verification/topology changes."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from dataclasses import replace

from ..config import PlacementConfig
from .fdar import place_fdar
from .models import (
    EligibilityState,
    PlacementMode,
    PlacementPeer,
    PlacementResult,
    PlacementStatus,
    SelectedReplica,
)
from .topology import FailureDomainTopology


@dataclass(frozen=True, slots=True)
class ReconfigurationPlan:
    object_id: str
    affected_objects: tuple[str, ...]
    invalidated_peer_ids: tuple[str, ...]
    replacement_candidates: tuple[str, ...]
    previous_placement: PlacementResult
    proposed_placement: PlacementResult
    required_moves: int
    success: bool
    reason: str


def plan_reconfiguration(
    previous: PlacementResult,
    topology: FailureDomainTopology,
    config: PlacementConfig,
) -> ReconfigurationPlan:
    """Preserve valid replicas and deterministically replace only invalidated slots."""

    if not config.reconfiguration.enabled:
        return ReconfigurationPlan(
            previous.object_id,
            (),
            (),
            (),
            previous,
            previous,
            0,
            False,
            "reconfiguration is disabled by configuration",
        )
    if previous.mode is not PlacementMode.FDAR:
        raise ValueError("reconfiguration requires a prior FDAR placement")

    decisions = {
        peer.peer_id: peer
        for peer in topology.peers
    }
    from .eligibility import decide_eligibility

    policy_decisions = {
        peer.peer_id: decide_eligibility(peer, config.verification_policy)
        for peer in topology.peers
    }
    preserved: list[SelectedReplica] = []
    invalidated: list[str] = []
    occupied_domains: set[str] = set()
    for selected in previous.selected_peers:
        peer = decisions.get(selected.peer_id)
        decision = policy_decisions.get(selected.peer_id)
        if peer is None or decision is None:
            invalidated.append(selected.peer_id)
            continue
        domain = topology.failure_domain(peer.peer_id, config.failure_domain_level)
        if (
            peer.available
            and decision.state in {EligibilityState.ELIGIBLE, EligibilityState.CONDITIONAL}
            and domain not in occupied_domains
        ):
            occupied_domains.add(domain)
            preserved.append(
                SelectedReplica(
                    peer_id=peer.peer_id,
                    failure_domain=domain,
                    domain_level=config.failure_domain_level,
                    verification_status=peer.verification_status,
                    confidence=peer.verification.confidence if peer.verification else None,
                    uncertainty=peer.verification.uncertainty if peer.verification else None,
                    why_eligible=decision.reason,
                    why_selected="preserved from prior placement to minimize movement",
                    preference_score=selected.preference_score,
                    topology_verification_state=peer.topology_verification_state,
                    witnessing_zone_verification_state=peer.witnessing_zone_verification_state,
                )
            )
        else:
            invalidated.append(selected.peer_id)

    current_policy_placement = place_fdar(previous.object_id, topology, config)
    if not config.reconfiguration.minimize_movement:
        old_ids = {item.peer_id for item in previous.selected_peers}
        new_ids = {item.peer_id for item in current_policy_placement.selected_peers}
        moves = len(old_ids - new_ids)
        return ReconfigurationPlan(
            object_id=previous.object_id,
            affected_objects=(previous.object_id,) if invalidated else (),
            invalidated_peer_ids=tuple(sorted(invalidated)),
            replacement_candidates=tuple(sorted(new_ids - old_ids)),
            previous_placement=previous,
            proposed_placement=current_policy_placement,
            required_moves=moves,
            success=current_policy_placement.placement_success,
            reason=(
                "recomputed placement without preserving valid replicas because movement minimization is disabled"
                if current_policy_placement.placement_success
                else current_policy_placement.placement_reason
            ),
        )

    slots_needed = max(previous.requested_replication_factor - len(preserved), 0)
    replacement_pool = tuple(
        peer for peer in topology.peers
        if peer.peer_id not in {item.peer_id for item in preserved}
        and topology.failure_domain(peer.peer_id, config.failure_domain_level) not in occupied_domains
        and peer.available
        and policy_decisions[peer.peer_id].state
        in {EligibilityState.ELIGIBLE, EligibilityState.CONDITIONAL}
    )
    if slots_needed:
        repair_config = replace(config, replication_factor=slots_needed)
        replacement_result = place_fdar(
            previous.object_id,
            topology,
            repair_config,
            peers=replacement_pool,
        )
        new_selected = tuple(preserved) + replacement_result.selected_peers
        success = (
            len(new_selected) == previous.requested_replication_factor
            and len({item.failure_domain for item in new_selected}) == len(new_selected)
        )
        if success:
            reason = (
                f"preserved {len(preserved)} valid replicas and replaced "
                f"{slots_needed} invalidated replica(s)"
            )
            final_status = PlacementStatus.SUCCESS
        else:
            reason = (
                f"preserved {len(preserved)} valid replicas but only "
                f"{len(replacement_result.selected_peers)} replacement domain(s) are available; "
                "diversity constraint remains unsatisfied"
            )
            final_status = (
                PlacementStatus.NO_ELIGIBLE_PEERS
                if not any(
                    peer.available
                    and policy_decisions[peer.peer_id].state
                    in {EligibilityState.ELIGIBLE, EligibilityState.CONDITIONAL}
                    for peer in topology.peers
                )
                else PlacementStatus.INSUFFICIENT_DOMAINS
            )
    else:
        new_selected = tuple(preserved)
        success = True
        reason = "all existing replicas remain eligible; no movement required"
        final_status = PlacementStatus.SUCCESS

    proposed = PlacementResult(
        object_id=previous.object_id,
        requested_replication_factor=previous.requested_replication_factor,
        selected_peers=tuple(new_selected),
        selected_failure_domains=tuple(item.failure_domain for item in new_selected),
        failure_domain_level=config.failure_domain_level,
        excluded_peers=current_policy_placement.excluded_peers,
        placement_status=final_status,
        placement_reason=reason,
        mode=PlacementMode.FDAR,
        eligible_peer_count=sum(
            decision.state in {EligibilityState.ELIGIBLE, EligibilityState.CONDITIONAL}
            for decision in policy_decisions.values()
        ),
        available_distinct_failure_domains=len({
            topology.failure_domain(peer.peer_id, config.failure_domain_level)
            for peer in topology.peers
            if peer.available
            and policy_decisions[peer.peer_id].state in {EligibilityState.ELIGIBLE, EligibilityState.CONDITIONAL}
        }),
        deterministic_selection_metadata={
            "algorithm": "minimal-movement repair using FDAR deterministic ranking",
            "preserved_replicas": str(len(preserved)),
            "replacement_slots": str(slots_needed),
        },
        verification_summary=dict(
            sorted(Counter(peer.verification_status.value for peer in topology.peers).items())
        ),
    )
    old_ids = {item.peer_id for item in previous.selected_peers}
    new_ids = {item.peer_id for item in proposed.selected_peers}
    moves = len(old_ids - new_ids)
    available_alternatives = tuple(
        sorted(peer.peer_id for peer in replacement_pool if peer.peer_id not in new_ids)
    )
    return ReconfigurationPlan(
        object_id=previous.object_id,
        affected_objects=(previous.object_id,) if invalidated else (),
        invalidated_peer_ids=tuple(sorted(invalidated)),
        replacement_candidates=available_alternatives,
        previous_placement=previous,
        proposed_placement=proposed,
        required_moves=moves,
        success=success,
        reason=reason,
    )
