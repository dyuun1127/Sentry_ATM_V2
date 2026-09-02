"""Minimal WSGI adapter for the Controller Decision application API."""

import json
from collections.abc import Callable, Iterable
from datetime import datetime
from http import HTTPStatus

from sentry_atm.api import (
    ControllerDecisionApiContract,
    ControllerDecisionManeuverModel,
    SubmitControllerDecisionRequest,
)

type StartResponse = Callable[[str, list[tuple[str, str]]], object]
type WsgiResponse = Iterable[bytes]

_COLLECTION_PATH = "/api/v1/controller-decisions"
_CURRENT_PATH = "/api/v1/controller-decisions/current"
_MAX_REQUEST_BODY_BYTES = 16_384
_REQUEST_FIELDS = {
    "recommendation_set_id",
    "recommendation_id",
    "decision_type",
    "decided_at_utc",
    "controller_position_id",
    "rationale",
    "modified_maneuver",
}
_MANEUVER_FIELDS = {
    "maneuver_type",
    "target_heading_deg",
    "target_altitude_ft",
    "target_ground_speed_kt",
    "delay_seconds",
    "target_sequence_position",
}


class ControllerDecisionWsgiApp:
    """Expose Decision submission and current Audit Log through WSGI."""

    __slots__ = ("_api",)

    def __init__(self, api: ControllerDecisionApiContract) -> None:
        if not isinstance(api, ControllerDecisionApiContract):
            raise TypeError("api must implement ControllerDecisionApiContract")
        self._api = api

    def __call__(
        self,
        environ: dict[str, object],
        start_response: StartResponse,
    ) -> WsgiResponse:
        try:
            method = _environ_text(environ, "REQUEST_METHOD", default="GET").upper()
            path = _environ_text(environ, "PATH_INFO", default="/")
            if path == _CURRENT_PATH:
                if method != "GET":
                    raise _HttpError(
                        HTTPStatus.METHOD_NOT_ALLOWED,
                        "METHOD_NOT_ALLOWED",
                        "use GET",
                        headers=(("Allow", "GET"),),
                    )
                return self._get_current(environ, start_response)
            if path == _COLLECTION_PATH:
                if method != "POST":
                    raise _HttpError(
                        HTTPStatus.METHOD_NOT_ALLOWED,
                        "METHOD_NOT_ALLOWED",
                        "use POST",
                        headers=(("Allow", "POST"),),
                    )
                return self._submit(environ, start_response)
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
        current = self._api.get_current()
        if current is None:
            return _empty_response(start_response, HTTPStatus.NO_CONTENT)
        return _json_response(start_response, HTTPStatus.OK, current.to_dict())

    def _submit(
        self,
        environ: dict[str, object],
        start_response: StartResponse,
    ) -> WsgiResponse:
        _reject_query(environ)
        payload = _read_json_object(environ)
        if set(payload) != _REQUEST_FIELDS:
            raise _HttpError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "INVALID_REQUEST",
                "body must contain exactly the Controller Decision command fields",
            )
        try:
            request = SubmitControllerDecisionRequest(
                recommendation_set_id=payload["recommendation_set_id"],  # type: ignore[arg-type]
                recommendation_id=payload["recommendation_id"],  # type: ignore[arg-type]
                decision_type=payload["decision_type"],  # type: ignore[arg-type]
                decided_at_utc=_parse_datetime(payload["decided_at_utc"]),
                controller_position_id=payload["controller_position_id"],  # type: ignore[arg-type]
                rationale=payload["rationale"],  # type: ignore[arg-type]
                modified_maneuver=_parse_maneuver(payload["modified_maneuver"]),
            )
            view = self._api.submit(request)
        except KeyError as error:
            message = str(error)
            code = (
                "RECOMMENDATION_SET_NOT_FOUND"
                if "recommendation_set_id" in message
                else "RECOMMENDATION_NOT_FOUND"
            )
            raise _HttpError(HTTPStatus.NOT_FOUND, code, message) from None
        except (TypeError, ValueError) as error:
            message = str(error)
            if "already has a final" in message or "last Audit Log" in message:
                raise _HttpError(
                    HTTPStatus.CONFLICT,
                    "DECISION_STATE_CONFLICT",
                    message,
                ) from None
            raise _HttpError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "INVALID_REQUEST",
                message,
            ) from None
        return _json_response(start_response, HTTPStatus.CREATED, view.to_dict())


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


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise TypeError("decided_at_utc must be an RFC 3339 string")
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        raise ValueError("decided_at_utc must be an RFC 3339 datetime") from None


def _parse_maneuver(value: object) -> ControllerDecisionManeuverModel | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != _MANEUVER_FIELDS:
        raise TypeError("modified_maneuver must contain exactly the fixed Maneuver fields")
    return ControllerDecisionManeuverModel(
        maneuver_type=value["maneuver_type"],  # type: ignore[arg-type]
        target_heading_deg=value["target_heading_deg"],  # type: ignore[arg-type]
        target_altitude_ft=value["target_altitude_ft"],  # type: ignore[arg-type]
        target_ground_speed_kt=value["target_ground_speed_kt"],  # type: ignore[arg-type]
        delay_seconds=value["delay_seconds"],  # type: ignore[arg-type]
        target_sequence_position=value["target_sequence_position"],  # type: ignore[arg-type]
    )


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
