"""Generate labeled research-style plots from synthetic evaluation records."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def plot_results(results: dict[str, Any], output_dir: str | Path) -> tuple[Path, ...]:
    """Write the required plots; all titles/axes explicitly identify synthetic data."""

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    records = results["records"]
    summaries = results["aggregated"]
    paths: list[Path] = []

    def save(fig, filename: str) -> None:
        fig.tight_layout()
        path = root / filename
        fig.savefig(path, dpi=140)
        plt.close(fig)
        paths.append(path)

    # Plot 1: suspicious selection counts by mode/scenario.
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for row in records:
        groups[(row["scenario"], row["mode"])].append(row["suspicious_selected_count"])
    scenarios = sorted({key[0] for key in groups})
    fig, axis = plt.subplots(figsize=(11, 5))
    width = 0.38
    for offset, mode in enumerate(("BASELINE", "FDAR")):
        values = [sum(groups.get((name, mode), [])) / max(len(groups.get((name, mode), [])), 1) for name in scenarios]
        axis.bar([index + (offset - 0.5) * width for index in range(len(scenarios))], values, width, label=mode)
    axis.set(title="SYNTHETIC: Suspicious replicas selected", ylabel="Mean suspicious selected peers", xticks=range(len(scenarios)), xticklabels=scenarios)
    axis.tick_params(axis="x", labelrotation=30)
    axis.legend()
    save(fig, "01_suspicious_selection.png")

    # Plot 2: failure-domain diversity ratio.
    fig, axis = plt.subplots(figsize=(11, 5))
    for mode, marker in (("BASELINE", "o"), ("FDAR", "s")):
        rows = [item for item in summaries if item["mode"] == mode and item["scenario"] != "distance_sweep"]
        axis.plot([item["scenario"] for item in rows], [item["mean_domain_diversity_ratio"] for item in rows], marker=marker, label=mode)
    axis.set(title="SYNTHETIC: Replica domain diversity", ylabel="Distinct domains / requested replicas", ylim=(0, 1.05))
    axis.tick_params(axis="x", labelrotation=30)
    axis.legend()
    save(fig, "02_domain_diversity.png")

    # Plot 3: placement success rate.
    fig, axis = plt.subplots(figsize=(11, 5))
    for mode, marker in (("BASELINE", "o"), ("FDAR", "s")):
        rows = [item for item in summaries if item["mode"] == mode and item["scenario"] != "distance_sweep"]
        axis.plot([item["scenario"] for item in rows], [item["placement_success_rate"] for item in rows], marker=marker, label=mode)
    axis.set(title="SYNTHETIC: Placement success rate", ylabel="Successful placement attempts / attempts", ylim=(0, 1.05))
    axis.tick_params(axis="x", labelrotation=30)
    axis.legend()
    save(fig, "03_placement_success.png")

    # Plot 4: reconfiguration movement.
    repair_rows = [item for item in records if item["reconfiguration_event_count"]]
    movement: dict[str, list[int]] = defaultdict(list)
    for item in repair_rows:
        movement[item["mode"]].append(item["movement_count"])
    fig, axis = plt.subplots(figsize=(7, 4))
    axis.bar(list(movement) or ["FDAR"], [sum(values) / len(values) for values in movement.values()] or [0])
    axis.set(title="SYNTHETIC: Reconfiguration movement plan", ylabel="Mean replicas moved (plans only)")
    save(fig, "04_reconfiguration_movement.png")

    # Plot 5: peer selection frequency across many objects.
    peer_counts: Counter[str] = Counter()
    for row in records:
        if row["scenario"] in {"multiple_objects", "repeated_trials"} and row["mode"] == "FDAR":
            peer_counts.update(row["selected_peers"])
    fig, axis = plt.subplots(figsize=(10, 5))
    axis.bar(list(sorted(peer_counts)), [peer_counts[key] for key in sorted(peer_counts)])
    axis.set(title="SYNTHETIC: FDAR peer selection frequency", ylabel="Selected replica instances")
    axis.tick_params(axis="x", labelrotation=30)
    save(fig, "05_peer_selection_frequency.png")

    # Plot 6: domain selection frequency across many objects.
    domain_counts: Counter[str] = Counter()
    for row in records:
        if row["scenario"] in {"multiple_objects", "repeated_trials"} and row["mode"] == "FDAR":
            domain_counts.update(row["selected_domains"])
    fig, axis = plt.subplots(figsize=(9, 5))
    axis.bar(list(sorted(domain_counts)), [domain_counts[key] for key in sorted(domain_counts)])
    axis.set(title="SYNTHETIC: FDAR failure-domain selection frequency", ylabel="Selected replica instances")
    save(fig, "06_domain_selection_frequency.png")

    # Plot 7: generated verification status distribution.
    status_counts: Counter[str] = Counter()
    status_seen: set[tuple[int, int, str]] = set()
    for row in records:
        identity = (row["seed"], row["trial"], row["scenario"])
        if identity not in status_seen:
            status_counts.update(row["verification_statuses"].values())
            status_seen.add(identity)
    fig, axis = plt.subplots(figsize=(7, 4))
    axis.bar(list(status_counts), [status_counts[key] for key in status_counts])
    axis.set(title="SYNTHETIC: Phase 3 verification statuses", ylabel="Generated peers")
    save(fig, "07_verification_status_distribution.png")

    # Plot 8: verification detection/false alarm only where synthetic truth is supplied.
    gt_rows = [item for item in summaries if item["mode"] == "FDAR" and item["synthetic_ground_truth"]]
    scenarios_gt = [item for item in gt_rows if item["mean_verification_detection_rate"] is not None]
    fig, axis = plt.subplots(figsize=(10, 5))
    if scenarios_gt:
        names = [item["scenario"] for item in scenarios_gt]
        axis.bar(names, [item["mean_verification_detection_rate"] for item in scenarios_gt], label="synthetic detection rate")
        axis.plot(names, [item["mean_verification_false_alarm_rate"] or 0 for item in scenarios_gt], "o-", label="synthetic false-alarm rate")
        axis.legend()
    axis.set(title="SYNTHETIC GROUND TRUTH ONLY: verification detection", ylabel="Rate (not real-world accuracy)", ylim=(0, 1.05))
    axis.tick_params(axis="x", labelrotation=30)
    save(fig, "08_synthetic_ground_truth_detection.png")

    # Plot 9: controlled location-claim mismatch sweep, not empirical calibration.
    sweep_rows = [
        item for item in summaries
        if item["scenario"] == "distance_sweep" and item["mode"] == "FDAR"
        and item["synthetic_location_mismatch_distance_km"] is not None
    ]
    sweep_rows.sort(key=lambda item: item["synthetic_location_mismatch_distance_km"])
    fig, axis = plt.subplots(figsize=(9, 5))
    measurable = [item for item in sweep_rows if item["mean_location_verification_detection_rate"] is not None]
    if measurable:
        distances = [item["synthetic_location_mismatch_distance_km"] for item in measurable]
        axis.plot(
            distances,
            [item["mean_location_verification_detection_rate"] for item in measurable],
            marker="o",
            label="synthetic mismatch detection",
        )
    if sweep_rows:
        axis.plot(
            [item["synthetic_location_mismatch_distance_km"] for item in sweep_rows],
            [item["mean_location_verification_false_alarm_rate"] or 0 for item in sweep_rows],
            marker="s",
            label="synthetic false alarm",
        )
    axis.set(
        title="SYNTHETIC MODEL SWEEP ONLY: location-claim mismatch",
        xlabel="Generated actual-to-claimed offset (km)",
        ylabel="Rate under configured model (not empirical accuracy)",
        ylim=(0, 1.05),
    )
    if measurable or sweep_rows:
        axis.legend()
    save(fig, "09_synthetic_location_distance_sweep.png")
    return tuple(paths)
