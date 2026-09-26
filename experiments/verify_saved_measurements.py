"""Apply Phase 3 inference to a saved Phase 2 batch and explicit witness metadata."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from location_verifier.config import load_config
from location_verifier.inference.verifier import load_saved_witness_evidence, verify
from location_verifier.models import GeoLocation, PeerClaim, Witness


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--witness-id", required=True)
    parser.add_argument("--witness-latitude", type=float, required=True)
    parser.add_argument("--witness-longitude", type=float, required=True)
    parser.add_argument("--witness-reliability", type=float, default=0.5)
    parser.add_argument("--claimed-latitude", type=float, required=True)
    parser.add_argument("--claimed-longitude", type=float, required=True)
    parser.add_argument("--claimed-failure-domain", required=True)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "configs" / "default.yaml")
    arguments = parser.parse_args()

    witness = Witness(
        arguments.witness_id,
        GeoLocation(arguments.witness_latitude, arguments.witness_longitude),
        reliability_score=arguments.witness_reliability,
    )
    witness_evidence = load_saved_witness_evidence(arguments.input, witness)
    claim = PeerClaim(
        witness_evidence.target_peer_id,
        GeoLocation(arguments.claimed_latitude, arguments.claimed_longitude),
        arguments.claimed_failure_domain,
    )
    result = verify(claim, [witness_evidence], load_config(arguments.config).inference)
    print(f"Peer: {result.peer_id}")
    print(f"Claimed failure domain: {result.claimed_failure_domain}")
    print(f"Status: {result.status.value}")
    print(f"Evidence-strength score: {result.confidence:.3f} (not probability)")
    print(f"Uncertainty: {result.uncertainty:.3f}")
    print("A single saved batch is expected to be INSUFFICIENT_EVIDENCE with default settings.")
    print("This is a consistency estimate, not proof of physical location.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
