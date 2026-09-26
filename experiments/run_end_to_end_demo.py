"""Run the complete SYNTHETIC / DRY-RUN measurement-to-FDAR pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from location_verifier.experiments.system_demo import run_synthetic_system_demo


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "configs" / "demo.yaml")
    parser.add_argument("--object-id")
    parser.add_argument("--replication-factor", type=int)
    parser.add_argument("--policy", choices=("strict", "balanced", "permissive"))
    parser.add_argument("--seed", type=int)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data" / "system_demo")
    arguments = parser.parse_args()

    result, detail = run_synthetic_system_demo(
        config_path=arguments.config,
        seed=arguments.seed,
        object_id=arguments.object_id,
        replication_factor=arguments.replication_factor,
        policy=arguments.policy,
    )
    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    result_path = arguments.output_dir / "system_run_result.json"
    result_path.write_text(
        json.dumps(result.to_dict(), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    initial_statuses = detail["initial_statuses"]
    suspicious = [peer_id for peer_id, status in initial_statuses.items() if status == "SUSPICIOUS"]
    uncertain = [peer_id for peer_id, status in initial_statuses.items() if status == "UNCERTAIN"]
    baseline = result.baseline_placement
    fdar = result.fdar_placement
    print("==================================================")
    print("FDAR END-TO-END DEMONSTRATION")
    print("==================================================")
    print("SYNTHETIC / DRY-RUN; no live pings, Cluster requests, or data movement")
    print("Measurement evidence")
    print("        |")
    print("Location verification")
    print("        |")
    print("VerificationResult")
    print("        |")
    print("FDAR eligibility")
    print("        |")
    print("Replica placement")
    print("        |")
    print("Verification-triggered reconfiguration")
    print("==================================================")
    print(f"Object: {result.object_id}")
    print(f"Peers: {len(result.claims)}; witnesses: {len({item.witness.witness_id for gt in detail['ground_truth'] for item in gt.witness_evidence})}")
    print(f"Synthetic measurements per witness: {detail['sample_count']}")
    print("Initial verification status per peer:")
    for peer_id, status in initial_statuses.items():
        print(f"  {peer_id}: {status}")
    print(f"Suspicious peers: {', '.join(suspicious) or '(none)'}")
    print(f"Uncertain peers: {', '.join(uncertain) or '(none)'}")
    print(f"Baseline replicas (before status change): {', '.join(item.peer_id for item in baseline.selected_peers) if baseline else '(not requested)'}")
    if baseline:
        print(f"Baseline domains: {', '.join(baseline.selected_failure_domains)}")
    print(f"FDAR status: {fdar.placement_status.value}")
    print(f"FDAR replicas (before status change): {', '.join(item.peer_id for item in fdar.selected_peers) or '(none)'}")
    print(f"FDAR domains (before status change): {', '.join(fdar.selected_failure_domains) or '(none)'}")
    print(f"Diversity satisfied: {fdar.placement_success and len(set(fdar.selected_failure_domains)) == len(fdar.selected_peers)}")
    print(f"Excluded/quarantined peers (initial FDAR): {', '.join(item.peer_id for item in fdar.excluded_peers) or '(none)'}")
    if result.reconfiguration:
        plan = result.reconfiguration
        print(f"Simulated status change: {result.metadata['verification_status_change']}")
        print(f"Reconfiguration proposed replicas: {', '.join(item.peer_id for item in plan.proposed_placement.selected_peers) or '(none)'}")
        print(f"Reconfiguration: {plan.reason}")
        print(f"Replicas preserved: {len(set(item.peer_id for item in plan.previous_placement.selected_peers) & set(item.peer_id for item in plan.proposed_placement.selected_peers))}")
        print(f"Replicas replaced: {len(set(item.peer_id for item in plan.proposed_placement.selected_peers) - set(item.peer_id for item in plan.previous_placement.selected_peers))}")
        print(f"Moves: {plan.required_moves}")
    else:
        print("Reconfiguration: not requested")
    print(f"Cluster action: dry-run diff only; desired additions={list(detail['cluster_action'].add_peer_ids)}; removals={list(detail['cluster_action'].remove_peer_ids)}")
    print(f"JSON result: {result_path.relative_to(PROJECT_ROOT) if result_path.is_relative_to(PROJECT_ROOT) else result_path}")
    print("Location evidence is plausibility, not cryptographic physical proof.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
