from datetime import datetime, timezone

import pytest

from location_verifier.models import (
    GeoLocation,
    MeasurementObservation,
    PeerClaim,
    VerificationResult,
    VerificationStatus,
    Witness,
)


def test_geo_location_accepts_valid_coordinates() -> None:
    assert GeoLocation(17.385, 78.4867).latitude == 17.385


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [(91, 0), (-91, 0), (0, 181), (0, -181)],
)
def test_geo_location_rejects_out_of_range_coordinates(
    latitude: float, longitude: float
) -> None:
    with pytest.raises(ValueError):
        GeoLocation(latitude, longitude)


def test_peer_claim_requires_identity_and_domain() -> None:
    with pytest.raises(ValueError, match="peer_id"):
        PeerClaim(" ", GeoLocation(0, 0), "building-a")


def test_measurement_requires_timezone_and_consistent_timeout() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        MeasurementObservation(datetime(2026, 1, 1), 12.0)
    with pytest.raises(ValueError, match="must not include an RTT"):
        MeasurementObservation(datetime.now(timezone.utc), 12.0, timed_out=True)


def test_witness_reliability_is_bounded() -> None:
    with pytest.raises(ValueError, match="reliability_score"):
        Witness("w1", GeoLocation(0, 0), reliability_score=1.1)


def test_verification_result_is_suitable_for_downstream_contract() -> None:
    result = VerificationResult(
        peer_id="peer-1",
        claimed_failure_domain="building-a",
        status=VerificationStatus.INSUFFICIENT_EVIDENCE,
        confidence=0.0,
        uncertainty=1.0,
    )
    assert result.status.value == "INSUFFICIENT_EVIDENCE"
    assert result.witness_agreement is None
