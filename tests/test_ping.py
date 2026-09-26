import subprocess

import pytest

from location_verifier.measurement.ping import (
    PingStatus,
    RealPingSource,
    build_ping_command,
    parse_ping_output,
)


@pytest.mark.parametrize(
    ("stdout", "expected_rtt"),
    [
        ("Reply from 192.0.2.1: time=12ms", 12.0),
        ("64 bytes from host: time=12.5 ms", 12.5),
        ("64 bytes from host: time<1ms", 1.0),
    ],
)
def test_parse_successful_ping_output(stdout: str, expected_rtt: float) -> None:
    result = parse_ping_output(stdout)

    assert result.status is PingStatus.SUCCESS
    assert result.rtt_ms == expected_rtt


def test_parse_timeout_unreachable_and_malformed_output() -> None:
    assert parse_ping_output("Request timed out.").status is PingStatus.TIMEOUT
    assert (
        parse_ping_output("Destination host unreachable").status
        is PingStatus.TARGET_UNREACHABLE
    )
    assert parse_ping_output("unexpected response", returncode=0).status is PingStatus.MALFORMED_OUTPUT


@pytest.mark.parametrize(
    ("platform_name", "expected"),
    [
        ("win32", ["ping", "-n", "1", "-w", "1500", "example.org"]),
        ("linux", ["ping", "-n", "-c", "1", "-W", "2", "example.org"]),
        ("darwin", ["ping", "-n", "-c", "1", "-W", "1500", "example.org"]),
    ],
)
def test_build_platform_specific_ping_arguments(
    platform_name: str, expected: list[str]
) -> None:
    assert build_ping_command("example.org", 1.5, platform_name) == expected


@pytest.mark.parametrize("host", ["-n", "bad host", "host;whoami", "bad..host"])
def test_invalid_target_is_rejected(host: str) -> None:
    with pytest.raises(ValueError):
        build_ping_command(host, 1.0, "linux")


def test_real_ping_source_uses_argument_list_without_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("location_verifier.measurement.ping.shutil.which", lambda _: "ping")
    seen: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen["command"] = command
        seen.update(kwargs)
        return subprocess.CompletedProcess(command, 0, "time=8.5 ms", "")

    monkeypatch.setattr("location_verifier.measurement.ping.subprocess.run", fake_run)
    result = RealPingSource("linux").ping_once("example.org", 1.0)

    assert result.status is PingStatus.SUCCESS
    assert result.rtt_ms == 8.5
    assert seen["shell"] is False
    assert seen["capture_output"] is True
    assert seen["command"][-1] == "example.org"


def test_real_ping_source_handles_missing_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("location_verifier.measurement.ping.shutil.which", lambda _: None)

    result = RealPingSource("linux").ping_once("example.org", 1.0)

    assert result.status is PingStatus.PING_COMMAND_UNAVAILABLE


def test_real_ping_source_handles_subprocess_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("location_verifier.measurement.ping.shutil.which", lambda _: "ping")

    def fake_run(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired("ping", 2)

    monkeypatch.setattr("location_verifier.measurement.ping.subprocess.run", fake_run)
    result = RealPingSource("linux").ping_once("example.org", 1.0)

    assert result.status is PingStatus.TIMEOUT
