"""Minimal WSGI adapter for the Exception Queue application API."""

import json
import re
from collections.abc import Callable, Iterable
from datetime import datetime
from http import HTTPStatus
from urllib.parse import parse_qs, unquote

from sentry_atm.api import (
    AcknowledgeExceptionRequest,
    ExceptionQueueApiContract,
)

type StartResponse = Callable[[str, list[tuple[str, str]]], object]
type WsgiResponse = Iterable[bytes]

_ACKNOWLEDGEMENT_PATH = re.compile(r"^/api/v1/exceptions/(?P<exception_id>[^/]+)/acknowledgements$")
_QUEUE_PATH = "/api/v1/exception-queue"
_MAX_REQUEST_BODY_BYTES = 16_384


class ExceptionQueueWsgiApp:
    """Expose Queue query and acknowledgement through a small WSGI boundary."""

    __slots__ = ("_api",)

    def __init__(self, api: ExceptionQueueApiContract) -> None:
        if not isinstance(api, ExceptionQueueApiContract):
            raise TypeError("api must implement ExceptionQueueApiContract")
        self._api = api

    def __call__(
        self,
        environ: dict[str, object],
        start_response: StartResponse,
    ) -> WsgiResponse:
        try:
            method = _environ_text(environ, "REQUEST_METHOD", default="GET").upper()
            path = _environ_text(environ, "PATH_INFO", default="/")
            if path == _QUEUE_PATH:
                if method != "GET":
                    raise _HttpError(
                        HTTPStatus.METHOD_NOT_ALLOWED,
                        "METHOD_NOT_ALLOWED",
                        "use GET",
                        headers=(("Allow", "GET"),),
                    )
                return self._get_queue(environ, start_response)

            match = _ACKNOWLEDGEMENT_PATH.fullmatch(path)
            if match is not None:
                if method != "POST":
                    raise _HttpError(
                        HTTPStatus.METHOD_NOT_ALLOWED,
                        "METHOD_NOT_ALLOWED",
                        "use POST",
                        headers=(("Allow", "POST"),),
                    )
                return self._acknowledge(environ, start_response, match["exception_id"])

            raise _HttpError(HTTPStatus.NOT_FOUND, "ROUTE_NOT_FOUND", "route not found")
        except _HttpError as error:
            return _json_response(
                start_response,
                error.status,
                {"error": {"code": error.code, "message": error.message}},
                extra_headers=error.headers,
            )

    def _get_queue(
        self,
        environ: dict[str, object],
        start_response: StartResponse,
    ) -> WsgiResponse:
        include_resolved = _parse_include_resolved(environ)
        view = self._api.get_current(include_resolved=include_resolved)
        if view is None:
            return _empty_response(start_response, HTTPStatus.NO_CONTENT)
        return _json_response(start_response, HTTPStatus.OK, view.to_dict())

    def _acknowledge(
        self,
        environ: dict[str, object],
        start_response: StartResponse,
        encoded_exception_id: str,
    ) -> WsgiResponse:
        include_resolved = _parse_include_resolved(environ)
        payload = _read_json_object(environ)
        if set(payload) != {"acknowledged_at_utc"}:
            raise _HttpError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "INVALID_REQUEST",
                "body must contain only acknowledged_at_utc",
            )
        try:
            acknowledged_at_utc = _parse_datetime(payload["acknowledged_at_utc"])
            request = AcknowledgeExceptionRequest(
                exception_id=unquote(encoded_exception_id),
                acknowledged_at_utc=acknowledged_at_utc,
            )
            view = self._api.acknowledge(
                request,
                include_resolved=include_resolved,
            )
        except KeyError:
            raise _HttpError(
                HTTPStatus.NOT_FOUND,
                "EXCEPTION_NOT_FOUND",
                "exception item not found",
            ) from None
        except (TypeError, ValueError) as error:
            message = str(error)
            if "resolved" in message or "must not precede" in message:
                raise _HttpError(
                    HTTPStatus.CONFLICT,
                    "EXCEPTION_STATE_CONFLICT",
                    message,
                ) from None
            raise _HttpError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "INVALID_REQUEST",
                message,
            ) from None
        return _json_response(start_response, HTTPStatus.OK, view.to_dict())


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


def _parse_include_resolved(environ: dict[str, object]) -> bool:
    query_text = _environ_text(environ, "QUERY_STRING", default="")
    query = parse_qs(query_text, keep_blank_values=True)
    if set(query) - {"include_resolved"}:
        raise _HttpError(
            HTTPStatus.BAD_REQUEST,
            "INVALID_QUERY",
            "unsupported query parameter",
        )
    values = query.get("include_resolved", ["false"])
    if len(values) != 1 or values[0].lower() not in {"true", "false"}:
        raise _HttpError(
            HTTPStatus.BAD_REQUEST,
            "INVALID_QUERY",
            "include_resolved must be true or false",
        )
    return values[0].lower() == "true"


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


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise TypeError("acknowledged_at_utc must be an RFC 3339 string")
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        raise ValueError("acknowledged_at_utc must be an RFC 3339 datetime") from None


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
