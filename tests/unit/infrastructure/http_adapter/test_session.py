import json
from io import BytesIO

import pytest

from sentry_atm.infrastructure.http import GoldenDemoSessionWsgiApp
from sentry_atm.runtime import build_golden_demo_session_runtime

_SESSION_PATH = "/api/v1/golden-demo/session"
_COMMAND_PATH = "/api/v1/golden-demo/session/commands"


def _request(
    app: GoldenDemoSessionWsgiApp,
    *,
    method: object = "GET",
    path: object = _SESSION_PATH,
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


def _command_body(
    command: object,
    *,
    extra: bool = False,
    fields: dict[str, object] | None = None,
) -> bytes:
    payload = {"command": command}
    payload.update(fields or {})
    if extra:
        payload["unexpected"] = True
    return json.dumps(payload).encode()


def _post(
    app: GoldenDemoSessionWsgiApp,
    command: str,
    *,
    fields: dict[str, object] | None = None,
):
    return _request(
        app,
        method="POST",
        path=_COMMAND_PATH,
        body=_command_body(command, fields=fields),
        content_type="application/json; charset=utf-8",
    )


def test_get_returns_deterministic_ready_session_json() -> None:
    session = build_golden_demo_session_runtime()

    status, headers, body = _request(session.http_app)
    repeated = _request(session.http_app)[2]
    payload = json.loads(body)

    assert status == 200
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert headers["Content-Length"] == str(len(body))
    assert headers["Cache-Control"] == "no-store"
    assert body == repeated
    assert payload["stage"] == "READY"
    assert payload["clock_state"] == "READY"
    assert payload["traffic_count"] == 8
    assert payload["recommendation"] is None
    assert payload["deviation"] is None
    assert payload["candidate_comparisons"] == []


def test_post_commands_run_full_session_and_get_returns_latest_state() -> None:
    session = build_golden_demo_session_runtime()
    expected = (
        ("START", "MONITORING", 0.0),
        ("ADVANCE_TO_CONFLICT", "CONFLICT_DETECTED", 70.0),
        ("GENERATE_RECOMMENDATION", "RECOMMENDATION_AVAILABLE", 75.0),
        ("ACCEPT_RECOMMENDATION", "DECISION_ACCEPTED", 90.0),
        ("APPLY_APPROVED_MANEUVER", "CONFLICT_RESOLVED", 90.0),
    )

    for command, expected_stage, expected_elapsed in expected:
        status, headers, body = _post(session.http_app, command)
        get_status, _, get_body = _request(session.http_app)
        payload = json.loads(body)

        assert status == 200
        assert get_status == 200
        assert body == get_body
        assert headers["Cache-Control"] == "no-store"
        assert payload["stage"] == expected_stage
        assert payload["elapsed_seconds"] == expected_elapsed

    final = json.loads(_request(session.http_app)[2])
    assert final["revalidation"]["resolved"] is True
    assert final["controller_decision"]["entries"][0]["decision_type"] == "ACCEPT"
    assert final["deviation"]["aircraft_id"] == "MIL-F01"
    assert [item["candidate_id"] for item in final["candidate_comparisons"]] == [
        "CAND-A",
        "CAND-B",
        "CAND-C",
        "CAND-D",
        "CAND-E",
    ]

    reset_status, _, reset_body = _post(session.http_app, "RESET")
    reset = json.loads(reset_body)
    assert reset_status == 200
    assert reset["stage"] == "READY"
    assert reset["run_number"] == 1


def _post_to_recommendation(session) -> None:
    for command in ("START", "ADVANCE_TO_CONFLICT", "GENERATE_RECOMMENDATION"):
        assert _post(session.http_app, command)[0] == 200


def test_modify_command_accepts_fixed_maneuver_schema_and_returns_audit() -> None:
    session = build_golden_demo_session_runtime()
    _post_to_recommendation(session)
    maneuver = {
        "maneuver_type": "ALTITUDE",
        "target_heading_deg": None,
        "target_altitude_ft": 8_800,
        "target_ground_speed_kt": None,
        "delay_seconds": None,
        "target_sequence_position": None,
    }

    status, _, body = _post(
        session.http_app,
        "MODIFY_RECOMMENDATION",
        fields={
            "rationale": "Maintain additional vertical margin",
            "modified_maneuver": maneuver,
        },
    )
    payload = json.loads(body)

    assert status == 200
    assert payload["stage"] == "DECISION_MODIFIED"
    entry = payload["controller_decision"]["entries"][-1]
    assert entry["decision_type"] == "MODIFY"
    assert entry["modified_maneuver"]["target_altitude_ft"] == 8_800
    assert entry["requires_revalidation"] is True
    assert payload["application_step_id"] is None


def test_modified_maneuver_revalidation_returns_json_without_application() -> None:
    session = build_golden_demo_session_runtime()
    _post_to_recommendation(session)
    maneuver = {
        "maneuver_type": "ALTITUDE",
        "target_heading_deg": None,
        "target_altitude_ft": 8_800,
        "target_ground_speed_kt": None,
        "delay_seconds": None,
        "target_sequence_position": None,
    }
    assert _post(
        session.http_app,
        "MODIFY_RECOMMENDATION",
        fields={
            "rationale": "Maintain additional vertical margin",
            "modified_maneuver": maneuver,
        },
    )[0] == 200

    status, _, body = _post(session.http_app, "REVALIDATE_MODIFIED_MANEUVER")
    payload = json.loads(body)

    assert status == 200
    assert payload["stage"] == "MODIFICATION_REVALIDATED"
    assert payload["elapsed_seconds"] == 90.0
    assert payload["application_step_id"] is None
    evidence = payload["modified_revalidation"]
    assert evidence["verdict"] == "SAFE"
    assert evidence["primary_conflict_status"] == "SAFE"
    assert evidence["primary_horizontal_separation_nm"] == pytest.approx(2.3)
    assert evidence["primary_vertical_separation_ft"] == pytest.approx(
        1_591.6666666667
    )
    assert evidence["safe_to_apply"] is True


def test_reject_command_returns_non_authorizing_audit() -> None:
    session = build_golden_demo_session_runtime()
    _post_to_recommendation(session)

    status, _, body = _post(
        session.http_app,
        "REJECT_RECOMMENDATION",
        fields={"rationale": "Coordinate a different sector strategy"},
    )
    payload = json.loads(body)

    assert status == 200
    assert payload["stage"] == "DECISION_REJECTED"
    entry = payload["controller_decision"]["entries"][-1]
    assert entry["decision_type"] == "REJECT"
    assert entry["modified_maneuver"] is None
    assert entry["authorizes_application"] is False


@pytest.mark.parametrize(
    "fields",
    [
        {"rationale": "", "modified_maneuver": None},
        {"rationale": "Missing Maneuver"},
        {"rationale": 1, "modified_maneuver": None},
        {
            "rationale": "No actual change",
            "modified_maneuver": {
                "maneuver_type": "ALTITUDE",
                "target_heading_deg": None,
                "target_altitude_ft": 9_000,
                "target_ground_speed_kt": None,
                "delay_seconds": None,
                "target_sequence_position": None,
            },
        },
    ],
)
def test_invalid_modify_payload_returns_422_without_advancing(fields: dict[str, object]) -> None:
    session = build_golden_demo_session_runtime()
    _post_to_recommendation(session)

    status, _, body = _post(
        session.http_app,
        "MODIFY_RECOMMENDATION",
        fields=fields,
    )

    assert status == 422
    assert json.loads(body)["error"]["code"] == "INVALID_REQUEST"
    assert session.read_api.get_current().stage.value == "RECOMMENDATION_AVAILABLE"
    assert session.runtime.simulation.clock.elapsed_seconds == 75.0


@pytest.mark.parametrize(
    ("method", "path", "expected_status", "expected_code", "allow"),
    [
        ("GET", "/missing", 404, "ROUTE_NOT_FOUND", None),
        ("POST", _SESSION_PATH, 405, "METHOD_NOT_ALLOWED", "GET"),
        ("GET", _COMMAND_PATH, 405, "METHOD_NOT_ALLOWED", "POST"),
    ],
)
def test_route_and_method_errors_are_explicit(
    method: str,
    path: str,
    expected_status: int,
    expected_code: str,
    allow: str | None,
) -> None:
    app = build_golden_demo_session_runtime().http_app

    status, headers, body = _request(app, method=method, path=path)

    assert status == expected_status
    assert json.loads(body)["error"]["code"] == expected_code
    assert headers.get("Allow") == allow
    assert headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", _SESSION_PATH), ("POST", _COMMAND_PATH)],
)
def test_query_parameters_are_rejected(method: str, path: str) -> None:
    app = build_golden_demo_session_runtime().http_app

    status, _, body = _request(
        app,
        method=method,
        path=path,
        query="unexpected=true",
        body=_command_body("START") if method == "POST" else b"",
    )

    assert status == 400
    assert json.loads(body)["error"]["code"] == "INVALID_QUERY"


