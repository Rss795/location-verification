"""Run actual M1 topology through M3 verification, M2 FDAR, and M4 planning."""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from location_verifier.config import load_config
from location_verifier.integrations.m1_adapter import (
    M1AdapterError,
    load_external_metadata,
    load_topology_map,
    parse_topology_map,
)
from location_verifier.integrations.m1_builder import build_from_document
from location_verifier.integrations.m1_pipeline import (
    generate_synthetic_m1_evidence,
    load_m1_witness_evidence,
    run_m1_pipeline,
)
from location_verifier.integrations.ipfs_cluster import (
    ClusterPeer,
    DryRunIPFSClusterAdapter,
    PinAllocation,
)
from location_verifier.models import VerificationStatus
from location_verifier.system import SystemOrchestrator


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    topology_group = parser.add_mutually_exclusive_group(required=True)
    topology_group.add_argument("--topology", type=Path, help="Existing M1 topology_map.json")
    topology_group.add_argument("--flat-claims", type=Path, help="Flat peer claims JSON; build the repository's reference M1 topology")
    parser.add_argument("--built-topology-output", type=Path, help="Optional path to save generated M1 topology JSON")
    parser.add_argument("--metadata", type=Path, required=True, help="External peer coordinates/endpoints and witness metadata JSON")
    evidence_group = parser.add_mutually_exclusive_group(required=True)
    evidence_group.add_argument("--evidence-dir", type=Path, help="Saved Phase 2 JSON batches keyed by M1 peer and witness IDs")
    evidence_group.add_argument("--synthetic", action="store_true", help="Generate synthetic RTTs; never real evidence")
    parser.add_argument("--dry-run", action="store_true", required=True, help="Required: only calculate desired state; never mutate Cluster")
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "configs" / "default.yaml")
    parser.add_argument("--object-id", default="m1-integrated-object")
    parser.add_argument("--replication-factor", type=int)
    parser.add_argument("--failure-domain-level", default="witnessing_zone", choices=("peer", "region", "asn", "witnessing_zone", "rack"))
    parser.add_argument("--policy", choices=("strict", "balanced", "permissive"))
    parser.add_argument("--simulate-status-change", help="Optional peer ID to mark SUSPICIOUS for an M4 plan")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data" / "m1_system" / "system_result.json")
    args = parser.parse_args()

    try:
        shared_config = load_config(args.config)
        if args.flat_claims:
            flat_claims = json.loads(args.flat_claims.read_text(encoding="utf-8"))
            generated_topology = build_from_document(flat_claims)
            snapshot = parse_topology_map(generated_topology)
            topology_source = "repository-owned reference M1 producer"
            if args.built_topology_output:
                args.built_topology_output.parent.mkdir(parents=True, exist_ok=True)
                args.built_topology_output.write_text(
                    json.dumps(generated_topology, indent=2, sort_keys=True, allow_nan=False) + "\n",
                    encoding="utf-8",
                )
        else:
            snapshot = load_topology_map(args.topology)
            topology_source = "supplied M1 topology_map.json; producer not independently validated"
        external_metadata = load_external_metadata(args.metadata)
        topology, _claims = snapshot.to_placement_topology(
            external_metadata,
            failure_domain_level=args.failure_domain_level,
        )
        placement_config = shared_config.placement
        if args.replication_factor is not None:
            placement_config = replace(placement_config, replication_factor=args.replication_factor)
        if args.policy is not None:
            placement_config = replace(
                placement_config,
                verification_policy=replace(placement_config.verification_policy, mode=args.policy),
            )
        # M1's declared hierarchy has no ``building`` level. Keep the selected
        # M1 level consistent for initial FDAR, M4 replanning, and the final diff.
        placement_config = replace(
            placement_config,
            failure_domain_level=args.failure_domain_level,
        )

        if args.synthetic:
            evidence_by_peer = generate_synthetic_m1_evidence(
                snapshot,
                external_metadata,
                shared_config.inference,
                shared_config.measurement,
            )
            evidence_source = "SYNTHETIC model-generated RTT; NOT REAL NETWORK MEASUREMENTS"
        else:
            evidence_by_peer = load_m1_witness_evidence(
                snapshot,
                external_metadata,
                args.evidence_dir,
            )
            evidence_source = "SAVED PHASE 2 MEASUREMENT JSON"

        execution = run_m1_pipeline(
            snapshot,
            external_metadata,
            evidence_by_peer,
            shared_config.inference,
            placement_config,
            object_id=args.object_id,
            failure_domain_level=args.failure_domain_level,
            evidence_source=evidence_source,
        )
        result = execution.result
        if args.simulate_status_change:
            orchestrator = SystemOrchestrator(shared_config.inference, placement_config)
            result = orchestrator.plan_verification_change(
                result,
                execution.topology,
                args.simulate_status_change,
                VerificationStatus.SUSPICIOUS,
            )
        target_placement = (
            result.reconfiguration.proposed_placement
            if result.reconfiguration
            else result.fdar_placement
        )
        current_allocation = external_metadata.current_pin_allocations.get(args.object_id, [])
        adapter = DryRunIPFSClusterAdapter(
            peers=tuple(ClusterPeer(peer.peer_id) for peer in execution.topology.peers),
            allocations={
                args.object_id: PinAllocation(args.object_id, tuple(current_allocation))
            },
        )
        cluster_action = adapter.represent_desired_placement(args.object_id, target_placement)
        payload = result.to_dict()
        payload["m1_topology"] = {
            "source": topology_source,
            "root_id": snapshot.root.id,
            "hierarchy": ["region", "asn", "witnessing_zone", "rack", "peer"],
            "failure_domain_level": args.failure_domain_level,
            "peers": [
                {
                    "peer_id": peer.peer_id,
                    "region": peer.region,
                    "asn": peer.asn,
                    "witnessing_zone": peer.witnessing_zone,
                    "rack": peer.rack,
                    "witnessing_zone_verification_state": peer.witnessing_zone_verification_state,
                    "effective_path_state": peer.topology_verification_state,
                    "path_states": list(peer.path_verification_states),
                }
                for peer in snapshot.peers
            ],
        }
        payload["m1_topology_with_m3_results"] = snapshot.with_location_verification(
            {item.peer_id: item for item in result.verification_results}
        )
        payload["measurement_source"] = evidence_source
        payload["cluster_dry_run"] = asdict(cluster_action)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    except (M1AdapterError, ValueError, OSError) as exc:
        parser.error(str(exc))

    print("==================================================")
    print("FDAR COMPLETE END-TO-END PIPELINE")
    print("==================================================")
    print("M1 topology loaded")
    print(f"Peers discovered: {execution.peer_count}")
    discovered_domains = (
        {peer.peer_id for peer in snapshot.peers}
        if args.failure_domain_level == "peer"
        else {peer.failure_domains[args.failure_domain_level] for peer in snapshot.peers}
    )
    print(f"Failure domains discovered ({args.failure_domain_level}): {len(discovered_domains)}")
    print(f"M3 evidence source: {execution.evidence_source}")
    if args.synthetic:
        print("DATA CLASS: SYNTHETIC EVALUATION (not real network measurements)")
    else:
        print("DATA CLASS: SAVED PHASE 2 MEASUREMENTS (real only if the saved batches were real)")
    print("M3 verification")
    for verification in result.verification_results:
        print(f"  {verification.peer_id}: {verification.status.value}")
    print("M2 FDAR placement")
    print(f"  status: {result.fdar_placement.placement_status.value}")
    print(f"  replicas: {', '.join(item.peer_id for item in result.fdar_placement.selected_peers) or '(none)'}")
    print(f"  domains: {', '.join(result.fdar_placement.selected_failure_domains) or '(none)'}")
    print(f"  diversity satisfied: {result.fdar_placement.placement_success and len(set(result.fdar_placement.selected_failure_domains)) == len(result.fdar_placement.selected_peers)}")
    print("M4 reconfiguration")
    if result.reconfiguration:
        plan = result.reconfiguration
        print(f"  invalidated: {', '.join(plan.invalidated_peer_ids) or '(none)'}")
        print(f"  preserved: {len(set(item.peer_id for item in plan.previous_placement.selected_peers) & set(item.peer_id for item in plan.proposed_placement.selected_peers))}")
        print(f"  replacements: {', '.join(set(item.peer_id for item in plan.proposed_placement.selected_peers) - set(item.peer_id for item in plan.previous_placement.selected_peers)) or '(none)'}")
        print(f"  moves: {plan.required_moves}")
    else:
        print("  no status-change request")
    print("IPFS Cluster: DRY-RUN; no pin changes or data movement")
    print(f"  additions: {list(cluster_action.add_peer_ids)}")
    print(f"  removals: {list(cluster_action.remove_peer_ids)}")
    print(f"Output JSON: {args.output}")
    print("RTT consistency is not proof of exact physical location.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
