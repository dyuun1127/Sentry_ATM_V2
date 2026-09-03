import json
from datetime import UTC, datetime, timedelta
from io import BytesIO
from urllib.parse import quote

import pytest

from sentry_atm.api import InProcessExceptionQueueApi
from sentry_atm.domain import (
    ConflictPair,
    ConflictRiskAssessment,
    RiskLevel,
    RiskReasonCode,
)
from sentry_atm.exception_queue import ExceptionQueueService
from sentry_atm.infrastructure.http import ExceptionQueueWsgiApp

START = datetime(2026, 9, 1, 3, 1, 10, tzinfo=UTC)


def _risk(
    at: datetime,
    *,
    level: RiskLevel = RiskLevel.HIGH,
    suffix: str = "001",
) -> ConflictRiskAssessment:
    return ConflictRiskAssessment(
        risk_assessment_id=f"RISK-{suffix}",
        conflict_id=f"CONFLICT-{suffix}",
        pair=ConflictPair("CIV-A02", "MIL-F01"),
        evaluated_at_utc=at,
        risk_score=0.0 if level is RiskLevel.LOW else 75.0,
        risk_level=level,
        tcpa_seconds=90.0,
        horizontal_separation_ratio=0.46,
        vertical_separation_ratio=0.5,
        reason_codes=(
            RiskReasonCode.NO_PREDICTED_CONFLICT
            if level is RiskLevel.LOW
            else RiskReasonCode.PREDICTED_SEPARATION_LOSS,
        ),
        policy_profile_id="POC_RISK_V1",
    )


def _service_with_active_item() -> ExceptionQueueService:
    service = ExceptionQueueService()
    service.refresh(START, risk_assessments=(_risk(START),))
    return service


def _request(
    app: ExceptionQueueWsgiApp,
    *,
    method: object = "GET",
    path: object = "/api/v1/exception-queue",
    query: object = "",
    body: bytes = b"",
    content_type: object = "application/json",
    content_length: object | None = None,
    stream: object | None = None,
) -> tuple[int, dict[str, str], bytes]:
    captured: dict[str, object] = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = headers

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "CONTENT_TYPE": content_type,
        "CONTENT_LENGTH": str(len(body)) if content_length is None else content_length,
        "wsgi.input": BytesIO(body) if stream is None else stream,
    }
    response_body = b"".join(app(environ, start_response))
    status_code = int(str(captured["status"]).split(maxsplit=1)[0])
    headers = dict(captured["headers"])  # type: ignore[arg-type]
    return status_code, headers, response_body


def _json_request_body(timestamp: str = "2026-09-01T03:01:11Z") -> bytes:
    return json.dumps({"acknowledged_at_utc": timestamp}).encode()


def test_get_returns_204_before_first_snapshot() -> None:
    app = ExceptionQueueWsgiApp(InProcessExceptionQueueApi(ExceptionQueueService()))

    status, headers, body = _request(app)

    assert status == 204
    assert headers == {"Content-Length": "0", "Cache-Control": "no-store"}
    assert body == b""


def test_get_returns_current_queue_as_deterministic_json() -> None:
    service = _service_with_active_item()
    app = ExceptionQueueWsgiApp(InProcessExceptionQueueApi(service))

    status, headers, body = _request(app)
    payload = json.loads(body)

    assert status == 200
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert headers["Content-Length"] == str(len(body))
    assert headers["Cache-Control"] == "no-store"
    assert payload["active_count"] == 1
    assert payload["top_exception_id"] == service.last_snapshot.top_item.exception_id  # type: ignore[union-attr]
    assert payload["items"][0]["severity"] == "HIGH"


def test_include_resolved_query_controls_history() -> None:
    service = _service_with_active_item()
    resolved_at = START + timedelta(seconds=10)
    service.refresh(
        resolved_at,
        risk_assessments=(_risk(resolved_at, level=RiskLevel.LOW, suffix="002"),),
    )
    app = ExceptionQueueWsgiApp(InProcessExceptionQueueApi(service))

    _, _, active_body = _request(app)
    _, _, history_body = _request(app, query="include_resolved=TrUe")

    assert json.loads(active_body)["items"] == []
    assert json.loads(history_body)["items"][0]["status"] == "RESOLVED"


def test_post_acknowledges_exception_item() -> None:
    service = _service_with_active_item()
    exception_id = service.last_snapshot.top_item.exception_id  # type: ignore[union-attr]
    path = f"/api/v1/exceptions/{quote(exception_id, safe='')}/acknowledgements"
    app = ExceptionQueueWsgiApp(InProcessExceptionQueueApi(service))

    status, _, body = _request(
        app,
        method="POST",
        path=path,
        body=_json_request_body(),
        content_type="application/json; charset=utf-8",
    )

    assert status == 200
    assert json.loads(body)["items"][0]["status"] == "ACKNOWLEDGED"
    assert service.last_snapshot.top_item.status.value == "ACKNOWLEDGED"  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("method", "path", "expected_status", "expected_code", "allow"),
    [
        ("GET", "/missing", 404, "ROUTE_NOT_FOUND", None),
        ("POST", "/api/v1/exception-queue", 405, "METHOD_NOT_ALLOWED", "GET"),
        (
            "GET",
            "/api/v1/exceptions/EXCEPTION-001/acknowledgements",
            405,
            "METHOD_NOT_ALLOWED",
            "POST",
        ),
    ],
)
def test_route_and_method_errors_are_explicit(
    method: str,
    path: str,
    expected_status: int,
    expected_code: str,
    allow: str | None,
) -> None:
    app = ExceptionQueueWsgiApp(InProcessExceptionQueueApi(ExceptionQueueService()))

    status, headers, body = _request(app, method=method, path=path)

    assert status == expected_status
    assert json.loads(body)["error"]["code"] == expected_code
    assert headers.get("Allow") == allow


