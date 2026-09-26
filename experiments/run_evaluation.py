"""Run the Phase 5 deterministic synthetic system evaluation."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from location_verifier.experiments.plotting import plot_results
from location_verifier.experiments.runner import (
    load_evaluation_settings,
    options_from_settings,
    phase_configs,
    run_evaluation,
)
from location_verifier.experiments.serialization import write_results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "configs" / "evaluation.yaml")
    parser.add_argument("--phase-config", type=Path, default=PROJECT_ROOT / "configs" / "default.yaml")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--scenario")
    parser.add_argument("--trials", type=int)
    parser.add_argument("--objects", type=int)
    parser.add_argument("--output-dir")
    parser.add_argument(
        "--distance-sweep-km",
        help="Comma-separated synthetic claim offsets (km), used by distance_sweep",
    )
    arguments = parser.parse_args()

    settings = load_evaluation_settings(arguments.config)
    try:
        distance_sweep = (
            tuple(float(value.strip()) for value in arguments.distance_sweep_km.split(","))
            if arguments.distance_sweep_km
            else None
        )
    except ValueError as exc:
        parser.error(f"--distance-sweep-km must be comma-separated numbers: {exc}")
    if distance_sweep is not None and (
        not distance_sweep
        or any(not math.isfinite(value) or value < 0 for value in distance_sweep)
        or len(set(distance_sweep)) != len(distance_sweep)
    ):
        parser.error("--distance-sweep-km values must be finite, non-negative, and unique")
    options = options_from_settings(
        settings,
        seed=arguments.seed,
        scenario=arguments.scenario,
        trials=arguments.trials,
        objects=arguments.objects,
        output_dir=arguments.output_dir,
        distance_sweep_km=distance_sweep,
    )
    inference_config, placement_config = phase_configs(arguments.phase_config)
    results = run_evaluation(options, inference_config, placement_config)
    paths = write_results(results, options.output_dir)
    plot_paths = plot_results(results, Path(options.output_dir) / "plots")

    print("SYNTHETIC SYSTEM EVALUATION; no live pings or IPFS operations were performed")
    print(f"Scenarios: {', '.join(item.value for item in options.scenarios)}")
    print(f"Seeds: {', '.join(str(item) for item in options.seeds)}; trials per scenario: {options.trials}")
    print(f"Placement records: {results['manifest']['records']}")
    for item in results["aggregated"]:
        distance = item.get("synthetic_location_mismatch_distance_km")
        distance_label = f" offset={distance:g}km" if distance is not None else ""
        detection = item.get("mean_location_verification_detection_rate")
        detection_label = (
            f" synthetic-location-detection={detection:.3f}"
            if detection is not None
            else ""
        )
        print(
            f"{item['scenario']}{distance_label} {item['mode']} policy={item['policy']}: "
            f"success={item['placement_success_rate']:.3f}, "
            f"mean diversity={item['mean_domain_diversity_ratio']:.3f}, "
            f"suspicious selected={item['mean_suspicious_selected_count']:.3f}"
            f"{detection_label}"
        )
    print("Outputs:")
    for path in (*paths.values(), *plot_paths):
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
