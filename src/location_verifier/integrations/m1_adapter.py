"""Adapter for the existing M1 topology_map.json schema.

This module validates and translates M1 output only. It does not build a second
topology tree or infer physical location. Coordinates and measurement endpoints
must come from a separate, explicit metadata source.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
import json
from pathlib import Path
from typing import Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from ..models import GeoLocation, PeerClaim
from ..placement.models import PlacementPeer
from ..placement.topology import FailureDomainTopology


class M1AdapterError(ValueError):
    """M1 topology or accompanying metadata is malformed/incomplete."""


class M1VerificationState(StrEnum):
    VERIFIED = "verified"
    UNVERIFIABLE_SHORT_RANGE = "unverifiable_short_range"
    UNTRUSTED = "untrusted"
    PENDING_CHECK = "pending_check"


class PeerNodeInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    peer_id: str = Field(min_length=1)
    weight: float = Field(default=1.0, gt=0)
    type: str = "node"


_BUCKET_TYPE_ALIASES = {
    "root": "root",
    "region": "region",
    "asn": "asn",
    "witnessing_zone": "witnessing_zone",
    "rack": "rack",
}
_VERIFICATION_STATE_ALIASES = {
    "verified": "verified",
    "unverifiable_short_range": "unverifiable_short_range",
    "untrusted": "untrusted",
    "pending_check": "pending_check",
}


def _normalize_m1_token(value: object, aliases: dict[str, str], *, field_name: str) -> str:
    """Accept teammate enum names/values without rebuilding M1's tree."""

    if isinstance(value, str):
        token = value.split(".")[-1].strip()
        mapped = aliases.get(token) or aliases.get(token.lower())
        if mapped is not None:
            return mapped
    raise ValueError(f"unsupported M1 {field_name}: {value!r}")


class TopologyBucketInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    type: Literal["root", "region", "asn", "witnessing_zone", "rack"]
    verification_state: Literal[
        "verified",
        "unverifiable_short_range",
        "untrusted",
        "pending_check",
    ] = "pending_check"
    children: list[Union["TopologyBucketInput", PeerNodeInput]] = Field(default_factory=list)

    @field_validator("type", mode="before")
    @classmethod
    def normalize_bucket_type(cls, value: object) -> str:
        return _normalize_m1_token(value, _BUCKET_TYPE_ALIASES, field_name="bucket type")

    @field_validator("verification_state", mode="before")
    @classmethod
    def normalize_verification_state(cls, value: object) -> str:
        return _normalize_m1_token(
            value, _VERIFICATION_STATE_ALIASES, field_name="verification_state"
        )


TopologyBucketInput.model_rebuild()


class PeerPhysicalMetadata(BaseModel):
    """Externally supplied coordinates and authorized measurement endpoint."""

    model_config = ConfigDict(extra="forbid")

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    target_host: str = Field(min_length=1)
    reliability_score: float = Field(default=0.5, ge=0, le=1)
    known_failure_domain: str | None = None


class WitnessMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    witness_id: str = Field(min_length=1)
    host: str = Field(min_length=1)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    reliability_score: float = Field(default=0.5, ge=0, le=1)
    known_failure_domain: str | None = None


class M1ExternalMetadata(BaseModel):
    """Sidecar fields M1 does not promise to include in its topology tree."""

    model_config = ConfigDict(extra="forbid")

    peers: dict[str, PeerPhysicalMetadata]
    witnesses: list[WitnessMetadata] = Field(min_length=1)
    current_pin_allocations: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def witness_ids_are_unique(self) -> "M1ExternalMetadata":
        ids = [witness.witness_id for witness in self.witnesses]
        if len(ids) != len(set(ids)):
            raise ValueError("witness_id values must be unique")
        return self


