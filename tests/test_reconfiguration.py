from dataclasses import replace

from location_verifier.config import PlacementConfig
from location_verifier.models import VerificationStatus
from location_verifier.placement.fdar import place_fdar
from location_verifier.placement.models import PlacementStatus
from location_verifier.placement.reconfiguration import plan_reconfiguration
from location_verifier.placement.topology import FailureDomainTopology


def test_status_change_replaces_only_invalid_peer(make_placement_peer) -> None:
    peers = [make_placement_peer(f"peer-{index}", f"BUILDING_{index}") for index in range(1, 5)]
    topology = FailureDomainTopology(peers=peers)
    config = PlacementConfig(replication_factor=3)
    before = place_fdar("object-r", topology, config)
    invalidated_peer_id = before.selected_peers[1].peer_id
    old_peer = topology.get_peer(invalidated_peer_id)
    topology.update_peer(
        replace(
            old_peer,
            verification=replace(
                old_peer.verification,
                status=VerificationStatus.SUSPICIOUS,
            ),
        )
    )

    plan = plan_reconfiguration(before, topology, config)

    assert plan.success
    assert plan.affected_objects == ("object-r",)
    assert plan.invalidated_peer_ids == (invalidated_peer_id,)
    assert plan.required_moves == 1
    assert invalidated_peer_id not in plan.replacement_candidates
    assert plan.proposed_placement.placement_status is PlacementStatus.SUCCESS
    assert invalidated_peer_id not in {item.peer_id for item in plan.proposed_placement.selected_peers}
    preserved = {item.peer_id for item in before.selected_peers} - {invalidated_peer_id}
    assert preserved <= {item.peer_id for item in plan.proposed_placement.selected_peers}
    assert len(set(plan.proposed_placement.selected_failure_domains)) == 3


def test_reconfiguration_fails_if_no_replacement_domain(make_placement_peer) -> None:
    peers = [make_placement_peer(f"peer-{index}", f"BUILDING_{index}") for index in range(1, 4)]
    topology = FailureDomainTopology(peers=peers)
    config = PlacementConfig(replication_factor=3)
    before = place_fdar("object-r", topology, config)
    invalidated_id = before.selected_peers[0].peer_id
    old = topology.get_peer(invalidated_id)
    topology.update_peer(
        replace(old, verification=replace(old.verification, status=VerificationStatus.SUSPICIOUS))
    )

    plan = plan_reconfiguration(before, topology, config)

    assert not plan.success
    assert plan.required_moves == 1
    assert len(plan.proposed_placement.selected_peers) == 2
    assert plan.proposed_placement.placement_status is PlacementStatus.INSUFFICIENT_DOMAINS


def test_reconfiguration_is_deterministic_and_noop_when_still_valid(make_placement_peer) -> None:
    peers = [make_placement_peer(f"peer-{index}", f"BUILDING_{index}") for index in range(1, 5)]
    topology = FailureDomainTopology(peers=peers)
    config = PlacementConfig(replication_factor=3)
    before = place_fdar("object-r", topology, config)

    first = plan_reconfiguration(before, topology, config)
    second = plan_reconfiguration(before, topology, config)

    assert first.success and first.required_moves == 0
    assert first.affected_objects == ()
    assert first.proposed_placement.to_json() == second.proposed_placement.to_json()


def test_disabled_reconfiguration_does_not_propose_movement(make_placement_peer) -> None:
    peers = [make_placement_peer(f"peer-{index}", f"BUILDING_{index}") for index in range(1, 4)]
    topology = FailureDomainTopology(peers=peers)
    config = PlacementConfig(replication_factor=3)
    before = place_fdar("object-r", topology, config)
    disabled = replace(config, reconfiguration=replace(config.reconfiguration, enabled=False))

    plan = plan_reconfiguration(before, topology, disabled)

    assert not plan.success
    assert plan.required_moves == 0
    assert plan.proposed_placement == before


def test_config_can_disable_movement_minimization(make_placement_peer) -> None:
    peers = [make_placement_peer(f"peer-{index}", f"BUILDING_{index}") for index in range(1, 5)]
    topology = FailureDomainTopology(peers=peers)
    config = PlacementConfig(replication_factor=3)
    before = place_fdar("object-r", topology, config)
    changed = replace(config, reconfiguration=replace(config.reconfiguration, minimize_movement=False))

    plan = plan_reconfiguration(before, topology, changed)

    assert plan.success
    assert "movement minimization is disabled" in plan.reason
    assert plan.proposed_placement.placement_status is PlacementStatus.SUCCESS