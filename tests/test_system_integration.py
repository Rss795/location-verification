from dataclasses import replace
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from location_verifier.config import (
    InferenceConfig,
    PlacementConfig,
    load_config,
)
from location_verifier.experiments.generator import generate_trial
from location_verifier.experiments.models import EvaluationSettings
from location_verifier.experiments.scenarios import ScenarioName
from location_verifier.experiments.system_demo import run_synthetic_system_demo
from location_verifier.integrations.ipfs_cluster import (
    ClusterAdapterError,
    ClusterPeer,
    DryRunIPFSClusterAdapter,
    InMemoryIPFSClusterAdapter,
    LocalIPFSClusterReadOnlyClient,
    PinAllocation,
)
from location_verifier.models import VerificationStatus
from location_verifier.placement.fdar import place_fdar
from location_verifier.placement.topology import FailureDomainTopology
from location_verifier.system import SystemOrchestrator, SystemRunStatus


PROJECT_ROOT = Path(__file__).parents[1]


def make_trial(scenario: ScenarioName, seed: int = 42):
    config = load_config(PROJECT_ROOT / "configs" / "demo.yaml")
    settings = EvaluationSettings(
        seeds=(seed,),
        trials=1,
        peers=12,
        witnesses=5,
        objects=1,
        replication_factor=config.placement.replication_factor,
        failure_domain_level=config.placement.failure_domain_level,
        scenarios=(scenario,),
        measurements_per_witness=config.measurement.samples,
    )
    return config, generate_trial(
        scenario,
        seed,
        settings,
        config.inference,
        config.placement,
    )


def run_generated_trial(trial, config, object_id="phase6-test-object"):
    orchestrator = SystemOrchestrator(config.inference, config.placement)
    return orchestrator.run(
        object_id,
        trial.topology,
        [item.claim for item in trial.peers],
        {item.peer_id: item.witness_evidence for item in trial.ground_truth},
        metadata={"label": "SYNTHETIC / DRY-RUN", "seed": 42},
    )


def test_end_to_end_dry_run_runs_measurement_verification_and_fdar(tmp_path: Path) -> None:
    result, details = run_synthetic_system_demo(
        config_path=PROJECT_ROOT / "configs" / "demo.yaml",
        seed=42,
    )

    assert result.metadata["dry_run"] is True
    assert result.metadata["label"] == "SYNTHETIC / DRY-RUN"
    assert len(result.claims) == 12
    assert len(result.verification_results) == 12
    assert result.baseline_placement is not None
    assert result.fdar_placement.placement_success
    assert result.reconfiguration is not None
    assert result.reconfiguration.required_moves == 1
    assert details["cluster_action"].dry_run


def test_phase3_verification_results_are_the_results_attached_to_fdar_peers() -> None:
    config, trial = make_trial(ScenarioName.ONE_SUSPICIOUS)
    result = run_generated_trial(trial, config)
    statuses = {item.peer_id: item.status for item in result.verification_results}

    assert statuses["peer-001"] is VerificationStatus.SUSPICIOUS
    assert "peer-001" not in {item.peer_id for item in result.fdar_placement.selected_peers}
    assert any(item.peer_id == "peer-001" for item in result.fdar_placement.excluded_peers)


def test_suspicious_peer_can_be_selected_by_baseline_but_is_quarantined_by_fdar() -> None:
    config, trial = make_trial(ScenarioName.ONE_SUSPICIOUS)
    result = run_generated_trial(trial, config, object_id="demo-object-0014")

    assert result.baseline_placement is not None
    assert "peer-001" in {item.peer_id for item in result.baseline_placement.selected_peers}
    assert "peer-001" not in {item.peer_id for item in result.fdar_placement.selected_peers}
    assert any(item.peer_id == "peer-001" for item in result.fdar_placement.excluded_peers)


def test_uncertain_status_and_policy_propagate_to_placement() -> None:
    config, trial = make_trial(ScenarioName.UNCERTAIN_PEERS)
    claims = [item.claim for item in trial.peers]
    evidence = {item.peer_id: item.witness_evidence for item in trial.ground_truth}
    strict = replace(config.placement, verification_policy=replace(config.placement.verification_policy, mode="strict"))
    balanced = replace(config.placement, verification_policy=replace(config.placement.verification_policy, mode="balanced"))

    strict_result = SystemOrchestrator(config.inference, strict).run("uncertain", trial.topology, claims, evidence)
    balanced_result = SystemOrchestrator(config.inference, balanced).run("uncertain", trial.topology, claims, evidence)

    assert all(item.status is VerificationStatus.UNCERTAIN for item in strict_result.verification_results)
    assert strict_result.fdar_placement.placement_status.value == "NO_ELIGIBLE_PEERS"
    assert balanced_result.fdar_placement.placement_success
    assert all(item.verification_status is VerificationStatus.UNCERTAIN for item in balanced_result.fdar_placement.selected_peers)


