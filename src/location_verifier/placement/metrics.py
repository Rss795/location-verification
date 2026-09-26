"""Descriptive placement metrics that do not imply ground-truth accuracy."""

from __future__ import annotations

from collections import Counter

from ..models import VerificationStatus
from .models import PlacementMetrics, PlacementResult, PlacementPeer


def calculate_metrics(
    result: PlacementResult,
    peers: tuple[PlacementPeer, ...] | list[PlacementPeer],
    *,
    reconfiguration_move_count: int = 0,
) -> PlacementMetrics:
    """Count replicas/domains/policy states; no accuracy metric is fabricated."""

    domain_counts = Counter(item.failure_domain for item in result.selected_peers)
    statuses = Counter(peer.verification_status for peer in peers)
    return PlacementMetrics(
        replica_count=len(result.selected_peers),
        distinct_failure_domains=len(domain_counts),
        domain_collision_count=sum(count - 1 for count in domain_counts.values() if count > 1),
        eligible_peer_count=result.eligible_peer_count,
        excluded_peer_count=len(result.excluded_peers),
        uncertain_peer_count=statuses[VerificationStatus.UNCERTAIN],
        suspicious_peer_count=statuses[VerificationStatus.SUSPICIOUS],
        placement_success=result.placement_success,
        reconfiguration_move_count=reconfiguration_move_count,
    )
