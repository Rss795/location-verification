"""Small deterministic hash-ranked hierarchical selection primitive."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Callable, Sequence

from .models import PlacementPeer
from .topology import FailureDomainTopology


@dataclass(frozen=True, slots=True)
class CrushSelection:
    peer: PlacementPeer
    failure_domain: str
    preference_score: float
    hash_fraction: float
    hash_digest: str


def deterministic_hash(object_id: str, peer_id: str, domain: str) -> tuple[float, str]:
    """Map stable identifiers to a repeatable [0, 1) score using SHA-256."""

    digest = hashlib.sha256(f"{object_id}\0{domain}\0{peer_id}".encode("utf-8")).hexdigest()
    fraction = int(digest, 16) / (1 << 256)
    return fraction, digest


def crush_select(
    object_id: str,
    candidates: Sequence[PlacementPeer],
    topology: FailureDomainTopology,
    domain_level: str,
    replica_count: int,
    score_peer: Callable[[PlacementPeer, str], float],
) -> tuple[CrushSelection, ...]:
    """Rank peers deterministically, selecting at most one peer per requested domain."""

    if not object_id.strip():
        raise ValueError("object_id must not be empty")
    if replica_count < 1:
        raise ValueError("replica_count must be at least 1")
    ranked: list[CrushSelection] = []
    seen_peer_ids: set[str] = set()
    for peer in candidates:
        if peer.peer_id in seen_peer_ids:
            continue
        seen_peer_ids.add(peer.peer_id)
        domain = topology.failure_domain(peer.peer_id, domain_level)
        hash_fraction, digest = deterministic_hash(object_id, peer.peer_id, domain)
        score = score_peer(peer, hash_fraction) * peer.weight
        ranked.append(CrushSelection(peer, domain, score, hash_fraction, digest))
    ranked.sort(key=lambda item: (-item.preference_score, item.hash_digest, item.peer.peer_id))

    selected: list[CrushSelection] = []
    used_domains: set[str] = set()
    for candidate in ranked:
        if candidate.failure_domain in used_domains:
            continue
        selected.append(candidate)
        used_domains.add(candidate.failure_domain)
        if len(selected) == replica_count:
            break
    return tuple(selected)
