"""Per-witness comparison between observed RTT features and expected range."""

from __future__ import annotations

from dataclasses import dataclass
import math

from ..measurement.collector import WitnessEvidence
from .latency_model import ExpectedLatency


@dataclass(frozen=True, slots=True)
class WitnessResidual:
    """Explainable witness-level residual and measurement feature snapshot."""

    witness_id: str
    target_peer_id: str
    distance_km: float
    observed_median_rtt_ms: float | None
    expected_rtt_ms: float
    expected_lower_ms: float
    expected_upper_ms: float
    residual_ms: float | None
    normalized_residual: float | None
    mad_rtt_ms: float | None
    jitter_ms: float | None
    packet_loss_rate: float
    sample_count: int
    successful_count: int
    within_expected_range: bool | None
    consistency_score: float | None

    def __post_init__(self) -> None:
        if not self.witness_id.strip() or not self.target_peer_id.strip():
            raise ValueError("witness and target identities must not be empty")
        if not math.isfinite(self.distance_km) or self.distance_km < 0:
            raise ValueError("distance_km must be finite and non-negative")
        if self.sample_count < 0 or not 0 <= self.successful_count <= self.sample_count:
            raise ValueError("residual sample counts are inconsistent")
        if not math.isfinite(self.packet_loss_rate) or not 0 <= self.packet_loss_rate <= 1:
            raise ValueError("packet_loss_rate must be between 0 and 1")
        residual_values = (self.residual_ms, self.normalized_residual, self.consistency_score)
        if self.observed_median_rtt_ms is None and any(value is not None for value in residual_values):
            raise ValueError("missing observed RTT must have unavailable residual features")
        if self.observed_median_rtt_ms is not None and any(value is None for value in residual_values):
            raise ValueError("observed RTT requires residual and consistency features")
        for value in (
            self.observed_median_rtt_ms,
            self.expected_rtt_ms,
            self.expected_lower_ms,
            self.expected_upper_ms,
            self.residual_ms,
            self.normalized_residual,
            self.mad_rtt_ms,
            self.jitter_ms,
            self.consistency_score,
        ):
            if value is not None and not math.isfinite(value):
                raise ValueError("residual features must be finite")
        if self.consistency_score is not None and not 0 <= self.consistency_score <= 1:
            raise ValueError("consistency_score must be between 0 and 1")


def analyze_residual(
    evidence: WitnessEvidence,
    distance_km: float,
    expected: ExpectedLatency,
) -> WitnessResidual:
    """Calculate a continuous consistency score without making a binary decision."""

    if not math.isfinite(distance_km) or distance_km < 0:
        raise ValueError("distance_km must be finite and non-negative")
    features = evidence.features
    observed = features.median_rtt_ms
    if observed is None:
        return WitnessResidual(
            witness_id=evidence.witness.witness_id,
            target_peer_id=evidence.target_peer_id,
            distance_km=distance_km,
            observed_median_rtt_ms=None,
            expected_rtt_ms=expected.expected_rtt_ms,
            expected_lower_ms=expected.lower_bound_ms,
            expected_upper_ms=expected.upper_bound_ms,
            residual_ms=None,
            normalized_residual=None,
            mad_rtt_ms=features.mad_rtt_ms,
            jitter_ms=features.jitter_ms,
            packet_loss_rate=features.packet_loss_rate,
            sample_count=features.sample_count,
            successful_count=features.successful_count,
            within_expected_range=None,
            consistency_score=None,
        )

    residual = observed - expected.expected_rtt_ms
    tolerance_excess = max(
        expected.lower_bound_ms - observed,
        observed - expected.upper_bound_ms,
        0.0,
    )
    observed_variability = max(
        features.mad_rtt_ms or 0.0,
        (features.jitter_ms or 0.0) / math.sqrt(2),
    )
    residual_scale = math.hypot(expected.model_uncertainty_ms, observed_variability)
    normalized = math.copysign(tolerance_excess / residual_scale, residual) if tolerance_excess else 0.0
    consistency = math.exp(-0.5 * normalized * normalized)
    return WitnessResidual(
        witness_id=evidence.witness.witness_id,
        target_peer_id=evidence.target_peer_id,
        distance_km=distance_km,
        observed_median_rtt_ms=observed,
        expected_rtt_ms=expected.expected_rtt_ms,
        expected_lower_ms=expected.lower_bound_ms,
        expected_upper_ms=expected.upper_bound_ms,
        residual_ms=residual,
        normalized_residual=normalized,
        mad_rtt_ms=features.mad_rtt_ms,
        jitter_ms=features.jitter_ms,
        packet_loss_rate=features.packet_loss_rate,
        sample_count=features.sample_count,
        successful_count=features.successful_count,
        within_expected_range=expected.lower_bound_ms <= observed <= expected.upper_bound_ms,
        consistency_score=consistency,
    )