@pytest.mark.parametrize(
    ("body", "content_type", "expected_status", "expected_code"),
    [
        (_command_body("START"), "text/plain", 415, "UNSUPPORTED_MEDIA_TYPE"),
        (b"not-json", "application/json", 400, "INVALID_JSON"),
        (b"[]", "application/json", 422, "INVALID_REQUEST"),
        (b"{}", "application/json", 422, "INVALID_REQUEST"),
        (_command_body("START", extra=True), "application/json", 422, "INVALID_REQUEST"),
        (_command_body(1), "application/json", 422, "INVALID_REQUEST"),
        (_command_body("UNKNOWN"), "application/json", 422, "INVALID_REQUEST"),
    ],
)
def test_command_body_validation_returns_explicit_4xx_without_mutation(
    body: bytes,
    content_type: str,
    expected_status: int,
    expected_code: str,
) -> None:
    session = build_golden_demo_session_runtime()

    status, _, response = _request(
        session.http_app,
        method="POST",
        path=_COMMAND_PATH,
        body=body,
        content_type=content_type,
    )

    assert status == expected_status
    assert json.loads(response)["error"]["code"] == expected_code
    assert session.read_api.get_current().stage.value == "READY"


@pytest.mark.parametrize(
    ("content_length", "stream", "expected_status", "expected_code"),
    [
        ("invalid", None, 400, "INVALID_CONTENT_LENGTH"),
        ("-1", None, 400, "INVALID_CONTENT_LENGTH"),
        ("16385", None, 413, "REQUEST_TOO_LARGE"),
        ("1", object(), 400, "INVALID_ENVIRONMENT"),
        ("3", BytesIO(b"{}"), 400, "INVALID_BODY_LENGTH"),
    ],
)
def test_content_boundary_validation(
    content_length: str,
    stream: object | None,
    expected_status: int,
    expected_code: str,
) -> None:
    app = build_golden_demo_session_runtime().http_app

    status, _, response = _request(
        app,
        method="POST",
        path=_COMMAND_PATH,
        content_length=content_length,
        stream=stream,
    )

    assert status == expected_status
    assert json.loads(response)["error"]["code"] == expected_code


def test_out_of_order_command_returns_409_without_session_change() -> None:
    session = build_golden_demo_session_runtime()
    before = session.read_api.get_current()

    status, _, body = _post(session.http_app, "ADVANCE_TO_CONFLICT")

    assert status == 409
    assert json.loads(body)["error"]["code"] == "SESSION_STATE_CONFLICT"
    assert session.read_api.get_current() == before


def test_adapter_validates_dependencies_and_wsgi_environment() -> None:
    first = build_golden_demo_session_runtime()
    second = build_golden_demo_session_runtime()
    with pytest.raises(TypeError, match="GoldenDemoSessionApiContract"):
        GoldenDemoSessionWsgiApp(object(), first.command_service)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="GoldenDemoSessionCommandApiContract"):
        GoldenDemoSessionWsgiApp(first.read_api, object())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="share one Session source"):
        GoldenDemoSessionWsgiApp(first.read_api, second.command_service)

    status, _, body = _request(first.http_app, method=object())
    assert status == 400
    assert json.loads(body)["error"]["code"] == "INVALID_ENVIRONMENT"
