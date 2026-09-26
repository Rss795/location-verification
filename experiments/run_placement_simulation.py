"""Run a deterministic synthetic baseline/FDAR and reconfiguration scenario."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from location_verifier.config import load_config
from location_verifier.models import GeoLocation, PeerClaim, VerificationResult, VerificationStatus
from location_verifier.placement.fdar import place_baseline, place_fdar
from location_verifier.placement.metrics import calculate_metrics
from location_verifier.placement.models import PlacementPeer
from location_verifier.placement.reconfiguration import plan_reconfiguration
from location_verifier.placement.topology import FailureDomainTopology


def build_synthetic_topology() -> FailureDomainTopology:
    """Create fixed peers spanning five buildings in two synthetic regions."""

    declarations = [
        ("peer-a1", "HYDERABAD", "CAMPUS", "A1", VerificationStatus.PLAUSIBLE, 0.92),
        ("peer-a2", "HYDERABAD", "CAMPUS", "A1", VerificationStatus.PLAUSIBLE, 0.88),
        ("peer-a3", "HYDERABAD", "CAMPUS", "A2", VerificationStatus.PLAUSIBLE, 0.90),
        ("peer-a4", "HYDERABAD", "CAMPUS", "A3", VerificationStatus.UNCERTAIN, 0.62),
        ("peer-b1", "REMOTE", "REMOTE_DC", "B1", VerificationStatus.PLAUSIBLE, 0.91),
        ("peer-b2", "REMOTE", "REMOTE_DC", "B2", VerificationStatus.SUSPICIOUS, 0.20),
    ]
    peers = []
    for peer_id, region, site, building, status, confidence in declarations:
        claim = PeerClaim(
            peer_id,
            GeoLocation(17.385, 78.4867),
            f"{region}/{site}/{building}",
        )
        result = VerificationResult(
            peer_id,
            claim.claimed_failure_domain,
            status,
            confidence,
            1 - confidence,
            witness_agreement=0.85 if status is not VerificationStatus.SUSPICIOUS else 0.25,
            evidence=({"measurement_quality": 0.9},),
        )
        peers.append(
            PlacementPeer(
                peer_id,
                claim,
                {"region": region, "site": site, "building": building, "floor": "F1"},
                result,
            )
        )
    return FailureDomainTopology(peers=peers)


def main() -> None:
    config = load_config(PROJECT_ROOT / "configs" / "default.yaml").placement
    topology = build_synthetic_topology()
    object_id = "synthetic-object-011"
    baseline = place_baseline(object_id, topology, config)
    fdar = place_fdar(object_id, topology, config)
    baseline_metrics = calculate_metrics(baseline, topology.peers)
    fdar_metrics = calculate_metrics(fdar, topology.peers)

    suspicious_peer = next(
        peer for peer in topology.peers
        if peer.verification_status is VerificationStatus.SUSPICIOUS
    )
    topology.update_peer(
        replace(
            suspicious_peer,
            verification=replace(
                suspicious_peer.verification,
                status=VerificationStatus.PLAUSIBLE,
                confidence=0.9,
                uncertainty=0.1,
            ),
        )
    )
    trusted_placement = place_fdar(object_id, topology, config)
    peer = topology.get_peer(suspicious_peer.peer_id)
    topology.update_peer(
        replace(
            peer,
            verification=replace(
                peer.verification,
                status=VerificationStatus.SUSPICIOUS,
                confidence=0.2,
                uncertainty=0.8,
            ),
        )
    )
    reconfiguration = plan_reconfiguration(trusted_placement, topology, config)

    payload = {
        "label": "SYNTHETIC SIMULATION; not measured network/accuracy data",
        "baseline": baseline.to_dict(),
        "fdar": fdar.to_dict(),
        "baseline_metrics": baseline_metrics.__dict__ if hasattr(baseline_metrics, "__dict__") else {
            key: getattr(baseline_metrics, key) for key in baseline_metrics.__dataclass_fields__
        },
        "fdar_metrics": fdar_metrics.__dict__ if hasattr(fdar_metrics, "__dict__") else {
            key: getattr(fdar_metrics, key) for key in fdar_metrics.__dataclass_fields__
        },
        "reconfiguration": {
            "success": reconfiguration.success,
            "invalidated_peer_ids": list(reconfiguration.invalidated_peer_ids),
            "required_moves": reconfiguration.required_moves,
            "reason": reconfiguration.reason,
            "proposed_placement": reconfiguration.proposed_placement.to_dict(),
        },
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
