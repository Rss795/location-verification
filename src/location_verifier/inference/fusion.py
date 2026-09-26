"""Reliability-weighted multi-witness evidence fusion."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence

from ..config import FusionConfig
from .outliers import OutlierAssessment
from .reliability import ReliabilityAssessment
from .residuals import WitnessResidual


@dataclass(frozen=True, slots=True)
class WitnessContribution:
    """One retained witness's calculated inference contribution."""

    residual: WitnessResidual
    reliability: ReliabilityAssessment
    outlier: OutlierAssessment
    fusion_weight: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.fusion_weight) or not 0 <= self.fusion_weight <= 1:
            raise ValueError("fusion_weight must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class FusedEvidence:
    """Aggregate support, contradiction, agreement, coverage, and score uncertainty."""

    support_score: float
    contradiction_score: float
    witness_agreement: float
    evidence_coverage: float
    confidence: float
    uncertainty: float
    usable_witness_count: int
    contributions: tuple[WitnessContribution, ...]

    def __post_init__(self) -> None:
        for name, value in (
            ("support_score", self.support_score),
            ("contradiction_score", self.contradiction_score),
            ("witness_agreement", self.witness_agreement),
            ("evidence_coverage", self.evidence_coverage),
            ("confidence", self.confidence),
            ("uncertainty", self.uncertainty),
        ):
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.usable_witness_count < 0:
            raise ValueError("usable_witness_count must be non-negative")
        if not math.isclose(self.confidence + self.uncertainty, 1.0, abs_tol=1e-9):
            raise ValueError("confidence and uncertainty must sum to 1")


def fuse_evidence(
    residuals: Sequence[WitnessResidual],
    reliabilities: Sequence[ReliabilityAssessment],
    outliers: Sequence[OutlierAssessment],
    config: FusionConfig,
) -> FusedEvidence:
    """Fuse per-witness consistency scores using reliability and robust down-weighting.

    Scores are evidence-strength indices, not calibrated probabilities. Outliers
    receive a configurable reduced weight, but their records are never removed.
    """

    reliability_by_id = {item.witness_id: item for item in reliabilities}
    outlier_by_id = {item.witness_id: item for item in outliers}
    contributions: list[WitnessContribution] = []
    for residual in residuals:
        reliability = reliability_by_id[residual.witness_id]
        outlier = outlier_by_id[residual.witness_id]
        base_weight = reliability.effective_reliability
        weight = base_weight * (
            config.outlier_weight_multiplier if outlier.is_outlier else 1.0
        )
        contributions.append(WitnessContribution(residual, reliability, outlier, weight))

    usable = [
        item for item in contributions
        if item.residual.consistency_score is not None and item.fusion_weight > 0
    ]
    total_weight = sum(item.fusion_weight for item in usable)
    if total_weight <= 0:
        return FusedEvidence(0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0, tuple(contributions))

    support = sum(
        item.fusion_weight * item.residual.consistency_score for item in usable
    ) / total_weight
    contradiction = 1.0 - support
    variance = sum(
        item.fusion_weight * (item.residual.consistency_score - support) ** 2
        for item in usable
    ) / total_weight
    agreement = max(0.0, 1.0 - math.sqrt(variance))
    count_coverage = min(len(usable) / config.minimum_witnesses, 1.0)
    mean_effective_reliability = sum(
        item.fusion_weight for item in usable
    ) / len(usable)
    coverage = count_coverage * mean_effective_reliability
    confidence = coverage * agreement * max(support, contradiction)
    confidence = min(max(confidence, 0.0), 1.0)
    return FusedEvidence(
        support_score=support,
        contradiction_score=contradiction,
        witness_agreement=agreement,
        evidence_coverage=coverage,
        confidence=confidence,
        uncertainty=1.0 - confidence,
        usable_witness_count=len(usable),
        contributions=tuple(contributions),
    )
