"""Same-origin static Web UI shell around the Golden Demo Session API.

스코프 배경 형상도 여기서 낸다. 공역·활주로·픽스·지형은 시나리오와 무관하고
시간에 따라 변하지 않으므로, 세션 API 의 매 초 갱신되는 읽기 모델에 실어 보내면
같은 30 KB 를 초당 한 번씩 다시 보내게 된다. 한 번 받아 두고 쓰는 것이 맞다.
"""

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from http import HTTPStatus
from importlib.resources import files

from sentry_atm.infrastructure.http.session import GoldenDemoSessionWsgiApp

type StartResponse = Callable[[str, list[tuple[str, str]]], object]
type WsgiResponse = Iterable[bytes]

_STATIC_PACKAGE = "sentry_atm.infrastructure.http"
_GEOMETRY_PATH = "/api/v1/reference/geometry"
_SECURITY_HEADERS = (
    ("Cache-Control", "no-store"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    (
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
        "base-uri 'none'; frame-ancestors 'none'",
    ),
)


@dataclass(frozen=True, slots=True)
class _StaticAsset:
    body: bytes
    content_type: str


class GoldenDemoWebWsgiApp:
    """Serve the UI shell and delegate every non-static route to the Session API."""

    __slots__ = ("_api_app", "_assets")

    def __init__(self, api_app: GoldenDemoSessionWsgiApp) -> None:
        if not isinstance(api_app, GoldenDemoSessionWsgiApp):
            raise TypeError("api_app must be a GoldenDemoSessionWsgiApp")
        self._api_app = api_app
        self._assets = _load_assets()

    @property
    def api_app(self) -> GoldenDemoSessionWsgiApp:
        return self._api_app

    def __call__(
        self,
        environ: dict[str, object],
        start_response: StartResponse,
    ) -> WsgiResponse:
        path = environ.get("PATH_INFO", "/")
        if not isinstance(path, str):
            return _text_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                b"invalid WSGI environment",
            )
        if path == _GEOMETRY_PATH:
            asset = _geometry_asset()
        else:
            asset = self._assets.get(path)
        if asset is None:
            return self._api_app(environ, start_response)

        method = environ.get("REQUEST_METHOD", "GET")
        if not isinstance(method, str):
            return _text_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                b"invalid WSGI environment",
            )
        method = method.upper()
        if method not in {"GET", "HEAD"}:
            return _text_response(
                start_response,
                HTTPStatus.METHOD_NOT_ALLOWED,
                b"use GET or HEAD",
                extra_headers=(("Allow", "GET, HEAD"),),
            )
        return _asset_response(
            start_response,
            asset,
            include_body=method == "GET",
        )


_geometry_cache: _StaticAsset | None = None


def _geometry_asset() -> _StaticAsset:
    """스코프 배경. 시나리오와 무관하므로 한 번 만들어 두고 돌려준다."""
    global _geometry_cache
    if _geometry_cache is None:
        from sentry_atm.api.geometry import scope_geometry

        _geometry_cache = _StaticAsset(
            json.dumps(scope_geometry(), ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
        )
    return _geometry_cache


def _load_assets() -> dict[str, _StaticAsset]:
    root = files(_STATIC_PACKAGE).joinpath("static")
    index = _StaticAsset(
        root.joinpath("index.html").read_bytes(),
        "text/html; charset=utf-8",
    )
    return {
        "/": index,
        "/index.html": index,
        "/assets/app.css": _StaticAsset(
            root.joinpath("app.css").read_bytes(),
            "text/css; charset=utf-8",
        ),
        "/assets/app.js": _StaticAsset(
            root.joinpath("app.js").read_bytes(),
            "text/javascript; charset=utf-8",
        ),
    }


def _asset_response(
    start_response: StartResponse,
    asset: _StaticAsset,
    *,
    include_body: bool,
) -> WsgiResponse:
    start_response(
        "200 OK",
        [
            ("Content-Type", asset.content_type),
            ("Content-Length", str(len(asset.body))),
            *_SECURITY_HEADERS,
        ],
    )
    return (asset.body,) if include_body else ()


def _text_response(
    start_response: StartResponse,
    status: HTTPStatus,
    body: bytes,
    *,
    extra_headers: tuple[tuple[str, str], ...] = (),
) -> WsgiResponse:
    start_response(
        f"{status.value} {status.phrase}",
        [
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Content-Length", str(len(body))),
            *_SECURITY_HEADERS,
            *extra_headers,
        ],
    )
    return (body,)
