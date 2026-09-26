"""Repeated probe orchestration and witness-level evidence records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import logging
import math
import time
from typing import Callable

from ..models import (
    MeasurementFailureReason,
    MeasurementObservation,
    Witness,
)
from .ping import PingResult, PingSource, PingStatus, RealPingSource, validate_target
from .statistics import MeasurementFeatures, extract_features

logger = logging.getLogger(__name__)


class MeasurementBatchStatus(StrEnum):
    """Collection outcome; these statuses are not location judgments."""

    COMPLETE = "COMPLETE"
    PARTIAL_MEASUREMENTS = "PARTIAL_MEASUREMENTS"
    TARGET_UNREACHABLE = "TARGET_UNREACHABLE"
    NO_SUCCESSFUL_MEASUREMENTS = "NO_SUCCESSFUL_MEASUREMENTS"


class MeasurementCollectionError(RuntimeError):
    """Fatal collection setup/runtime error with a machine-readable ping status."""

    def __init__(self, status: PingStatus, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, slots=True)
class MeasurementBatch:
    """Raw observations and derived descriptive features for one witness-target pair."""

    witness_id: str
    target_peer_id: str
    host: str
    started_at: datetime
    completed_at: datetime
    observations: tuple[MeasurementObservation, ...]
    features: MeasurementFeatures
    status: MeasurementBatchStatus

    def __post_init__(self) -> None:
        if not self.witness_id.strip() or not self.target_peer_id.strip():
            raise ValueError("witness_id and target_peer_id must not be empty")
        validate_target(self.host)
        for timestamp in (self.started_at, self.completed_at):
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError("batch timestamps must be timezone-aware")
        if self.completed_at < self.started_at:
            raise ValueError("completed_at must not precede started_at")
        if not self.observations:
            raise ValueError("a measurement batch must contain observations")
        if self.features.sample_count != len(self.observations):
            raise ValueError("feature sample_count must match observations")


@dataclass(frozen=True, slots=True)
class WitnessEvidence:
    """Witness identity and source location linked to raw batch evidence."""

    witness: Witness
    target_peer_id: str
    batch: MeasurementBatch

    def __post_init__(self) -> None:
        if self.batch.witness_id != self.witness.witness_id:
            raise ValueError("batch witness_id must match witness")
        if self.batch.target_peer_id != self.target_peer_id:
            raise ValueError("batch target_peer_id must match evidence target")

    @property
    def observations(self) -> tuple[MeasurementObservation, ...]:
        """Retain direct access to the raw observations for downstream analysis."""

        return self.batch.observations

    @property
    def features(self) -> MeasurementFeatures:
        """Return descriptive features without making a consistency judgment."""

        return self.batch.features


def _failure_reason(status: PingStatus) -> MeasurementFailureReason:
    return {
        PingStatus.TIMEOUT: MeasurementFailureReason.TIMEOUT,
        PingStatus.TARGET_UNREACHABLE: MeasurementFailureReason.TARGET_UNREACHABLE,
        PingStatus.MALFORMED_OUTPUT: MeasurementFailureReason.MALFORMED_OUTPUT,
        PingStatus.COMMAND_ERROR: MeasurementFailureReason.COMMAND_ERROR,
    }[status]


def _batch_status(observations: tuple[MeasurementObservation, ...]) -> MeasurementBatchStatus:
    successes = sum(observation.rtt_ms is not None for observation in observations)
    if successes == len(observations):
        return MeasurementBatchStatus.COMPLETE
    if successes:
        return MeasurementBatchStatus.PARTIAL_MEASUREMENTS
    if all(
        observation.failure_reason is MeasurementFailureReason.TARGET_UNREACHABLE
        for observation in observations
    ):
        return MeasurementBatchStatus.TARGET_UNREACHABLE
    return MeasurementBatchStatus.NO_SUCCESSFUL_MEASUREMENTS


def collect_measurements(
    host: str,
    samples: int = 50,
    timeout_seconds: float = 2.0,
    interval_seconds: float = 0.2,
    *,
    source: PingSource | None = None,
    witness_id: str = "local",
    target_peer_id: str = "target",
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], datetime] | None = None,
) -> MeasurementBatch:
    """Collect exactly ``samples`` probes, waiting only between consecutive probes."""

    try:
        validate_target(host)
    except ValueError as exc:
        raise MeasurementCollectionError(PingStatus.INVALID_TARGET, str(exc)) from exc
    if isinstance(samples, bool) or not isinstance(samples, int) or samples < 1:
        raise ValueError("samples must be a positive integer")
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be finite and positive")
    if not math.isfinite(interval_seconds) or interval_seconds < 0:
        raise ValueError("interval_seconds must be finite and non-negative")
    if not witness_id.strip() or not target_peer_id.strip():
        raise ValueError("witness_id and target_peer_id must not be empty")

    active_source = source or RealPingSource()
    timestamp = clock or (lambda: datetime.now(timezone.utc))
    started_at = timestamp()
    logger.info(
        "Starting measurements witness=%s target=%s samples=%d",
        witness_id,
        target_peer_id,
        samples,
    )
    collected: list[MeasurementObservation] = []
    fatal_statuses = {
        PingStatus.PING_COMMAND_UNAVAILABLE,
        PingStatus.INVALID_TARGET,
    }
    for index in range(samples):
        result: PingResult = active_source.ping_once(host, timeout_seconds)
        if result.status in fatal_statuses:
            logger.error(
                "Measurement stopped witness=%s target=%s status=%s",
                witness_id,
                target_peer_id,
                result.status.value,
            )
            raise MeasurementCollectionError(
                result.status,
                result.detail or f"measurement failed with status {result.status.value}",
            )
        if result.status is PingStatus.SUCCESS:
            collected.append(MeasurementObservation(timestamp(), result.rtt_ms))
        elif result.status is PingStatus.TIMEOUT:
            logger.warning("Ping timeout witness=%s target=%s", witness_id, target_peer_id)
            collected.append(
                MeasurementObservation(
                    timestamp(),
                    None,
                    timed_out=True,
                    failure_reason=MeasurementFailureReason.TIMEOUT,
                )
            )
        else:
            collected.append(
                MeasurementObservation(
                    timestamp(),
                    None,
                    failure_reason=_failure_reason(result.status),
                )
            )
        if index + 1 < samples and interval_seconds:
            sleeper(interval_seconds)

    observations = tuple(collected)
    completed_at = timestamp()
    features = extract_features(observations)
    status = _batch_status(observations)
    logger.info(
        "Completed measurements witness=%s target=%s status=%s successes=%d/%d",
        witness_id,
        target_peer_id,
        status.value,
        features.successful_count,
        features.sample_count,
    )
    return MeasurementBatch(
        witness_id=witness_id,
        target_peer_id=target_peer_id,
        host=host,
        started_at=started_at,
        completed_at=completed_at,
        observations=observations,
        features=features,
        status=status,
    )
