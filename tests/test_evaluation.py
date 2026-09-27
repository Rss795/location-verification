from dataclasses import replace
import json
from pathlib import Path

import pytest

from location_verifier.config import load_config
from location_verifier.experiments.aggregation import aggregate_records
from location_verifier.experiments.generator import generate_trial
from location_verifier.inference.distance import haversine_distance_km
from location_verifier.experiments.metrics import placement_metrics, reconfiguration_metrics
from location_verifier.experiments.models import EvaluationOptions, EvaluationSettings
from location_verifier.experiments.plotting import (
    _scenario_policy_categories,
    _verification_status_counts,
    plot_results,
)
from location_verifier.experiments.runner import load_evaluation_settings, run_evaluation
from location_verifier.experiments.scenarios import ScenarioName
from location_verifier.experiments.serialization import write_results
from location_verifier.models import VerificationStatus
from location_verifier.placement.fdar import place_baseline, place_fdar
from location_verifier.placement.reconfiguration import plan_reconfiguration


PROJECT_ROOT = Path(__file__).parents[1]


@pytest.fixture
def phase_configs():
    config = load_config(PROJECT_ROOT / "configs" / "default.yaml")
    return config.inference, config.placement


def settings(*, peers: int = 12, objects: int = 4, witnesses: int = 5) -> EvaluationSettings:
    return EvaluationSettings(
        seeds=(42,),
        trials=1,
        peers=peers,
        witnesses=witnesses,
        objects=objects,
        replication_factor=3,
        failure_domain_level="building",
        measurements_per_witness=20,
    )


def test_scenario_generation_is_reproducible_and_seeded(phase_configs) -> None:
    inference, placement = phase_configs
    first = generate_trial(ScenarioName.ONE_SUSPICIOUS, 42, settings(), inference, placement)
    repeated = generate_trial(ScenarioName.ONE_SUSPICIOUS, 42, settings(), inference, placement)
    other_seed = generate_trial(ScenarioName.ONE_SUSPICIOUS, 43, settings(), inference, placement)

    assert first.ground_truth == repeated.ground_truth
    assert first.peers == repeated.peers
    assert first.ground_truth != other_seed.ground_truth
    assert all(item.actual_failure_domain for item in first.ground_truth)


def test_all_honest_scenario_uses_phase3_verifier_and_has_no_suspicious_peers(phase_configs) -> None:
    inference, placement = phase_configs
    trial = generate_trial(ScenarioName.ALL_HONEST, 42, settings(), inference, placement)

    assert all(item.actual_failure_domain == item.claimed_failure_domain for item in trial.ground_truth)
    assert all(item.verification.status is VerificationStatus.PLAUSIBLE for item in trial.ground_truth)
    assert all(peer.verification is not None for peer in trial.peers)
    assert place_baseline("honest", trial.topology, trial.placement_config).placement_success
    assert place_fdar("honest", trial.topology, trial.placement_config).placement_success


def test_false_claims_are_classified_by_phase3_not_directly_labeled(phase_configs) -> None:
    inference, placement = phase_configs
    one = generate_trial(ScenarioName.ONE_SUSPICIOUS, 42, settings(), inference, placement)
    mismatch = [item for item in one.ground_truth if item.actual_failure_domain != item.claimed_failure_domain]

    assert len(mismatch) == 1
    assert mismatch[0].actual_location != mismatch[0].claimed_location
    assert mismatch[0].verification.status is VerificationStatus.SUSPICIOUS
    multiple = generate_trial(ScenarioName.MULTIPLE_SUSPICIOUS, 42, settings(), inference, placement)
    assert sum(item.verification.status is VerificationStatus.SUSPICIOUS for item in multiple.ground_truth) >= 2


