"""Phase 3 orchestration from peer claim and Phase 2 evidence to a result record."""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime
import json
from pathlib import Path
from typing import Sequence

from ..config import InferenceConfig
from ..measurement.collector import (
    MeasurementBatch,
    MeasurementBatchStatus,
    WitnessEvidence,
)
from ..measurement.statistics import MeasurementFeatures
from ..models import (
    MeasurementFailureReason,
    MeasurementObservation,
    PeerClaim,
    VerificationResult,
    VerificationStatus,
    Witness,
)
from .distance import haversine_distance_km
from .fusion import FusedEvidence, fuse_evidence
from .latency_model import LatencyModel
from .outliers import detect_sample_outliers, detect_witness_outliers
from .reliability import assess_reliability
from .residuals import WitnessResidual, analyze_residual


def _status(
    fused: FusedEvidence,
    residuals: Sequence[WitnessResidual],
    config: InferenceConfig,
) -> tuple[VerificationStatus, tuple[str, ...]]:
    if fused.usable_witness_count < config.fusion.minimum_witnesses:
        return VerificationStatus.INSUFFICIENT_EVIDENCE, ("too few usable witnesses",)

    measured_distances = [
        item.distance_km
        for item in residuals
        if item.observed_median_rtt_ms is not None
    ]
    if measured_distances and all(
        distance < config.decision.short_distance_km for distance in measured_distances
    ):
        return VerificationStatus.UNCERTAIN, (
            "short-distance ambiguity: all witnesses are within the configured low-discrimination range",
        )

    if fused.witness_agreement < config.decision.minimum_agreement:
        return VerificationStatus.UNCERTAIN, ("witness evidence is conflicting",)
    if fused.evidence_coverage < config.decision.minimum_evidence_coverage:
        return VerificationStatus.UNCERTAIN, ("measurement quality or witness reliability is limited",)
    if fused.support_score >= config.decision.plausible_support_threshold:
        return VerificationStatus.PLAUSIBLE, (
            "reliability-weighted evidence is predominantly consistent with the claim",
        )
    if fused.contradiction_score >= config.decision.suspicious_contradiction_threshold:
        return VerificationStatus.SUSPICIOUS, (
            "reliability-weighted evidence is substantially inconsistent with the claim",
        )
    return VerificationStatus.UNCERTAIN, (
        "evidence does not decisively support or contradict the claim",
    )


