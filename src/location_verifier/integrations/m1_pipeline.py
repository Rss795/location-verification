"""Run M1 topology through existing Phase 3/4/6 using explicit sidecar metadata."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Mapping

from ..config import InferenceConfig, MeasurementConfig, PlacementConfig
from ..inference.distance import haversine_distance_km
from ..inference.latency_model import LatencyModel
from ..inference.verifier import load_saved_witness_evidence
from ..integrations.ipfs_cluster import (
    ClusterPeer,
    DesiredPlacementAction,
    DryRunIPFSClusterAdapter,
    PinAllocation,
)
from ..measurement.collector import (
    MeasurementBatch,
    MeasurementBatchStatus,
    WitnessEvidence,
)
from ..measurement.statistics import extract_features
from ..models import MeasurementObservation, VerificationStatus, Witness
from ..placement.topology import FailureDomainTopology
from ..system import SystemOrchestrator, SystemRunResult
from .m1_adapter import (
    M1AdapterError,
    M1ExternalMetadata,
    M1TopologySnapshot,
    is_loopback_host,
)


@dataclass(frozen=True, slots=True)
class M1SystemExecution:
    topology_snapshot: M1TopologySnapshot
    topology: FailureDomainTopology
    result: SystemRunResult
    cluster_action: DesiredPlacementAction
    evidence_source: str
    peer_count: int
    witness_count: int
    measurement_samples: int


def _witness_model(item) -> Witness:
    from ..models import GeoLocation

    return Witness(
        item.witness_id,
        GeoLocation(item.latitude, item.longitude),
        item.known_failure_domain,
        reliability_score=item.reliability_score,
    )


def load_m1_witness_evidence(
    snapshot: M1TopologySnapshot,
    metadata: M1ExternalMetadata,
    evidence_directory: str | Path,
) -> dict[str, tuple[WitnessEvidence, ...]]:
    """Load one saved Phase 2 JSON batch per M1 peer and configured witness.

    Standard Phase 2 output filenames are accepted. Batches are indexed by their
    embedded target_peer_id and witness_id fields. Witness coordinates and
    reliability are supplied by the explicit metadata sidecar.
    """

    root = Path(evidence_directory).resolve()
    if not root.is_dir():
        raise M1AdapterError(f"Phase 2 evidence directory does not exist: {root}")
    batch_paths: dict[tuple[str, str], Path] = {}
    for candidate in root.rglob("*_features.json"):
        resolved_candidate = candidate.resolve()
        if root not in resolved_candidate.parents:
            raise M1AdapterError("Phase 2 evidence file escaped the evidence directory")
        try:
            payload = json.loads(resolved_candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise M1AdapterError(f"invalid Phase 2 JSON batch {candidate}: {exc}") from exc
        if not isinstance(payload, dict):
            raise M1AdapterError(f"Phase 2 JSON batch must contain an object: {candidate}")
        target_peer_id = payload.get("target_peer_id")
        witness_id = payload.get("witness_id")
        if isinstance(target_peer_id, str) and isinstance(witness_id, str):
            key = (target_peer_id, witness_id)
            if key in batch_paths:
                raise M1AdapterError(f"duplicate Phase 2 batch for peer/witness {key}")
            batch_paths[key] = resolved_candidate

    evidence_by_peer: dict[str, tuple[WitnessEvidence, ...]] = {}
    missing: list[str] = []
    for peer in snapshot.peers:
        peer_items: list[WitnessEvidence] = []
        external_peer = metadata.peers[peer.peer_id]
        for witness_metadata in metadata.witnesses:
            key = (peer.peer_id, witness_metadata.witness_id)
            evidence_path = batch_paths.get(key)
            if evidence_path is None:
                missing.append(f"peer={peer.peer_id}, witness={witness_metadata.witness_id}")
                continue
            evidence = load_saved_witness_evidence(
                evidence_path,
                _witness_model(witness_metadata),
            )
            if evidence.target_peer_id != peer.peer_id:
                raise M1AdapterError(
                    f"saved evidence target {evidence.target_peer_id} does not match M1 peer {peer.peer_id}"
                )
            if evidence.batch.host != external_peer.target_host:
                raise M1AdapterError(
                    f"saved evidence host for {peer.peer_id}/{witness_metadata.witness_id} "
                    "does not match the declared peer target_host"
                )
            peer_items.append(evidence)
        evidence_by_peer[peer.peer_id] = tuple(peer_items)
    if missing:
        raise M1AdapterError(
            "missing Phase 2 witness evidence files: " + ", ".join(missing[:12])
        )
    return evidence_by_peer


def generate_synthetic_m1_evidence(
    snapshot: M1TopologySnapshot,
    metadata: M1ExternalMetadata,
    inference_config: InferenceConfig,
    measurement_config: MeasurementConfig,
) -> dict[str, tuple[WitnessEvidence, ...]]:
    """Generate model-consistent synthetic samples, explicitly not network evidence."""

    from ..models import GeoLocation, PeerClaim

    latency_model = LatencyModel(inference_config.latency_model)
    result: dict[str, tuple[WitnessEvidence, ...]] = {}
    base_timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for peer in snapshot.peers:
        external_peer = metadata.peers[peer.peer_id]
        location = GeoLocation(external_peer.latitude, external_peer.longitude)
        claim = PeerClaim(
            peer.peer_id,
            location,
            peer.failure_domains.get("witnessing_zone", peer.peer_id),
        )
        peer_evidence: list[WitnessEvidence] = []
        for witness_metadata in metadata.witnesses:
            witness = _witness_model(witness_metadata)
            distance = haversine_distance_km(witness.location, claim.claimed_location)
            expected = latency_model.predict(distance).expected_rtt_ms
            observations = tuple(
                MeasurementObservation(
                    base_timestamp + timedelta(milliseconds=index),
                    max(0.1, expected),
                )
                for index in range(measurement_config.samples)
            )
            features = extract_features(observations)
            batch = MeasurementBatch(
                witness_id=witness.witness_id,
                target_peer_id=peer.peer_id,
                host=external_peer.target_host,
                started_at=base_timestamp,
                completed_at=base_timestamp + timedelta(milliseconds=measurement_config.samples),
                observations=observations,
                features=features,
                status=MeasurementBatchStatus.COMPLETE,
            )
            peer_evidence.append(WitnessEvidence(witness, peer.peer_id, batch))
        result[peer.peer_id] = tuple(peer_evidence)
    return result


REAL_MEASUREMENT_LABEL = (
    "REAL MEASUREMENTS collected from this vantage using Phase 2. "
    "This process is one witness only. Independent remote witnesses must collect "
    "their own batches. RTT is not proof of exact physical location."
)
LOOPBACK_MEASUREMENT_LABEL = (
    "REAL MEASUREMENTS of loopback/localhost connectivity only. "
    "This is not geographic location evidence."
)


def collect_real_m1_measurements(
    snapshot: M1TopologySnapshot,
    metadata: M1ExternalMetadata,
    measurement_config: MeasurementConfig,
    *,
    witness_id: str,
    output_dir: str | Path,
    ping_source=None,
    allow_loopback: bool = False,
):
    """Ping each M1 peer's declared target_host from this vantage and save Phase 2 JSON.

    The caller must be an authorized witness listed in the sidecar. This function does
    not impersonate other witnesses and does not invent coordinates.
    """

    from ..measurement.collector import collect_measurements
    from ..measurement.storage import save_measurement_batch

    witness = next((item for item in metadata.witnesses if item.witness_id == witness_id), None)
    if witness is None:
        raise M1AdapterError(f"witness_id {witness_id!r} is not present in M1 sidecar metadata")
    m1_ids = {peer.peer_id for peer in snapshot.peers}
    if m1_ids != set(metadata.peers):
        raise M1AdapterError(
            "peer metadata IDs must exactly match M1 peers; "
            f"missing={sorted(m1_ids - set(metadata.peers))}, extra={sorted(set(metadata.peers) - m1_ids)}"
        )
    loopback_peers = [
        peer.peer_id
        for peer in snapshot.peers
        if is_loopback_host(metadata.peers[peer.peer_id].target_host)
    ]
    if loopback_peers and not allow_loopback:
        raise M1AdapterError(
            "refusing loopback/localhost M1 targets as geographic evidence: "
            + ", ".join(loopback_peers)
            + "; pass allow_loopback only for connectivity tests"
        )
    root = Path(output_dir)
    raw_dir = root / "raw"
    processed_dir = root / "processed"
    saved: list[Path] = []
    for peer in snapshot.peers:
        external = metadata.peers[peer.peer_id]
        batch = collect_measurements(
            host=external.target_host,
            samples=measurement_config.samples,
            timeout_seconds=measurement_config.timeout_seconds,
            interval_seconds=measurement_config.interval_seconds,
            source=ping_source,
            witness_id=witness.witness_id,
            target_peer_id=peer.peer_id,
        )
        _raw, processed = save_measurement_batch(batch, raw_dir, processed_dir)
        saved.append(processed)
    label = LOOPBACK_MEASUREMENT_LABEL if loopback_peers else REAL_MEASUREMENT_LABEL
    return tuple(saved), label


def run_m1_pipeline(
    snapshot: M1TopologySnapshot,
    metadata: M1ExternalMetadata,
    evidence_by_peer: Mapping[str, tuple[WitnessEvidence, ...]],
    inference_config: InferenceConfig,
    placement_config: PlacementConfig,
    *,
    object_id: str,
    failure_domain_level: str = "witnessing_zone",
    include_baseline: bool = True,
    evidence_source: str,
) -> M1SystemExecution:
    """Convert authoritative M1 domains to existing topology and run M3/M2/M4 system API."""

    topology, claims = snapshot.to_placement_topology(
        metadata,
        failure_domain_level=failure_domain_level,
    )
    active_placement = PlacementConfig(
        replication_factor=placement_config.replication_factor,
        failure_domain_level=failure_domain_level,
        verification_policy=placement_config.verification_policy,
        scoring=placement_config.scoring,
        reconfiguration=placement_config.reconfiguration,
    )
    result = SystemOrchestrator(inference_config, active_placement).run(
        object_id,
        topology,
        claims,
        evidence_by_peer,
        include_baseline=include_baseline,
        metadata={
            "topology_source": "M1 topology_map.json",
            "evidence_source": evidence_source,
            "failure_domain_level": failure_domain_level,
            "m1_peer_count": len(snapshot.peers),
            "m1_witnessing_zone_preserved": True,
            "m1_verification_states": {
                peer.peer_id: {
                    "effective_path_state": peer.topology_verification_state,
                    "witnessing_zone_state": peer.witnessing_zone_verification_state,
                    "path_states": list(peer.path_verification_states),
                }
                for peer in snapshot.peers
            },
        },
    )
    verification_by_peer = {
        verification.peer_id: verification
        for verification in result.verification_results
    }
    verified_topology = FailureDomainTopology(topology.hierarchy_levels)
    for peer in topology.peers:
        verified_topology.add_peer(
            replace(peer, verification=verification_by_peer[peer.peer_id])
        )
    cluster_peers = tuple(ClusterPeer(peer.peer_id) for peer in verified_topology.peers)
    allocations = {
        content_id: PinAllocation(content_id, tuple(peer_ids))
        for content_id, peer_ids in metadata.current_pin_allocations.items()
    }
    cluster_adapter = DryRunIPFSClusterAdapter(cluster_peers, allocations)
    cluster_action = cluster_adapter.represent_desired_placement(object_id, result.fdar_placement)
    sample_counts = [
        evidence.batch.features.sample_count
        for items in evidence_by_peer.values()
        for evidence in items
    ]
    return M1SystemExecution(
        snapshot,
        verified_topology,
        result,
        cluster_action,
        evidence_source,
        len(snapshot.peers),
        len(metadata.witnesses),
        max(sample_counts, default=0),
    )