def test_suspicious_scenario_baseline_can_select_claim_fdar_quarantines(phase_configs) -> None:
    inference, placement = phase_configs
    trial = generate_trial(ScenarioName.ONE_SUSPICIOUS, 42, settings(objects=100), inference, placement)
    suspicious_id = next(
        item.peer_id for item in trial.ground_truth
        if item.verification.status is VerificationStatus.SUSPICIOUS
    )
    suspicious_selected_by_baseline = False
    suspicious_selected_by_fdar = False
    for object_index in range(100):
        object_id = f"eval-one-suspicious-{object_index}"
        baseline = place_baseline(object_id, trial.topology, trial.placement_config)
        fdar = place_fdar(object_id, trial.topology, trial.placement_config)
        suspicious_selected_by_baseline |= suspicious_id in {item.peer_id for item in baseline.selected_peers}
        suspicious_selected_by_fdar |= suspicious_id in {item.peer_id for item in fdar.selected_peers}

    assert suspicious_selected_by_baseline
    assert not suspicious_selected_by_fdar


def test_uncertain_scenario_reaches_all_three_configured_policies(phase_configs, tmp_path) -> None:
    inference, placement = phase_configs
    trial = generate_trial(ScenarioName.UNCERTAIN_PEERS, 42, settings(), inference, placement)
    assert all(peer.verification_status is VerificationStatus.UNCERTAIN for peer in trial.peers)
    options = EvaluationOptions(
        scenarios=(ScenarioName.UNCERTAIN_PEERS,),
        seeds=(42,),
        trials=1,
        objects=3,
        output_dir=str(tmp_path),
        peers=12,
        witnesses=5,
        replication_factor=3,
        failure_domain_level="building",
        measurements_per_witness=20,
        uncertain_policies=("strict", "balanced", "permissive"),
    )
    results = run_evaluation(options, inference, placement)
    statuses = {
        (item["mode"], item["policy"]): item["placement_success_rate"]
        for item in results["aggregated"]
    }

    assert statuses[("FDAR", "strict")] == 0
    assert statuses[("FDAR", "balanced")] == 1
    assert statuses[("FDAR", "permissive")] == 1
    assert statuses[("BASELINE", "strict")] == statuses[("BASELINE", "balanced")]


def test_domain_shortfall_fails_fdar_but_baseline_uses_claimed_domains(phase_configs) -> None:
    inference, placement = phase_configs
    trial = generate_trial(ScenarioName.DOMAIN_SHORTFALL, 42, settings(), inference, placement)

    baseline = place_baseline("shortfall", trial.topology, trial.placement_config)
    fdar = place_fdar("shortfall", trial.topology, trial.placement_config)

    assert baseline.placement_success
    assert fdar.placement_status.value == "INSUFFICIENT_DOMAINS"
    assert fdar.available_distinct_failure_domains == 2
    assert len(fdar.selected_peers) == 2


def test_synthetic_ground_truth_confusion_metrics_are_separate(phase_configs) -> None:
    inference, placement = phase_configs
    trial = generate_trial(ScenarioName.ONE_SUSPICIOUS, 42, settings(), inference, placement)
    result = place_fdar("gt", trial.topology, trial.placement_config)
    metrics = placement_metrics(result, trial.peers, trial.ground_truth)

    assert metrics["verification_true_positive"] == 1
    assert metrics["verification_false_negative"] == 0
    assert metrics["verification_detection_rate"] == 1
    assert metrics["suspicious_exclusion_rate"] == 1


def test_reconfiguration_metrics_report_minimal_repair(phase_configs) -> None:
    inference, placement = phase_configs
    trial = generate_trial(ScenarioName.STATUS_CHANGE, 42, settings(), inference, placement)
    initial = place_fdar("repair", trial.topology, trial.placement_config)
    changed_id = initial.selected_peers[0].peer_id
    changed_peer = trial.topology.get_peer(changed_id)
    trial.topology.update_peer(
        replace(
            changed_peer,
            verification=replace(
                changed_peer.verification,
                status=VerificationStatus.SUSPICIOUS,
            ),
        )
    )
    plan = plan_reconfiguration(initial, trial.topology, trial.placement_config)
    measures = reconfiguration_metrics(initial, plan.proposed_placement)

    assert plan.success
    assert measures["replicas_preserved"] == 2
    assert measures["replicas_replaced"] == 1
    assert measures["movement_count"] == 1
    assert measures["movement_ratio"] == pytest.approx(1 / 3)
    assert measures["domain_preserved_after_reconfiguration"]


