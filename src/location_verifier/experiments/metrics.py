"""Evaluation measures for placement, verification labels, and reconfiguration."""

from __future__ import annotations

from collections import Counter
from typing import Any

from ..models import VerificationStatus
from ..inference.distance import haversine_distance_km
from ..placement.models import PlacementResult, PlacementPeer
from .generator import GroundTruthPeer


def placement_metrics(
    result: PlacementResult,
    peers: tuple[PlacementPeer, ...],
    ground_truth: tuple[GroundTruthPeer, ...],
) -> dict[str, Any]:
    """Calculate placement and explicitly synthetic verification metrics."""

    selected = {item.peer_id: item for item in result.selected_peers}
    excluded = {item.peer_id: item for item in result.excluded_peers}
    peer_by_id = {peer.peer_id: peer for peer in peers}
    truth_by_id = {item.peer_id: item for item in ground_truth}
    suspicious_selected = sum(
        item.verification_status is VerificationStatus.SUSPICIOUS
        for item in selected.values()
    )
    suspicious_candidates = [
        item for item in ground_truth
        if item.actual_failure_domain != item.claimed_failure_domain
    ]
    suspicious_excluded = sum(
        item.peer_id in excluded
        and peer_by_id[item.peer_id].verification_status is VerificationStatus.SUSPICIOUS
        for item in suspicious_candidates
    )
    uncertain_selected = sum(
        item.verification_status is VerificationStatus.UNCERTAIN
        for item in selected.values()
    )
    uncertain_excluded = sum(
        peer_by_id[peer_id].verification_status is VerificationStatus.UNCERTAIN
        for peer_id in excluded
    )
    true_positive = false_positive = true_negative = false_negative = 0
    loc_tp = loc_fp = loc_tn = loc_fn = 0
    for peer_id, truth in truth_by_id.items():
        actual_mismatch = truth.actual_failure_domain != truth.claimed_failure_domain
        detected = peer_by_id[peer_id].verification_status is VerificationStatus.SUSPICIOUS
        if actual_mismatch and detected:
            true_positive += 1
        elif actual_mismatch:
            false_negative += 1
        elif detected:
            false_positive += 1
        else:
            true_negative += 1
        location_mismatch = (
            haversine_distance_km(truth.actual_location, truth.claimed_location) > 1e-6
        )
        location_flagged = peer_by_id[peer_id].verification_status is VerificationStatus.SUSPICIOUS
        if location_mismatch and location_flagged:
            loc_tp += 1
        elif location_mismatch:
            loc_fn += 1
        elif location_flagged:
            loc_fp += 1
        else:
            loc_tn += 1
    detection_denominator = true_positive + false_negative
    false_alarm_denominator = false_positive + true_negative
    location_detection_denominator = loc_tp + loc_fn
    location_false_alarm_denominator = loc_fp + loc_tn
    requested = result.requested_replication_factor
    return {
        "placement_success": result.placement_success,
        "placement_success_count": int(result.placement_success),
        "replica_count": len(selected),
        "distinct_failure_domains": len(set(result.selected_failure_domains)),
        "domain_collision_count": sum(
            count - 1 for count in Counter(result.selected_failure_domains).values() if count > 1
        ),
        "domain_diversity_ratio": len(set(result.selected_failure_domains)) / requested,
        "eligible_peer_count": result.eligible_peer_count,
        "excluded_peer_count": len(excluded),
        "suspicious_selected_count": suspicious_selected,
        "suspicious_excluded_count": suspicious_excluded,
        "eligible_suspicious_peer_count": len(suspicious_candidates),
        "uncertain_selected_count": uncertain_selected,
        "uncertain_excluded_count": uncertain_excluded,
        "suspicious_selection_rate": suspicious_selected / len(selected) if selected else 0.0,
        "suspicious_exclusion_rate": (
            suspicious_excluded / len(suspicious_candidates)
            if suspicious_candidates
            else None
        ),
        "verification_true_positive": true_positive,
        "verification_false_positive": false_positive,
        "verification_true_negative": true_negative,
        "verification_false_negative": false_negative,
        "verification_detection_rate": (
            true_positive / detection_denominator if detection_denominator else None
        ),
        "verification_false_alarm_rate": (
            false_positive / false_alarm_denominator if false_alarm_denominator else None
        ),
        "synthetic_location_mismatch_peer_count": loc_tp + loc_fn,
        "location_verification_true_positive": loc_tp,
        "location_verification_false_positive": loc_fp,
        "location_verification_true_negative": loc_tn,
        "location_verification_false_negative": loc_fn,
        "location_verification_detection_rate": (
            loc_tp / location_detection_denominator
            if location_detection_denominator
            else None
        ),
        "location_verification_false_alarm_rate": (
            loc_fp / location_false_alarm_denominator
            if location_false_alarm_denominator
            else None
        ),
        "selected_peers": [item.peer_id for item in result.selected_peers],
        "selected_domains": list(result.selected_failure_domains),
        "placement_reason": result.placement_reason,
    }


def reconfiguration_metrics(
    previous: PlacementResult,
    proposed: PlacementResult,
) -> dict[str, Any]:
    """Summarize a placement repair plan without implying data transfer occurred."""

    previous_ids = {item.peer_id for item in previous.selected_peers}
    proposed_ids = {item.peer_id for item in proposed.selected_peers}
    preserved = len(previous_ids & proposed_ids)
    removed = len(previous_ids - proposed_ids)
    added = len(proposed_ids - previous_ids)
    replicas = previous.requested_replication_factor
    return {
        "reconfiguration_event_count": 1,
        "replicas_preserved": preserved,
        "replicas_removed": removed,
        "replicas_replaced": added,
        "movement_count": removed,
        "movement_ratio": removed / replicas if replicas else 0.0,
        "domain_preserved_after_reconfiguration": (
            proposed.placement_success
            and len(set(proposed.selected_failure_domains)) == len(proposed.selected_peers)
        ),
        "reconfiguration_success": proposed.placement_success,
    }
