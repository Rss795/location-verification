import json
from pathlib import Path
import subprocess
import sys

import pytest

from location_verifier.integrations.m1_adapter import parse_topology_map
from location_verifier.integrations.m1_builder import build_from_document, build_m1_topology
from location_verifier.models import VerificationResult, VerificationStatus


PROJECT_ROOT = Path(__file__).parents[1]


def test_flat_claims_build_and_roundtrip_through_m1_adapter() -> None:
    claims = json.loads((PROJECT_ROOT / "examples/m1/flat_peer_claims.example.json").read_text())
    topology = build_from_document(claims)
    snapshot = parse_topology_map(topology)

    assert [peer.peer_id for peer in snapshot.peers] == [
        "peer-001", "peer-002", "peer-003", "peer-004"
    ]
    assert snapshot.peers[0].witnessing_zone == "LOCAL_CAMPUS_ZONE_A"
    assert snapshot.peers[0].witnessing_zone_verification_state == "unverifiable_short_range"
    assert snapshot.peers[3].weight == pytest.approx(0.75)


def test_flat_builder_keeps_repeated_labels_separate_under_different_parents() -> None:
    topology = build_m1_topology([
        {"peer_id": "a", "region": "r1", "asn": "AS1", "witnessing_zone": "zone", "rack": "rack"},
        {"peer_id": "b", "region": "r2", "asn": "AS2", "witnessing_zone": "zone", "rack": "rack"},
    ])
    snapshot = parse_topology_map(topology)
    assert snapshot.peers[0].witnessing_zone == snapshot.peers[1].witnessing_zone
    assert snapshot.peers[0].failure_domains["witnessing_zone"] != snapshot.peers[1].failure_domains["witnessing_zone"]


def test_flat_builder_rejects_duplicate_peers_and_conflicting_bucket_states_cautiously() -> None:
    claim = {"peer_id": "a", "region": "r", "asn": "AS1", "witnessing_zone": "z", "rack": "x"}
    with pytest.raises(ValueError, match="unique"):
        build_m1_topology([claim, claim])

    other = {**claim, "peer_id": "b", "witnessing_zone_state": "untrusted"}
    snapshot = parse_topology_map(build_m1_topology([claim, other]))
    assert all(peer.witnessing_zone_verification_state == "untrusted" for peer in snapshot.peers)


def test_m3_annotations_are_peer_level_and_do_not_rewrite_shared_m1_buckets() -> None:
    claims = json.loads((PROJECT_ROOT / "examples/m1/flat_peer_claims.example.json").read_text())
    snapshot = parse_topology_map(build_from_document(claims))
    result_by_id = {
        peer.peer_id: VerificationResult(
            peer.peer_id,
            peer.failure_domains["witnessing_zone"],
            VerificationStatus.UNCERTAIN,
            0.42,
            0.3,
            0.6,
        )
        for peer in snapshot.peers
    }
    annotated = snapshot.with_location_verification(result_by_id)
    peer_leaf = annotated["root"]["children"][0]["children"][0]["children"][0]["children"][0]["children"][0]
    assert peer_leaf["m3_location_verification"]["status"] == "UNCERTAIN"
    assert peer_leaf["m3_location_verification"]["evidence_strength_score"] == pytest.approx(0.42)
    assert peer_leaf["m3_location_verification"]["score_semantics"].startswith("uncalibrated")
    assert snapshot.peers[0].witnessing_zone_verification_state == "unverifiable_short_range"


def test_full_system_cli_builds_m1_and_runs_synthetic_dry_run(tmp_path: Path) -> None:
    topology_path = tmp_path / "generated_topology.json"
    result_path = tmp_path / "result.json"
    completed = subprocess.run(
        [
            sys.executable,
            "experiments/run_full_system.py",
            "--flat-claims", "examples/m1/flat_peer_claims.example.json",
            "--built-topology-output", str(topology_path),
            "--metadata", "examples/m1/peer_witness_metadata.example.json",
            "--synthetic", "--dry-run",
            "--failure-domain-level", "witnessing_zone",
            "--simulate-status-change", "peer-003",
            "--output", str(result_path),
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(result_path.read_text(encoding="utf-8"))
    generated = json.loads(topology_path.read_text(encoding="utf-8"))
    assert len(parse_topology_map(generated).peers) == 4
    assert result["m1_topology"]["source"] == "repository-owned reference M1 producer"
    assert result["reconfiguration"]["invalidated_peer_ids"] == ["peer-003"]
    assert result["reconfiguration"]["proposed_placement"]["failure_domain_level"] == "witnessing_zone"
    assert result["cluster_dry_run"]["dry_run"] is True
    assert result["m1_topology_with_m3_results"]["root"]["children"]
    leaves = []

    def visit(node: dict[str, object]) -> None:
        for child in node["children"]:
            if "children" in child:
                visit(child)
            else:
                leaves.append(child)

    visit(result["m1_topology_with_m3_results"]["root"])
    peer_three = next(leaf for leaf in leaves if leaf["peer_id"] == "peer-003")
    assert peer_three["m3_location_verification"]["status"] == "SUSPICIOUS"
    assert "SYNTHETIC EVALUATION" in completed.stdout
