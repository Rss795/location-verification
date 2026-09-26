"""Compare baseline and FDAR metrics on the same deterministic synthetic pool."""

from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from location_verifier.config import load_config
from location_verifier.placement.fdar import place_baseline, place_fdar
from location_verifier.placement.metrics import calculate_metrics
from run_placement_simulation import build_synthetic_topology


def main() -> None:
    config = load_config(PROJECT_ROOT / "configs" / "default.yaml").placement
    topology = build_synthetic_topology()
    object_id = "synthetic-object-011"
    baseline = place_baseline(object_id, topology, config)
    fdar = place_fdar(object_id, topology, config)
    baseline_metrics = calculate_metrics(baseline, topology.peers)
    fdar_metrics = calculate_metrics(fdar, topology.peers)

    print("SYNTHETIC COMPARISON; no ground-truth accuracy is calculated")
    print(f"Baseline status: {baseline.placement_status.value}")
    print(f"Baseline peers: {', '.join(item.peer_id for item in baseline.selected_peers) or '(none)'}")
    print(f"Baseline domains: {baseline_metrics.distinct_failure_domains}")
    print(f"Baseline suspicious peers selected: {sum(item.verification_status.value == 'SUSPICIOUS' for item in baseline.selected_peers)}")
    print(f"FDAR status: {fdar.placement_status.value}")
    print(f"FDAR peers: {', '.join(item.peer_id for item in fdar.selected_peers) or '(none)'}")
    print(f"FDAR domains: {fdar_metrics.distinct_failure_domains}")
    print(f"FDAR excluded peers: {fdar_metrics.excluded_peer_count}")
    print(f"FDAR uncertain peers in candidate pool: {fdar_metrics.uncertain_peer_count}")
    print("Accuracy: not reported; synthetic scenario has no empirical validation claim")


if __name__ == "__main__":
    main()
