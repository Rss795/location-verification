"""Collect Phase 2 RTT batches for every peer in an M1 topology map.

This script measures authorized peer target hosts from THIS vantage only. It does
not impersonate other witnesses. Loopback/localhost probes are refused unless
explicitly allowed, and even then they are labeled as connectivity data only.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from location_verifier.config import load_config
from location_verifier.integrations.m1_adapter import (
    M1AdapterError,
    load_external_metadata,
    load_topology_map,
)
from location_verifier.integrations.m1_pipeline import collect_real_m1_measurements


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topology", type=Path, required=True, help="M1 topology_map.json")
    parser.add_argument("--metadata", type=Path, required=True, help="External peer/witness metadata JSON")
    parser.add_argument("--witness-id", required=True, help="This machine's witness ID from the sidecar")
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "configs" / "default.yaml")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "real_measurements",
    )
    parser.add_argument(
        "--allow-loopback",
        action="store_true",
        help="Allow 127.0.0.1/localhost targets as connectivity tests only",
    )
    args = parser.parse_args()

    try:
        config = load_config(args.config)
        snapshot = load_topology_map(args.topology)
        metadata = load_external_metadata(args.metadata)
        saved, label = collect_real_m1_measurements(
            snapshot,
            metadata,
            config.measurement,
            witness_id=args.witness_id,
            output_dir=args.output_dir,
            allow_loopback=args.allow_loopback,
        )
    except (M1AdapterError, ValueError, OSError) as exc:
        parser.error(str(exc))

    print("==================================================")
    print("M1 PHASE 2 COLLECTION")
    print("==================================================")
    print(label)
    print(f"M1 peers measured: {len(snapshot.peers)}")
    print(f"Witness: {args.witness_id}")
    print("Saved feature files:")
    for path in saved:
        print(f"  {path}")
    print("Independent remote witnesses must collect separately.")
    print("RTT is not proof of exact physical location.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
