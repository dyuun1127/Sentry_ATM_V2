import pytest

import sentry_atm.infrastructure.http.release_check as release_check
from sentry_atm.infrastructure.http.release_check import (
    GoldenDemoReleasePreflightFailure,
    GoldenDemoReleasePreflightReport,
    print_golden_demo_release_preflight_report,
    run_golden_demo_release_preflight,
)


def test_release_preflight_verifies_runtime_assets_offline_and_loopback() -> None:
    report = run_golden_demo_release_preflight()

    assert tuple(item.code for item in report.checks) == (
        "PYTHON",
        "PACKAGE",
        "ASSETS",
        "OFFLINE",
        "LOOPBACK",
    )
    assert report.checks[0].detail.endswith(">= 3.12")
    assert report.checks[1].detail == "sentry-atm 0.1.0"
    assert report.checks[-1].detail == "default server host is 127.0.0.1"


def test_preflight_rejects_unsupported_python_external_assets_and_non_loopback() -> None:
    with pytest.raises(GoldenDemoReleasePreflightFailure, match="3.12 or newer"):
        release_check._require_supported_python((3, 11, 9))

    with pytest.raises(GoldenDemoReleasePreflightFailure, match="external URL"):
        release_check._require_offline_assets(
            {"index.html": b'<script src="https://example.invalid/app.js"></script>'}
        )

    with pytest.raises(GoldenDemoReleasePreflightFailure, match="only to 127.0.0.1"):
        release_check._require_loopback_host("0.0.0.0")
    with pytest.raises(GoldenDemoReleasePreflightFailure, match="not a valid IP"):
        release_check._require_loopback_host("localhost")


def test_preflight_report_printer_is_stable_and_validates_input(capsys) -> None:
    report = run_golden_demo_release_preflight()

    print_golden_demo_release_preflight_report(report)

    output = capsys.readouterr().out
    assert "[PASS] PYTHON" in output
    assert "[PASS] LOOPBACK" in output
    assert "RELEASE PREFLIGHT PASSED (5 checks)" in output
    with pytest.raises(TypeError, match="GoldenDemoReleasePreflightReport"):
        print_golden_demo_release_preflight_report(object())  # type: ignore[arg-type]

    assert isinstance(report, GoldenDemoReleasePreflightReport)
