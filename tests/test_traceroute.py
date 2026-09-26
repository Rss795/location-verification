import subprocess

from location_verifier.measurement.traceroute import (
    TracerouteStatus,
    collect_traceroute,
)


def test_traceroute_is_optional_when_command_is_missing(monkeypatch) -> None:
    monkeypatch.setattr("location_verifier.measurement.traceroute.shutil.which", lambda _: None)

    result = collect_traceroute("example.org", platform_name="linux")

    assert result.status is TracerouteStatus.UNAVAILABLE


def test_traceroute_returns_structured_hops(monkeypatch) -> None:
    monkeypatch.setattr("location_verifier.measurement.traceroute.shutil.which", lambda _: "traceroute")
    monkeypatch.setattr(
        "location_verifier.measurement.traceroute.subprocess.run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command, 0, "traceroute to host\n 1 192.0.2.1 1.2 ms\n", ""
        ),
    )

    result = collect_traceroute("example.org", platform_name="linux")

    assert result.status is TracerouteStatus.SUCCESS
    assert result.hops == ("1 192.0.2.1 1.2 ms",)


def test_traceroute_invalid_target_does_not_raise() -> None:
    result = collect_traceroute("bad host")

    assert result.status is TracerouteStatus.INVALID_TARGET
