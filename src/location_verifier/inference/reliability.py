"""Interpretable evidence quality and witness reliability components."""

from __future__ import annotations

from dataclasses import dataclass
import math

from ..config import ReliabilityConfig
from ..measurement.collector import WitnessEvidence


@dataclass(frozen=True, slots=True)
class ReliabilityAssessment:
    """Measurement quality and adjusted witness reliability, each in [0, 1]."""

    witness_id: str
    sample_completeness: float
    stability: float
    loss_quality: float
    measurement_quality: float
    prior_reliability: float
    effective_reliability: float

    def __post_init__(self) -> None:
        for name, value in (
            ("sample_completeness", self.sample_completeness),
            ("stability", self.stability),
            ("loss_quality", self.loss_quality),
            ("measurement_quality", self.measurement_quality),
            ("prior_reliability", self.prior_reliability),
            ("effective_reliability", self.effective_reliability),
        ):
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")


def assess_reliability(
    evidence: WitnessEvidence,
    config: ReliabilityConfig,
) -> ReliabilityAssessment:
    """Combine sample sufficiency, RTT stability, loss, and declared reliability.

    Measurement quality is the configured weighted arithmetic mean of completeness,
    stability, and timeout quality. Effective reliability multiplies it by the
    witness's prior score; no witness is discarded by this calculation.
    """

    features = evidence.features
    completeness = min(features.successful_count / config.minimum_samples, 1.0)
    if features.median_rtt_ms is None:
        stability = 0.0
    else:
        variability = (features.mad_rtt_ms or 0.0) + (features.jitter_ms or 0.0) / 2
        stability = 1.0 / (1.0 + variability / config.variability_scale_ms)
    loss_quality = 1.0 - features.packet_loss_rate
    quality = (
        config.sample_weight * completeness
        + config.stability_weight * stability
        + config.loss_weight * loss_quality
    )
    prior = evidence.witness.reliability_score
    return ReliabilityAssessment(
        witness_id=evidence.witness.witness_id,
        sample_completeness=completeness,
        stability=stability,
        loss_quality=loss_quality,
        measurement_quality=quality,
        prior_reliability=prior,
        effective_reliability=prior * quality,
    )
