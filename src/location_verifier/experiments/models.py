"""Evaluation configuration and serializable per-object experiment records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import math
from typing import Any

from .scenarios import ScenarioName


@dataclass(frozen=True, slots=True)
class EvaluationSettings:
    seeds: tuple[int, ...] = (42,)
    trials: int = 1
    peers: int = 12
    witnesses: int = 5
    objects: int = 100
    replication_factor: int = 3
    failure_domain_level: str = "building"
    scenarios: tuple[ScenarioName, ...] = tuple(ScenarioName)
    uncertain_policies: tuple[str, ...] = ("strict", "balanced", "permissive")
    output_dir: str = "data/experiments"
    measurements_per_witness: int = 30
    distance_sweep_km: tuple[float, ...] = (0, 10, 25, 50, 100, 250, 500, 1000, 2000, 5000, 8000, 10000, 15000)

    def __post_init__(self) -> None:
        if not self.seeds or self.trials < 1 or self.peers < 3 or self.witnesses < 1:
            raise ValueError("evaluation seeds/trials/peers/witnesses are too small")
        if self.objects < 1 or self.replication_factor < 1 or self.measurements_per_witness < 1:
            raise ValueError("evaluation object/replication/measurement counts must be positive")
        if not self.failure_domain_level.strip() or not self.output_dir.strip():
            raise ValueError("failure_domain_level and output_dir must not be empty")
        if (
            not self.distance_sweep_km
            or any(not math.isfinite(distance) or distance < 0 for distance in self.distance_sweep_km)
            or len(set(self.distance_sweep_km)) != len(self.distance_sweep_km)
        ):
            raise ValueError("distance_sweep_km must contain unique non-negative distances")


@dataclass(frozen=True, slots=True)
class EvaluationOptions:
    scenarios: tuple[ScenarioName, ...]
    seeds: tuple[int, ...]
    trials: int
    objects: int
    output_dir: str
    peers: int
    witnesses: int
    replication_factor: int
    failure_domain_level: str
    measurements_per_witness: int
    uncertain_policies: tuple[str, ...] = ("strict", "balanced", "permissive")
    distance_sweep_km: tuple[float, ...] = (0, 10, 25, 50, 100, 250, 500, 1000, 2000, 5000, 8000, 10000, 15000)


@dataclass(frozen=True, slots=True)
class EvaluationRecord:
    experiment_name: str
    scenario: str
    seed: int
    trial: int
    object_id: str
    timestamp_utc: str
    data_label: str
    ground_truth_available: bool
    peer_count: int
    witness_count: int
    object_count: int
    replication_factor: int
    failure_domain_level: str
    mode: str
    policy: str
    placement_status: str
    selected_peers: tuple[str, ...]
    selected_domains: tuple[str, ...]
    requested_replicas: int
    replica_count: int
    distinct_failure_domains: int
    domain_collision_count: int
    domain_diversity_ratio: float
    eligible_peer_count: int
    excluded_peer_count: int
    suspicious_selected_count: int
    suspicious_excluded_count: int
    uncertain_selected_count: int
    uncertain_excluded_count: int
    suspicious_selection_rate: float
    suspicious_exclusion_rate: float | None
    eligible_suspicious_peer_count: int
    verification_true_positive: int | None
    verification_false_positive: int | None
    verification_true_negative: int | None
    verification_false_negative: int | None
    verification_detection_rate: float | None
    verification_false_alarm_rate: float | None
    reconfiguration_event_count: int = 0
    replicas_preserved: int = 0
    replicas_replaced: int = 0
    movement_count: int = 0
    movement_ratio: float = 0.0
    domain_preserved_after_reconfiguration: bool | None = None
    reconfiguration_success: bool | None = None
    actual_domains: dict[str, str] = field(default_factory=dict)
    claimed_domains: dict[str, str] = field(default_factory=dict)
    verification_statuses: dict[str, str] = field(default_factory=dict)
    limitations: tuple[str, ...] = (
        "SYNTHETIC data; not real network validation",
        "Phase 3 confidence is an uncalibrated evidence-strength score, not probability",
    )
    synthetic_location_mismatch_distance_km: float | None = None
    synthetic_location_mismatch_peer_count: int = 0
    location_verification_true_positive: int | None = None
    location_verification_false_positive: int | None = None
    location_verification_true_negative: int | None = None
    location_verification_false_negative: int | None = None
    location_verification_detection_rate: float | None = None
    location_verification_false_alarm_rate: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
        }