@dataclass(frozen=True, slots=True)
class M1PeerRecord:
    peer_id: str
    weight: float
    region: str
    asn: str
    witnessing_zone: str
    rack: str
    witnessing_zone_verification_state: str
    topology_verification_state: str
    path_verification_states: tuple[str, ...]

    @property
    def failure_domains(self) -> dict[str, str]:
        """Return unambiguous, parent-qualified domain keys for placement.

        M1 bucket IDs are labels in a hierarchy and need not be globally unique.
        JSON arrays keep each path segment unambiguous even if an ID contains a
        separator character. The public M1 fields above retain their original
        labels, including the required ``witnessing_zone`` terminology.
        """

        path = {
            "region": (self.region,),
            "asn": (self.region, self.asn),
            "witnessing_zone": (self.region, self.asn, self.witnessing_zone),
            "rack": (self.region, self.asn, self.witnessing_zone, self.rack),
        }
        return {
            level: json.dumps(parts, ensure_ascii=False, separators=(",", ":"))
            for level, parts in path.items()
        }


@dataclass(frozen=True, slots=True)
class M1TopologySnapshot:
    root: TopologyBucketInput
    peers: tuple[M1PeerRecord, ...]

    def with_location_verification(
        self, results: Mapping[str, object]
    ) -> dict[str, object]:
        """Serialize a derived M1 view with peer-level M3 annotations.

        M3 results are attached to peer leaves. Shared M1 bucket states are
        intentionally left intact because a peer result does not establish the
        state of every peer in its region, ASN, witnessing zone, or rack.
        """
        expected = {peer.peer_id for peer in self.peers}
        if set(results) != expected:
            raise M1AdapterError(
                "M3 result IDs must exactly match M1 peers; "
                f"missing={sorted(expected - set(results))}, extra={sorted(set(results) - expected)}"
            )
        root = self.root.model_dump(mode="json")

        def annotate(bucket: dict[str, object]) -> None:
            for child in bucket["children"]:
                if "children" in child:
                    annotate(child)
                else:
                    peer_id = child["peer_id"]
                    result = results[peer_id]
                    status = getattr(getattr(result, "status", None), "value", None)
                    if status is None:
                        status = getattr(result, "status", None)
                    score = getattr(result, "confidence", None)
                    if not isinstance(status, str) or not isinstance(score, (int, float)):
                        raise M1AdapterError(f"invalid M3 result for M1 peer {peer_id}")
                    child["m3_location_verification"] = {
                        "status": status,
                        "evidence_strength_score": float(score),
                        "score_semantics": "uncalibrated evidence strength; not a probability",
                    }

        annotate(root)
        return {"root": root}

    def to_placement_topology(
        self,
        metadata: M1ExternalMetadata,
        *,
        failure_domain_level: str = "witnessing_zone",
    ) -> tuple[FailureDomainTopology, tuple[PeerClaim, ...]]:
        if failure_domain_level not in {"peer", "region", "asn", "witnessing_zone", "rack"}:
            raise M1AdapterError(f"unsupported M1 failure-domain level: {failure_domain_level}")
        m1_ids = {peer.peer_id for peer in self.peers}
        metadata_ids = set(metadata.peers)
        if m1_ids != metadata_ids:
            raise M1AdapterError(
                f"peer metadata IDs must exactly match M1 peers; "
                f"missing={sorted(m1_ids - metadata_ids)}, extra={sorted(metadata_ids - m1_ids)}"
            )
        placement_peers: list[PlacementPeer] = []
        claims: list[PeerClaim] = []
        for m1_peer in self.peers:
            external = metadata.peers[m1_peer.peer_id]
            location = GeoLocation(external.latitude, external.longitude)
            claimed_domain = (
                m1_peer.peer_id
                if failure_domain_level == "peer"
                else m1_peer.failure_domains[failure_domain_level]
            )
            claim = PeerClaim(m1_peer.peer_id, location, claimed_domain)
            claims.append(claim)
            placement_peers.append(
                PlacementPeer(
                    peer_id=m1_peer.peer_id,
                    claim=claim,
                    failure_domains=m1_peer.failure_domains,
                    topology_verification_state=m1_peer.topology_verification_state,
                    witnessing_zone_verification_state=m1_peer.witnessing_zone_verification_state,
                    topology_verification_states=m1_peer.path_verification_states,
                    weight=m1_peer.weight,
                )
            )
        topology = FailureDomainTopology(
            ("region", "asn", "witnessing_zone", "rack"),
            placement_peers,
        )
        return topology, tuple(claims)


