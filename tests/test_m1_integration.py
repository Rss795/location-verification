from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

import pytest

from location_verifier.config import load_config
from location_verifier.integrations.m1_adapter import (
    M1AdapterError,
    M1ExternalMetadata,
    load_external_metadata,
    load_topology_map,
    parse_topology_map,
)
from location_verifier.integrations.m1_pipeline import (
    generate_synthetic_m1_evidence,
    load_m1_witness_evidence,
    run_m1_pipeline,
)
from location_verifier.models import VerificationResult, VerificationStatus
from location_verifier.placement.eligibility import decide_eligibility
from location_verifier.placement.models import EligibilityState
from location_verifier.system import SystemOrchestrator


PROJECT_ROOT = Path(__file__).parents[1]
M1_DIR = PROJECT_ROOT / "examples" / "m1"
TOPOLOGY_PATH = M1_DIR / "topology_map.example.json"
METADATA_PATH = M1_DIR / "peer_witness_metadata.example.json"


def test_m1_example_validates_expected_hierarchy_and_preserves_zone_state() -> None:
    snapshot = load_topology_map(TOPOLOGY_PATH)

    assert snapshot.root.type == "root"
    assert len(snapshot.peers) == 4
    peer = next(item for item in snapshot.peers if item.peer_id == "peer-001")
    assert peer.region == "REGION_ALPHA"
    assert peer.asn == "AS64500"
    assert peer.witnessing_zone == "LOCAL_CAMPUS_ZONE_A"
    assert peer.rack == "RACK_A1"
    assert peer.witnessing_zone_verification_state == "unverifiable_short_range"
    assert peer.topology_verification_state == "unverifiable_short_range"
    assert "datacenter" not in peer.failure_domains


def test_m1_bucket_ids_are_qualified_by_their_parent_path() -> None:
    payload = json.loads(TOPOLOGY_PATH.read_text(encoding="utf-8"))
    beta_zone = payload["root"]["children"][1]["children"][0]["children"][0]
    beta_zone["id"] = "LOCAL_CAMPUS_ZONE_A"
    snapshot = parse_topology_map(payload)
    metadata = load_external_metadata(METADATA_PATH)
    topology, _claims = snapshot.to_placement_topology(
        metadata, failure_domain_level="witnessing_zone"
    )

    alpha_peer = topology.get_peer("peer-001")
    beta_peer = topology.get_peer("peer-003")
    assert alpha_peer.witnessing_zone_verification_state == "unverifiable_short_range"
    assert alpha_peer.failure_domains["witnessing_zone"] != beta_peer.failure_domains["witnessing_zone"]
    assert snapshot.peers[0].witnessing_zone == snapshot.peers[2].witnessing_zone == "LOCAL_CAMPUS_ZONE_A"


def test_m1_rejects_invalid_hierarchy_and_duplicate_peer_ids() -> None:
    invalid = {
        "id": "root",
        "type": "root",
        "children": [{"id": "not-asn", "type": "asn", "children": []}],
    }
    with pytest.raises(M1AdapterError, match="invalid M1 hierarchy"):
        parse_topology_map(invalid)

    duplicate = json.loads(TOPOLOGY_PATH.read_text(encoding="utf-8"))
    rack = duplicate["root"]["children"][0]["children"][0]["children"][0]["children"][0]
    rack["children"].append({"peer_id": "peer-001", "weight": 1.0, "type": "node"})
    with pytest.raises(M1AdapterError, match="duplicate peer ID"):
        parse_topology_map(duplicate)


def test_m1_untrusted_bucket_state_is_preserved_through_adapter() -> None:
    payload = json.loads(TOPOLOGY_PATH.read_text(encoding="utf-8"))
    zone = payload["root"]["children"][0]["children"][0]["children"][0]
    zone["verification_state"] = "untrusted"
    snapshot = parse_topology_map(payload)
    peer = next(item for item in snapshot.peers if item.peer_id == "peer-001")

    assert peer.witnessing_zone_verification_state == "untrusted"
    assert peer.topology_verification_state == "untrusted"
    assert "untrusted" in peer.path_verification_states


def test_m1_json_and_external_metadata_require_explicit_coordinates() -> None:
    metadata = load_external_metadata(METADATA_PATH)
    assert set(metadata.peers) == {item.peer_id for item in load_topology_map(TOPOLOGY_PATH).peers}
    with pytest.raises(Exception):
        M1ExternalMetadata.model_validate(
            {"peers": {"peer-x": {"target_host": "host"}}, "witnesses": []}
        )


def test_m1_peernode_weight_is_preserved_in_internal_placement_record() -> None:
    snapshot = load_topology_map(TOPOLOGY_PATH)
    metadata = load_external_metadata(METADATA_PATH)
    topology, _claims = snapshot.to_placement_topology(metadata, failure_domain_level="witnessing_zone")

    assert topology.get_peer("peer-004").weight == pytest.approx(0.75)


