import json

from location_verifier.config import (
    PlacementConfig,
    PlacementScoringConfig,
    VerificationPolicyConfig,
    load_config,
)
from location_verifier.models import VerificationStatus
from location_verifier.placement.fdar import place_baseline, place_fdar
from location_verifier.placement.metrics import calculate_metrics
from location_verifier.placement.models import PlacementMode, PlacementStatus
from location_verifier.placement.topology import FailureDomainTopology


def test_fdar_rf_1_rf_2_rf_3_respects_domain_diversity(make_placement_peer) -> None:
    peers = [make_placement_peer(f"peer-{i}", f"BUILDING_{i}") for i in range(1, 5)]
    topology = FailureDomainTopology(peers=peers)

    for factor in (1, 2, 3):
        result = place_fdar("object-1", topology, PlacementConfig(replication_factor=factor))
        assert result.placement_status is PlacementStatus.SUCCESS
        assert len(result.selected_peers) == factor
        assert len(set(result.selected_failure_domains)) == factor


def test_topology_with_duplicate_peers_in_building_cannot_overreplicate(make_placement_peer) -> None:
    peers = [
        make_placement_peer("peer-a1", "BUILDING_A"),
        make_placement_peer("peer-a2", "BUILDING_A"),
        make_placement_peer("peer-b1", "BUILDING_B"),
    ]
    topology = FailureDomainTopology(peers=peers)

    result = place_fdar("object-1", topology, PlacementConfig(replication_factor=3))

    assert result.placement_status is PlacementStatus.INSUFFICIENT_DOMAINS
    assert len(result.selected_peers) == 2
    assert result.available_distinct_failure_domains == 2
    assert "not allowed to violate" in result.placement_reason


def test_fdar_excludes_suspicious_peer_and_records_quarantine(make_placement_peer) -> None:
    peers = [
        make_placement_peer("suspicious", "BUILDING_A", VerificationStatus.SUSPICIOUS),
        make_placement_peer("good-b", "BUILDING_B"),
        make_placement_peer("good-c", "BUILDING_C"),
    ]
    topology = FailureDomainTopology(peers=peers)
    result = place_fdar("object-1", topology, PlacementConfig(replication_factor=3))

    assert result.placement_status is PlacementStatus.INSUFFICIENT_DOMAINS
    assert "suspicious" not in {item.peer_id for item in result.selected_peers}
    excluded = next(item for item in result.excluded_peers if item.peer_id == "suspicious")
    assert excluded.state.value == "QUARANTINED"
    assert excluded.verification_status is VerificationStatus.SUSPICIOUS
    assert excluded.confidence == 0.9


def test_uncertain_policy_balanced_permissive_and_strict(make_placement_peer) -> None:
    uncertain = make_placement_peer("uncertain", "BUILDING_A", VerificationStatus.UNCERTAIN)
    other = make_placement_peer("good", "BUILDING_B")
    topology = FailureDomainTopology(peers=[uncertain, other])

    strict = place_fdar("obj", topology, PlacementConfig(replication_factor=2, verification_policy=VerificationPolicyConfig("strict")))
    balanced = place_fdar("obj", topology, PlacementConfig(replication_factor=2, verification_policy=VerificationPolicyConfig("balanced")))
    permissive = place_fdar("obj", topology, PlacementConfig(replication_factor=2, verification_policy=VerificationPolicyConfig("permissive")))

    assert strict.placement_status is PlacementStatus.INSUFFICIENT_DOMAINS
    assert balanced.placement_success and permissive.placement_success
    assert next(item for item in balanced.selected_peers if item.peer_id == "uncertain").why_eligible.startswith("verification is uncertain")


def test_determinism_and_verification_confidence_preference(make_placement_peer) -> None:
    high = make_placement_peer("high", "BUILDING_A", confidence=0.99, agreement=1, quality=1)
    low = make_placement_peer("low", "BUILDING_B", confidence=0.1, agreement=0.1, quality=0.1)
    peers = [high, low]
    topology = FailureDomainTopology(peers=peers)
    config = PlacementConfig(
        replication_factor=1,
        scoring=PlacementScoringConfig(0.7, 0.1, 0.1, 0.1),
    )

    first = place_fdar("object-deterministic", topology, config)
    second = place_fdar("object-deterministic", topology, config)

    assert [item.peer_id for item in first.selected_peers] == [item.peer_id for item in second.selected_peers]
    assert first.selected_peers[0].peer_id == "high"
    assert first.to_json() == second.to_json()
    json.loads(first.to_json())


