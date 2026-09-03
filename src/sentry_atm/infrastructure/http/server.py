"""Loopback-only local server for the Golden Demo Session WSGI app."""

from argparse import ArgumentParser, ArgumentTypeError
from collections.abc import Sequence
from dataclasses import dataclass
from wsgiref.simple_server import WSGIServer, make_server

from sentry_atm.infrastructure.http.web import GoldenDemoWebWsgiApp
from sentry_atm.runtime import build_golden_demo_session_runtime

_LOOPBACK_HOST = "127.0.0.1"
_DEFAULT_PORT = 8000


@dataclass(frozen=True, slots=True)
class LocalGoldenDemoServerSettings:
    """Validated process-local server settings with a fixed loopback host."""

    port: int = _DEFAULT_PORT

    def __post_init__(self) -> None:
        if type(self.port) is not int or not 0 <= self.port <= 65_535:
            raise ValueError("port must be an integer from 0 through 65535")

    @property
    def host(self) -> str:
        return _LOOPBACK_HOST


def create_local_golden_demo_server(
    settings: LocalGoldenDemoServerSettings | None = None,
) -> WSGIServer:
    """Bind one fresh Golden Demo Session Runtime to the IPv4 loopback interface."""

    resolved = settings or LocalGoldenDemoServerSettings()
    runtime = build_golden_demo_session_runtime()
    web_app = GoldenDemoWebWsgiApp(runtime.http_app)
    return make_server(resolved.host, resolved.port, web_app)


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
    arguments = parser.parse_args(argv)
    return run_local_golden_demo_server(LocalGoldenDemoServerSettings(port=arguments.port))


def _cli_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise ArgumentTypeError("port must be an integer") from error
    if not 1 <= port <= 65_535:
        raise ArgumentTypeError("port must be from 1 through 65535")
    return port
