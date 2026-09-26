"""Build the repository's typed M1 hierarchy from a flat peer-claims JSON file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from location_verifier.integrations.m1_adapter import parse_topology_map
from location_verifier.integrations.m1_builder import build_from_document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claims", type=Path, required=True, help="JSON object containing a peers array")
    parser.add_argument("--output", type=Path, required=True, help="Output M1 topology_map.json")
    parser.add_argument("--root-id", default="default_root")
    args = parser.parse_args()
    try:
        source = json.loads(args.claims.read_text(encoding="utf-8"))
        topology = build_from_document(source, root_id=args.root_id)
        # Enforce the consumer contract before committing output.
        snapshot = parse_topology_map(topology)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(topology, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    print("M1 topology built by the repository's reference producer")
    print("This output is not validation of the absent authoritative teammate producer.")
    print(f"Peers: {len(snapshot.peers)}")
    print(f"Output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
