"""Raw measurement and processed feature export for reproducible analysis."""

from __future__ import annotations

import csv
from dataclasses import asdict
import json
from pathlib import Path
import re

from .collector import MeasurementBatch


def _filename_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "item"


def save_measurement_batch(
    batch: MeasurementBatch,
    raw_directory: str | Path,
    processed_directory: str | Path,
) -> tuple[Path, Path]:
    """Save one batch's raw observations as CSV and summary/features as JSON."""

    timestamp = batch.started_at.strftime("%Y%m%dT%H%M%S%fZ")
    stem = (
        f"{timestamp}_{_filename_part(batch.witness_id)}_"
        f"{_filename_part(batch.target_peer_id)}"
    )
    raw_path = Path(raw_directory) / f"{stem}_observations.csv"
    processed_path = Path(processed_directory) / f"{stem}_features.json"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    processed_path.parent.mkdir(parents=True, exist_ok=True)

    with raw_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=(
                "witness_id",
                "target_peer_id",
                "host",
                "batch_status",
                "timestamp",
                "rtt_ms",
                "timed_out",
                "failure_reason",
            ),
        )
        writer.writeheader()
        for observation in batch.observations:
            writer.writerow(
                {
                    "witness_id": batch.witness_id,
                    "target_peer_id": batch.target_peer_id,
                    "host": batch.host,
                    "batch_status": batch.status.value,
                    "timestamp": observation.timestamp.isoformat(),
                    "rtt_ms": observation.rtt_ms,
                    "timed_out": observation.timed_out,
                    "failure_reason": (
                        observation.failure_reason.value
                        if observation.failure_reason is not None
                        else ""
                    ),
                }
            )

    payload = {
        "witness_id": batch.witness_id,
        "target_peer_id": batch.target_peer_id,
        "host": batch.host,
        "started_at": batch.started_at.isoformat(),
        "completed_at": batch.completed_at.isoformat(),
        "status": batch.status.value,
        "observations": [
            {
                "timestamp": item.timestamp.isoformat(),
                "rtt_ms": item.rtt_ms,
                "timed_out": item.timed_out,
                "failure_reason": (
                    item.failure_reason.value if item.failure_reason is not None else None
                ),
            }
            for item in batch.observations
        ],
        "features": asdict(batch.features),
    }
    processed_path.write_text(
        json.dumps(payload, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return raw_path, processed_path
