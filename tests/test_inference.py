from datetime import datetime, timezone
import math

import pytest

from location_verifier.config import (
    DecisionConfig,
    FusionConfig,
    InferenceConfig,
    LatencyModelConfig,
    OutlierConfig,
    ReliabilityConfig,
    load_config,
)
from location_verifier.inference.distance import haversine_distance_km
from location_verifier.inference.fusion import fuse_evidence
from location_verifier.inference.latency_model import ExpectedLatency, LatencyModel
from location_verifier.inference.outliers import (
    detect_sample_outliers,
    detect_witness_outliers,
)
from location_verifier.inference.reliability import assess_reliability
from location_verifier.inference.residuals import WitnessResidual, analyze_residual
from location_verifier.inference.verifier import (
    load_saved_witness_evidence,
    verify,
)
from location_verifier.measurement.collector import (
    MeasurementBatch,
    MeasurementBatchStatus,
    WitnessEvidence,
)
from location_verifier.measurement.statistics import extract_features
from location_verifier.measurement.storage import save_measurement_batch
from location_verifier.models import (
    GeoLocation,
    MeasurementFailureReason,
    MeasurementObservation,
    PeerClaim,
    VerificationStatus,
    Witness,
)

UTC_NOW = datetime(2026, 9, 26, tzinfo=timezone.utc)


def make_evidence(
    witness_id: str,
    witness_location: GeoLocation,
    rtts: list[float | None],
    *,
    prior_reliability: float = 0.9,
    target_peer_id: str = "peer-1",
) -> WitnessEvidence:
    observations = tuple(
        MeasurementObservation(
            UTC_NOW,
            value,
            timed_out=value is None,
            failure_reason=(MeasurementFailureReason.TIMEOUT if value is None else None),
        )
        for value in rtts
    )
    features = extract_features(observations)
    successes = features.successful_count
    status = (
        MeasurementBatchStatus.COMPLETE
        if successes == features.sample_count
        else MeasurementBatchStatus.PARTIAL_MEASUREMENTS
        if successes
        else MeasurementBatchStatus.NO_SUCCESSFUL_MEASUREMENTS
    )
    batch = MeasurementBatch(
        witness_id=witness_id,
        target_peer_id=target_peer_id,
        host="198.51.100.7",
        started_at=UTC_NOW,
        completed_at=UTC_NOW,
        observations=observations,
        features=features,
        status=status,
    )
    return WitnessEvidence(
        Witness(witness_id, witness_location, reliability_score=prior_reliability),
        target_peer_id,
        batch,
    )


def expected_rtt(witness_location: GeoLocation, claim: PeerClaim, config: InferenceConfig) -> float:
    distance = haversine_distance_km(witness_location, claim.claimed_location)
    return LatencyModel(config.latency_model).predict(distance).expected_rtt_ms


def three_supporting_witnesses(config: InferenceConfig, claim: PeerClaim) -> list[WitnessEvidence]:
    locations = [GeoLocation(0, 10), GeoLocation(10, 0), GeoLocation(-10, -10)]
    return [
        make_evidence(
            f"witness-{index}",
            location,
            [expected_rtt(location, claim, config)] * 20,
        )
        for index, location in enumerate(locations, start=1)
    ]


def test_haversine_identical_known_city_and_dateline_distances() -> None:
    location = GeoLocation(17.385, 78.4867)
    assert haversine_distance_km(location, location) == 0
    new_york = GeoLocation(40.7128, -74.0060)
    london = GeoLocation(51.5074, -0.1278)
    assert haversine_distance_km(new_york, london) == pytest.approx(5570, abs=3)
    assert haversine_distance_km(GeoLocation(0, 179), GeoLocation(0, -179)) == pytest.approx(222.4, abs=0.5)


def test_latency_model_returns_configurable_range_and_grows_with_distance() -> None:
    model = LatencyModel(LatencyModelConfig())
    zero = model.predict(0)
    distant = model.predict(1000)

    assert zero.expected_rtt_ms == 8
    assert zero.lower_bound_ms <= zero.expected_rtt_ms <= zero.upper_bound_ms
    assert distant.expected_rtt_ms > zero.expected_rtt_ms
    assert distant.model_uncertainty_ms > zero.model_uncertainty_ms
    with pytest.raises(ValueError):
        model.predict(-1)
    with pytest.raises(ValueError):
        LatencyModel(LatencyModelConfig(uncertainty_ms=0))