def test_system_shortfall_reports_failure_without_violating_diversity() -> None:
    config, trial = make_trial(ScenarioName.DOMAIN_SHORTFALL)
    result = run_generated_trial(trial, config, object_id="shortfall")

    assert result.status is SystemRunStatus.PLACEMENT_FAILED
    assert result.fdar_placement.placement_status.value == "INSUFFICIENT_DOMAINS"
    assert result.fdar_placement.available_distinct_failure_domains == 2
    assert len(result.fdar_placement.selected_failure_domains) == 2
    assert len(set(result.fdar_placement.selected_failure_domains)) == 2


def test_verification_status_change_plans_minimal_reconfiguration() -> None:
    config, trial = make_trial(ScenarioName.ALL_HONEST)
    result = run_generated_trial(trial, config, object_id="reconfigure")
    selected_id = result.fdar_placement.selected_peers[0].peer_id
    verified_topology = FailureDomainTopology(trial.topology.hierarchy_levels)
    verification_by_peer = {item.peer_id: item for item in result.verification_results}
    for peer in trial.peers:
        verified_topology.add_peer(replace(peer, verification=verification_by_peer[peer.peer_id]))

    changed = SystemOrchestrator(config.inference, config.placement).plan_verification_change(
        result,
        verified_topology,
        selected_id,
        VerificationStatus.SUSPICIOUS,
    )

    assert changed.status is SystemRunStatus.RECONFIGURATION_PLANNED
    assert next(item for item in changed.verification_results if item.peer_id == selected_id).status is VerificationStatus.SUSPICIOUS
    assert changed.reconfiguration is not None
    assert changed.reconfiguration.required_moves == 1
    assert len(changed.reconfiguration.proposed_placement.selected_peers) == 3
    assert len(set(changed.reconfiguration.proposed_placement.selected_failure_domains)) == 3


def test_dry_run_adapter_does_not_mutate_inventory_or_allocations(make_placement_peer) -> None:
    peers = [make_placement_peer(f"p{index}", f"B{index}") for index in range(1, 4)]
    topology = FailureDomainTopology(peers=peers)
    placement = place_fdar("cid-1", topology, PlacementConfig(replication_factor=2))
    initial_peers = tuple(ClusterPeer(peer.peer_id) for peer in peers)
    initial_allocation = PinAllocation("cid-1", ("p1", "p2"))
    adapter = DryRunIPFSClusterAdapter(initial_peers, {"cid-1": initial_allocation})

    before_peers = adapter.discover_peers()
    before_allocation = adapter.get_pin_allocations("cid-1")
    action = adapter.represent_desired_placement("cid-1", placement)

    assert action.dry_run
    assert action.operation == "REPRESENT_DESIRED_PLACEMENT_ONLY"
    assert adapter.discover_peers() == before_peers
    assert adapter.get_pin_allocations("cid-1") == before_allocation


def test_mock_adapter_discovers_peers_reads_allocations_and_builds_diff(make_placement_peer) -> None:
    peers = [make_placement_peer(f"p{index}", f"B{index}") for index in range(1, 4)]
    topology = FailureDomainTopology(peers=peers)
    placement = place_fdar("cid-1", topology, PlacementConfig(replication_factor=2))
    adapter = InMemoryIPFSClusterAdapter(
        [ClusterPeer(peer.peer_id) for peer in peers],
        {"cid-1": PinAllocation("cid-1", ("p1", "p2"))},
    )

    action = adapter.represent_desired_placement("cid-1", placement)

    assert len(adapter.discover_peers()) == 3
    assert action.current_peer_ids == ("p1", "p2")
    assert set(action.add_peer_ids) | set(action.remove_peer_ids) <= {"p1", "p2", "p3"}


def test_system_result_serializes_verification_placement_and_reconfiguration() -> None:
    result, _ = run_synthetic_system_demo(config_path=PROJECT_ROOT / "configs" / "demo.yaml", seed=42)

    payload = result.to_dict()
    encoded = json.dumps(payload, allow_nan=False)

    assert payload["status"] == "RECONFIGURATION_PLANNED"
    assert len(payload["verification_results"]) == 12
    assert payload["fdar_placement"]["mode"] == "FDAR"
    assert payload["reconfiguration"]["required_moves"] == 1
    assert "not cryptographic proof" in payload["research_boundary"]
    assert json.loads(encoded)["metadata"]["dry_run"] is True


def test_demo_config_defaults_to_disabled_dry_run_loopback_only() -> None:
    config = load_config(PROJECT_ROOT / "configs" / "demo.yaml")
    assert not config.ipfs_cluster.enabled
    assert config.ipfs_cluster.dry_run
    assert config.ipfs_cluster.base_url == "http://127.0.0.1:9094"


def test_cluster_client_rejects_non_loopback_and_credentials() -> None:
    with pytest.raises(ValueError, match="loopback"):
        LocalIPFSClusterReadOnlyClient("http://example.com:9094")
    with pytest.raises(ValueError, match="credentials"):
        LocalIPFSClusterReadOnlyClient("http://user:secret@127.0.0.1:9094")


