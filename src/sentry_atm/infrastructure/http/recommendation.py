"""Minimal read-only WSGI adapter for the Recommendation application API."""

import json
from collections.abc import Callable, Iterable
from http import HTTPStatus

from sentry_atm.api import RecommendationApiContract

type StartResponse = Callable[[str, list[tuple[str, str]]], object]
type WsgiResponse = Iterable[bytes]

_RECOMMENDATION_PATH = "/api/v1/recommendations/current"


class RecommendationWsgiApp:
    """Expose only the current Recommendation read endpoint."""

    __slots__ = ("_api",)

    def __init__(self, api: RecommendationApiContract) -> None:
        if not isinstance(api, RecommendationApiContract):
            raise TypeError("api must implement RecommendationApiContract")
        self._api = api

    def __call__(
        self,
        environ: dict[str, object],
        start_response: StartResponse,
    ) -> WsgiResponse:
        try:
            method = _environ_text(environ, "REQUEST_METHOD", default="GET").upper()
            path = _environ_text(environ, "PATH_INFO", default="/")
            if path != _RECOMMENDATION_PATH:
                raise _HttpError(HTTPStatus.NOT_FOUND, "ROUTE_NOT_FOUND", "route not found")
            if method != "GET":
                raise _HttpError(
                    HTTPStatus.METHOD_NOT_ALLOWED,
                    "METHOD_NOT_ALLOWED",
                    "use GET",
                    headers=(("Allow", "GET"),),
                )
            query = _environ_text(environ, "QUERY_STRING", default="")
            if query:
                raise _HttpError(
                    HTTPStatus.BAD_REQUEST,
                    "INVALID_QUERY",
                    "query parameters are not supported",
                )
            current = self._api.get_current()
            if current is None:
                return _empty_response(start_response, HTTPStatus.NO_CONTENT)
            return _json_response(start_response, HTTPStatus.OK, current.to_dict())
        except _HttpError as error:
            return _json_response(
                start_response,
                error.status,
                {"error": {"code": error.code, "message": error.message}},
                extra_headers=error.headers,
            )


class _HttpError(Exception):
    def __init__(
        self,
        status: HTTPStatus,
        code: str,
        message: str,
        *,
        headers: tuple[tuple[str, str], ...] = (),
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers


def _environ_text(
    environ: dict[str, object],
    key: str,
    *,
    default: str,
) -> str:
    value = environ.get(key, default)
    if not isinstance(value, str):
        raise _HttpError(HTTPStatus.BAD_REQUEST, "INVALID_ENVIRONMENT", f"{key} must be text")
    return value


def _json_response(
    start_response: StartResponse,
    status: HTTPStatus,
    payload: dict[str, object],
    *,
    extra_headers: tuple[tuple[str, str], ...] = (),
) -> WsgiResponse:
    body = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    start_response(
        f"{status.value} {status.phrase}",
        [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
            *extra_headers,
        ],
    )
    return (body,)


def _empty_response(start_response: StartResponse, status: HTTPStatus) -> WsgiResponse:
    start_response(
        f"{status.value} {status.phrase}",
        [("Content-Length", "0"), ("Cache-Control", "no-store")],
    )
    return (b"",)
