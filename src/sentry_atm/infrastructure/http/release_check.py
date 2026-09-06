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

# XML 이름공간 식별자. 생김새는 URL 이지만 가져오는 자원이 아니라 이름이며,
# SVG 요소를 만들려면 이 문자열이 반드시 있어야 한다 (`createElementNS`).
#
# 문자열을 쪼개 검사를 피하지 않는다. 그렇게 하면 진짜 외부 자원도 같은 방법으로
# 숨길 수 있게 되어 검사가 아무것도 지키지 못한다. 허용하는 것을 적어 두면
# 무엇이 예외인지 남는다.
_ALLOWED_URIS = (b"http://www.w3.org/2000/svg",)


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
        # 기본값이 여전히 루프백인지를 본다. `--host` 로 밖에 여는 것은 명시적인
        # 선택이며, 그때는 서버가 시작하면서 큰 글씨로 알린다. 이 검문소가
        # 보증하는 것은 **아무것도 안 주고 띄웠을 때 밖으로 새지 않는다**는 것이다.
        GoldenDemoReleasePreflightCheck("LOOPBACK", f"default server host is {host}"),
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
        for allowed in _ALLOWED_URIS:
            lowered = lowered.replace(allowed, b"")
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