def verify(
    peer_claim: PeerClaim,
    witness_evidence: Sequence[WitnessEvidence],
    config: InferenceConfig | None = None,
) -> VerificationResult:
    """Evaluate location consistency; the result is evidence, not physical proof."""

    active_config = config or InferenceConfig()
    if not isinstance(peer_claim, PeerClaim):
        raise TypeError("peer_claim must be a PeerClaim")
    evidence_items = tuple(witness_evidence)
    seen_witnesses: set[str] = set()
    for item in evidence_items:
        if not isinstance(item, WitnessEvidence):
            raise TypeError("each evidence item must be WitnessEvidence")
        if item.target_peer_id != peer_claim.peer_id:
            raise ValueError("witness evidence target does not match peer claim")
        if item.witness.witness_id in seen_witnesses:
            raise ValueError(f"duplicate witness evidence: {item.witness.witness_id}")
        seen_witnesses.add(item.witness.witness_id)

    latency_model = LatencyModel(active_config.latency_model)
    residuals: list[WitnessResidual] = []
    reliabilities = []
    for item in evidence_items:
        distance = haversine_distance_km(item.witness.location, peer_claim.claimed_location)
        expected = latency_model.predict(distance)
        residuals.append(analyze_residual(item, distance, expected))
        reliabilities.append(assess_reliability(item, active_config.reliability))
    outliers = detect_witness_outliers(residuals, active_config.outlier_detection)
    fused = fuse_evidence(residuals, reliabilities, outliers, active_config.fusion)
    status, status_reasons = _status(fused, residuals, active_config)

    outlier_by_id = {item.witness_id: item for item in outliers}
    reliability_by_id = {item.witness_id: item for item in reliabilities}
    detail_records: list[dict[str, object]] = []
    for residual, evidence_item in zip(residuals, evidence_items):
        reliability = reliability_by_id[residual.witness_id]
        outlier = outlier_by_id[residual.witness_id]
        detail_records.append(
            {
                "witness_id": residual.witness_id,
                "distance_km": residual.distance_km,
                "observed_median_rtt_ms": residual.observed_median_rtt_ms,
                "expected_rtt_ms": residual.expected_rtt_ms,
                "expected_lower_ms": residual.expected_lower_ms,
                "expected_upper_ms": residual.expected_upper_ms,
                "residual_ms": residual.residual_ms,
                "normalized_residual": residual.normalized_residual,
                "within_expected_range": residual.within_expected_range,
                "consistency_score": residual.consistency_score,
                "mad_rtt_ms": residual.mad_rtt_ms,
                "jitter_ms": residual.jitter_ms,
                "packet_loss_rate": residual.packet_loss_rate,
                "sample_count": residual.sample_count,
                "successful_count": residual.successful_count,
                "measurement_quality": reliability.measurement_quality,
                "prior_witness_reliability": reliability.prior_reliability,
                "effective_reliability": reliability.effective_reliability,
                "outlier": outlier.is_outlier,
                "outlier_score": outlier.outlier_score,
                "outlier_reason": outlier.reason,
                "retained_for_analysis": outlier.retained_for_analysis,
                "sample_outliers": [
                    {
                        "observation_index": sample_outlier.observation_index,
                        "is_outlier": sample_outlier.is_outlier,
                        "robust_z_score": sample_outlier.robust_z_score,
                        "retained_for_analysis": sample_outlier.retained_for_analysis,
                    }
                    for sample_outlier in detect_sample_outliers(
                        evidence_item.observations, active_config.outlier_detection
                    )
                ],
            }
        )
    detail_records.append(
        {
            "aggregate": {
                "support_score": fused.support_score,
                "contradiction_score": fused.contradiction_score,
                "witness_agreement": fused.witness_agreement,
                "evidence_coverage": fused.evidence_coverage,
                "confidence": fused.confidence,
                "uncertainty": fused.uncertainty,
                "usable_witness_count": fused.usable_witness_count,
                "confidence_interpretation": "uncalibrated evidence-strength score, not probability",
                "reasons": list(status_reasons),
            }
        }
    )
    return VerificationResult(
        peer_id=peer_claim.peer_id,
        claimed_failure_domain=peer_claim.claimed_failure_domain,
        status=status,
        confidence=fused.confidence,
        uncertainty=fused.uncertainty,
        witness_agreement=(
            fused.witness_agreement if fused.usable_witness_count else None
        ),
        evidence=tuple(detail_records),
    )


def load_saved_witness_evidence(
    path: str | Path,
    witness: Witness,
) -> WitnessEvidence:
    """Rebuild Phase 2 evidence from processed JSON; caller supplies witness metadata."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("witness_id") != witness.witness_id:
        raise ValueError("saved batch witness_id does not match supplied witness")
    try:
        observations = tuple(
            MeasurementObservation(
                timestamp=datetime.fromisoformat(item["timestamp"]),
                rtt_ms=item["rtt_ms"],
                timed_out=bool(item["timed_out"]),
                failure_reason=(
                    MeasurementFailureReason(item["failure_reason"])
                    if item.get("failure_reason") is not None
                    else None
                ),
            )
            for item in payload["observations"]
        )
        raw_features = payload["features"]
        allowed_fields = {item.name for item in fields(MeasurementFeatures)}
        features = MeasurementFeatures(
            **{name: raw_features[name] for name in allowed_fields}
        )
        batch = MeasurementBatch(
            witness_id=payload["witness_id"],
            target_peer_id=payload["target_peer_id"],
            host=payload["host"],
            started_at=datetime.fromisoformat(payload["started_at"]),
            completed_at=datetime.fromisoformat(payload["completed_at"]),
            observations=observations,
            features=features,
            status=MeasurementBatchStatus(payload["status"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid saved Phase 2 batch: {path}") from exc
    return WitnessEvidence(witness, batch.target_peer_id, batch)
