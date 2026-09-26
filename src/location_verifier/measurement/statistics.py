"""Reproducible descriptive features for raw RTT observations."""

from __future__ import annotations

from dataclasses import dataclass
import math
from statistics import fmean, median, pstdev
from typing import Iterable

from ..models import MeasurementObservation


@dataclass(frozen=True, slots=True)
class MeasurementFeatures:
    """Immutable summary of a batch; absent RTT features remain ``None``."""

    sample_count: int
    successful_count: int
    timeout_count: int
    packet_loss_rate: float
    minimum_rtt_ms: float | None
    maximum_rtt_ms: float | None
    mean_rtt_ms: float | None
    median_rtt_ms: float | None
    standard_deviation_ms: float | None
    p50_rtt_ms: float | None
    p75_rtt_ms: float | None
    p90_rtt_ms: float | None
    p95_rtt_ms: float | None
    jitter_ms: float | None
    mad_rtt_ms: float | None
    failure_count: int

    def __post_init__(self) -> None:
        if self.sample_count < 0 or not 0 <= self.successful_count <= self.sample_count:
            raise ValueError("sample and successful counts are inconsistent")
        if not 0 <= self.timeout_count <= self.sample_count:
            raise ValueError("timeout_count must be within the sample count")
        if not 0 <= self.failure_count <= self.sample_count:
            raise ValueError("failure_count must be within the sample count")
        if self.failure_count != self.sample_count - self.successful_count:
            raise ValueError("failure_count must equal unsuccessful samples")
        if self.timeout_count > self.failure_count:
            raise ValueError("timeout_count cannot exceed failure_count")
        if not math.isfinite(self.packet_loss_rate) or not 0 <= self.packet_loss_rate <= 1:
            raise ValueError("packet_loss_rate must be between 0 and 1")
        expected_loss = (
            self.timeout_count / self.sample_count if self.sample_count else 1.0
        )
        if not math.isclose(self.packet_loss_rate, expected_loss):
            raise ValueError("packet_loss_rate must equal timeout_count / sample_count")
        rtt_features = (
            self.minimum_rtt_ms,
            self.maximum_rtt_ms,
            self.mean_rtt_ms,
            self.median_rtt_ms,
            self.standard_deviation_ms,
            self.p50_rtt_ms,
            self.p75_rtt_ms,
            self.p90_rtt_ms,
            self.p95_rtt_ms,
            self.jitter_ms,
            self.mad_rtt_ms,
        )
        if self.successful_count == 0 and any(value is not None for value in rtt_features):
            raise ValueError("RTT features must be unavailable when there are no successes")
        if self.successful_count > 0 and any(value is None for value in rtt_features):
            raise ValueError("RTT features must be populated when successes exist")
        if any(value is not None and (not math.isfinite(value) or value < 0) for value in rtt_features):
            raise ValueError("RTT features must be finite and non-negative")


def _linear_percentile(values: list[float], percentile: float) -> float:
    """Compute NumPy's default linear percentile using rank (n - 1) * q."""

    if len(values) == 1:
        return values[0]
    rank = (len(values) - 1) * percentile
    lower_index = math.floor(rank)
    upper_index = math.ceil(rank)
    fraction = rank - lower_index
    return values[lower_index] + fraction * (values[upper_index] - values[lower_index])


def extract_features(
    observations: Iterable[MeasurementObservation],
) -> MeasurementFeatures:
    """Summarize RTTs, timeouts, and other failed observations without inference."""

    items = tuple(observations)
    values = [item.rtt_ms for item in items if item.rtt_ms is not None]
    successful_count = len(values)
    timeout_count = sum(item.timed_out for item in items)
    failure_count = len(items) - successful_count
    packet_loss_rate = timeout_count / len(items) if items else 1.0
    if not values:
        return MeasurementFeatures(
            sample_count=len(items),
            successful_count=0,
            timeout_count=timeout_count,
            packet_loss_rate=packet_loss_rate,
            minimum_rtt_ms=None,
            maximum_rtt_ms=None,
            mean_rtt_ms=None,
            median_rtt_ms=None,
            standard_deviation_ms=None,
            p50_rtt_ms=None,
            p75_rtt_ms=None,
            p90_rtt_ms=None,
            p95_rtt_ms=None,
            jitter_ms=None,
            mad_rtt_ms=None,
            failure_count=failure_count,
        )

    sorted_values = sorted(values)
    center = median(sorted_values)
    differences = [
        abs(right - left)
        for left, right in zip(values, values[1:])
    ]
    return MeasurementFeatures(
        sample_count=len(items),
        successful_count=successful_count,
        timeout_count=timeout_count,
        packet_loss_rate=packet_loss_rate,
        minimum_rtt_ms=sorted_values[0],
        maximum_rtt_ms=sorted_values[-1],
        mean_rtt_ms=fmean(values),
        median_rtt_ms=center,
        standard_deviation_ms=pstdev(values),
        p50_rtt_ms=_linear_percentile(sorted_values, 0.50),
        p75_rtt_ms=_linear_percentile(sorted_values, 0.75),
        p90_rtt_ms=_linear_percentile(sorted_values, 0.90),
        p95_rtt_ms=_linear_percentile(sorted_values, 0.95),
        jitter_ms=fmean(differences) if differences else 0.0,
        mad_rtt_ms=median([abs(value - center) for value in values]),
        failure_count=failure_count,
    )
