"""Machine-readable JSON and CSV outputs for evaluation runs."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def write_results(results: dict[str, Any], output_dir: str | Path) -> dict[str, Path]:
    """Write manifest/raw records/aggregates in JSON and raw records in CSV."""

    root = Path(output_dir)
    raw_dir = root / "raw"
    aggregate_dir = root / "aggregated"
    raw_dir.mkdir(parents=True, exist_ok=True)
    aggregate_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "evaluation_manifest.json"
    records_path = raw_dir / "evaluation_records.json"
    csv_path = raw_dir / "evaluation_records.csv"
    aggregate_path = aggregate_dir / "evaluation_summary.json"
    manifest_path.write_text(
        json.dumps(results["manifest"], indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    records_path.write_text(
        json.dumps(results["records"], indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    aggregate_path.write_text(
        json.dumps(results["aggregated"], indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    fieldnames = sorted({key for item in results["records"] for key in item})
    with csv_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for record in results["records"]:
            writer.writerow(
                {
                    key: json.dumps(value, sort_keys=True, allow_nan=False)
                    if isinstance(value, (dict, list, tuple))
                    else value
                    for key, value in record.items()
                }
            )
    return {
        "manifest": manifest_path,
        "records_json": records_path,
        "records_csv": csv_path,
        "aggregated_json": aggregate_path,
    }
