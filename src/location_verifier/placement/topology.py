"""Mutable registry for a configurable physical failure-domain hierarchy."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from .models import PlacementPeer


DEFAULT_HIERARCHY = ("region", "site", "building", "floor")


class FailureDomainTopology:
    """Store peers under arbitrary ordered domain levels, independent of GPS distance."""

    def __init__(
        self,
        hierarchy_levels: Iterable[str] = DEFAULT_HIERARCHY,
        peers: Iterable[PlacementPeer] = (),
    ) -> None:
        levels = tuple(hierarchy_levels)
        if not levels or len(set(levels)) != len(levels):
            raise ValueError("hierarchy_levels must be non-empty and unique")
        if any(not level.strip() or level == "peer" for level in levels):
            raise ValueError("hierarchy levels must be non-empty and exclude reserved 'peer'")
        self.hierarchy_levels = levels
        self._peers: dict[str, PlacementPeer] = {}
        for peer in peers:
            self.add_peer(peer)

    @property
    def peers(self) -> tuple[PlacementPeer, ...]:
        return tuple(self._peers[key] for key in sorted(self._peers))

    def add_peer(self, peer: PlacementPeer) -> None:
        if peer.peer_id in self._peers:
            raise ValueError(f"duplicate peer_id: {peer.peer_id}")
        missing = set(self.hierarchy_levels) - set(peer.failure_domains)
        extra = set(peer.failure_domains) - set(self.hierarchy_levels)
        if missing or extra:
            raise ValueError(
                f"peer {peer.peer_id} hierarchy mismatch; missing={sorted(missing)}, extra={sorted(extra)}"
            )
        self._peers[peer.peer_id] = peer

    def update_peer(self, peer: PlacementPeer) -> None:
        if peer.peer_id not in self._peers:
            raise KeyError(f"unknown peer_id: {peer.peer_id}")
        missing = set(self.hierarchy_levels) - set(peer.failure_domains)
        extra = set(peer.failure_domains) - set(self.hierarchy_levels)
        if missing or extra:
            raise ValueError(
                f"peer {peer.peer_id} hierarchy mismatch; missing={sorted(missing)}, extra={sorted(extra)}"
            )
        self._peers[peer.peer_id] = peer

    def get_peer(self, peer_id: str) -> PlacementPeer:
        try:
            return self._peers[peer_id]
        except KeyError as exc:
            raise KeyError(f"unknown peer_id: {peer_id}") from exc

    def failure_domain(self, peer_id: str, level: str) -> str:
        peer = self.get_peer(peer_id)
        if level == "peer":
            return peer.peer_id
        if level not in self.hierarchy_levels:
            raise ValueError(f"unknown failure-domain level: {level}")
        return peer.failure_domains[level]

    def peers_by_domain(self, level: str) -> dict[str, tuple[PlacementPeer, ...]]:
        groups: dict[str, list[PlacementPeer]] = defaultdict(list)
        for peer in self.peers:
            groups[self.failure_domain(peer.peer_id, level)].append(peer)
        return {domain: tuple(members) for domain, members in sorted(groups.items())}
