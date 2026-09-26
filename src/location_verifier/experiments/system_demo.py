"""Deterministic synthetic dry-run fixture for the final system pipeline."""

from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import yaml

from ..config import load_config
from ..integrations.ipfs_cluster import (
    ClusterPeer,
    DryRunIPFSClusterAdapter,
    PinAllocation,
)
from ..models import VerificationStatus
from ..placement.fdar import place_baseline, place_fdar
from ..placement.topology import FailureDomainTopology
from ..system import SystemOrchestrator, SystemRunResult
from .generator import generate_trial
from .models import EvaluationSettings
from .scenarios import ScenarioName


def run_synthetic_system_demo(
    *,
    config_path: str | Path,
    seed: int | None = None,
    object_id: str | None = None,
    replication_factor: int | None = None,
    policy: str | None = None,
) -> tuple[SystemRunResult, dict[str, Any]]:
    """Run generated Phase 2 evidence through Phase 3/4/6, with no network calls."""

    config_path = Path(config_path)
    config = load_config(config_path)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    demo = raw.get("demo", {})
    active_seed = int(seed if seed is not None else demo.get("seed", 42))
    peer_count = int(demo.get("peer_count", 12))
    witness_count = int(demo.get("witness_count", 5))
    sample_count = config.measurement.samples
    factor = replication_factor or config.placement.replication_factor
    settings = EvaluationSettings(
        seeds=(active_seed,),
        trials=1,
        peers=peer_count,
        witnesses=witness_count,
        objects=1,
        replication_factor=factor,
        failure_domain_level=config.placement.failure_domain_level,
        scenarios=(ScenarioName.ONE_SUSPICIOUS,),
        measurements_per_witness=sample_count,
    )
    trial = generate_trial(
        ScenarioName.ONE_SUSPICIOUS,
        active_seed,
        settings,
        config.inference,
        config.placement,
    )
    claims = tuple(item.claim for item in trial.peers)
    evidence_by_peer = {
        item.peer_id: item.witness_evidence
        for item in trial.ground_truth
    }
    active_placement = replace(
        trial.placement_config,
        verification_policy=replace(
            trial.placement_config.verification_policy,
            mode=policy or trial.placement_config.verification_policy.mode,
        ),
    )

    selected_object_id = object_id
    if selected_object_id is None:
        suspicious_ids = {
            peer.peer_id
            for peer in trial.peers
            if peer.verification_status is VerificationStatus.SUSPICIOUS
        }
        prefix = str(demo.get("object_id_prefix", "demo-object"))
        for candidate_index in range(1000):
            candidate = f"{prefix}-{candidate_index:04d}"
            baseline = place_baseline(candidate, trial.topology, active_placement)
            fdar = place_fdar(candidate, trial.topology, active_placement)
            baseline_ids = {item.peer_id for item in baseline.selected_peers}
            fdar_ids = {item.peer_id for item in fdar.selected_peers}
            if baseline_ids & suspicious_ids and not fdar_ids & suspicious_ids:
                selected_object_id = candidate
                break
        if selected_object_id is None:
            selected_object_id = f"{prefix}-fixed"

    orchestrator = SystemOrchestrator(config.inference, active_placement)
    result = orchestrator.run(
        selected_object_id,
        trial.topology,
        claims,
        evidence_by_peer,
        metadata={
            "label": "SYNTHETIC / DRY-RUN",
            "seed": active_seed,
            "peer_count": len(trial.peers),
            "witness_count": len(trial.witnesses),
            "measurements_per_witness": sample_count,
            "phase3_confidence": "uncalibrated evidence-strength score, not probability",
        },
    )
    initial_statuses = {
        item.peer_id: item.status.value
        for item in result.verification_results
    }

    verified_topology = FailureDomainTopology(trial.topology.hierarchy_levels)
    result_by_peer = {item.peer_id: item for item in result.verification_results}
    for peer in trial.peers:
        verified_topology.add_peer(replace(peer, verification=result_by_peer[peer.peer_id]))
    plausible_selected = next(
        (
            item.peer_id
            for item in result.fdar_placement.selected_peers
            if result_by_peer[item.peer_id].status is VerificationStatus.PLAUSIBLE
        ),
        None,
    )
    if plausible_selected is not None:
        result = orchestrator.plan_verification_change(
            result,
            verified_topology,
            plausible_selected,
            VerificationStatus.SUSPICIOUS,
        )
        verified_topology.update_peer(
            replace(
                verified_topology.get_peer(plausible_selected),
                verification=replace(
                    result_by_peer[plausible_selected],
                    status=VerificationStatus.SUSPICIOUS,
                ),
            )
        )

    suspicious_ids = {
        peer.peer_id
        for peer in trial.peers
        if result_by_peer[peer.peer_id].status is VerificationStatus.SUSPICIOUS
    }
    existing_ids = tuple(item.peer_id for item in result.fdar_placement.selected_peers)
    cluster = DryRunIPFSClusterAdapter(
        peers=tuple(ClusterPeer(peer.peer_id) for peer in verified_topology.peers),
        allocations={
            str(demo.get("content_id", "synthetic-demo-content")): PinAllocation(
                str(demo.get("content_id", "synthetic-demo-content")), existing_ids
            )
        },
    )
    target_placement = (
        result.reconfiguration.proposed_placement
        if result.reconfiguration
        else result.fdar_placement
    )
    cluster_action = cluster.represent_desired_placement(
        str(demo.get("content_id", "synthetic-demo-content")),
        target_placement,
    )
    metadata = {
        **result.metadata,
        "dry_run": True,
        "cluster_adapter": "in-memory read-only fixture",
        "cluster_desired_diff": asdict(cluster_action),
        "suspicious_peer_ids": sorted(suspicious_ids),
    }
    result = replace(result, metadata=metadata)
    return result, {
        "topology": verified_topology,
        "ground_truth": trial.ground_truth,
        "cluster_adapter": cluster,
        "cluster_action": cluster_action,
        "seed": active_seed,
        "sample_count": sample_count,
        "initial_statuses": initial_statuses,
    }