@pytest.mark.parametrize("observed", [8.0, 1000.0, 0.2])
def test_residuals_inside_and_outside_range_are_continuous(observed: float) -> None:
    config = InferenceConfig()
    claim = PeerClaim("peer-1", GeoLocation(0, 0), "domain-b")
    location = GeoLocation(0, 10)
    evidence = make_evidence("w1", location, [observed] * 20)
    distance = haversine_distance_km(location, claim.claimed_location)
    expected = LatencyModel(config.latency_model).predict(distance)
    residual = analyze_residual(evidence, distance, expected)

    assert residual.observed_median_rtt_ms == observed
    assert residual.residual_ms == pytest.approx(observed - expected.expected_rtt_ms)
    assert residual.normalized_residual is not None
    assert 0 <= residual.consistency_score <= 1
    if expected.lower_bound_ms <= observed <= expected.upper_bound_ms:
        assert residual.consistency_score == 1
    else:
        assert residual.consistency_score < 1


def test_missing_rtt_produces_unavailable_residual_features() -> None:
    config = InferenceConfig()
    claim = PeerClaim("peer-1", GeoLocation(0, 0), "domain-b")
    evidence = make_evidence("w1", GeoLocation(0, 10), [None] * 12)
    distance = haversine_distance_km(evidence.witness.location, claim.claimed_location)
    residual = analyze_residual(evidence, distance, LatencyModel(config.latency_model).predict(distance))

    assert residual.observed_median_rtt_ms is None
    assert residual.normalized_residual is None
    assert residual.consistency_score is None
    assert residual.packet_loss_rate == 1


def test_residual_below_expected_lower_bound_is_signed_and_inconsistent() -> None:
    config = InferenceConfig(
        latency_model=LatencyModelConfig(
            baseline_rtt_ms=100,
            propagation_factor_ms_per_km=0.01,
            uncertainty_ms=5,
            uncertainty_per_100_km_ms=0,
            minimum_rtt_ms=0.1,
        )
    )
    claim = PeerClaim("peer-1", GeoLocation(0, 0), "domain-b")
    location = GeoLocation(0, 10)
    evidence = make_evidence("w1", location, [20.0] * 20)
    distance = haversine_distance_km(location, claim.claimed_location)
    expected = LatencyModel(config.latency_model).predict(distance)

    residual = analyze_residual(evidence, distance, expected)

    assert residual.observed_median_rtt_ms < residual.expected_lower_ms
    assert residual.normalized_residual < 0
    assert residual.consistency_score < 1


def test_high_mad_increases_residual_uncertainty_without_discarding_data() -> None:
    config = InferenceConfig()
    claim = PeerClaim("peer-1", GeoLocation(0, 0), "domain-b")
    location = GeoLocation(0, 10)
    stable = make_evidence("stable", location, [1000.0] * 20)
    variable = make_evidence("variable", location, [950.0, 1050.0] * 10)
    distance = haversine_distance_km(location, claim.claimed_location)
    expected = LatencyModel(config.latency_model).predict(distance)

    stable_residual = analyze_residual(stable, distance, expected)
    variable_residual = analyze_residual(variable, distance, expected)

    assert variable_residual.mad_rtt_ms > stable_residual.mad_rtt_ms
    assert abs(variable_residual.normalized_residual) < abs(stable_residual.normalized_residual)
    assert len(variable.observations) == 20


def test_reliability_rewards_stable_complete_samples_and_penalizes_noise_loss() -> None:
    stable = make_evidence("stable", GeoLocation(0, 10), [20.0] * 20)
    noisy = make_evidence("noisy", GeoLocation(0, 10), [10.0, 80.0] * 5 + [None] * 10)
    config = ReliabilityConfig(minimum_samples=10)

    stable_score = assess_reliability(stable, config)
    noisy_score = assess_reliability(noisy, config)

    assert stable_score.measurement_quality > noisy_score.measurement_quality
    assert stable_score.effective_reliability <= stable.witness.reliability_score
    assert noisy_score.loss_quality < stable_score.loss_quality
    assert assess_reliability(
        make_evidence("few", GeoLocation(0, 10), [20.0] * 3), config
    ).sample_completeness == pytest.approx(0.3)


