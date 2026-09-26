"""Collect one real measurement batch; this script does not verify location."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from location_verifier.config import load_config
from location_verifier.logging_config import configure_logging
from location_verifier.measurement.collector import (
    MeasurementCollectionError,
    collect_measurements,
)
from location_verifier.measurement.storage import save_measurement_batch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "configs" / "default.yaml")
    parser.add_argument("--target-host", default=os.getenv("FDAR_TARGET_HOST"))
    parser.add_argument("--target-peer-id", default=os.getenv("FDAR_TARGET_PEER_ID"))
    parser.add_argument("--witness-id", default=os.getenv("FDAR_WITNESS_ID"))
    arguments = parser.parse_args()
    if not arguments.target_host or not arguments.target_peer_id or not arguments.witness_id:
        parser.error("--target-host, --target-peer-id, and --witness-id (or matching environment variables) are required")

    config = load_config(arguments.config)
    if config.witnesses and arguments.witness_id not in {
        witness.witness_id for witness in config.witnesses
    }:
        parser.error("witness ID is not present in the selected configuration")
    configure_logging(config.log_level)
    try:
        batch = collect_measurements(
            host=arguments.target_host,
            samples=config.measurement.samples,
            timeout_seconds=config.measurement.timeout_seconds,
            interval_seconds=config.measurement.interval_seconds,
            witness_id=arguments.witness_id,
            target_peer_id=arguments.target_peer_id,
        )
    except MeasurementCollectionError as exc:
        logging.getLogger(__name__).error("Measurement collection stopped: %s", exc.status.value)
        return 2

    raw_path, features_path = save_measurement_batch(
        batch,
        PROJECT_ROOT / "data" / "raw",
        PROJECT_ROOT / "data" / "processed",
    )
    features = batch.features
    print("Measurement complete (evidence collection only)")
    print(f"Witness: {batch.witness_id}")
    print(f"Target: {batch.target_peer_id}")
    print(f"Status: {batch.status.value}")
    print(f"Samples: {features.sample_count}")
    print(f"Successful: {features.successful_count}")
    print(f"Timeouts: {features.timeout_count}")
    print(f"Packet loss: {features.packet_loss_rate:.1%}")
    for label, value in (
        ("Median RTT", features.median_rtt_ms),
        ("P95 RTT", features.p95_rtt_ms),
        ("Jitter", features.jitter_ms),
        ("MAD", features.mad_rtt_ms),
    ):
        print(f"{label}: {value:.3f} ms" if value is not None else f"{label}: unavailable")
    print(f"Raw CSV: {raw_path.relative_to(PROJECT_ROOT)}")
    print(f"Features JSON: {features_path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