_EXPECTED_CHILD = {
    "root": "region",
    "region": "asn",
    "asn": "witnessing_zone",
    "witnessing_zone": "rack",
    "rack": "peer",
}
_STATE_CAUTION_PRIORITY = {
    "verified": 0,
    "pending_check": 1,
    "unverifiable_short_range": 2,
    "untrusted": 3,
}


def _parse_bucket(raw: object) -> TopologyBucketInput:
    try:
        return TopologyBucketInput.model_validate(raw)
    except ValidationError as exc:
        raise M1AdapterError(f"invalid M1 topology_map.json schema: {exc}") from exc


def parse_topology_map(payload: object) -> M1TopologySnapshot:
    """Validate an M1 tree and flatten peer hierarchy without rebuilding it."""

    if isinstance(payload, dict) and "root" in payload:
        root_payload = payload["root"]
    elif isinstance(payload, dict) and "topology" in payload:
        root_payload = payload["topology"]
    else:
        root_payload = payload
    root = _parse_bucket(root_payload)
    if root.type != "root":
        raise M1AdapterError("M1 topology root bucket must have type 'root'")

    flattened: list[M1PeerRecord] = []
    seen_ids: set[str] = set()

    def visit(bucket: TopologyBucketInput, path: dict[str, str], states: tuple[str, ...]) -> None:
        expected_child_type = _EXPECTED_CHILD[bucket.type]
        next_path = dict(path)
        if bucket.type != "root":
            next_path[bucket.type] = bucket.id
        next_states = states + (bucket.verification_state,)
        for child in bucket.children:
            if isinstance(child, TopologyBucketInput):
                if expected_child_type == "peer" or child.type != expected_child_type:
                    raise M1AdapterError(
                        f"invalid M1 hierarchy: {bucket.type} '{bucket.id}' "
                        f"must contain {expected_child_type}, found {child.type}"
                    )
                visit(child, next_path, next_states)
            else:
                if expected_child_type != "peer":
                    raise M1AdapterError(
                        f"invalid M1 hierarchy: {bucket.type} '{bucket.id}' must contain {expected_child_type} buckets"
                    )
                if child.peer_id in seen_ids:
                    raise M1AdapterError(f"duplicate peer ID in M1 topology: {child.peer_id}")
                seen_ids.add(child.peer_id)
                if set(next_path) != {"region", "asn", "witnessing_zone", "rack"}:
                    raise M1AdapterError(f"incomplete M1 hierarchy for peer {child.peer_id}")
                zone_state = next(
                    state
                    for current_bucket_type, state in zip(
                        ("root", "region", "asn", "witnessing_zone", "rack"),
                        next_states,
                    )
                    if current_bucket_type == "witnessing_zone"
                )
                effective_state = max(next_states, key=lambda state: _STATE_CAUTION_PRIORITY[state])
                flattened.append(
                    M1PeerRecord(
                        child.peer_id,
                        child.weight,
                        next_path["region"],
                        next_path["asn"],
                        next_path["witnessing_zone"],
                        next_path["rack"],
                        zone_state,
                        effective_state,
                        next_states,
                    )
                )

    visit(root, {}, ())
    if not flattened:
        raise M1AdapterError("M1 topology contains no PeerNode leaves")
    return M1TopologySnapshot(root, tuple(sorted(flattened, key=lambda item: item.peer_id)))


def load_topology_map(path: str | Path) -> M1TopologySnapshot:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise M1AdapterError(f"could not read M1 topology map: {path}: {exc}") from exc
    return parse_topology_map(payload)


def load_external_metadata(path: str | Path) -> M1ExternalMetadata:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return M1ExternalMetadata.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise M1AdapterError(f"invalid external M1 coordinate/witness metadata: {path}: {exc}") from exc


def is_loopback_host(host: str) -> bool:
    """Return True for localhost/loopback names that cannot support geography claims."""

    normalized = host.strip().lower().split("%", 1)[0]
    return normalized in {"127.0.0.1", "::1", "localhost", "0:0:0:0:0:0:0:1"}
