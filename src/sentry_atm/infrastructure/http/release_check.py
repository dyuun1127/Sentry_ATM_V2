"""Fast environment and package preflight for the local Golden Demo release."""

import sys
from dataclasses import dataclass
from importlib.resources import files
from ipaddress import ip_address

from sentry_atm import __version__
from sentry_atm.infrastructure.http.server import LocalGoldenDemoServerSettings

_MINIMUM_PYTHON = (3, 12)
_REQUIRED_ASSETS = ("index.html", "app.css", "app.js")
_EXTERNAL_MARKERS = (b"http://", b"https://", b"//cdn.")


class GoldenDemoReleasePreflightFailure(RuntimeError):
    """Raised when the presentation environment is not release-ready."""


@dataclass(frozen=True, slots=True)
class GoldenDemoReleasePreflightCheck:
    """One deterministic release-readiness check."""

    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class GoldenDemoReleasePreflightReport:
    """Ordered checks completed before the full HTTP regression."""

    checks: tuple[GoldenDemoReleasePreflightCheck, ...]


def run_golden_demo_release_preflight() -> GoldenDemoReleasePreflightReport:
    """Verify the runtime, package assets, offline boundary and loopback policy."""

    python_version = tuple(sys.version_info[:3])
    _require_supported_python(python_version)
    assets = _read_required_assets()
    _require_offline_assets(assets)
    host = LocalGoldenDemoServerSettings(port=0).host
    _require_loopback_host(host)
    checks = (
        GoldenDemoReleasePreflightCheck(
            "PYTHON",
            f"{python_version[0]}.{python_version[1]}.{python_version[2]} >= 3.12",
        ),
        GoldenDemoReleasePreflightCheck("PACKAGE", f"sentry-atm {__version__}"),
        GoldenDemoReleasePreflightCheck(
            "ASSETS",
            "index.html, app.css and app.js packaged and non-empty",
        ),
        GoldenDemoReleasePreflightCheck("OFFLINE", "UI assets contain no external URL"),
        GoldenDemoReleasePreflightCheck("LOOPBACK", f"server host fixed to {host}"),
    )
    return GoldenDemoReleasePreflightReport(checks=checks)


def print_golden_demo_release_preflight_report(
    report: GoldenDemoReleasePreflightReport,
) -> None:
    """Print a stable preflight summary before the scenario regression."""

    if not isinstance(report, GoldenDemoReleasePreflightReport):
        raise TypeError("report must be a GoldenDemoReleasePreflightReport")
    for item in report.checks:
        print(f"[PASS] {item.code:<14} {item.detail}")
    print(f"SENTRY ATM RELEASE PREFLIGHT PASSED ({len(report.checks)} checks)")


def _require_supported_python(version: tuple[int, int, int]) -> None:
    if version[:2] < _MINIMUM_PYTHON:
        raise GoldenDemoReleasePreflightFailure(
            f"Python 3.12 or newer is required; found {version[0]}.{version[1]}.{version[2]}"
        )


def _read_required_assets() -> dict[str, bytes]:
    static_root = files("sentry_atm.infrastructure.http").joinpath("static")
    assets: dict[str, bytes] = {}
    for name in _REQUIRED_ASSETS:
        resource = static_root.joinpath(name)
        try:
            content = resource.read_bytes()
        except (FileNotFoundError, OSError) as error:
            raise GoldenDemoReleasePreflightFailure(
                f"required packaged UI asset is unavailable: {name}"
            ) from error
        if not content:
            raise GoldenDemoReleasePreflightFailure(
                f"required packaged UI asset is empty: {name}"
            )
        assets[name] = content
    return assets


def _require_offline_assets(assets: dict[str, bytes]) -> None:
    for name, content in assets.items():
        lowered = content.lower()
        if any(marker in lowered for marker in _EXTERNAL_MARKERS):
            raise GoldenDemoReleasePreflightFailure(
                f"packaged UI asset contains an external URL: {name}"
            )


def _require_loopback_host(host: str) -> None:
    try:
        address = ip_address(host)
    except ValueError as error:
        raise GoldenDemoReleasePreflightFailure(
            f"Golden Demo server host is not a valid IP address: {host}"
        ) from error
    if not address.is_loopback or host != "127.0.0.1":
        raise GoldenDemoReleasePreflightFailure(
            f"Golden Demo server must bind only to 127.0.0.1; found {host}"
        )