def _residual(witness_id: str, normalized: float | None) -> WitnessResidual:
    return WitnessResidual(
        witness_id=witness_id,
        target_peer_id="peer-1",
        distance_km=1000,
        observed_median_rtt_ms=20,
        expected_rtt_ms=20,
        expected_lower_ms=10,
        expected_upper_ms=30,
        residual_ms=0,
        normalized_residual=normalized,
        mad_rtt_ms=0,
        jitter_ms=0,
        packet_loss_rate=0,
        sample_count=20,
        successful_count=20,
        within_expected_range=True,
        consistency_score=math.exp(-0.5 * normalized * normalized) if normalized is not None else None,
    )


def test_witness_outlier_detection_flags_pattern_deviation_but_retains_it() -> None:
    residuals = [_residual("a", 0), _residual("b", 0), _residual("c", 10)]
    assessments = detect_witness_outliers(residuals, OutlierConfig())

    assert [item.is_outlier for item in assessments] == [False, False, True]
    assert all(item.retained_for_analysis for item in assessments)
    assert "group median" in assessments[2].reason


def test_small_witness_group_does_not_label_outliers() -> None:
    assessments = detect_witness_outliers(
        [_residual("a", 0), _residual("b", 10)], OutlierConfig()
    )
    assert not any(item.is_outlier for item in assessments)


def test_multiple_witness_outliers_are_flagged_when_a_majority_is_consistent() -> None:
    residuals = [
        _residual("a", 0),
        _residual("b", 0),
        _residual("c", 0),
        _residual("d", 10),
        _residual("e", -10),
    ]

    assessments = detect_witness_outliers(residuals, OutlierConfig())

    assert [item.is_outlier for item in assessments] == [False, False, False, True, True]
    assert all(item.retained_for_analysis for item in assessments)


def test_individual_rtt_outlier_is_flagged_without_removal() -> None:
    observations = make_evidence("w", GeoLocation(0, 10), [20.0] * 10 + [500.0]).observations
    assessments = detect_sample_outliers(observations, OutlierConfig())
    flagged = [item for item in assessments if item.is_outlier]

    assert len(flagged) == 1
    assert flagged[0].observation_index == 10
    assert flagged[0].retained_for_analysis


def test_fusion_accounts_for_quality_and_reports_uncalibrated_scores() -> None:
    residuals = [_residual("a", 0), _residual("b", 0)]
    reliability = [
        assess_reliability(make_evidence(name, GeoLocation(0, 10), [20.0] * 20), ReliabilityConfig())
        for name in ("a", "b")
    ]
    outliers = detect_witness_outliers(residuals, OutlierConfig())
    fused = fuse_evidence(residuals, reliability, outliers, FusionConfig())

    assert fused.support_score == 1
    assert fused.contradiction_score == 0
    assert fused.witness_agreement == 1
    assert fused.evidence_coverage > 0
    assert 0 < fused.confidence <= 1
    assert fused.uncertainty == pytest.approx(1 - fused.confidence)


def test_fusion_weights_more_reliable_witness_more_strongly() -> None:
    residuals = [_residual("reliable", 0), _residual("unreliable", 4)]
    reliable_assessment = assess_reliability(
        make_evidence("reliable", GeoLocation(0, 10), [20.0] * 20, prior_reliability=1.0),
        ReliabilityConfig(),
    )
    unreliable_assessment = assess_reliability(
        make_evidence("unreliable", GeoLocation(0, 10), [20.0] * 20, prior_reliability=0.1),
        ReliabilityConfig(),
    )
    outliers = detect_witness_outliers(residuals, OutlierConfig())

    fused = fuse_evidence(
        residuals,
        [reliable_assessment, unreliable_assessment],
        outliers,
        FusionConfig(),
    )

    assert fused.support_score > (residuals[0].consistency_score + residuals[1].consistency_score) / 2


def test_verifier_reaches_plausible_status_with_consistent_distributed_evidence() -> None:
    config = InferenceConfig()
    claim = PeerClaim("peer-1", GeoLocation(0, 0), "building-b")
    result = verify(claim, three_supporting_witnesses(config, claim), config)

    assert result.status is VerificationStatus.PLAUSIBLE
    assert result.confidence > 0
    assert result.uncertainty < 1
    assert result.evidence[-1]["aggregate"]["support_score"] == 1


