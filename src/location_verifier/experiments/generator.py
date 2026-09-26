"""Seeded synthetic peer/witness generation using the real Phase 3 verifier."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import random
import math

from ..config import InferenceConfig, PlacementConfig
from ..inference.distance import haversine_distance_km
from ..inference.latency_model import LatencyModel
from ..inference.verifier import verify
from ..measurement.collector import (
    MeasurementBatch,
    MeasurementBatchStatus,
    WitnessEvidence,
)
from ..measurement.statistics import extract_features
from ..models import (
    GeoLocation,
    MeasurementObservation,
    PeerClaim,
    VerificationResult,
    VerificationStatus,
    Witness,
)
from ..placement.models import PlacementPeer
from ..placement.topology import FailureDomainTopology
from .models import EvaluationSettings
from .scenarios import ScenarioName


@dataclass(frozen=True, slots=True)
class GroundTruthPeer:
    peer_id: str
    actual_location: GeoLocation
    actual_failure_domain: str
    claimed_location: GeoLocation
    claimed_failure_domain: str
    verification: VerificationResult
    witness_evidence: tuple[WitnessEvidence, ...]


@dataclass(frozen=True, slots=True)
class GeneratedTrial:
    topology: FailureDomainTopology
    peers: tuple[PlacementPeer, ...]
    ground_truth: tuple[GroundTruthPeer, ...]
    witnesses: tuple[Witness, ...]
    inference_config: InferenceConfig
    placement_config: PlacementConfig


_BUILDINGS = ("A1", "A2", "A3", "B1", "B2", "C1")
_LOCAL = GeoLocation(17.385, 78.4867)
_REMOTE = GeoLocation(-23.5505, -46.6333)


def _location_for_domain(domain: str, rng: random.Random) -> GeoLocation:
    offsets = {
        "A1": (0.00, 0.00), "A2": (0.08, 0.02), "A3": (-0.06, 0.04),
        "B1": (0.20, -0.12), "B2": (-0.18, 0.14), "C1": (0.32, 0.28),
    }
    latitude_offset, longitude_offset = offsets[domain]
    return GeoLocation(
        _LOCAL.latitude + latitude_offset + rng.uniform(-0.002, 0.002),
        _LOCAL.longitude + longitude_offset + rng.uniform(-0.002, 0.002),
    )


def _offset_location(location: GeoLocation, distance_km: float, bearing_degrees: float) -> GeoLocation:
    """Return a destination point using a spherical-Earth great-circle offset."""
    import math

    radius_km = 6371.0088
    angular = distance_km / radius_km
    bearing = math.radians(bearing_degrees)
    latitude_1 = math.radians(location.latitude)
    longitude_1 = math.radians(location.longitude)
    latitude_2 = math.asin(
        math.sin(latitude_1) * math.cos(angular)
        + math.cos(latitude_1) * math.sin(angular) * math.cos(bearing)
    )
    longitude_2 = longitude_1 + math.atan2(
        math.sin(bearing) * math.sin(angular) * math.cos(latitude_1),
        math.cos(angular) - math.sin(latitude_1) * math.sin(latitude_2),
    )
    return GeoLocation(math.degrees(latitude_2), (math.degrees(longitude_2) + 540) % 360 - 180)


def _witnesses(
    count: int,
    claim_location: GeoLocation,
    scenario: ScenarioName,
) -> tuple[Witness, ...]:
    if scenario is ScenarioName.UNCERTAIN_PEERS:
        locations = [
            GeoLocation(claim_location.latitude + index * 0.00005, claim_location.longitude)
            for index in range(count)
        ]
    else:
        locations = [
            GeoLocation(17.385, 78.4867),
            GeoLocation(28.6139, 77.2090),
            GeoLocation(13.0827, 80.2707),
            GeoLocation(19.0760, 72.8777),
            GeoLocation(22.5726, 88.3639),
            GeoLocation(27.7172, 85.3240),
        ][:count]
        while len(locations) < count:
            index = len(locations)
            locations.append(GeoLocation(-33.8688 + index, 151.2090 - index))
    return tuple(Witness(f"witness-{index + 1}", location, reliability_score=0.9) for index, location in enumerate(locations))


def _synthetic_evidence(
    peer_id: str,
    actual_location: GeoLocation,
    witnesses: tuple[Witness, ...],
    sample_count: int,
    rng: random.Random,
    inference_config: InferenceConfig,
) -> tuple[WitnessEvidence, ...]:
    latency_model = LatencyModel(inference_config.latency_model)
    evidence: list[WitnessEvidence] = []
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for witness_index, witness in enumerate(witnesses):
        distance = haversine_distance_km(witness.location, actual_location)
        center_rtt = latency_model.predict(distance).expected_rtt_ms
        observations = tuple(
            MeasurementObservation(
                base_time + timedelta(milliseconds=index),
                max(0.1, center_rtt + rng.uniform(-0.8, 0.8)),
            )
            for index in range(sample_count)
        )
        features = extract_features(observations)
        batch = MeasurementBatch(
            witness_id=witness.witness_id,
            target_peer_id=peer_id,
            host=f"synthetic-{peer_id}.invalid",
            started_at=base_time,
            completed_at=base_time + timedelta(milliseconds=sample_count),
            observations=observations,
            features=features,
            status=MeasurementBatchStatus.COMPLETE,
        )
        evidence.append(WitnessEvidence(witness, peer_id, batch))
    return tuple(evidence)


def generate_trial(
    scenario: ScenarioName,
    seed: int,
    settings: EvaluationSettings,
    inference_config: InferenceConfig,
    placement_config: PlacementConfig,
    *,
    policy: str | None = None,
    mismatch_distance_km: float | None = None,
) -> GeneratedTrial:
    """Generate actual/claimed topology and invoke Phase 3 for every peer."""

    rng = random.Random(seed)
    if scenario is ScenarioName.DISTANCE_SWEEP:
        if (
            mismatch_distance_km is None
            or not math.isfinite(mismatch_distance_km)
            or mismatch_distance_km < 0
        ):
            raise ValueError("distance_sweep requires a non-negative mismatch_distance_km")
    elif mismatch_distance_km is not None:
        raise ValueError("mismatch_distance_km is only valid for distance_sweep")
    peer_count = max(settings.peers, 6)
    assigned_domains = [_BUILDINGS[index % len(_BUILDINGS)] for index in range(peer_count)]
    actual_locations: dict[str, GeoLocation] = {}
    claimed_locations: dict[str, GeoLocation] = {}
    claimed_domains: dict[str, str] = {}
    suspicious_count = 0
    if scenario is ScenarioName.ONE_SUSPICIOUS:
        suspicious_count = 1
    elif scenario is ScenarioName.MULTIPLE_SUSPICIOUS:
        suspicious_count = max(2, peer_count // 3)
    elif scenario is ScenarioName.DOMAIN_SHORTFALL:
        suspicious_count = peer_count - 2

    for index in range(peer_count):
        peer_id = f"peer-{index + 1:03d}"
        actual_domain = assigned_domains[index]
        actual_location = _location_for_domain(actual_domain, rng)
        actual_locations[peer_id] = actual_location
        if index < suspicious_count:
            actual_location = _REMOTE
            actual_locations[peer_id] = actual_location
            claimed_domain = _BUILDINGS[(index + 1) % len(_BUILDINGS)]
            claimed_location = _LOCAL
        elif scenario is ScenarioName.DISTANCE_SWEEP and index == 0:
            # Model the relevant spoofing direction: a peer is actually farther
            # away while claiming the nearer coordinate. The evidence is still
            # generated at actual_location and the domain label is held fixed.
            claimed_location = actual_location
            actual_location = _offset_location(
                actual_location,
                mismatch_distance_km,
                rng.uniform(0.0, 360.0),
            )
            actual_locations[peer_id] = actual_location
            # Hold the declared failure-domain label constant so this sweep
            # isolates coordinate-claim discrepancy from topology-label errors.
            claimed_domain = actual_domain
        else:
            claimed_domain = actual_domain
            claimed_location = actual_location
        claimed_domains[peer_id] = claimed_domain
        claimed_locations[peer_id] = claimed_location

    witnesses = _witnesses(settings.witnesses, _LOCAL, scenario)
    generated: list[PlacementPeer] = []
    ground_truth: list[GroundTruthPeer] = []
    for index in range(peer_count):
        peer_id = f"peer-{index + 1:03d}"
        actual_domain = assigned_domains[index]
        claimed_domain = claimed_domains[peer_id]
        actual_location = actual_locations[peer_id]
        claimed_location = claimed_locations[peer_id]
        peer_witnesses = _witnesses(settings.witnesses, claimed_location, scenario)
        evidence = _synthetic_evidence(
            peer_id,
            actual_location,
            peer_witnesses,
            settings.measurements_per_witness,
            rng,
            inference_config,
        )
        claim = PeerClaim(peer_id, claimed_location, claimed_domain)
        verification = verify(claim, evidence, inference_config)
        region = "REMOTE" if claimed_domain in {"B1", "B2"} else "HYDERABAD"
        site = "REMOTE_DC" if region == "REMOTE" else "CAMPUS"
        placement_peer = PlacementPeer(
            peer_id,
            claim,
            {
                "region": region,
                "site": site,
                "building": claimed_domain,
                "floor": "F1",
            },
            verification,
        )
        generated.append(placement_peer)
        ground_truth.append(
            GroundTruthPeer(
                peer_id,
                actual_location,
                actual_domain,
                claimed_location,
                claimed_domain,
                verification,
                evidence,
            )
        )

    active_placement_config = replace(
        placement_config,
        replication_factor=settings.replication_factor,
        failure_domain_level=settings.failure_domain_level,
        verification_policy=replace(
            placement_config.verification_policy,
            mode=policy or placement_config.verification_policy.mode,
        ),
    )
    topology = FailureDomainTopology(peers=generated)
    return GeneratedTrial(
        topology,
        tuple(generated),
        tuple(ground_truth),
        witnesses,
        inference_config,
        active_placement_config,
    )
