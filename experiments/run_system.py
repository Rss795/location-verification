"""Run the final synthetic orchestrator; explicit --dry-run is required."""

from __future__ import annotations

import argparse
from pathlib import Path
import runpy
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", required=True)
    parser.add_argument("--object-id")
    parser.add_argument("--replication-factor", type=int)
    parser.add_argument("--policy", choices=("strict", "balanced", "permissive"))
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "configs" / "demo.yaml")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data" / "system_demo")
    parser.add_argument("--seed", type=int)
    arguments = parser.parse_args()
    sys.argv = [
        str(PROJECT_ROOT / "experiments" / "run_end_to_end_demo.py"),
        "--config", str(arguments.config),
        "--output-dir", str(arguments.output_dir),
    ]
    if arguments.object_id:
        sys.argv.extend(("--object-id", arguments.object_id))
    if arguments.replication_factor:
        sys.argv.extend(("--replication-factor", str(arguments.replication_factor)))
    if arguments.policy:
        sys.argv.extend(("--policy", arguments.policy))
    if arguments.seed is not None:
        sys.argv.extend(("--seed", str(arguments.seed)))
    runpy.run_path(str(PROJECT_ROOT / "experiments" / "run_end_to_end_demo.py"), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
