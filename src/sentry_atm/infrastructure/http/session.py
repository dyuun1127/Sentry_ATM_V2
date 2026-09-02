"""Minimal WSGI adapter for the Golden Demo Session APIs."""

import json
from collections.abc import Callable, Iterable
from http import HTTPStatus

from sentry_atm.api import (
    GoldenDemoSessionApiContract,
    GoldenDemoSessionCommand,
    GoldenDemoSessionCommandApiContract,
)

type StartResponse = Callable[[str, list[tuple[str, str]]], object]
type WsgiResponse = Iterable[bytes]

_SESSION_PATH = "/api/v1/golden-demo/session"
_COMMAND_PATH = "/api/v1/golden-demo/session/commands"
_MAX_REQUEST_BODY_BYTES = 16_384


class GoldenDemoSessionWsgiApp:
    """Expose current Session state and fixed checkpoint Commands through WSGI."""

    __slots__ = ("_command_api", "_read_api")

    def __init__(
        self,
        read_api: GoldenDemoSessionApiContract,
        command_api: GoldenDemoSessionCommandApiContract,
    ) -> None:
        if not isinstance(read_api, GoldenDemoSessionApiContract):
            raise TypeError("read_api must implement GoldenDemoSessionApiContract")
        if not isinstance(command_api, GoldenDemoSessionCommandApiContract):
            raise TypeError("command_api must implement GoldenDemoSessionCommandApiContract")
        if command_api.read_api is not read_api:
            raise ValueError("read_api and command_api must share one Session source")
        self._read_api = read_api
        self._command_api = command_api

    def __call__(
        self,
        environ: dict[str, object],
        start_response: StartResponse,
    ) -> WsgiResponse:
        try:
            method = _environ_text(environ, "REQUEST_METHOD", default="GET").upper()
            path = _environ_text(environ, "PATH_INFO", default="/")
            if path == _SESSION_PATH:
                if method != "GET":
                    raise _HttpError(
                        HTTPStatus.METHOD_NOT_ALLOWED,
                        "METHOD_NOT_ALLOWED",
                        "use GET",
                        headers=(("Allow", "GET"),),
                    )
                return self._get_current(environ, start_response)
            if path == _COMMAND_PATH:
                if method != "POST":
                    raise _HttpError(
                        HTTPStatus.METHOD_NOT_ALLOWED,
                        "METHOD_NOT_ALLOWED",
                        "use POST",
                        headers=(("Allow", "POST"),),
                    )
                return self._execute(environ, start_response)
            raise _HttpError(HTTPStatus.NOT_FOUND, "ROUTE_NOT_FOUND", "route not found")
        except _HttpError as error:
            return _json_response(
                start_response,
                error.status,
                {"error": {"code": error.code, "message": error.message}},
                extra_headers=error.headers,
            )

    def _get_current(
        self,
        environ: dict[str, object],
        start_response: StartResponse,
    ) -> WsgiResponse:
        _reject_query(environ)
        return _json_response(
            start_response,
            HTTPStatus.OK,
            self._read_api.get_current().to_dict(),
        )

    def _execute(
        self,
        environ: dict[str, object],
        start_response: StartResponse,
    ) -> WsgiResponse:
        _reject_query(environ)
        payload = _read_json_object(environ)
        if set(payload) != {"command"}:
            raise _HttpError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "INVALID_REQUEST",
                "body must contain only command",
            )
        try:
            command_value = payload["command"]
            if not isinstance(command_value, str):
                raise TypeError("command must be text")
            command = GoldenDemoSessionCommand(command_value)
        except (TypeError, ValueError) as error:
            raise _HttpError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "INVALID_REQUEST",
                str(error),
            ) from None
        try:
            current = self._command_api.execute(command)
        except ValueError as error:
            raise _HttpError(
                HTTPStatus.CONFLICT,
                "SESSION_STATE_CONFLICT",
                str(error),
            ) from None
        return _json_response(start_response, HTTPStatus.OK, current.to_dict())


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
        raise _HttpError(
            HTTPStatus.BAD_REQUEST,
            "INVALID_ENVIRONMENT",
            f"{key} must be text",
        )
    return value


def _reject_query(environ: dict[str, object]) -> None:
    if _environ_text(environ, "QUERY_STRING", default=""):
        raise _HttpError(
            HTTPStatus.BAD_REQUEST,
            "INVALID_QUERY",
            "query parameters are not supported",
        )


def _read_json_object(environ: dict[str, object]) -> dict[str, object]:
    content_type = _environ_text(environ, "CONTENT_TYPE", default="")
    if content_type.split(";", maxsplit=1)[0].strip().lower() != "application/json":
        raise _HttpError(
            HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
            "UNSUPPORTED_MEDIA_TYPE",
            "Content-Type must be application/json",
        )
    content_length_text = _environ_text(environ, "CONTENT_LENGTH", default="")
    try:
        content_length = int(content_length_text)
    except ValueError:
        raise _HttpError(
            HTTPStatus.BAD_REQUEST,
            "INVALID_CONTENT_LENGTH",
            "Content-Length must be an integer",
        ) from None
    if content_length < 0:
        raise _HttpError(
            HTTPStatus.BAD_REQUEST,
            "INVALID_CONTENT_LENGTH",
            "Content-Length must be non-negative",
        )
    if content_length > _MAX_REQUEST_BODY_BYTES:
        raise _HttpError(
            HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            "REQUEST_TOO_LARGE",
            "request body exceeds 16384 bytes",
        )
    stream = environ.get("wsgi.input")
    if not hasattr(stream, "read"):
        raise _HttpError(
            HTTPStatus.BAD_REQUEST,
            "INVALID_ENVIRONMENT",
            "wsgi.input must be readable",
        )
    try:
        raw_body = stream.read(content_length)  # type: ignore[union-attr]
        if not isinstance(raw_body, bytes) or len(raw_body) != content_length:
            raise _HttpError(
                HTTPStatus.BAD_REQUEST,
                "INVALID_BODY_LENGTH",
                "request body length does not match Content-Length",
            )
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _HttpError(
            HTTPStatus.BAD_REQUEST,
            "INVALID_JSON",
            "request body must be valid UTF-8 JSON",
        ) from None
    if not isinstance(payload, dict):
        raise _HttpError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "INVALID_REQUEST",
            "request body must be a JSON object",
        )
    return payload


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
