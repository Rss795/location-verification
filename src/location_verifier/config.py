"""Configuration loading and validation for the verifier prototype."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from .models import GeoLocation


@dataclass(frozen=True, slots=True)
class MeasurementConfig:
    """Controls repeated network measurement."""

    samples: int = 50
    timeout_seconds: float = 2.0
    interval_seconds: float = 0.2

    def __post_init__(self) -> None:
        if self.samples < 1:
            raise ValueError("measurement.samples must be at least 1")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("measurement.timeout_seconds must be finite and positive")
        if not math.isfinite(self.interval_seconds) or self.interval_seconds < 0:
            raise ValueError("measurement.interval_seconds must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class WitnessConfig:
    """Static endpoint and declared location for a configured witness."""

    witness_id: str
    host: str
    location: GeoLocation
    known_failure_domain: str | None = None

    def __post_init__(self) -> None:
        if not self.witness_id.strip():
            raise ValueError("witness.id must not be empty")
        if not self.host.strip():
            raise ValueError("witness.host must not be empty")


@dataclass(frozen=True, slots=True)
class IPFSClusterConfig:
    """Safe local Cluster adapter settings; integration is disabled by default."""

    enabled: bool = False
    base_url: str = "http://127.0.0.1:9094"
    dry_run: bool = True
    request_timeout_seconds: float = 2.0

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("ipfs_cluster.base_url must be an HTTP(S) URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("credentials must not be embedded in ipfs_cluster.base_url")
        if parsed.hostname.lower() not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("ipfs_cluster.base_url must target localhost or a loopback address")
        if not math.isfinite(self.request_timeout_seconds) or self.request_timeout_seconds <= 0:
            raise ValueError("ipfs_cluster.request_timeout_seconds must be finite and positive")


@dataclass(frozen=True, slots=True)
class VerifierConfig:
    """Top-level configuration loaded from YAML."""

    measurement: MeasurementConfig
    witnesses: tuple[WitnessConfig, ...]
    log_level: str = "INFO"
    inference: "InferenceConfig" = field(default_factory=lambda: InferenceConfig())
    placement: "PlacementConfig" = field(default_factory=lambda: PlacementConfig())
    ipfs_cluster: IPFSClusterConfig = field(default_factory=IPFSClusterConfig)


@dataclass(frozen=True, slots=True)
class LatencyModelConfig:
    """Transparent assumed RTT-distance envelope parameters, in milliseconds/km."""

    baseline_rtt_ms: float = 8.0
    propagation_factor_ms_per_km: float = 0.01
    uncertainty_ms: float = 15.0
    uncertainty_per_100_km_ms: float = 2.0
    minimum_rtt_ms: float = 0.1

    def __post_init__(self) -> None:
        values = (
            self.baseline_rtt_ms,
            self.propagation_factor_ms_per_km,
            self.uncertainty_ms,
            self.uncertainty_per_100_km_ms,
            self.minimum_rtt_ms,
        )
        if any(not math.isfinite(value) for value in values):
            raise ValueError("latency model parameters must be finite")
        if self.baseline_rtt_ms < 0 or self.propagation_factor_ms_per_km < 0:
            raise ValueError("latency baseline and propagation factor must be non-negative")
        if self.uncertainty_ms <= 0 or self.uncertainty_per_100_km_ms < 0:
            raise ValueError("latency uncertainty must be positive and non-negative per 100 km")
        if self.minimum_rtt_ms <= 0:
            raise ValueError("minimum_rtt_ms must be positive")


@dataclass(frozen=True, slots=True)
class ReliabilityConfig:
    """Configurable evidence-quality weights; these are prototype assumptions."""

    minimum_samples: int = 10
    variability_scale_ms: float = 20.0
    sample_weight: float = 0.25
    stability_weight: float = 0.35
    loss_weight: float = 0.40

    def __post_init__(self) -> None:
        if self.minimum_samples < 1 or not math.isfinite(self.variability_scale_ms) or self.variability_scale_ms <= 0:
            raise ValueError("reliability sample and variability settings must be positive")
        weights = (self.sample_weight, self.stability_weight, self.loss_weight)
        if any(not math.isfinite(weight) or weight < 0 for weight in weights):
            raise ValueError("reliability weights must be finite and non-negative")
        if not math.isclose(sum(weights), 1.0, abs_tol=1e-9):
            raise ValueError("reliability weights must sum to 1")


@dataclass(frozen=True, slots=True)
class OutlierConfig:
    """Robust peer-group residual outlier settings."""

    robust_z_threshold: float = 3.5
    minimum_witnesses: int = 3
    scale_floor: float = 0.1

    def __post_init__(self) -> None:
        if not math.isfinite(self.robust_z_threshold) or self.robust_z_threshold <= 0:
            raise ValueError("outlier robust_z_threshold must be positive")
        if self.minimum_witnesses < 3:
            raise ValueError("outlier minimum_witnesses must be at least 3")
        if not math.isfinite(self.scale_floor) or self.scale_floor <= 0:
            raise ValueError("outlier scale_floor must be finite and positive")


@dataclass(frozen=True, slots=True)
class FusionConfig:
    """Evidence fusion support thresholds and outlier retention weight."""

    minimum_witnesses: int = 2
    outlier_weight_multiplier: float = 0.25

    def __post_init__(self) -> None:
        if self.minimum_witnesses < 1:
            raise ValueError("fusion minimum_witnesses must be at least 1")
        if not math.isfinite(self.outlier_weight_multiplier) or not 0 <= self.outlier_weight_multiplier <= 1:
            raise ValueError("outlier_weight_multiplier must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class DecisionConfig:
    """Evidence-score decision thresholds and short-distance caution parameters."""

    plausible_support_threshold: float = 0.65
    suspicious_contradiction_threshold: float = 0.65
    minimum_agreement: float = 0.55
    minimum_evidence_coverage: float = 0.45
    short_distance_km: float = 50.0

    def __post_init__(self) -> None:
        for name, value in (
            ("plausible_support_threshold", self.plausible_support_threshold),
            ("suspicious_contradiction_threshold", self.suspicious_contradiction_threshold),
            ("minimum_agreement", self.minimum_agreement),
            ("minimum_evidence_coverage", self.minimum_evidence_coverage),
        ):
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
        if not math.isfinite(self.short_distance_km) or self.short_distance_km < 0:
            raise ValueError("short_distance_km must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class InferenceConfig:
    """All Phase 3 model and decision parameters."""

    latency_model: LatencyModelConfig = field(default_factory=LatencyModelConfig)
    reliability: ReliabilityConfig = field(default_factory=ReliabilityConfig)
    outlier_detection: OutlierConfig = field(default_factory=OutlierConfig)
    fusion: FusionConfig = field(default_factory=FusionConfig)
    decision: DecisionConfig = field(default_factory=DecisionConfig)


@dataclass(frozen=True, slots=True)
class VerificationPolicyConfig:
    mode: str = "balanced"
    balanced_uncertain_multiplier: float = 0.5
    permissive_uncertain_multiplier: float = 0.5
    short_range_mode: str = "balanced"
    short_range_preference_multiplier: float = 0.5

    def __post_init__(self) -> None:
        if self.mode not in {"strict", "balanced", "permissive"}:
            raise ValueError("placement verification policy mode must be strict, balanced, or permissive")
        if self.short_range_mode not in {"strict", "balanced", "permissive"}:
            raise ValueError("short_range_mode must be strict, balanced, or permissive")
        for name, value in (
            ("balanced_uncertain_multiplier", self.balanced_uncertain_multiplier),
            ("permissive_uncertain_multiplier", self.permissive_uncertain_multiplier),
            ("short_range_preference_multiplier", self.short_range_preference_multiplier),
        ):
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class PlacementScoringConfig:
    confidence_weight: float = 0.30
    witness_agreement_weight: float = 0.25
    measurement_quality_weight: float = 0.20
    deterministic_hash_weight: float = 0.25

    def __post_init__(self) -> None:
        weights = (
            self.confidence_weight,
            self.witness_agreement_weight,
            self.measurement_quality_weight,
            self.deterministic_hash_weight,
        )
        if any(not math.isfinite(weight) or weight < 0 for weight in weights):
            raise ValueError("placement scoring weights must be finite and non-negative")
        if not math.isclose(sum(weights), 1.0, abs_tol=1e-9):
            raise ValueError("placement scoring weights must sum to 1")


@dataclass(frozen=True, slots=True)
class ReconfigurationConfig:
    enabled: bool = True
    minimize_movement: bool = True


@dataclass(frozen=True, slots=True)
class PlacementConfig:
    replication_factor: int = 3
    failure_domain_level: str = "building"
    verification_policy: VerificationPolicyConfig = field(default_factory=VerificationPolicyConfig)
    scoring: PlacementScoringConfig = field(default_factory=PlacementScoringConfig)
    reconfiguration: ReconfigurationConfig = field(default_factory=ReconfigurationConfig)

    def __post_init__(self) -> None:
        if self.replication_factor < 1:
            raise ValueError("placement.replication_factor must be at least 1")
        if not self.failure_domain_level.strip():
            raise ValueError("placement.failure_domain_level must not be empty")


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a mapping")
    return value


def load_config(path: str | Path) -> VerifierConfig:
    """Load and validate verifier settings from a YAML file."""

    config_path = Path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read configuration file: {config_path}") from exc
    root = _mapping(raw, "configuration")

    measurement_raw = _mapping(root.get("measurement", {}), "measurement")
    measurement = MeasurementConfig(
        samples=int(measurement_raw.get("samples", 50)),
        timeout_seconds=float(measurement_raw.get("timeout_seconds", 2.0)),
        interval_seconds=float(measurement_raw.get("interval_seconds", 0.2)),
    )

    witnesses_raw = root.get("witnesses", [])
    if not isinstance(witnesses_raw, list):
        raise ValueError("witnesses must be a list")
    witnesses: list[WitnessConfig] = []
    for index, item in enumerate(witnesses_raw):
        witness = _mapping(item, f"witnesses[{index}]")
        location_raw = _mapping(witness.get("location"), f"witnesses[{index}].location")
        try:
            witness_id = witness.get("witness_id", witness.get("id"))
            if witness_id is None:
                raise KeyError("witness_id")
            location = GeoLocation(
                latitude=float(location_raw["latitude"]),
                longitude=float(location_raw["longitude"]),
            )
            witnesses.append(
                WitnessConfig(
                    witness_id=str(witness_id),
                    host=str(witness["host"]),
                    location=location,
                    known_failure_domain=(
                        str(witness["known_failure_domain"])
                        if witness.get("known_failure_domain") is not None
                        else None
                    ),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid witness configuration at index {index}") from exc

    log_level = str(root.get("log_level", "INFO")).upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError("log_level must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")
    inference_raw = _mapping(root.get("inference", {}), "inference")
    latency_raw = _mapping(inference_raw.get("latency_model", {}), "inference.latency_model")
    reliability_raw = _mapping(inference_raw.get("reliability", {}), "inference.reliability")
    outlier_raw = _mapping(inference_raw.get("outlier_detection", {}), "inference.outlier_detection")
    fusion_raw = _mapping(inference_raw.get("fusion", {}), "inference.fusion")
    decision_raw = _mapping(inference_raw.get("decision", {}), "inference.decision")
    inference = InferenceConfig(
        latency_model=LatencyModelConfig(**latency_raw),
        reliability=ReliabilityConfig(**reliability_raw),
        outlier_detection=OutlierConfig(**outlier_raw),
        fusion=FusionConfig(**fusion_raw),
        decision=DecisionConfig(**decision_raw),
    )
    placement_raw = _mapping(root.get("placement", {}), "placement")
    policy_raw = _mapping(placement_raw.get("verification_policy", {}), "placement.verification_policy")
    scoring_raw = _mapping(placement_raw.get("scoring", {}), "placement.scoring")
    reconfiguration_raw = _mapping(placement_raw.get("reconfiguration", {}), "placement.reconfiguration")
    placement = PlacementConfig(
        replication_factor=int(placement_raw.get("replication_factor", 3)),
        failure_domain_level=str(placement_raw.get("failure_domain_level", "building")),
        verification_policy=VerificationPolicyConfig(**policy_raw),
        scoring=PlacementScoringConfig(**scoring_raw),
        reconfiguration=ReconfigurationConfig(**reconfiguration_raw),
    )
    cluster_raw = _mapping(root.get("ipfs_cluster", {}), "ipfs_cluster")
    ipfs_cluster = IPFSClusterConfig(
        enabled=bool(cluster_raw.get("enabled", False)),
        base_url=str(cluster_raw.get("base_url", "http://127.0.0.1:9094")),
        dry_run=bool(cluster_raw.get("dry_run", True)),
        request_timeout_seconds=float(cluster_raw.get("request_timeout_seconds", 2.0)),
    )
    return VerifierConfig(measurement, tuple(witnesses), log_level, inference, placement, ipfs_cluster)