def test_m1_short_range_state_is_cautious_and_not_malicious() -> None:
    config = load_config(PROJECT_ROOT / "configs" / "default.yaml")
    snapshot = load_topology_map(TOPOLOGY_PATH)
    metadata = load_external_metadata(METADATA_PATH)
    topology, _claims = snapshot.to_placement_topology(metadata, failure_domain_level="witnessing_zone")
    peer = topology.get_peer("peer-001")
    peer = replace(peer, verification=None)
    # A plausible M3 result must not erase the independent M1 short-range state.
    peer = replace(
        peer,
        verification=VerificationResult(
            "peer-001", peer.claim.claimed_failure_domain,
            VerificationStatus.PLAUSIBLE, 0.8, 0.2, 0.8,
        ),
    )
    balanced = decide_eligibility(peer, config.placement.verification_policy)
    strict_policy = replace(config.placement.verification_policy, short_range_mode="strict")
    strict = decide_eligibility(peer, strict_policy)

    assert peer.verification_status is VerificationStatus.PLAUSIBLE
    assert peer.witnessing_zone_verification_state == "unverifiable_short_range"
    assert balanced.state is EligibilityState.CONDITIONAL
    assert "short range" in balanced.reason
    assert strict.state is EligibilityState.INELIGIBLE
    assert "malicious" not in balanced.reason


def test_m1_short_range_never_overrides_suspicious_or_insufficient_phase3() -> None:
    config = load_config(PROJECT_ROOT / "configs/default.yaml")
    snapshot = load_topology_map(TOPOLOGY_PATH)
    metadata = load_external_metadata(METADATA_PATH)
    topology, _claims = snapshot.to_placement_topology(metadata, failure_domain_level="witnessing_zone")
    base = topology.get_peer("peer-001")
    suspicious = replace(
        base,
        verification=VerificationResult(
            "peer-001", base.claim.claimed_failure_domain,
            VerificationStatus.SUSPICIOUS, 0.8, 0.2, 0.8,
        ),
    )
    insufficient = replace(base, verification=None)

    suspicious_decision = decide_eligibility(suspicious, config.placement.verification_policy)
    insufficient_decision = decide_eligibility(insufficient, config.placement.verification_policy)

    assert suspicious_decision.state is EligibilityState.QUARANTINED
    assert insufficient_decision.state is EligibilityState.INELIGIBLE


def test_m1_untrusted_quarantines_and_pending_state_is_retained() -> None:
    from location_verifier.models import VerificationResult

    config = load_config(PROJECT_ROOT / "configs/default.yaml")
    snapshot = load_topology_map(TOPOLOGY_PATH)
    metadata = load_external_metadata(METADATA_PATH)
    topology, _claims = snapshot.to_placement_topology(metadata, failure_domain_level="witnessing_zone")
    peer = topology.get_peer("peer-002")
    plausible = VerificationResult(
        peer.peer_id, peer.claim.claimed_failure_domain,
        VerificationStatus.PLAUSIBLE, 0.9, 0.1, 0.9,
    )
    untrusted = replace(peer, verification=plausible, topology_verification_state="untrusted")
    pending = replace(peer, verification=plausible, topology_verification_state="pending_check")

    assert decide_eligibility(untrusted, config.placement.verification_policy).state is EligibilityState.QUARANTINED
    pending_decision = decide_eligibility(pending, config.placement.verification_policy)
    assert pending_decision.state is EligibilityState.ELIGIBLE
    assert pending_decision.topology_verification_state == "pending_check"


def test_m1_end_to_end_json_to_m3_m2_m4_and_cluster_dry_run() -> None:
    config = load_config(PROJECT_ROOT / "configs" / "demo.yaml")
    snapshot = load_topology_map(TOPOLOGY_PATH)
    metadata = load_external_metadata(METADATA_PATH)
    evidence = generate_synthetic_m1_evidence(
        snapshot, metadata, config.inference, config.measurement
    )
    execution = run_m1_pipeline(
        snapshot,
        metadata,
        evidence,
        config.inference,
        config.placement,
        object_id="m1-e2e-object",
        failure_domain_level="witnessing_zone",
        evidence_source="SYNTHETIC M1 adapter integration test",
    )

    assert execution.peer_count == 4
    assert execution.witness_count == 3
    assert len(execution.result.verification_results) == 4
    assert execution.result.fdar_placement.failure_domain_level == "witnessing_zone"
    assert execution.cluster_action.dry_run
    assert execution.cluster_action.operation == "REPRESENT_DESIRED_PLACEMENT_ONLY"
    assert execution.result.metadata["m1_witnessing_zone_preserved"] is True
    assert execution.topology.get_peer("peer-001").witnessing_zone_verification_state == "unverifiable_short_range"


