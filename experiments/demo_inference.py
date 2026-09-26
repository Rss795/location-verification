"""Run a deterministic synthetic Phase 3 scenario; values are not real measurements."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from location_verifier.config import InferenceConfig
from location_verifier.inference.distance import haversine_distance_km
from location_verifier.inference.latency_model import LatencyModel
from location_verifier.inference.verifier import verify
from location_verifier.measurement.collector import (
    MeasurementBatch,
    MeasurementBatchStatus,
    WitnessEvidence,
)
from location_verifier.measurement.statistics import extract_features
from location_verifier.models import (
    GeoLocation,
    MeasurementObservation,
    PeerClaim,
    Witness,
)


def main() -> None:
    config = InferenceConfig()
    claim = PeerClaim("synthetic-peer", GeoLocation(0, 0), "synthetic-domain-b")
    witnesses = [
        Witness("synthetic-witness-a", GeoLocation(0, 10), reliability_score=0.9),
        Witness("synthetic-witness-b", GeoLocation(10, 0), reliability_score=0.9),
        Witness("synthetic-witness-c", GeoLocation(-10, -10), reliability_score=0.9),
    ]
    evidence: list[WitnessEvidence] = []
    now = datetime(2026, 9, 26, tzinfo=timezone.utc)
    model = LatencyModel(config.latency_model)
    for witness in witnesses:
        distance = haversine_distance_km(witness.location, claim.claimed_location)
        expected = model.predict(distance).expected_rtt_ms
        observations = tuple(MeasurementObservation(now, expected) for _ in range(20))
        features = extract_features(observations)
        batch = MeasurementBatch(
            witness_id=witness.witness_id,
            target_peer_id=claim.peer_id,
            host="synthetic.invalid",
            started_at=now,
            completed_at=now,
            observations=observations,
            features=features,
            status=MeasurementBatchStatus.COMPLETE,
        )
        evidence.append(WitnessEvidence(witness, claim.peer_id, batch))

    result = verify(claim, evidence, config)
    print("SYNTHETIC DEMONSTRATION ONLY; no network measurements were made.")
    print(f"Peer: {result.peer_id}")
    print(f"Status: {result.status.value}")
    print(f"Evidence-strength score: {result.confidence:.3f} (not probability)")
    print(f"Uncertainty: {result.uncertainty:.3f}")
    print(f"Witness agreement: {result.witness_agreement:.3f}")


if __name__ == "__main__":
    main()
