"""Generate labeled research-style plots from synthetic evaluation records."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _verification_status_counts(records: list[dict[str, Any]]) -> Counter[str]:
    """Count generated peer statuses once per trial and distinct sweep offset."""
    counts: Counter[str] = Counter()
    seen: set[tuple[int, int, str, float | None]] = set()
    for row in records:
        identity = (
            row["seed"],
            row["trial"],
            row["scenario"],
            row.get("synthetic_location_mismatch_distance_km"),
        )
        if identity not in seen:
            counts.update(row["verification_statuses"].values())
            seen.add(identity)
    return counts


def _scenario_policy_categories(rows: list[dict[str, Any]]) -> tuple[list[tuple[str, str]], list[str]]:
    """Build explicit x-axis categories when scenarios vary placement policy."""
    categories = sorted({(row["scenario"], row["policy"]) for row in rows})
    policies_by_scenario: dict[str, set[str]] = defaultdict(set)
    for scenario, policy in categories:
        policies_by_scenario[scenario].add(policy)
    labels = [
        scenario if len(policies_by_scenario[scenario]) == 1 else f"{scenario} ({policy})"
        for scenario, policy in categories
    ]
    return categories, labels


def plot_results(results: dict[str, Any], output_dir: str | Path) -> tuple[Path, ...]:
    """Write only plots supported by the supplied synthetic records."""

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    records = results["records"]
    summaries = results["aggregated"]
    paths: list[Path] = []
    filenames = (
        "01_suspicious_selection.png",
        "02_domain_diversity.png",
        "03_placement_success.png",
        "04_reconfiguration_movement.png",
        "05_peer_selection_frequency.png",
        "06_domain_selection_frequency.png",
        "07_verification_status_distribution.png",
        "08_synthetic_ground_truth_detection.png",
        "09_synthetic_location_distance_sweep.png",
    )

    # Remove stale plots from a prior run in the same output directory. These
    # names are reserved for this function's generated artifacts.
    for filename in filenames:
        (root / filename).unlink(missing_ok=True)

    def save(fig, filename: str) -> None:
        fig.tight_layout()
        path = root / filename
        fig.savefig(path, dpi=140)
        plt.close(fig)
        paths.append(path)

    # Plot 1: suspicious selection counts by mode/scenario.
    groups: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for row in records:
        if row["scenario"] != "distance_sweep":
            groups[(row["scenario"], row["policy"], row["mode"])].append(row["suspicious_selected_count"])
    plot1_rows = [row for row in records if row["scenario"] != "distance_sweep"]
    categories, labels = _scenario_policy_categories(plot1_rows)
    if categories:
        fig, axis = plt.subplots(figsize=(11, 5))
        width = 0.38
        for offset, mode in enumerate(("BASELINE", "FDAR")):
            values = [
                sum(groups.get((scenario, policy, mode), [])) / max(len(groups.get((scenario, policy, mode), [])), 1)
                for scenario, policy in categories
            ]
            axis.bar([index + (offset - 0.5) * width for index in range(len(categories))], values, width, label=mode)
        axis.set(title="SYNTHETIC: Suspicious replicas selected", ylabel="Mean suspicious selected peers", xticks=range(len(categories)), xticklabels=labels)
        axis.tick_params(axis="x", labelrotation=30)
        axis.legend()
        save(fig, "01_suspicious_selection.png")

    # Plot 2: failure-domain diversity ratio.
    diversity_rows = [item for item in summaries if item["scenario"] != "distance_sweep"]
    if diversity_rows:
        fig, axis = plt.subplots(figsize=(11, 5))
        categories, labels = _scenario_policy_categories(diversity_rows)
        for mode, marker in (("BASELINE", "o"), ("FDAR", "s")):
            values_by_category = {
                (item["scenario"], item["policy"]): item["mean_domain_diversity_ratio"]
                for item in diversity_rows if item["mode"] == mode
            }
            axis.plot(labels, [values_by_category.get(category, float("nan")) for category in categories], marker=marker, label=mode)
        axis.set(title="SYNTHETIC: Replica domain diversity", ylabel="Distinct domains / requested replicas", ylim=(0, 1.05))
        axis.tick_params(axis="x", labelrotation=30)
        axis.legend()
        save(fig, "02_domain_diversity.png")

    # Plot 3: placement success rate.
    success_rows = [item for item in summaries if item["scenario"] != "distance_sweep"]
    if success_rows:
        fig, axis = plt.subplots(figsize=(11, 5))
        categories, labels = _scenario_policy_categories(success_rows)
        for mode, marker in (("BASELINE", "o"), ("FDAR", "s")):
            values_by_category = {
                (item["scenario"], item["policy"]): item["placement_success_rate"]
                for item in success_rows if item["mode"] == mode
            }
            axis.plot(labels, [values_by_category.get(category, float("nan")) for category in categories], marker=marker, label=mode)
        axis.set(title="SYNTHETIC: Placement success rate", ylabel="Successful placement attempts / attempts", ylim=(0, 1.05))
        axis.tick_params(axis="x", labelrotation=30)
        axis.legend()
        save(fig, "03_placement_success.png")

    # Plot 4: reconfiguration movement.
    repair_rows = [item for item in records if item["reconfiguration_event_count"]]
    movement: dict[str, list[int]] = defaultdict(list)
    for item in repair_rows:
        movement[item["mode"]].append(item["movement_count"])
    if movement:
        fig, axis = plt.subplots(figsize=(7, 4))
        axis.bar(list(movement), [sum(values) / len(values) for values in movement.values()])
        axis.set(title="SYNTHETIC: Reconfiguration movement plan", ylabel="Mean replicas moved (plans only)")
        save(fig, "04_reconfiguration_movement.png")

    # Plot 5: peer selection frequency across many objects.
    peer_counts: Counter[str] = Counter()
    for row in records:
        if row["scenario"] in {"multiple_objects", "repeated_trials"} and row["mode"] == "FDAR":
            peer_counts.update(row["selected_peers"])
    if peer_counts:
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
    if domain_counts:
        fig, axis = plt.subplots(figsize=(9, 5))
        axis.bar(list(sorted(domain_counts)), [domain_counts[key] for key in sorted(domain_counts)])
        axis.set(title="SYNTHETIC: FDAR failure-domain selection frequency", ylabel="Selected replica instances")
        save(fig, "06_domain_selection_frequency.png")

    # Plot 7: generated verification status distribution.
    status_counts = _verification_status_counts(records)
    if status_counts:
        fig, axis = plt.subplots(figsize=(7, 4))
        axis.bar(list(status_counts), [status_counts[key] for key in status_counts])
        axis.set(title="SYNTHETIC: Phase 3 verification statuses", ylabel="Generated peers")
        save(fig, "07_verification_status_distribution.png")

    # Plot 8: verification detection/false alarm only where synthetic truth is supplied.
    gt_rows = [item for item in summaries if item["mode"] == "FDAR" and item["synthetic_ground_truth"]]
    scenarios_gt = [item for item in gt_rows if item["mean_verification_detection_rate"] is not None]
    if scenarios_gt:
        fig, axis = plt.subplots(figsize=(10, 5))
        names = [item["scenario"] for item in scenarios_gt]
        axis.bar(names, [item["mean_verification_detection_rate"] for item in scenarios_gt], label="synthetic detection rate")
        axis.plot(names, [item["mean_verification_false_alarm_rate"] or 0 for item in scenarios_gt], "o-", label="synthetic false-alarm rate")
        axis.set(title="SYNTHETIC GROUND TRUTH ONLY: verification detection", ylabel="Rate (not real-world accuracy)", ylim=(0, 1.05))
        axis.tick_params(axis="x", labelrotation=30)
        axis.legend()
        save(fig, "08_synthetic_ground_truth_detection.png")

    # Plot 9: controlled location-claim mismatch sweep, not empirical calibration.
    sweep_rows = [
        item for item in summaries
        if item["scenario"] == "distance_sweep" and item["mode"] == "FDAR"
        and item["synthetic_location_mismatch_distance_km"] is not None
    ]
    sweep_rows.sort(key=lambda item: item["synthetic_location_mismatch_distance_km"])
    measurable = [item for item in sweep_rows if item["mean_location_verification_detection_rate"] is not None]
    if sweep_rows:
        fig, axis = plt.subplots(figsize=(9, 5))
    if sweep_rows and measurable:
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
    if sweep_rows:
        axis.set(
            title="SYNTHETIC MODEL SWEEP ONLY: location-claim mismatch",
            xlabel="Generated actual-to-claimed offset (km)",
            ylabel="Rate under configured model (not empirical accuracy)",
            ylim=(0, 1.05),
        )
        axis.legend()
        save(fig, "09_synthetic_location_distance_sweep.png")
    return tuple(paths)
