"""Aggregate per-object evaluation records without fabricating accuracy metrics."""

from __future__ import annotations

from collections import defaultdict
from statistics import fmean
from typing import Any, Iterable


_MEAN_FIELDS = (
    "placement_success_count",
    "replica_count",
    "distinct_failure_domains",
    "domain_collision_count",
    "domain_diversity_ratio",
    "eligible_peer_count",
    "excluded_peer_count",
    "suspicious_selected_count",
    "suspicious_excluded_count",
    "uncertain_selected_count",
    "uncertain_excluded_count",
    "suspicious_selection_rate",
    "synthetic_location_mismatch_peer_count",
    "reconfiguration_event_count",
    "replicas_preserved",
    "replicas_replaced",
    "movement_count",
    "movement_ratio",
)


def aggregate_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group object-level records by scenario, mode, and policy; compute means/rates."""

    groups: dict[tuple[str, str, str, float | None], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[(
            record["scenario"],
            record["mode"],
            record["policy"],
            record.get("synthetic_location_mismatch_distance_km"),
        )].append(record)
    summaries: list[dict[str, Any]] = []
    for (scenario, mode, policy, mismatch_distance_km), items in sorted(
        groups.items(),
        key=lambda pair: (
            pair[0][0], pair[0][1], pair[0][2],
            -1.0 if pair[0][3] is None else pair[0][3],
        ),
    ):
        attempts = len(items)
        summary: dict[str, Any] = {
            "scenario": scenario,
            "mode": mode,
            "policy": policy,
            "synthetic_location_mismatch_distance_km": mismatch_distance_km,
            "attempts": attempts,
            "placement_success_rate": sum(item["placement_success_count"] for item in items) / attempts,
        }
        for field in _MEAN_FIELDS:
            summary[f"mean_{field}"] = fmean(float(item[field]) for item in items)
        for field in (
            "verification_detection_rate",
            "verification_false_alarm_rate",
            "suspicious_exclusion_rate",
            "location_verification_detection_rate",
            "location_verification_false_alarm_rate",
        ):
            values = [float(item[field]) for item in items if item.get(field) is not None]
            summary[f"mean_{field}"] = fmean(values) if values else None
        domain_preservation_values = [
            float(item["domain_preserved_after_reconfiguration"])
            for item in items
            if item.get("domain_preserved_after_reconfiguration") is not None
        ]
        summary["domain_preservation_rate_after_reconfiguration"] = (
            fmean(domain_preservation_values) if domain_preservation_values else None
        )
        reconfiguration_values = [
            float(item["reconfiguration_success"])
            for item in items
            if item.get("reconfiguration_success") is not None
        ]
        summary["reconfiguration_success_rate"] = (
            fmean(reconfiguration_values) if reconfiguration_values else None
        )
        summary["synthetic_ground_truth"] = all(item["ground_truth_available"] for item in items)
        summaries.append(summary)
    return summaries
