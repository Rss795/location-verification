"""Scenario/trial/object runner over the existing verifier and placement APIs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ..config import (
    InferenceConfig,
    PlacementConfig,
    VerificationPolicyConfig,
    load_config,
)
from ..models import VerificationResult, VerificationStatus
from ..placement.fdar import place_baseline, place_fdar
from ..placement.reconfiguration import plan_reconfiguration
from .aggregation import aggregate_records
from .generator import GeneratedTrial, generate_trial
from .metrics import placement_metrics, reconfiguration_metrics
from .models import EvaluationOptions, EvaluationSettings
from .scenarios import SCENARIOS, ScenarioName
from .serialization import write_results


def load_evaluation_settings(path: str | Path) -> EvaluationSettings:
    """Load dedicated evaluation parameters from YAML."""

    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    scenario_names = tuple(ScenarioName(name) for name in payload.get("scenarios", list(SCENARIOS)))
    return EvaluationSettings(
        seeds=tuple(int(seed) for seed in payload.get("seeds", [42])),
        trials=int(payload.get("trials", 1)),
        peers=int(payload.get("peers", 12)),
        witnesses=int(payload.get("witnesses", 5)),
        objects=int(payload.get("objects", 100)),
        replication_factor=int(payload.get("replication_factor", 3)),
        failure_domain_level=str(payload.get("failure_domain_level", "building")),
        scenarios=scenario_names,
        uncertain_policies=tuple(payload.get("uncertain_policies", ["strict", "balanced", "permissive"])),
        output_dir=str(payload.get("output_dir", "data/experiments")),
        measurements_per_witness=int(payload.get("measurements_per_witness", 30)),
        distance_sweep_km=tuple(
            float(value)
            for value in payload.get(
                "distance_sweep_km", (0, 10, 25, 50, 100, 250, 500, 1000, 2000, 5000, 8000, 10000, 15000)
            )
        ),
    )


def _object_count(scenario: ScenarioName, options: EvaluationOptions) -> int:
    if scenario in {
        ScenarioName.ONE_SUSPICIOUS,
        ScenarioName.MULTIPLE_SUSPICIOUS,
        ScenarioName.MULTIPLE_OBJECTS,
        ScenarioName.REPEATED_TRIALS,
    }:
        return options.objects
    return 1


def _records_for_trial(
    scenario: ScenarioName,
    seed: int,
    trial_index: int,
    options: EvaluationOptions,
    inference_config: InferenceConfig,
    base_placement_config: PlacementConfig,
    mismatch_distance_km: float | None = None,
) -> list[dict[str, Any]]:
    generated = generate_trial(
        scenario,
        seed,
        EvaluationSettings(
            seeds=(seed,),
            trials=1,
            peers=options.peers,
            witnesses=options.witnesses,
            objects=options.objects,
            replication_factor=options.replication_factor,
            failure_domain_level=options.failure_domain_level,
            scenarios=(scenario,),
            uncertain_policies=options.uncertain_policies,
            measurements_per_witness=options.measurements_per_witness,
        ),
        inference_config,
        base_placement_config,
        mismatch_distance_km=mismatch_distance_km,
    )
    policies = options.uncertain_policies if scenario is ScenarioName.UNCERTAIN_PEERS else (base_placement_config.verification_policy.mode,)
    records: list[dict[str, Any]] = []
    for policy in policies:
        placement_config = replace(
            generated.placement_config,
            verification_policy=VerificationPolicyConfig(
                mode=policy,
                balanced_uncertain_multiplier=generated.placement_config.verification_policy.balanced_uncertain_multiplier,
                permissive_uncertain_multiplier=generated.placement_config.verification_policy.permissive_uncertain_multiplier,
            ),
        )
        object_count = _object_count(scenario, options)
        for object_index in range(object_count):
            distance_suffix = (
                f"-d{mismatch_distance_km:g}km" if mismatch_distance_km is not None else ""
            )
            object_id = f"eval-{scenario.value}{distance_suffix}-s{seed}-t{trial_index:03d}-o{object_index:05d}"
            baseline = place_baseline(object_id, generated.topology, placement_config)
            fdar = place_fdar(object_id, generated.topology, placement_config)
            baseline_metrics = placement_metrics(baseline, generated.peers, generated.ground_truth)
            fdar_metrics = placement_metrics(fdar, generated.peers, generated.ground_truth)
            for mode, result, metrics in (
                ("BASELINE", baseline, baseline_metrics),
                ("FDAR", fdar, fdar_metrics),
            ):
                record: dict[str, Any] = {
                    "experiment_name": "fdar_system_evaluation",
                    "scenario": scenario.value,
                    "scenario_description": SCENARIOS[scenario],
                    "seed": seed,
                    "trial": trial_index,
                    "object_id": object_id,
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "data_label": "SYNTHETIC SIMULATION; no real network measurements",
                    "synthetic_location_mismatch_distance_km": mismatch_distance_km,
                    "ground_truth_available": True,
                    "peer_count": len(generated.peers),
                    "witness_count": len(generated.witnesses),
                    "object_count": object_count,
                    "replication_factor": placement_config.replication_factor,
                    "failure_domain_level": placement_config.failure_domain_level,
                    "mode": mode,
                    "policy": policy,
                    "configuration": {
                        "seed": seed,
                        "trial": trial_index,
                        "scenario": scenario.value,
                        "peer_count": len(generated.peers),
                        "witness_count": len(generated.witnesses),
                        "object_count": object_count,
                        "measurements_per_witness": options.measurements_per_witness,
                        "replication_factor": placement_config.replication_factor,
                        "failure_domain_level": placement_config.failure_domain_level,
                        "placement_mode": mode,
                        "placement_policy": policy,
                        "phase3_inference": asdict(inference_config),
                        "phase4_placement": asdict(placement_config),
                    },
                    "placement_status": result.placement_status.value,
                    "requested_replicas": result.requested_replication_factor,
                    "actual_domains": {item.peer_id: item.actual_failure_domain for item in generated.ground_truth},
                    "claimed_domains": {item.peer_id: item.claimed_failure_domain for item in generated.ground_truth},
                    "actual_locations": {
                        item.peer_id: {
                            "latitude": item.actual_location.latitude,
                            "longitude": item.actual_location.longitude,
                        }
                        for item in generated.ground_truth
                    },
                    "claimed_locations": {
                        item.peer_id: {
                            "latitude": item.claimed_location.latitude,
                            "longitude": item.claimed_location.longitude,
                        }
                        for item in generated.ground_truth
                    },
                    "verification_statuses": {item.peer_id: item.verification.status.value for item in generated.ground_truth},
                    "limitations": [
                        "SYNTHETIC data; not real network validation",
                        "NO GROUND TRUTH outside generated scenario labels",
                        "Phase 3 confidence is uncalibrated evidence strength, not probability",
                    ],
                    **metrics,
                }
                if scenario is ScenarioName.STATUS_CHANGE and mode == "FDAR" and result.placement_success:
                    changed_topology = _status_change_topology(generated, result)
                    plan = plan_reconfiguration(result, changed_topology, placement_config)
                    repair_metrics = reconfiguration_metrics(result, plan.proposed_placement)
                    record.update(repair_metrics)
                    record["reconfiguration_event_count"] = 1
                    record["reconfiguration_success"] = plan.success
                    record["reconfiguration_reason"] = plan.reason
                    record["invalidated_peer_ids"] = list(plan.invalidated_peer_ids)
                    record["replacement_candidates"] = list(plan.replacement_candidates)
                    record["verification_status_transition"] = {
                        "peer_id": plan.invalidated_peer_ids[0] if plan.invalidated_peer_ids else None,
                        "from": VerificationStatus.PLAUSIBLE.value,
                        "to": VerificationStatus.SUSPICIOUS.value,
                    }
                else:
                    record.update(
                        {
                            "reconfiguration_event_count": 0,
                            "replicas_preserved": 0,
                            "replicas_replaced": 0,
                            "movement_count": 0,
                            "movement_ratio": 0.0,
                            "domain_preserved_after_reconfiguration": None,
                            "reconfiguration_success": None,
                        }
                    )
                records.append(record)
    return records


def _status_change_topology(generated: GeneratedTrial, placement_result):
    from ..placement.topology import FailureDomainTopology

    topology = FailureDomainTopology(peers=generated.peers)
    if not placement_result.selected_peers:
        return topology
    selected_id = placement_result.selected_peers[0].peer_id
    selected_peer = topology.get_peer(selected_id)
    current = selected_peer.verification
    if current is None:
        return topology
    topology.update_peer(
        replace(
            selected_peer,
            verification=replace(current, status=VerificationStatus.SUSPICIOUS),
        )
    )
    return topology


def run_evaluation(
    options: EvaluationOptions,
    inference_config: InferenceConfig,
    placement_config: PlacementConfig,
) -> dict[str, Any]:
    """Run configured synthetic scenarios, trials, and object placements."""

    records: list[dict[str, Any]] = []
    for scenario in options.scenarios:
        for trial_index in range(options.trials):
            seed = options.seeds[trial_index % len(options.seeds)] + (
                trial_index // len(options.seeds)
            ) * 1_000_003
            distances = (
                options.distance_sweep_km
                if scenario is ScenarioName.DISTANCE_SWEEP
                else (None,)
            )
            for mismatch_distance_km in distances:
                records.extend(
                    _records_for_trial(
                        scenario,
                        seed,
                        trial_index,
                        options,
                        inference_config,
                        placement_config,
                        mismatch_distance_km,
                    )
                )
    summaries = aggregate_records(records)
    manifest = {
        "experiment_name": "fdar_system_evaluation",
        "label": "SYNTHETIC SIMULATION; not real network validation",
        "seeds": list(options.seeds),
        "effective_trial_seeds": [
            options.seeds[index % len(options.seeds)]
            + (index // len(options.seeds)) * 1_000_003
            for index in range(options.trials)
        ],
        "trials": options.trials,
        "distance_sweep_km": list(options.distance_sweep_km),
        "scenarios": [item.value for item in options.scenarios],
        "records": len(records),
        "configuration": asdict(options),
        "phase3_inference_configuration": asdict(inference_config),
        "phase4_placement_configuration": asdict(placement_config),
        "phase3_confidence_note": "uncalibrated evidence-strength score, not probability",
        "ground_truth_note": "ground truth exists only for generated synthetic scenario labels; no checked-in loopback measurement is included",
    }
    return {"manifest": manifest, "records": records, "aggregated": summaries}


def options_from_settings(
    settings: EvaluationSettings,
    *,
    seed: int | None = None,
    scenario: str | None = None,
    trials: int | None = None,
    objects: int | None = None,
    output_dir: str | None = None,
    distance_sweep_km: tuple[float, ...] | None = None,
) -> EvaluationOptions:
    scenarios = (ScenarioName(scenario),) if scenario else settings.scenarios
    seeds = (seed,) if seed is not None else settings.seeds
    return EvaluationOptions(
        scenarios=scenarios,
        seeds=seeds,
        trials=trials if trials is not None else settings.trials,
        objects=objects if objects is not None else settings.objects,
        output_dir=output_dir if output_dir is not None else settings.output_dir,
        peers=settings.peers,
        witnesses=settings.witnesses,
        replication_factor=settings.replication_factor,
        failure_domain_level=settings.failure_domain_level,
        measurements_per_witness=settings.measurements_per_witness,
        uncertain_policies=settings.uncertain_policies,
        distance_sweep_km=(
            settings.distance_sweep_km if distance_sweep_km is None else distance_sweep_km
        ),
    )


def phase_configs(config_path: str | Path):
    config = load_config(config_path)
    return config.inference, config.placement
