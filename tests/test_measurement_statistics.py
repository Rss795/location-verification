from datetime import datetime, timezone

import pytest

from location_verifier.measurement.statistics import MeasurementFeatures, extract_features
from location_verifier.models import MeasurementFailureReason, MeasurementObservation


def observation(rtt: float | None, *, timeout: bool = False) -> MeasurementObservation:
    return MeasurementObservation(
        datetime.now(timezone.utc),
        rtt,
        timed_out=timeout,
        failure_reason=(MeasurementFailureReason.TIMEOUT if timeout else None),
    )


def test_extracts_descriptive_statistics_and_linear_percentiles() -> None:
    features = extract_features([observation(10), observation(20), observation(30), observation(40)])

    assert features.sample_count == 4
    assert features.successful_count == 4
    assert features.timeout_count == 0
    assert features.packet_loss_rate == 0
    assert features.minimum_rtt_ms == 10
    assert features.maximum_rtt_ms == 40
    assert features.mean_rtt_ms == 25
    assert features.median_rtt_ms == 25
    assert features.p50_rtt_ms == 25
    assert features.p75_rtt_ms == 32.5
    assert features.p90_rtt_ms == 37
    assert features.p95_rtt_ms == 38.5
    assert features.jitter_ms == 10
    assert features.mad_rtt_ms == 10


def test_jitter_uses_consecutive_successful_observations() -> None:
    features = extract_features(
        [observation(10), observation(None, timeout=True), observation(25)]
    )

    assert features.jitter_ms == 15
    assert features.timeout_count == 1
    assert features.packet_loss_rate == pytest.approx(1 / 3)


def test_all_timeouts_have_no_fabricated_rtt_features() -> None:
    features = extract_features([observation(None, timeout=True) for _ in range(3)])

    assert features.sample_count == 3
    assert features.successful_count == 0
    assert features.timeout_count == 3
    assert features.packet_loss_rate == 1.0
    assert features.median_rtt_ms is None
    assert features.p95_rtt_ms is None
    assert features.jitter_ms is None
    assert features.mad_rtt_ms is None


def test_single_success_and_empty_batch_are_defined() -> None:
    single = extract_features([observation(14.0)])
    empty = extract_features([])

    assert single.jitter_ms == 0.0
    assert single.mad_rtt_ms == 0
    assert empty.sample_count == 0
    assert empty.packet_loss_rate == 1.0
    assert empty.mean_rtt_ms is None


def test_packet_loss_counts_timeouts_not_other_failure_types() -> None:
    unreachable = MeasurementObservation(
        datetime.now(timezone.utc),
        None,
        failure_reason=MeasurementFailureReason.TARGET_UNREACHABLE,
    )
    features = extract_features([unreachable, observation(None, timeout=True)])

    assert features.failure_count == 2
    assert features.timeout_count == 1
    assert features.packet_loss_rate == 0.5


def test_feature_model_rejects_impossible_counts() -> None:
    with pytest.raises(ValueError, match="sample and successful counts"):
        MeasurementFeatures(
            sample_count=1,
            successful_count=2,
            timeout_count=0,
            packet_loss_rate=0,
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
            failure_count=0,
        )