def test_multiple_objects_have_deterministic_peer_and_domain_counts(phase_configs, tmp_path) -> None:
    inference, placement = phase_configs
    options = EvaluationOptions(
        scenarios=(ScenarioName.MULTIPLE_OBJECTS,),
        seeds=(42,),
        trials=1,
        objects=10,
        output_dir=str(tmp_path),
        peers=12,
        witnesses=5,
        replication_factor=3,
        failure_domain_level="building",
        measurements_per_witness=10,
    )
    first = run_evaluation(options, inference, placement)
    second = run_evaluation(options, inference, placement)

    stable_fields = ("scenario", "seed", "trial", "object_id", "mode", "selected_peers", "selected_domains")
    assert len(first["records"]) == 20
    assert [tuple(item[key] for key in stable_fields) for item in first["records"]] == [
        tuple(item[key] for key in stable_fields) for item in second["records"]
    ]
    assert all(item["domain_collision_count"] == 0 for item in first["records"])


def test_aggregation_and_serialization_are_machine_readable(phase_configs, tmp_path) -> None:
    inference, placement = phase_configs
    options = EvaluationOptions(
        scenarios=(ScenarioName.ONE_SUSPICIOUS,), seeds=(42,), trials=1,
        objects=3, output_dir=str(tmp_path), peers=12, witnesses=5,
        replication_factor=3, failure_domain_level="building", measurements_per_witness=10,
    )
    results = run_evaluation(options, inference, placement)
    summary = aggregate_records(results["records"])
    paths = write_results(results, tmp_path)

    assert summary
    assert json.loads(paths["manifest"].read_text(encoding="utf-8"))["label"].startswith("SYNTHETIC")
    rows = json.loads(paths["records_json"].read_text(encoding="utf-8"))
    assert rows[0]["actual_locations"]
    assert rows[0]["claimed_locations"]
    assert paths["records_csv"].exists()
    assert json.loads(paths["aggregated_json"].read_text(encoding="utf-8"))


def test_evaluation_config_and_effective_trial_seeds_are_recorded(phase_configs, tmp_path) -> None:
    loaded = load_evaluation_settings(PROJECT_ROOT / "configs" / "evaluation.yaml")
    assert loaded.trials == 10
    assert loaded.objects == 100
    assert len(loaded.scenarios) == 9
    assert 500 in loaded.distance_sweep_km

    inference, placement = phase_configs
    options = EvaluationOptions(
        scenarios=(ScenarioName.ALL_HONEST,),
        seeds=(12, 13),
        trials=3,
        objects=1,
        output_dir=str(tmp_path),
        peers=6,
        witnesses=2,
        replication_factor=2,
        failure_domain_level="building",
        measurements_per_witness=5,
    )
    result = run_evaluation(options, inference, placement)
    assert result["manifest"]["effective_trial_seeds"] == [12, 13, 1_000_015]


def test_repeated_trial_aggregation_groups_seeded_object_placements(phase_configs, tmp_path) -> None:
    inference, placement = phase_configs
    options = EvaluationOptions(
        scenarios=(ScenarioName.REPEATED_TRIALS,),
        seeds=(30, 31),
        trials=2,
        objects=2,
        output_dir=str(tmp_path),
        peers=8,
        witnesses=3,
        replication_factor=3,
        failure_domain_level="building",
        measurements_per_witness=5,
    )
    result = run_evaluation(options, inference, placement)
    fdar_summary = next(item for item in result["aggregated"] if item["mode"] == "FDAR")

    assert fdar_summary["attempts"] == 4
    assert fdar_summary["placement_success_rate"] == 1
    assert fdar_summary["mean_reconfiguration_event_count"] == 0


