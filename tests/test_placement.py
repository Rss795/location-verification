import pytest

from location_verifier.models import VerificationStatus
from location_verifier.placement.eligibility import decide_eligibility
from location_verifier.placement.models import EligibilityState
from location_verifier.placement.topology import FailureDomainTopology


def test_topology_inserts_peers_and_resolves_hierarchy(make_placement_peer) -> None:
    peers = [make_placement_peer("peer-a", "BUILDING_A"), make_placement_peer("peer-b", "BUILDING_B")]
    topology = FailureDomainTopology(peers=peers)

    assert topology.get_peer("peer-a") == peers[0]
    assert topology.failure_domain("peer-a", "building") == "BUILDING_A"
    assert topology.failure_domain("peer-a", "site") == "SITE_1"
    assert topology.failure_domain("peer-a", "peer") == "peer-a"
    assert tuple(topology.peers_by_domain("building")) == ("BUILDING_A", "BUILDING_B")


def test_topology_rejects_duplicate_peers_invalid_hierarchy_and_missing_levels(make_placement_peer) -> None:
    peer = make_placement_peer("peer-a", "BUILDING_A")
    with pytest.raises(ValueError, match="duplicate peer"):
        FailureDomainTopology(peers=[peer, peer])
    with pytest.raises(ValueError, match="unique"):
        FailureDomainTopology(["region", "region"])
    with pytest.raises(ValueError, match="hierarchy mismatch"):
        FailureDomainTopology(peers=[type(peer)(peer.peer_id, peer.claim, {"building": "A"}, peer.verification)])


def test_peer_domain_mapping_is_immutable(make_placement_peer) -> None:
    peer = make_placement_peer("peer-a", "BUILDING_A")
    with pytest.raises(TypeError):
        peer.failure_domains["building"] = "BUILDING_B"


@pytest.mark.parametrize(
    ("mode", "status", "expected_state"),
    [
        ("strict", VerificationStatus.PLAUSIBLE, EligibilityState.ELIGIBLE),
        ("strict", VerificationStatus.UNCERTAIN, EligibilityState.INELIGIBLE),
        ("balanced", VerificationStatus.UNCERTAIN, EligibilityState.CONDITIONAL),
        ("permissive", VerificationStatus.UNCERTAIN, EligibilityState.ELIGIBLE),
        ("permissive", VerificationStatus.SUSPICIOUS, EligibilityState.QUARANTINED),
        ("balanced", VerificationStatus.INSUFFICIENT_EVIDENCE, EligibilityState.INELIGIBLE),
    ],
)
def test_verification_status_policy(make_placement_peer, mode, status, expected_state) -> None:
    from location_verifier.config import VerificationPolicyConfig

    peer = make_placement_peer("peer-x", "BUILDING_X", status)
    decision = decide_eligibility(peer, VerificationPolicyConfig(mode=mode))

    assert decision.state is expected_state
    if status is VerificationStatus.SUSPICIOUS:
        assert "not labeled malicious" in decision.reason


def test_uncertain_peer_preference_is_configurable(make_placement_peer) -> None:
    from location_verifier.config import VerificationPolicyConfig

    decision = decide_eligibility(
        make_placement_peer("peer-u", "BUILDING_U", VerificationStatus.UNCERTAIN),
        VerificationPolicyConfig(mode="balanced", balanced_uncertain_multiplier=0.3),
    )

    assert decision.preference_multiplier == 0.3