def test_m1_short_range_strict_policy_seeks_other_domains_or_fails() -> None:
    config = load_config(PROJECT_ROOT / "configs/demo.yaml")
    strict_placement = replace(
        config.placement,
        verification_policy=replace(
            config.placement.verification_policy,
            short_range_mode="strict",
        ),
    )
    snapshot = load_topology_map(TOPOLOGY_PATH)
    metadata = load_external_metadata(METADATA_PATH)
    evidence = generate_synthetic_m1_evidence(snapshot, metadata, config.inference, config.measurement)
    execution = run_m1_pipeline(
        snapshot,
        metadata,
        evidence,
        config.inference,
        strict_placement,
        object_id="m1-short-range-strict",
        failure_domain_level="witnessing_zone",
        evidence_source="SYNTHETIC M1 short-range test",
    )

    assert execution.topology.get_peer("peer-001").witnessing_zone_verification_state == "unverifiable_short_range"
    assert execution.result.fdar_placement.placement_status.value == "INSUFFICIENT_DOMAINS"
    assert execution.result.fdar_placement.available_distinct_failure_domains == 2
    assert len(execution.result.fdar_placement.selected_peers) == 2
    assert len(set(execution.result.fdar_placement.selected_failure_domains)) == len(
        execution.result.fdar_placement.selected_failure_domains
    )


def test_m1_verification_change_reconfiguration_preserves_other_domains() -> None:
    config = load_config(PROJECT_ROOT / "configs/demo.yaml")
    snapshot = load_topology_map(TOPOLOGY_PATH)
    metadata = load_external_metadata(METADATA_PATH)
    evidence = generate_synthetic_m1_evidence(snapshot, metadata, config.inference, config.measurement)
    execution = run_m1_pipeline(
        snapshot, metadata, evidence, config.inference, config.placement,
        object_id="m1-m4-change", failure_domain_level="witnessing_zone",
        evidence_source="SYNTHETIC M1 reconfiguration test",
    )
    initial = execution.result.fdar_placement
    selected_peer = "peer-003"
    assert selected_peer in {item.peer_id for item in initial.selected_peers}
    m1_placement_config = replace(config.placement, failure_domain_level="witnessing_zone")
    updated = SystemOrchestrator(config.inference, m1_placement_config).plan_verification_change(
        execution.result,
        execution.topology,
        selected_peer,
        VerificationStatus.SUSPICIOUS,
    )

    assert updated.reconfiguration is not None
    assert updated.reconfiguration.required_moves == 1
    assert updated.reconfiguration.success
    assert len(set(updated.reconfiguration.proposed_placement.selected_failure_domains)) == 3


def test_saved_phase2_evidence_is_bound_to_m1_peer_and_witness(tmp_path: Path) -> None:
    config = load_config(PROJECT_ROOT / "configs/demo.yaml")
    snapshot = load_topology_map(TOPOLOGY_PATH)
    metadata = load_external_metadata(METADATA_PATH)
    evidence = generate_synthetic_m1_evidence(snapshot, metadata, config.inference, config.measurement)
    from location_verifier.measurement.storage import save_measurement_batch

    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    for peer_id, witness_evidence in evidence.items():
        for item in witness_evidence:
            _raw, stored = save_measurement_batch(
                item.batch,
                tmp_path / "raw",
                tmp_path / "stored",
            )
            filename = f"{peer_id}__{item.witness.witness_id}_features.json"
            (processed_dir / filename).write_bytes(stored.read_bytes())

    loaded = load_m1_witness_evidence(snapshot, metadata, processed_dir)
    assert all(len(items) == len(metadata.witnesses) for items in loaded.values())
    assert all(item.target_peer_id == peer_id for peer_id, items in loaded.items() for item in items)

    first_file = next(processed_dir.glob("*_features.json"))
    first_file.unlink()
    with pytest.raises(M1AdapterError, match="missing Phase 2"):
        load_m1_witness_evidence(snapshot, metadata, processed_dir)