def test_verifier_reaches_suspicious_status_for_consistent_large_residuals() -> None:
    config = InferenceConfig()
    claim = PeerClaim("peer-1", GeoLocation(0, 0), "building-b")
    locations = [GeoLocation(0, 10), GeoLocation(10, 0), GeoLocation(-10, -10)]
    evidence = [make_evidence(f"w{i}", location, [500.0] * 20) for i, location in enumerate(locations)]

    result = verify(claim, evidence, config)

    assert result.status is VerificationStatus.SUSPICIOUS
    assert result.evidence[-1]["aggregate"]["contradiction_score"] > 0.99


def test_verifier_marks_short_distance_evidence_uncertain() -> None:
    config = InferenceConfig(decision=DecisionConfig(short_distance_km=50))
    claim = PeerClaim("peer-1", GeoLocation(0, 0), "building-b")
    evidence = [
        make_evidence("w1", GeoLocation(0.01, 0), [8.0] * 20),
        make_evidence("w2", GeoLocation(0, 0.01), [8.0] * 20),
    ]

    result = verify(claim, evidence, config)

    assert result.status is VerificationStatus.UNCERTAIN
    assert "short-distance ambiguity" in result.evidence[-1]["aggregate"]["reasons"][0]


def test_verifier_returns_insufficient_for_no_usable_measurements() -> None:
    claim = PeerClaim("peer-1", GeoLocation(0, 0), "building-b")
    evidence = [
        make_evidence(f"w{i}", GeoLocation(0, 10 * i), [None] * 20)
        for i in (1, 2)
    ]

    result = verify(claim, evidence)

    assert result.status is VerificationStatus.INSUFFICIENT_EVIDENCE
    assert result.confidence == 0
    assert result.uncertainty == 1


def test_verifier_marks_conflicting_witnesses_uncertain_and_checks_identity() -> None:
    config = InferenceConfig()
    claim = PeerClaim("peer-1", GeoLocation(0, 0), "building-b")
    location_a = GeoLocation(0, 10)
    location_b = GeoLocation(10, 0)
    evidence = [
        make_evidence("a", location_a, [expected_rtt(location_a, claim, config)] * 20),
        make_evidence("b", location_b, [500.0] * 20),
    ]
    assert verify(claim, evidence, config).status is VerificationStatus.UNCERTAIN

    wrong_target = make_evidence("c", GeoLocation(10, 10), [20.0] * 20, target_peer_id="other")
    with pytest.raises(ValueError, match="does not match"):
        verify(claim, [wrong_target], config)
    with pytest.raises(ValueError, match="duplicate"):
        verify(claim, [evidence[0], evidence[0]], config)


def test_low_coverage_is_uncertain_even_when_latency_is_consistent() -> None:
    config = InferenceConfig(reliability=ReliabilityConfig(minimum_samples=20))
    claim = PeerClaim("peer-1", GeoLocation(0, 0), "building-b")
    locations = [GeoLocation(0, 10), GeoLocation(10, 0)]
    evidence = [
        make_evidence(
            f"w{i}",
            location,
            [expected_rtt(location, claim, config)] * 3,
            prior_reliability=0.1,
        )
        for i, location in enumerate(locations)
    ]

    assert verify(claim, evidence, config).status is VerificationStatus.UNCERTAIN


def test_saved_phase_two_json_loads_with_explicit_witness_metadata(tmp_path) -> None:
    evidence = make_evidence("w1", GeoLocation(0, 10), [12.0] * 5)
    raw_path, processed_path = save_measurement_batch(
        evidence.batch, tmp_path / "raw", tmp_path / "processed"
    )
    del raw_path

    loaded = load_saved_witness_evidence(
        processed_path,
        Witness("w1", GeoLocation(0, 10), reliability_score=0.8),
    )

    assert loaded.target_peer_id == "peer-1"
    assert loaded.features.median_rtt_ms == 12
    assert len(loaded.observations) == 5


def test_inference_configuration_is_loaded_and_validated(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "inference:\n  latency_model:\n    baseline_rtt_ms: 12\n"
        "  decision:\n    short_distance_km: 25\n",
        encoding="utf-8",
    )
    config = load_config(path).inference
    assert config.latency_model.baseline_rtt_ms == 12
    assert config.decision.short_distance_km == 25

    with pytest.raises(ValueError, match="sum to 1"):
        ReliabilityConfig(sample_weight=0.5, stability_weight=0.5, loss_weight=0.5)