def test_local_http_adapter_uses_get_and_validates_peer_response(monkeypatch) -> None:
    seen = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'[{"id":"peer-a"},{"id":"peer-b"}]'

    def fake_urlopen(request, timeout):
        seen["method"] = request.method
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("location_verifier.integrations.ipfs_cluster.urlopen", fake_urlopen)
    client = LocalIPFSClusterReadOnlyClient("http://localhost:9094", request_timeout_seconds=0.4)

    peers = client.discover_peers()

    assert [peer.peer_id for peer in peers] == ["peer-a", "peer-b"]
    assert seen == {"method": "GET", "url": "http://localhost:9094/peers", "timeout": 0.4}


def test_local_http_adapter_reads_pin_allocations_with_get(monkeypatch) -> None:
    seen = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"allocations":["peer-a","peer-b"]}'

    def fake_urlopen(request, timeout):
        seen["method"] = request.method
        seen["url"] = request.full_url
        return FakeResponse()

    monkeypatch.setattr("location_verifier.integrations.ipfs_cluster.urlopen", fake_urlopen)
    client = LocalIPFSClusterReadOnlyClient("http://127.0.0.1:9094")

    allocation = client.get_pin_allocations("cid/with slash")

    assert allocation == PinAllocation("cid/with slash", ("peer-a", "peer-b"))
    assert seen == {"method": "GET", "url": "http://127.0.0.1:9094/pins/cid%2Fwith%20slash"}


def test_local_http_adapter_handles_unavailable_cluster(monkeypatch) -> None:
    def unavailable(*_args, **_kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr("location_verifier.integrations.ipfs_cluster.urlopen", unavailable)
    client = LocalIPFSClusterReadOnlyClient("http://127.0.0.1:9094")

    with pytest.raises(ClusterAdapterError, match="GET failed"):
        client.discover_peers()


def test_local_http_adapter_does_not_follow_redirects() -> None:
    redirected_requests = []

    class DestinationHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            redirected_requests.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"[]")

        def log_message(self, *_args):
            pass

    destination = ThreadingHTTPServer(("127.0.0.1", 0), DestinationHandler)
    destination_thread = threading.Thread(target=destination.serve_forever, daemon=True)
    destination_thread.start()

    class RedirectHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header(
                "Location",
                f"http://127.0.0.1:{destination.server_port}/escaped",
            )
            self.end_headers()

        def log_message(self, *_args):
            pass

    redirector = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    redirect_thread = threading.Thread(target=redirector.serve_forever, daemon=True)
    redirect_thread.start()
    try:
        client = LocalIPFSClusterReadOnlyClient(
            f"http://127.0.0.1:{redirector.server_port}"
        )
        with pytest.raises(ClusterAdapterError, match="GET failed"):
            client.discover_peers()
        assert redirected_requests == []
    finally:
        redirector.shutdown()
        redirector.server_close()
        redirect_thread.join(timeout=2)
        destination.shutdown()
        destination.server_close()
        destination_thread.join(timeout=2)


def test_local_http_adapter_rejects_malformed_peer_response(monkeypatch) -> None:
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'[{"peer":"missing-id"}]'

    monkeypatch.setattr(
        "location_verifier.integrations.ipfs_cluster.urlopen",
        lambda *_args, **_kwargs: FakeResponse(),
    )
    client = LocalIPFSClusterReadOnlyClient("http://localhost:9094")

    with pytest.raises(ClusterAdapterError, match="peer ID"):
        client.discover_peers()


def test_phase6_demo_cli_runs_and_writes_json(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "experiments" / "run_end_to_end_demo.py"),
            "--config",
            str(PROJECT_ROOT / "configs" / "demo.yaml"),
            "--seed",
            "42",
            "--output-dir",
            str(tmp_path),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "FDAR END-TO-END DEMONSTRATION" in completed.stdout
    assert "SYNTHETIC / DRY-RUN" in completed.stdout
    output = json.loads((tmp_path / "system_run_result.json").read_text(encoding="utf-8"))
    assert output["metadata"]["dry_run"] is True


def test_system_cli_requires_explicit_dry_run_and_executes(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "experiments" / "run_system.py"),
            "--dry-run",
            "--config",
            str(PROJECT_ROOT / "configs" / "demo.yaml"),
            "--output-dir",
            str(tmp_path),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "FDAR END-TO-END DEMONSTRATION" in completed.stdout
    assert (tmp_path / "system_run_result.json").exists()


def test_end_to_end_demo_is_deterministic_for_fixed_seed() -> None:
    first, _ = run_synthetic_system_demo(config_path=PROJECT_ROOT / "configs" / "demo.yaml", seed=42)
    second, _ = run_synthetic_system_demo(config_path=PROJECT_ROOT / "configs" / "demo.yaml", seed=42)

    assert first.to_dict() == second.to_dict()
