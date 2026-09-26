"""Transparent distance-conditioned expected RTT envelope (engineering model)."""

from __future__ import annotations

from dataclasses import dataclass
import math

from ..config import LatencyModelConfig


@dataclass(frozen=True, slots=True)
class ExpectedLatency:
    """Expected RTT center, tolerance interval, and its half-width uncertainty."""

    expected_rtt_ms: float
    lower_bound_ms: float
    upper_bound_ms: float
    model_uncertainty_ms: float

    def __post_init__(self) -> None:
        values = (
            self.expected_rtt_ms,
            self.lower_bound_ms,
            self.upper_bound_ms,
            self.model_uncertainty_ms,
        )
        if any(not math.isfinite(value) or value < 0 for value in values):
            raise ValueError("expected latency values must be finite and non-negative")
        if self.lower_bound_ms > self.expected_rtt_ms or self.expected_rtt_ms > self.upper_bound_ms:
            raise ValueError("expected RTT must be within its bounds")
        if self.model_uncertainty_ms <= 0:
            raise ValueError("model uncertainty must be positive")


class LatencyModel:
    """A configurable baseline-plus-propagation model with a broad uncertainty band."""

    def __init__(self, config: LatencyModelConfig) -> None:
        self.config = config

    def predict(self, distance_km: float) -> ExpectedLatency:
        """Estimate an RTT range; parameters are explicit prototype assumptions."""

        if not math.isfinite(distance_km) or distance_km < 0:
            raise ValueError("distance_km must be finite and non-negative")
        expected = max(
            self.config.minimum_rtt_ms,
            self.config.baseline_rtt_ms
            + self.config.propagation_factor_ms_per_km * distance_km,
        )
        uncertainty = (
            self.config.uncertainty_ms
            + self.config.uncertainty_per_100_km_ms * (distance_km / 100.0)
        )
        return ExpectedLatency(
            expected_rtt_ms=expected,
            lower_bound_ms=max(self.config.minimum_rtt_ms, expected - uncertainty),
            upper_bound_ms=expected + uncertainty,
            model_uncertainty_ms=uncertainty,
        )