def test_baseline_uses_same_domains_but_ignores_verification(make_placement_peer) -> None:
    peers = [
        make_placement_peer("suspicious", "BUILDING_A", VerificationStatus.SUSPICIOUS),
        make_placement_peer("good-b", "BUILDING_B"),
        make_placement_peer("good-c", "BUILDING_C"),
    ]
    topology = FailureDomainTopology(peers=peers)
    config = PlacementConfig(replication_factor=3)

    baseline = place_baseline("object-baseline", topology, config)
    fdar = place_fdar("object-baseline", topology, config)

    assert baseline.mode is PlacementMode.BASELINE
    assert baseline.placement_success
    assert "suspicious" in {item.peer_id for item in baseline.selected_peers}
    assert fdar.placement_status is PlacementStatus.INSUFFICIENT_DOMAINS


def test_all_honest_equal_evidence_matches_baseline_selection(make_placement_peer) -> None:
    peers = [
        make_placement_peer(
            f"peer-{index}",
            f"BUILDING_{index}",
            confidence=0.9,
            agreement=0.9,
            quality=0.9,
        )
        for index in range(1, 5)
    ]
    topology = FailureDomainTopology(peers=peers)
    config = PlacementConfig(replication_factor=3)

    baseline = place_baseline("honest-object", topology, config)
    fdar = place_fdar("honest-object", topology, config)

    assert {item.peer_id for item in baseline.selected_peers} == {
        item.peer_id for item in fdar.selected_peers
    }


def test_no_eligible_peers_empty_topology_and_peer_level(make_placement_peer) -> None:
    empty = FailureDomainTopology()
    no_peers = place_fdar("obj", empty, PlacementConfig())
    assert no_peers.placement_status is PlacementStatus.NO_ELIGIBLE_PEERS

    peers = [make_placement_peer("p1", "BUILDING_A"), make_placement_peer("p2", "BUILDING_A")]
    topology = FailureDomainTopology(peers=peers)
    peer_domains = place_fdar("obj", topology, PlacementConfig(replication_factor=2, failure_domain_level="peer"))
    assert peer_domains.placement_success


def test_all_suspicious_or_unavailable_peers_are_explicitly_unavailable(make_placement_peer) -> None:
    suspicious = make_placement_peer("s", "BUILDING_S", VerificationStatus.SUSPICIOUS)
    unavailable = make_placement_peer("u", "BUILDING_U", available=False)
    topology = FailureDomainTopology(peers=[suspicious, unavailable])

    result = place_fdar("obj", topology, PlacementConfig(replication_factor=1))

    assert result.placement_status is PlacementStatus.NO_ELIGIBLE_PEERS
    assert {item.peer_id for item in result.excluded_peers} == {"s", "u"}


def test_metrics_are_descriptive_not_accuracy(make_placement_peer) -> None:
    peers = [
        make_placement_peer("u", "A", VerificationStatus.UNCERTAIN),
        make_placement_peer("s", "B", VerificationStatus.SUSPICIOUS),
        make_placement_peer("p", "C"),
    ]
    topology = FailureDomainTopology(peers=peers)
    result = place_fdar("obj", topology, PlacementConfig(replication_factor=1))
    metrics = calculate_metrics(result, peers)

    assert metrics.placement_success
    assert metrics.replica_count == 1
    assert metrics.distinct_failure_domains == 1
    assert metrics.domain_collision_count == 0
    assert metrics.uncertain_peer_count == 1
    assert metrics.suspicious_peer_count == 1


def test_placement_config_loaded_from_default_yaml() -> None:
    from pathlib import Path

    config = load_config(Path(__file__).parents[1] / "configs" / "default.yaml")
    assert config.placement.replication_factor == 3
    assert config.placement.verification_policy.mode == "balanced"