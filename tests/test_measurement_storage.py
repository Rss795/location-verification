import csv
import json
from datetime import datetime, timezone

from location_verifier.measurement.collector import collect_measurements
from location_verifier.measurement.ping import PingResult, PingStatus
from location_verifier.measurement.storage import save_measurement_batch


class OneResultSource:
    def ping_once(self, host: str, timeout_seconds: float) -> PingResult:
        assert host == "example.org"
        assert timeout_seconds == 2.0
        return PingResult(PingStatus.SUCCESS, 12.5)


def test_batch_exports_raw_csv_and_feature_json(tmp_path) -> None:
    batch = collect_measurements(
        "example.org",
        samples=1,
        interval_seconds=0,
        source=OneResultSource(),
        witness_id="witness/one",
        target_peer_id="peer:one",
        clock=lambda: datetime(2026, 9, 26, tzinfo=timezone.utc),
    )

    raw_path, features_path = save_measurement_batch(
        batch, tmp_path / "raw", tmp_path / "processed"
    )

    with raw_path.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    payload = json.loads(features_path.read_text(encoding="utf-8"))
    assert len(rows) == 1
    assert rows[0]["rtt_ms"] == "12.5"
    assert payload["observations"][0]["rtt_ms"] == 12.5
    assert payload["features"]["median_rtt_ms"] == 12.5
    assert "/" not in raw_path.name and ":" not in features_path.name