def test_plotting_generates_all_supported_plots_with_policy_categories(phase_configs, tmp_path) -> None:
    inference, placement = phase_configs
    options = EvaluationOptions(
        scenarios=(ScenarioName.ALL_HONEST, ScenarioName.ONE_SUSPICIOUS, ScenarioName.UNCERTAIN_PEERS, ScenarioName.STATUS_CHANGE, ScenarioName.MULTIPLE_OBJECTS, ScenarioName.DISTANCE_SWEEP),
        seeds=(42,), trials=1, objects=3, output_dir=str(tmp_path), peers=12,
        witnesses=5, replication_factor=3, failure_domain_level="building", measurements_per_witness=10,
        distance_sweep_km=(0, 50, 500, 1000),
    )
    results = run_evaluation(options, inference, placement)

    paths = plot_results(results, tmp_path / "plots")

    assert len(paths) == 9
    assert all(path.exists() and path.stat().st_size > 0 for path in paths)
    categories, labels = _scenario_policy_categories(results["aggregated"])
    uncertain_labels = {
        labels[index] for index, (scenario, _) in enumerate(categories)
        if scenario == "uncertain_peers"
    }
    assert uncertain_labels == {
        "uncertain_peers (balanced)",
        "uncertain_peers (permissive)",
        "uncertain_peers (strict)",
    }


def test_distance_only_plotting_omits_unsupported_charts_and_counts_each_offset(phase_configs, tmp_path) -> None:
    inference, placement = phase_configs
    options = EvaluationOptions(
        scenarios=(ScenarioName.DISTANCE_SWEEP,), seeds=(42,), trials=1,
        objects=1, output_dir=str(tmp_path), peers=6, witnesses=5,
        replication_factor=3, failure_domain_level="building", measurements_per_witness=10,
        distance_sweep_km=(500, 1000),
    )
    results = run_evaluation(options, inference, placement)
    paths = plot_results(results, tmp_path / "plots")

    assert {path.name for path in paths} == {
        "07_verification_status_distribution.png",
        "09_synthetic_location_distance_sweep.png",
    }
    assert all(path.exists() and path.stat().st_size > 0 for path in paths)

    # Each offset contributes one generated peer-status set; BASELINE and
    # FDAR are duplicate views of that same trial evidence.
    status_records = [
        {
            "seed": 42,
            "trial": 0,
            "scenario": "distance_sweep",
            "mode": mode,
            "synthetic_location_mismatch_distance_km": offset,
            "verification_statuses": {"peer-a": "PLAUSIBLE", "peer-b": "UNCERTAIN"},
        }
        for offset in (500.0, 1000.0)
        for mode in ("BASELINE", "FDAR")
    ]
    assert _verification_status_counts(status_records) == {"PLAUSIBLE": 2, "UNCERTAIN": 2}


def test_distance_sweep_isolates_coordinate_offset_and_records_synthetic_location_metrics(phase_configs, tmp_path) -> None:
    inference, placement = phase_configs
    options = EvaluationOptions(
        scenarios=(ScenarioName.DISTANCE_SWEEP,), seeds=(42, 43), trials=2,
        objects=1, output_dir=str(tmp_path), peers=6, witnesses=5,
        replication_factor=3, failure_domain_level="building", measurements_per_witness=10,
        distance_sweep_km=(0, 250, 500, 1000),
    )
    results = run_evaluation(options, inference, placement)
    assert len(results["records"]) == 16  # 4 distances x 2 seeds x 2 placement modes
    requested_offsets = {row["synthetic_location_mismatch_distance_km"] for row in results["records"]}
    assert requested_offsets == {0, 250, 500, 1000}
    assert all("location_verification_detection_rate" in row for row in results["records"])
    assert all(row["synthetic_location_mismatch_peer_count"] == (0 if row["synthetic_location_mismatch_distance_km"] == 0 else 1) for row in results["records"])
    summaries = [item for item in results["aggregated"] if item["mode"] == "FDAR"]
    assert {item["synthetic_location_mismatch_distance_km"] for item in summaries} == requested_offsets

    trial = generate_trial(
        ScenarioName.DISTANCE_SWEEP, 42, settings(peers=6), inference, placement,
        mismatch_distance_km=500,
    )
    target = trial.ground_truth[0]
    assert haversine_distance_km(target.actual_location, target.claimed_location) == pytest.approx(500)
    assert target.actual_failure_domain == target.claimed_failure_domain
