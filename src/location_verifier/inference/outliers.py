"""Robust group-level outlier flags that preserve anomalous evidence."""

from __future__ import annotations

from dataclasses import dataclass
import math
from statistics import median
from typing import Sequence

from ..config import OutlierConfig
from ..models import MeasurementObservation
from .residuals import WitnessResidual


@dataclass(frozen=True, slots=True)
class OutlierAssessment:
    """An evidence-pattern outlier flag, never an accusation of malicious intent."""

    witness_id: str
    is_outlier: bool
    outlier_score: float | None
    reason: str
    retained_for_analysis: bool = True

    def __post_init__(self) -> None:
        if not self.witness_id.strip():
            raise ValueError("witness_id must not be empty")
        if self.outlier_score is not None and (
            not math.isfinite(self.outlier_score) or self.outlier_score < 0
        ):
            raise ValueError("outlier_score must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class SampleOutlierAssessment:
    """Robust single-sample RTT flag; index points into the original observations."""

    observation_index: int
    is_outlier: bool
    robust_z_score: float | None
    retained_for_analysis: bool = True

    def __post_init__(self) -> None:
        if self.observation_index < 0:
            raise ValueError("observation_index must be non-negative")
        if self.robust_z_score is not None and (
            not math.isfinite(self.robust_z_score) or self.robust_z_score < 0
        ):
            raise ValueError("robust_z_score must be finite and non-negative")


def detect_sample_outliers(
    observations: Sequence[MeasurementObservation],
    config: OutlierConfig,
) -> tuple[SampleOutlierAssessment, ...]:
    """Flag extreme RTT samples by median/MAD without deleting them."""

    successful = [
        (index, item.rtt_ms)
        for index, item in enumerate(observations)
        if item.rtt_ms is not None
    ]
    if len(successful) < 3:
        return tuple(
            SampleOutlierAssessment(index, False, None)
            for index, item in enumerate(observations)
            if item.rtt_ms is not None
        )
    values = [value for _, value in successful]
    center = median(values)
    mad = median([abs(value - center) for value in values])
    scale = max(mad, config.scale_floor)
    output: list[SampleOutlierAssessment] = []
    for index, value in successful:
        score = 0.6745 * abs(value - center) / scale
        output.append(
            SampleOutlierAssessment(
                index,
                score > config.robust_z_threshold,
                score,
            )
        )
    return tuple(output)


def detect_witness_outliers(
    residuals: Sequence[WitnessResidual],
    config: OutlierConfig,
) -> tuple[OutlierAssessment, ...]:
    """Flag unusually distant normalized residuals using a median/MAD robust z.

    All records remain retained. With fewer than the configured minimum usable
    witnesses, the group is too small to label any witness an outlier.
    """

    usable = [item for item in residuals if item.normalized_residual is not None]
    if len(usable) < config.minimum_witnesses:
        return tuple(
            OutlierAssessment(item.witness_id, False, None, "insufficient witness group size")
            for item in residuals
        )
    values = [item.normalized_residual for item in usable]
    center = median(values)
    mad = median([abs(value - center) for value in values])
    scale = max(mad, config.scale_floor)
    scores = {
        item.witness_id: abs(0.6745 * (item.normalized_residual - center) / scale)
        for item in usable
    }
    output: list[OutlierAssessment] = []
    for item in residuals:
        score = scores.get(item.witness_id)
        if score is None:
            output.append(
                OutlierAssessment(item.witness_id, False, None, "no usable RTT residual")
            )
        elif score > config.robust_z_threshold:
            output.append(
                OutlierAssessment(
                    item.witness_id,
                    True,
                    score,
                    "normalized residual differs from the witness-group median",
                )
            )
        else:
            output.append(OutlierAssessment(item.witness_id, False, score, "within group pattern"))
    return tuple(output)
