"""Failure-domain grouping helpers used by hierarchical placement."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from .models import PlacementPeer
from .topology import FailureDomainTopology


def group_by_failure_domain(
    topology: FailureDomainTopology,
    peers: Iterable[PlacementPeer],
    level: str,
) -> dict[str, tuple[PlacementPeer, ...]]:
    """Group the given candidates at one configured hierarchy level."""

    groups: dict[str, list[PlacementPeer]] = defaultdict(list)
    for peer in peers:
        groups[topology.failure_domain(peer.peer_id, level)].append(peer)
    return {
        domain: tuple(sorted(members, key=lambda item: item.peer_id))
        for domain, members in sorted(groups.items())
    }