@pytest.mark.parametrize(
    "query",
    [
        "unknown=true",
        "include_resolved=",
        "include_resolved=maybe",
        "include_resolved=true&include_resolved=false",
    ],
)
def test_query_validation_returns_400(query: str) -> None:
    app = ExceptionQueueWsgiApp(InProcessExceptionQueueApi(ExceptionQueueService()))

    status, _, body = _request(app, query=query)

    assert status == 400
    assert json.loads(body)["error"]["code"] == "INVALID_QUERY"


@pytest.mark.parametrize(
    ("body", "content_type", "expected_status", "expected_code"),
    [
        (_json_request_body(), "text/plain", 415, "UNSUPPORTED_MEDIA_TYPE"),
        (b"not-json", "application/json", 400, "INVALID_JSON"),
        (b"[]", "application/json", 422, "INVALID_REQUEST"),
        (b"{}", "application/json", 422, "INVALID_REQUEST"),
        (b'{"acknowledged_at_utc": 1}', "application/json", 422, "INVALID_REQUEST"),
        (b'{"acknowledged_at_utc": "bad"}', "application/json", 422, "INVALID_REQUEST"),
        (
            b'{"acknowledged_at_utc": "2026-09-01T03:01:11", "extra": true}',
            "application/json",
            422,
            "INVALID_REQUEST",
        ),
    ],
)
def test_post_body_validation_returns_explicit_4xx(
    body: bytes,
    content_type: str,
    expected_status: int,
    expected_code: str,
) -> None:
    app = ExceptionQueueWsgiApp(InProcessExceptionQueueApi(ExceptionQueueService()))

    status, _, response = _request(
        app,
        method="POST",
        path="/api/v1/exceptions/EXCEPTION-001/acknowledgements",
        body=body,
        content_type=content_type,
    )

    assert status == expected_status
    assert json.loads(response)["error"]["code"] == expected_code


@pytest.mark.parametrize(
    ("content_length", "stream", "expected_status", "expected_code"),
    [
        ("invalid", None, 400, "INVALID_CONTENT_LENGTH"),
        ("-1", None, 400, "INVALID_CONTENT_LENGTH"),
        ("16385", None, 413, "REQUEST_TOO_LARGE"),
        ("1", object(), 400, "INVALID_ENVIRONMENT"),
        ("2", BytesIO(b"{}"), 422, "INVALID_REQUEST"),
        ("3", BytesIO(b"{}"), 400, "INVALID_BODY_LENGTH"),
    ],
)
def test_content_boundary_validation(
    content_length: str,
    stream: object | None,
    expected_status: int,
    expected_code: str,
) -> None:
    app = ExceptionQueueWsgiApp(InProcessExceptionQueueApi(ExceptionQueueService()))

    status, _, response = _request(
        app,
        method="POST",
        path="/api/v1/exceptions/EXCEPTION-001/acknowledgements",
        content_length=content_length,
        stream=stream,
    )

    assert status == expected_status
    assert json.loads(response)["error"]["code"] == expected_code


def test_unknown_resolved_and_time_regression_are_mapped() -> None:
    service = _service_with_active_item()
    app = ExceptionQueueWsgiApp(InProcessExceptionQueueApi(service))

    missing_status, _, missing_body = _request(
        app,
        method="POST",
        path="/api/v1/exceptions/MISSING/acknowledgements",
        body=_json_request_body(),
    )
    assert missing_status == 404
    assert json.loads(missing_body)["error"]["code"] == "EXCEPTION_NOT_FOUND"

    exception_id = service.last_snapshot.top_item.exception_id  # type: ignore[union-attr]
    path = f"/api/v1/exceptions/{exception_id}/acknowledgements"
    regression_status, _, regression_body = _request(
        app,
        method="POST",
        path=path,
        body=_json_request_body("2026-09-01T03:01:09Z"),
    )
    assert regression_status == 409
    assert json.loads(regression_body)["error"]["code"] == "EXCEPTION_STATE_CONFLICT"

    resolved_at = START + timedelta(seconds=10)
    service.refresh(
        resolved_at,
        risk_assessments=(_risk(resolved_at, level=RiskLevel.LOW, suffix="002"),),
    )
    resolved_status, _, resolved_body = _request(
        app,
        method="POST",
        path=path,
        body=_json_request_body("2026-09-01T03:01:20Z"),
    )
    assert resolved_status == 409
    assert json.loads(resolved_body)["error"]["code"] == "EXCEPTION_STATE_CONFLICT"


def test_adapter_rejects_wrong_api_and_invalid_wsgi_text() -> None:
    with pytest.raises(TypeError, match="ExceptionQueueApiContract"):
        ExceptionQueueWsgiApp(object())  # type: ignore[arg-type]
    app = ExceptionQueueWsgiApp(InProcessExceptionQueueApi(ExceptionQueueService()))

    status, _, body = _request(app, method=object())

    assert status == 400
    assert json.loads(body)["error"]["code"] == "INVALID_ENVIRONMENT"
