"""Generate Phase 5 plots from an existing aggregate evaluation JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from location_verifier.experiments.plotting import plot_results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=PROJECT_ROOT / "data/experiments/raw/evaluation_records.json")
    parser.add_argument("--aggregated", type=Path, default=PROJECT_ROOT / "data/experiments/aggregated/evaluation_summary.json")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data/experiments/plots")
    arguments = parser.parse_args()
    results = {
        "records": json.loads(arguments.input.read_text(encoding="utf-8")),
        "aggregated": json.loads(arguments.aggregated.read_text(encoding="utf-8")),
    }
    paths = plot_results(results, arguments.output_dir)
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
