"""Local server for the Golden Demo Session WSGI app.

기본은 루프백 전용이다. `--host` 로 명시했을 때만 밖으로 열리며, 열리는 순간
밖에서 온 요청은 읽기만 된다 — 까닭은 `access.py` 에 적었다.
"""

from argparse import ArgumentParser, ArgumentTypeError
from collections.abc import Sequence
from dataclasses import dataclass
from wsgiref.simple_server import WSGIServer, make_server

from sentry_atm.infrastructure.http.access import (
    CONTROL_MODES,
    LOOPBACK_ADDRESSES,
    ViewerGuard,
)
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

    host: str = _LOOPBACK_HOST
    """어디에 붙일 것인가. 기본은 루프백이며, 밖으로 여는 것은 명시해야 한다."""

    control: str = "local"
    """누가 조작할 수 있는가 — "local"(루프백 직접) 또는 "any"."""

    def __post_init__(self) -> None:
        if type(self.port) is not int or not 0 <= self.port <= 65_535:
            raise ValueError("port must be an integer from 0 through 65535")
        if self.scenario not in _SESSION_BUILDERS:
            raise ValueError(
                f"scenario must be one of {sorted(_SESSION_BUILDERS)}"
            )
        if not isinstance(self.host, str) or not self.host:
            raise ValueError("host must be a non-empty string")
        if self.control not in CONTROL_MODES:
            raise ValueError(f"control must be one of {list(CONTROL_MODES)}")

    @property
    def external(self) -> bool:
        """루프백 밖으로 열려 있는가."""
        return self.host not in LOOPBACK_ADDRESSES


def create_local_golden_demo_server(
    settings: LocalGoldenDemoServerSettings | None = None,
) -> WSGIServer:
    """Bind one fresh Golden Demo Session Runtime to the IPv4 loopback interface."""

    resolved = settings or LocalGoldenDemoServerSettings()
    runtime = _SESSION_BUILDERS[resolved.scenario]()
    web_app = GoldenDemoWebWsgiApp(runtime.http_app, runtime, settings=resolved)
    # 겉옷은 밖으로 열었을 때만 씌운다. 루프백 전용일 때는 씌워도 통과할 뿐이지만,
    # 없는 편이 경로가 짧고 무엇이 도는지가 분명하다.
    served = ViewerGuard(web_app, control=resolved.control) if resolved.external else web_app
    return make_server(
        resolved.host,
        resolved.port,
        served,
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

    resolved = settings or LocalGoldenDemoServerSettings()
    with create_local_golden_demo_server(resolved) as server:
        url = f"http://{server.server_address[0]}:{server.server_port}"
        print(f"SENTRY ATM Golden Demo API: {url}")
        _print_exposure(resolved, server.server_port)
        print("Press Ctrl+C to stop.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("SENTRY ATM Golden Demo API stopped.")
    return 0


def _print_exposure(settings: LocalGoldenDemoServerSettings, port: int) -> None:
    """밖으로 열었으면 그 사실을 조용히 지나가지 않는다."""
    if not settings.external:
        return
    print()
    print("  ** 외부 공개 중 — 이 데모는 인증이 없고 세션이 하나다. **")
    print(f"     바인드 {settings.host}:{port}")
    if settings.control == "any":
        print("     조작 권한: 누구나 (--control any). 주소를 아는 사람이 시연을 바꿀 수 있다.")
    else:
        print("     조작 권한: 이 기계의 루프백 요청만. 밖에서는 읽기만 된다.")
        print(f"     발표자는 http://127.0.0.1:{port} 로 직접 연다.")
    print("     공개 인터넷에 두지 않는다. 끝나면 Ctrl+C 로 닫는다.")
    print()


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
        "--host",
        default=_LOOPBACK_HOST,
        help=(
            "interface to bind (default: %(default)s). "
            "Anything else opens the demo to other machines and makes every "
            "remote request read-only unless --control any is given."
        ),
    )
    parser.add_argument(
        "--control",
        default="local",
        choices=list(CONTROL_MODES),
        help=(
            "who may send commands when bound outside loopback: "
            "local (default, the operator on this machine) or any"
        ),
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
            host=arguments.host,
            control=arguments.control,
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
