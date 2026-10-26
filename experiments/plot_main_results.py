"""Create a compact, presentation-ready set of the four main synthetic results."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECORDS = PROJECT_ROOT / "data/experiments/raw/evaluation_records.json"
DISTANCE_RECORDS = PROJECT_ROOT / "data/experiments/distance_sweep_extended/raw/evaluation_records.json"
OUTPUT_DIR = PROJECT_ROOT / "docs/figures/main-results"

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def _read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise SystemExit(
            f"Required records not found: {path}\n"
            "Generate the synthetic evaluations first; see docs/synthetic_results.md."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _means_by_scenario(
    rows: list[dict[str, Any]],
    scenario: str,
    field: str,
    mode: str,
) -> float:
    values = [
        float(row[field])
        for row in rows
        if row["scenario"] == scenario
        and row["policy"] == "balanced"
        and row["mode"] == mode
        and row[field] is not None
    ]
    if not values:
        raise SystemExit(f"No {field} records for {scenario}/{mode}/balanced.")
    return sum(values) / len(values)


def _finish(axis, path: Path) -> None:
    axis.figure.tight_layout()
    axis.figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(axis.figure)


def main() -> int:
    results = _read_records(DEFAULT_RECORDS)
    sweep = _read_records(DISTANCE_RECORDS)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    blue = "#3274A1"
    orange = "#E1812C"
    grid = "#D9DEE5"

    # 1. Compare suspicious selections only in honest and mismatch scenarios.
    scenarios = ["all_honest", "one_suspicious", "multiple_suspicious"]
    labels = ["All honest", "One suspicious", "Multiple suspicious"]
    x = np.arange(len(scenarios))
    width = 0.34
    fig, axis = plt.subplots(figsize=(8.4, 4.8))
    for offset, (mode, label, color) in enumerate((("BASELINE", "Baseline", blue), ("FDAR", "FDAR", orange))):
        values = [_means_by_scenario(results, name, "suspicious_selected_count", mode) for name in scenarios]
        bars = axis.bar(x + (offset - 0.5) * width, values, width, color=color, label=label)
        axis.bar_label(bars, fmt="%.2f", padding=3, fontsize=9)
    axis.set(title="1. Suspicious peers selected", ylabel="Mean suspicious replicas per placement", xticks=x, xticklabels=labels)
    axis.set_ylim(0, 1.15)
    axis.yaxis.grid(True, color=grid, linewidth=0.8)
    axis.set_axisbelow(True)
    axis.legend(frameon=False, ncols=2, loc="upper left")
    _finish(axis, OUTPUT_DIR / "01_suspicious_selection.png")

    # 2. Compare domain diversity using the balanced eligibility policy.
    scenarios = ["all_honest", "one_suspicious", "multiple_suspicious", "domain_shortfall"]
    labels = ["All honest", "One suspicious", "Multiple suspicious", "Domain shortfall"]
    x = np.arange(len(scenarios))
    fig, axis = plt.subplots(figsize=(8.4, 4.8))
    for offset, (mode, label, color) in enumerate((("BASELINE", "Baseline", blue), ("FDAR", "FDAR", orange))):
        values = [_means_by_scenario(results, name, "domain_diversity_ratio", mode) for name in scenarios]
        bars = axis.bar(x + (offset - 0.5) * width, values, width, color=color, label=label)
        axis.bar_label(bars, fmt="%.2f", padding=3, fontsize=9)
    axis.set(title="2. Replica failure-domain diversity", ylabel="Distinct domains / 3 requested replicas", xticks=x, xticklabels=labels)
    axis.set_ylim(0, 1.18)
    axis.yaxis.grid(True, color=grid, linewidth=0.8)
    axis.set_axisbelow(True)
    axis.legend(frameon=False, ncols=2, loc="upper center", bbox_to_anchor=(0.5, -0.14))
    _finish(axis, OUTPUT_DIR / "02_domain_diversity.png")

    # 3. Show whether each method fills the requested replication factor.
    fig, axis = plt.subplots(figsize=(8.4, 4.8))
    for offset, (mode, label, color) in enumerate((("BASELINE", "Baseline", blue), ("FDAR", "FDAR", orange))):
        values = [
            100 * _means_by_scenario(results, name, "placement_success", mode)
            for name in scenarios
        ]
        bars = axis.bar(x + (offset - 0.5) * width, values, width, color=color, label=label)
        axis.bar_label(bars, fmt="%.0f%%", padding=3, fontsize=9)
    axis.set(title="3. Full placement success", ylabel="Attempts reaching all 3 replicas", xticks=x, xticklabels=labels)
    axis.set_ylim(0, 118)
    axis.yaxis.grid(True, color=grid, linewidth=0.8)
    axis.set_axisbelow(True)
    axis.legend(frameon=False, ncols=2, loc="upper center", bbox_to_anchor=(0.5, -0.14))
    _finish(axis, OUTPUT_DIR / "03_placement_success.png")

    # 4. Show verifier behavior as the generated coordinate mismatch increases.
    sweep_groups: dict[float, dict[str, list[float]]] = defaultdict(lambda: {"detection": [], "false_alarm": []})
    for row in sweep:
        if row["scenario"] != "distance_sweep" or row["mode"] != "FDAR":
            continue
        distance = row["synthetic_location_mismatch_distance_km"]
        if distance is None:
            continue
        if row["location_verification_detection_rate"] is not None:
            sweep_groups[float(distance)]["detection"].append(float(row["location_verification_detection_rate"]))
        if row["location_verification_false_alarm_rate"] is not None:
            sweep_groups[float(distance)]["false_alarm"].append(float(row["location_verification_false_alarm_rate"]))
    distances = sorted(sweep_groups)
    if not distances:
        raise SystemExit("No FDAR distance-sweep records with synthetic location metrics found.")
    means = lambda key: [
        sum(sweep_groups[distance][key]) / len(sweep_groups[distance][key])
        if sweep_groups[distance][key]
        else float("nan")
        for distance in distances
    ]
    fig, axis = plt.subplots(figsize=(8.4, 4.8))
    axis.plot(distances, means("detection"), color=blue, marker="o", linewidth=2.2, label="Mismatch detection")
    axis.plot(distances, means("false_alarm"), color=orange, marker="s", linewidth=2.2, label="False alarm")
    axis.set(title="4. Verification across generated location offsets", xlabel="Generated actual-to-claimed offset (km)", ylabel="Rate in this synthetic run")
    axis.set_ylim(-0.03, 1.08)
    axis.set_yticks(np.linspace(0, 1, 6), labels=["0%", "20%", "40%", "60%", "80%", "100%"])
    axis.yaxis.grid(True, color=grid, linewidth=0.8)
    axis.set_axisbelow(True)
    axis.legend(frameon=False, loc="upper left")
    _finish(axis, OUTPUT_DIR / "04_distance_sweep_detection.png")

    for path in sorted(OUTPUT_DIR.glob("*.png")):
        print(path.relative_to(PROJECT_ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
