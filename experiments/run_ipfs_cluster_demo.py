"""Read-only local IPFS Cluster inventory check or synthetic dry-run demo."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from location_verifier.config import load_config
from location_verifier.integrations.ipfs_cluster import (
    ClusterAdapterError,
    LocalIPFSClusterReadOnlyClient,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--live", action="store_true")
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "configs" / "default.yaml")
    arguments = parser.parse_args()
    config = load_config(arguments.config).ipfs_cluster
    if arguments.dry_run:
        print("DRY-RUN ONLY: no Cluster HTTP request and no mutation")
        print(f"Configured local endpoint: {config.base_url}")
        print("Use experiments/run_end_to_end_demo.py for the complete synthetic pipeline.")
        return 0
    if not config.enabled:
        print("LIVE IPFS CLUSTER: NOT RUN (ipfs_cluster.enabled is false)")
        return 0
    if config.dry_run is False:
        print("Live mutation mode is unsupported; this adapter is read-only by design.")
        return 2
    try:
        client = LocalIPFSClusterReadOnlyClient(
            config.base_url,
            config.request_timeout_seconds,
        )
        peers = client.discover_peers()
    except (ClusterAdapterError, ValueError) as exc:
        print(f"LIVE IPFS CLUSTER: NOT RUN ({exc})")
        return 0
    print("LIVE IPFS CLUSTER: READ-ONLY INVENTORY COMPLETED")
    print(f"Discovered peers: {len(peers)}")
    for peer in peers:
        print(f"  {peer.peer_id}")
    print("No pin changes or data movement were requested or performed.")
    print("Location/failure-domain metadata remains external and was not inferred from Cluster IDs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