def test_full_system_cli_runs_m1_m3_m2_m4_and_cluster_dry_run(tmp_path: Path) -> None:
    metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    metadata["current_pin_allocations"] = {"m1-integrated-object": ["peer-003"]}
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "experiments" / "run_full_system.py"),
            "--topology", str(TOPOLOGY_PATH),
            "--metadata", str(metadata_path),
            "--synthetic",
            "--dry-run",
            "--failure-domain-level", "witnessing_zone",
            "--simulate-status-change", "peer-003",
            "--output", str(tmp_path / "m1-system.json"),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "M1 topology loaded" in completed.stdout
    assert "witnessing_zone" in completed.stdout
    assert "IPFS Cluster: DRY-RUN" in completed.stdout
    assert "M4 reconfiguration" in completed.stdout
    assert "replacements: peer-004" in completed.stdout
    payload = json.loads((tmp_path / "m1-system.json").read_text(encoding="utf-8"))
    assert payload["metadata"]["topology_source"] == "M1 topology_map.json"
    assert payload["cluster_dry_run"]["dry_run"] is True
    assert payload["fdar_placement"]["failure_domain_level"] == "witnessing_zone"
    assert payload["reconfiguration"]["proposed_placement"]["failure_domain_level"] == "witnessing_zone"
    assert "peer-003" in payload["cluster_dry_run"]["remove_peer_ids"]
    assert "peer-004" in payload["cluster_dry_run"]["add_peer_ids"]
    assert "SYNTHETIC EVALUATION" in completed.stdout


def test_m1_accepts_teammate_enum_names_without_renaming_witnessing_zone() -> None:
    payload = json.loads(TOPOLOGY_PATH.read_text(encoding="utf-8"))

    def rewrite(node: object) -> None:
        if not isinstance(node, dict):
            return
        if node.get("type") not in {None, "node"}:
            node["type"] = f"BucketType.{str(node['type']).upper()}"
            node["verification_state"] = f"VerificationState.{str(node['verification_state']).upper()}"
        for child in node.get("children", []):
            rewrite(child)

    rewrite(payload["root"])
    snapshot = parse_topology_map(payload)
    peer = next(item for item in snapshot.peers if item.peer_id == "peer-001")
    assert peer.witnessing_zone == "LOCAL_CAMPUS_ZONE_A"
    assert peer.witnessing_zone_verification_state == "unverifiable_short_range"


def test_m1_pipeline_serializes_excluded_short_range_peers() -> None:
    config = load_config(PROJECT_ROOT / "configs" / "demo.yaml")
    strict_placement = replace(
        config.placement,
        verification_policy=replace(config.placement.verification_policy, short_range_mode="strict"),
    )
    snapshot = load_topology_map(TOPOLOGY_PATH)
    metadata = load_external_metadata(METADATA_PATH)
    evidence = generate_synthetic_m1_evidence(snapshot, metadata, config.inference, config.measurement)
    execution = run_m1_pipeline(
        snapshot,
        metadata,
        evidence,
        config.inference,
        strict_placement,
        object_id="m1-serialize-excluded",
        failure_domain_level="witnessing_zone",
        evidence_source="SYNTHETIC M1 serialization test",
    )
    payload = execution.result.to_dict()
    excluded = payload["fdar_placement"]["excluded_peers"]
    assert payload["fdar_placement"]["placement_status"] == "INSUFFICIENT_DOMAINS"
    assert any(
        item["peer_id"] == "peer-001"
        and item["witnessing_zone_verification_state"] == "unverifiable_short_range"
        for item in excluded
    )


def test_real_m1_collection_refuses_loopback_and_saves_labeled_batches(tmp_path: Path) -> None:
    from location_verifier.integrations.m1_pipeline import collect_real_m1_measurements
    from location_verifier.measurement.ping import PingResult, PingStatus

    class ConstantSource:
        def ping_once(self, host: str, timeout_seconds: float) -> PingResult:
            return PingResult(PingStatus.SUCCESS, 11.0)

    snapshot = load_topology_map(TOPOLOGY_PATH)
    metadata = load_external_metadata(METADATA_PATH)
    loopback_payload = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    for peer_id in loopback_payload["peers"]:
        loopback_payload["peers"][peer_id]["target_host"] = "127.0.0.1"
    loopback_metadata = M1ExternalMetadata.model_validate(loopback_payload)
    measurement = replace(load_config(PROJECT_ROOT / "configs" / "demo.yaml").measurement, samples=1, interval_seconds=0.0)

    with pytest.raises(M1AdapterError, match="loopback"):
        collect_real_m1_measurements(
            snapshot,
            loopback_metadata,
            measurement,
            witness_id="witness-1",
            output_dir=tmp_path / "blocked",
            ping_source=ConstantSource(),
        )

    saved, loopback_label = collect_real_m1_measurements(
        snapshot,
        loopback_metadata,
        measurement,
        witness_id="witness-1",
        output_dir=tmp_path / "loopback",
        ping_source=ConstantSource(),
        allow_loopback=True,
    )
    assert saved
    assert "not geographic" in loopback_label.lower()

    saved_real, real_label = collect_real_m1_measurements(
        snapshot,
        metadata,
        measurement,
        witness_id="witness-1",
        output_dir=tmp_path / "real",
        ping_source=ConstantSource(),
    )
    assert len(saved_real) == len(snapshot.peers)
    assert "REAL MEASUREMENTS" in real_label
    assert "SYNTHETIC" not in real_label
