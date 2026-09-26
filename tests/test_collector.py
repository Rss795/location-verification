from datetime import datetime, timezone

import pytest

from location_verifier.measurement.collector import (
    MeasurementBatchStatus,
    MeasurementCollectionError,
    WitnessEvidence,
    collect_measurements,
)
from location_verifier.measurement.ping import PingResult, PingStatus
from location_verifier.models import GeoLocation, Witness


class ScriptedSource:
    def __init__(self, results: list[PingResult]) -> None:
        self.results = iter(results)
        self.calls: list[tuple[str, float]] = []

    def ping_once(self, host: str, timeout_seconds: float) -> PingResult:
        self.calls.append((host, timeout_seconds))
        return next(self.results)


def test_collector_observes_exact_sample_count_and_interval() -> None:
    source = ScriptedSource(
        [
            PingResult(PingStatus.SUCCESS, 10.0),
            PingResult(PingStatus.TIMEOUT),
            PingResult(PingStatus.SUCCESS, 14.0),
        ]
    )
    sleeps: list[float] = []
    fixed_time = datetime(2026, 9, 26, tzinfo=timezone.utc)

    batch = collect_measurements(
        "example.org",
        samples=3,
        timeout_seconds=0.7,
        interval_seconds=0.05,
        source=source,
        witness_id="w1",
        target_peer_id="peer-1",
        sleeper=sleeps.append,
        clock=lambda: fixed_time,
    )

    assert len(batch.observations) == 3
    assert len(source.calls) == 3
    assert all(call == ("example.org", 0.7) for call in source.calls)
    assert sleeps == [0.05, 0.05]
    assert batch.status is MeasurementBatchStatus.PARTIAL_MEASUREMENTS
    assert batch.features.timeout_count == 1
    assert batch.observations[0].timestamp.tzinfo is timezone.utc
    assert batch.started_at == batch.completed_at == fixed_time


def test_collector_classifies_all_unreachable_target() -> None:
    batch = collect_measurements(
        "example.org",
        samples=2,
        interval_seconds=0,
        source=ScriptedSource(
            [PingResult(PingStatus.TARGET_UNREACHABLE) for _ in range(2)]
        ),
    )

    assert batch.status is MeasurementBatchStatus.TARGET_UNREACHABLE
    assert batch.features.successful_count == 0
    assert batch.features.median_rtt_ms is None


def test_collector_classifies_timeout_only_batch() -> None:
    batch = collect_measurements(
        "example.org",
        samples=2,
        interval_seconds=0,
        source=ScriptedSource([PingResult(PingStatus.TIMEOUT) for _ in range(2)]),
    )

    assert batch.status is MeasurementBatchStatus.NO_SUCCESSFUL_MEASUREMENTS
    assert batch.features.packet_loss_rate == 1.0


def test_collector_fails_fast_for_missing_ping_command() -> None:
    with pytest.raises(MeasurementCollectionError) as error:
        collect_measurements(
            "example.org",
            samples=3,
            source=ScriptedSource([PingResult(PingStatus.PING_COMMAND_UNAVAILABLE)]),
        )

    assert error.value.status is PingStatus.PING_COMMAND_UNAVAILABLE


def test_collector_rejects_invalid_target_and_settings() -> None:
    with pytest.raises(MeasurementCollectionError) as error:
        collect_measurements("bad host", samples=1)
    assert error.value.status is PingStatus.INVALID_TARGET
    with pytest.raises(ValueError, match="positive integer"):
        collect_measurements("example.org", samples=0)


def test_witness_evidence_links_witness_and_batch() -> None:
    batch = collect_measurements(
        "example.org",
        samples=1,
        interval_seconds=0,
        source=ScriptedSource([PingResult(PingStatus.SUCCESS, 11.0)]),
        witness_id="w1",
        target_peer_id="peer-1",
    )
    evidence = WitnessEvidence(Witness("w1", GeoLocation(10, 20)), "peer-1", batch)

    assert evidence.observations == batch.observations
    assert evidence.features == batch.features
    with pytest.raises(ValueError, match="witness_id"):
        WitnessEvidence(Witness("w2", GeoLocation(10, 20)), "peer-1", batch)
