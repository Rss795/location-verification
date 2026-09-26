from pathlib import Path

import pytest

from location_verifier.config import load_config


PROJECT_ROOT = Path(__file__).parents[1]


def test_default_config_loads_without_bundled_real_witnesses() -> None:
    config = load_config(PROJECT_ROOT / "configs" / "default.yaml")

    assert config.measurement.samples == 50
    assert config.measurement.timeout_seconds == 2.0
    assert config.witnesses == ()


def test_config_loads_witness_metadata(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "measurement:\n  samples: 12\nwitnesses:\n"
        "  - id: w1\n    host: witness.example\n"
        "    location:\n      latitude: 10\n      longitude: 20\n",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.measurement.samples == 12
    assert config.witnesses[0].witness_id == "w1"
    assert config.witnesses[0].location.longitude == 20


def test_config_accepts_phase_two_witness_id_key(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "witnesses:\n  - witness_id: w2\n    host: localhost\n"
        "    location:\n      latitude: 0\n      longitude: 0\n",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.witnesses[0].witness_id == "w2"


def test_config_rejects_invalid_measurement_settings(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("measurement:\n  samples: 0\n", encoding="utf-8")

    with pytest.raises(ValueError, match="at least 1"):
        load_config(config_path)


def test_config_rejects_non_finite_measurement_settings(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("measurement:\n  timeout_seconds: .nan\n", encoding="utf-8")

    with pytest.raises(ValueError, match="finite and positive"):
        load_config(config_path)
