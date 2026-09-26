from collections.abc import Callable

import pytest

from location_verifier.models import (
    GeoLocation,
    PeerClaim,
    VerificationResult,
    VerificationStatus,
)
from location_verifier.placement.models import PlacementPeer


@pytest.fixture
def make_placement_peer() -> Callable[..., PlacementPeer]:
    def factory(
        peer_id: str,
        building: str,
        status: VerificationStatus = VerificationStatus.PLAUSIBLE,
        *,
        confidence: float = 0.9,
        agreement: float = 0.9,
        quality: float = 0.9,
        available: bool = True,
        region: str = "REGION_1",
        site: str = "SITE_1",
    ) -> PlacementPeer:
        verification = VerificationResult(
            peer_id=peer_id,
            claimed_failure_domain=f"domain-{building}",
            status=status,
            confidence=confidence,
            uncertainty=1.0 - confidence,
            witness_agreement=agreement,
            evidence=({"measurement_quality": quality},),
        )
        claim = PeerClaim(peer_id, GeoLocation(17.385, 78.4867), f"domain-{building}")
        return PlacementPeer(
            peer_id,
            claim,
            {"region": region, "site": site, "building": building, "floor": "F1"},
            verification,
            available,
        )

    return factory