"""Loopback-only local server for the Golden Demo Session WSGI app."""

from argparse import ArgumentParser, ArgumentTypeError
from collections.abc import Sequence
from dataclasses import dataclass
from wsgiref.simple_server import WSGIServer, make_server

from sentry_atm.infrastructure.http.web import GoldenDemoWebWsgiApp
from sentry_atm.runtime import (
    build_golden_demo_session_runtime,
    build_sortie_session_runtime,
)

_LOOPBACK_HOST = "127.0.0.1"
_DEFAULT_PORT = 8000

# 기본값은 소티다. 골든 데모는 8대가 5분 동안 떠 있는 회귀 고정물이고, 시연에서
# 보여줄 것은 13단계 소티다. 기본을 골든 데모로 두면 서버를 그냥 띄웠을 때
# 시연과 다른 것이 나온다.
_DEFAULT_SCENARIO = "sortie"
_SESSION_BUILDERS = {
    "sortie": build_sortie_session_runtime,
    "golden": build_golden_demo_session_runtime,
}


@dataclass(frozen=True, slots=True)
class LocalGoldenDemoServerSettings:
    """Validated process-local server settings with a fixed loopback host."""

    port: int = _DEFAULT_PORT
    scenario: str = _DEFAULT_SCENARIO
    """어떤 시나리오를 돌 것인가 — "sortie" 또는 "golden"."""

    def __post_init__(self) -> None:
        if type(self.port) is not int or not 0 <= self.port <= 65_535:
            raise ValueError("port must be an integer from 0 through 65535")
        if self.scenario not in _SESSION_BUILDERS:
            raise ValueError(
                f"scenario must be one of {sorted(_SESSION_BUILDERS)}"
            )

    @property
    def host(self) -> str:
        return _LOOPBACK_HOST


def create_local_golden_demo_server(
    settings: LocalGoldenDemoServerSettings | None = None,
) -> WSGIServer:
    """Bind one fresh Golden Demo Session Runtime to the IPv4 loopback interface."""

    resolved = settings or LocalGoldenDemoServerSettings()
    runtime = _SESSION_BUILDERS[resolved.scenario]()
    web_app = GoldenDemoWebWsgiApp(runtime.http_app, runtime)
    return make_server(
        resolved.host,
        resolved.port,
        web_app,
        server_class=_ExclusiveWSGIServer,
    )


class _ExclusiveWSGIServer(WSGIServer):
    """이미 그 포트를 쓰고 있으면 조용히 겹치지 않고 실패한다.

    `wsgiref` 는 기본으로 `SO_REUSEADDR` 을 켜는데, Windows 에서 그 옵션은
    **두 프로세스가 같은 포트를 함께 잡도록** 허용한다 (POSIX 와 뜻이 다르다).
    그러면 옛 프로세스를 죽이지 못한 채 새로 띄웠을 때 둘 다 살아 있고, 요청은
    둘 중 하나로 간다 — 코드를 고쳐도 화면이 그대로인 상황이 되며, 무엇이
    잘못됐는지 알아내기가 매우 어렵다. 실제로 그렇게 시간을 썼다.

    겹쳐 뜨느니 못 뜨는 것이 낫다. 포트가 이미 쓰이고 있으면 그 사실이 바로
    드러나야 한다.
    """

    allow_reuse_address = 0


def run_local_golden_demo_server(
    settings: LocalGoldenDemoServerSettings | None = None,
) -> int:
    """Serve until interrupted, closing the listening socket on exit."""

    with create_local_golden_demo_server(settings) as server:
        url = f"http://{server.server_address[0]}:{server.server_port}"
        print(f"SENTRY ATM Golden Demo API: {url}")
        print("Press Ctrl+C to stop.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("SENTRY ATM Golden Demo API stopped.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Parse the local server CLI without permitting a non-loopback bind."""

    parser = ArgumentParser(description="SENTRY ATM local Golden Demo API server")
    parser.add_argument(
        "--port",
        default=_DEFAULT_PORT,
        type=_cli_port,
        help=f"loopback TCP port (default: {_DEFAULT_PORT})",
    )
    parser.add_argument(
        "--scenario",
        default=_DEFAULT_SCENARIO,
        choices=sorted(_SESSION_BUILDERS),
        help=f"which scenario to run (default: {_DEFAULT_SCENARIO})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="run the deterministic end-to-end demo readiness check and exit",
    )
    arguments = parser.parse_args(argv)
    if arguments.check:
        return run_local_golden_demo_check()
    return run_local_golden_demo_server(
        LocalGoldenDemoServerSettings(
            port=arguments.port,
            scenario=arguments.scenario,
        )
    )


def run_local_golden_demo_check() -> int:
    """Run release preflight and regression without loading either for normal serving."""

    from sentry_atm.infrastructure.http.demo_check import (
        GoldenDemoRegressionFailure,
        print_golden_demo_regression_report,
        run_golden_demo_regression,
    )
    from sentry_atm.infrastructure.http.release_check import (
        GoldenDemoReleasePreflightFailure,
        print_golden_demo_release_preflight_report,
        run_golden_demo_release_preflight,
    )

    try:
        preflight = run_golden_demo_release_preflight()
        report = run_golden_demo_regression()
    except (
        GoldenDemoRegressionFailure,
        GoldenDemoReleasePreflightFailure,
        OSError,
    ) as error:
        print(f"[FAIL] {error}")
        return 1
    print_golden_demo_release_preflight_report(preflight)
    print_golden_demo_regression_report(report)
    return 0


def _cli_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise ArgumentTypeError("port must be an integer") from error
    if not 1 <= port <= 65_535:
        raise ArgumentTypeError("port must be from 1 through 65535")
    return port
