"""Project-owned producer that builds the documented M1 hierarchy from flat claims.

This is an executable reference producer for this repository. It is deliberately
not described as the absent teammate M1 implementation or as independently
validated against that implementation.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

M1_STATE = Literal["verified", "unverifiable_short_range", "untrusted", "pending_check"]
STATE_CAUTION_PRIORITY = {
    "verified": 0,
    "pending_check": 1,
    "unverifiable_short_range": 2,
    "untrusted": 3,
}


class FlatPeerClaim(BaseModel):
    """A typed peer claim with every required M1 hierarchy label supplied."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    peer_id: str = Field(min_length=1)
    region: str = Field(min_length=1)
    asn: str = Field(min_length=1)
    witnessing_zone: str = Field(min_length=1)
    rack: str = Field(min_length=1)
    weight: float = Field(default=1.0, gt=0)
    region_state: M1_STATE = "pending_check"
    asn_state: M1_STATE = "pending_check"
    witnessing_zone_state: M1_STATE = "pending_check"
    rack_state: M1_STATE = "pending_check"


class FlatClaimsDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    peers: list[FlatPeerClaim] = Field(min_length=1)


def build_m1_topology(
    claims: Iterable[FlatPeerClaim | dict[str, object]], *, root_id: str = "default_root"
) -> dict[str, object]:
    """Build deterministic ``root/region/asn/witnessing_zone/rack/peer`` JSON.

    Bucket IDs are scoped to their parent paths, so repeated labels do not merge
    across parents. Conflicting claims about one bucket take the most cautious
    verification state.
    """
    if not root_id.strip():
        raise ValueError("root_id must not be empty")
    try:
        peers = [
            item if isinstance(item, FlatPeerClaim) else FlatPeerClaim.model_validate(item)
            for item in claims
        ]
    except ValidationError as exc:
        raise ValueError(f"invalid flat M1 peer claim: {exc}") from exc
    if not peers:
        raise ValueError("at least one flat peer claim is required")
    ids = [item.peer_id for item in peers]
    if len(ids) != len(set(ids)):
        raise ValueError("peer_id values must be unique")

    root: dict[str, object] = {
        "id": root_id, "type": "root", "verification_state": "verified", "children": []
    }
    buckets: dict[tuple[str, ...], dict[str, object]] = {(): root}
    levels = (
        ("region", "region_state"),
        ("asn", "asn_state"),
        ("witnessing_zone", "witnessing_zone_state"),
        ("rack", "rack_state"),
    )
    for peer in sorted(peers, key=lambda item: item.peer_id):
        path: tuple[str, ...] = ()
        parent = root
        for level, state_field in levels:
            label = getattr(peer, level)
            path += (label,)
            bucket = buckets.get(path)
            if bucket is None:
                bucket = {
                    "id": label,
                    "type": level,
                    "verification_state": getattr(peer, state_field),
                    "children": [],
                }
                buckets[path] = bucket
                parent["children"].append(bucket)
            else:
                prior, current = bucket["verification_state"], getattr(peer, state_field)
                if STATE_CAUTION_PRIORITY[current] > STATE_CAUTION_PRIORITY[prior]:
                    bucket["verification_state"] = current
            parent = bucket
        parent["children"].append(
            {"peer_id": peer.peer_id, "weight": peer.weight, "type": "node"}
        )

    def sort_tree(node: dict[str, object]) -> None:
        node["children"].sort(key=lambda item: item.get("id", item.get("peer_id", "")))
        for child in node["children"]:
            if "children" in child:
                sort_tree(child)

    sort_tree(root)
    return {"root": root}


def build_from_document(payload: object, *, root_id: str = "default_root") -> dict[str, object]:
    """Validate a flat-claims document then produce the adapter's input format."""
    try:
        document = FlatClaimsDocument.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"invalid flat M1 claims document: {exc}") from exc
    return build_m1_topology(document.peers, root_id=root_id)
