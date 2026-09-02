import json
from datetime import UTC, datetime, timedelta
from io import BytesIO

import pytest

from sentry_atm.api import InProcessControllerDecisionApi
from sentry_atm.controller_decision import DeterministicControllerDecisionService
from sentry_atm.domain import (
    AltitudeManeuver,
    CandidateCostEstimate,
    CandidateSafetyValidationResult,
    ConflictEvent,
    ConflictPair,
    ConflictStatus,
    RecommendationAvailability,
    RecommendationReasonCode,
    ResolutionCandidate,
    ResolutionObjective,
    ResolutionRecommendation,
    ResolutionRecommendationSet,
    ResolutionValidationReasonCode,
    ResolutionValidationVerdict,
    SeparationMinimum,
)
from sentry_atm.infrastructure.http import ControllerDecisionWsgiApp

EVALUATED_AT = datetime(2026, 9, 1, 3, 1, 15, tzinfo=UTC)
RECOMMENDED_AT = EVALUATED_AT + timedelta(seconds=5)
DECIDED_AT = RECOMMENDED_AT + timedelta(seconds=5)


def _recommendation_set(suffix: str = "A") -> ResolutionRecommendationSet:
    candidate = ResolutionCandidate(
        candidate_id=f"CAND-{suffix}",
        target_aircraft_id="MIL-F01",
        maneuver=AltitudeManeuver(9_000),
        objective=ResolutionObjective.VERTICAL_SEPARATION,
        effective_from_utc=EVALUATED_AT,
        cost=CandidateCostEstimate(operational_cost_score=10),
    )
    conflict = ConflictEvent(
        conflict_id=f"CONFLICT-{suffix}",
        pair=ConflictPair("CIV-A02", "MIL-F01"),
        status=ConflictStatus.SAFE,
        evaluated_at_utc=EVALUATED_AT,
        closest_approach_time_utc=EVALUATED_AT + timedelta(seconds=120),
        minimum_separation=SeparationMinimum(1.356, 1_016.25),
        rule_profile_id="POC_TERMINAL_V1",
    )
    validation = CandidateSafetyValidationResult(
        validation_result_id=f"VALIDATION-{suffix}",
        candidate_id=candidate.candidate_id,
        evaluated_at_utc=EVALUATED_AT,
        verdict=ResolutionValidationVerdict.SAFE,
        primary_conflict=conflict,
        secondary_conflicts=(),
        performance_feasible=True,
        rule_violations=(),
        reason_codes=(ResolutionValidationReasonCode.PRIMARY_CONFLICT_RESOLVED,),
        validation_profile_id="POC_SAFETY_V1",
    )
    recommendation = ResolutionRecommendation(
        recommendation_id=f"RECOMMENDATION-{suffix}",
        rank=1,
        candidate=candidate,
        validation_result=validation,
        generated_at_utc=RECOMMENDED_AT,
        reason_codes=tuple(RecommendationReasonCode),
        explanation="Validated safe recommendation",
    )
    return ResolutionRecommendationSet(
        recommendation_set_id=f"RECOMMENDATION-SET-{suffix}",
        source_exception_id=f"EXCEPTION-{suffix}",
        source_candidate_batch_id=f"BATCH-{suffix}",
        source_validation_run_id=f"RUN-{suffix}",
        generated_at_utc=RECOMMENDED_AT,
        ranking_policy_id="POC_RECOMMENDATION_V1",
        availability=RecommendationAvailability.AVAILABLE,
        recommendations=(recommendation,),
    )


class _Lookup:
    def __init__(self, values=()):
        self.values = {item.recommendation_set_id: item for item in values}

    def get_recommendation_set(self, recommendation_set_id):
        return self.values.get(recommendation_set_id)


def _app(*sets) -> tuple[ControllerDecisionWsgiApp, DeterministicControllerDecisionService]:
    service = DeterministicControllerDecisionService()
    api = InProcessControllerDecisionApi(service, _Lookup(sets))
    return ControllerDecisionWsgiApp(api), service


def _request(
    app: ControllerDecisionWsgiApp,
    *,
    method: object = "GET",
    path: object = "/api/v1/controller-decisions/current",
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


def _body(
    suffix: str = "A",
    *,
    decision_type: str = "ACCEPT",
    decided_at_utc: str = "2026-09-01T03:01:25Z",
    rationale=None,
    modified_maneuver=None,
    recommendation_id: str | None = None,
) -> bytes:
    return json.dumps(
        {
            "recommendation_set_id": f"RECOMMENDATION-SET-{suffix}",
            "recommendation_id": (
                f"RECOMMENDATION-{suffix}" if recommendation_id is None else recommendation_id
            ),
            "decision_type": decision_type,
            "decided_at_utc": decided_at_utc,
            "controller_position_id": "RKTU-DEMO-CONTROLLER",
            "rationale": rationale,
            "modified_maneuver": modified_maneuver,
        }
    ).encode()


def _heading_maneuver() -> dict[str, object]:
    return {
        "maneuver_type": "HEADING",
        "target_heading_deg": 190,
        "target_altitude_ft": None,
        "target_ground_speed_kt": None,
        "delay_seconds": None,
        "target_sequence_position": None,
    }


def _post(app, body: bytes) -> tuple[int, dict[str, str], bytes]:
    return _request(
        app,
        method="POST",
        path="/api/v1/controller-decisions",
        body=body,
        content_type="application/json; charset=utf-8",
    )


def test_get_returns_204_before_first_decision() -> None:
    app, _ = _app(_recommendation_set())

    status, headers, body = _request(app)

    assert status == 204
    assert headers == {"Content-Length": "0", "Cache-Control": "no-store"}
    assert body == b""


def test_post_accept_returns_201_and_get_returns_same_audit_log() -> None:
    app, service = _app(_recommendation_set())

    status, headers, body = _post(app, _body())
    get_status, _, get_body = _request(app)
    payload = json.loads(body)

    assert status == 201
    assert get_status == 200
    assert body == get_body
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert headers["Content-Length"] == str(len(body))
    assert headers["Cache-Control"] == "no-store"
    assert payload["revision"] == 1
    assert payload["entries"][0]["decision_type"] == "ACCEPT"
    assert payload["entries"][0]["authorizes_application"] is True
    assert service.last_audit_log.accepted_entries[0].approved_candidate is not None  # type: ignore[union-attr]


def test_post_modify_returns_fixed_maneuver_schema_without_authorizing() -> None:
    app, service = _app(_recommendation_set())

    status, _, body = _post(
        app,
        _body(
            decision_type="MODIFY",
            rationale="Use a smaller vector for adjacent traffic",
            modified_maneuver=_heading_maneuver(),
        ),
    )
    entry = json.loads(body)["entries"][0]

    assert status == 201
    assert entry["modified_maneuver"] == _heading_maneuver()
    assert entry["requires_revalidation"] is True
    assert entry["authorizes_application"] is False
    assert service.last_audit_log.modified_entries[0].approved_candidate is None  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("method", "path", "expected_status", "expected_code", "allow"),
    [
        ("GET", "/missing", 404, "ROUTE_NOT_FOUND", None),
        ("GET", "/api/v1/controller-decisions", 405, "METHOD_NOT_ALLOWED", "POST"),
        (
            "POST",
            "/api/v1/controller-decisions/current",
            405,
            "METHOD_NOT_ALLOWED",
            "GET",
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
    app, _ = _app()

    status, headers, body = _request(app, method=method, path=path)

    assert status == expected_status
    assert json.loads(body)["error"]["code"] == expected_code
    assert headers.get("Allow") == allow


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_query_parameters_are_rejected(method: str) -> None:
    app, _ = _app(_recommendation_set())
    path = (
        "/api/v1/controller-decisions/current"
        if method == "GET"
        else "/api/v1/controller-decisions"
    )

    status, _, body = _request(app, method=method, path=path, query="unexpected=true")

    assert status == 400
    assert json.loads(body)["error"]["code"] == "INVALID_QUERY"


@pytest.mark.parametrize(
    ("body", "content_type", "expected_status", "expected_code"),
    [
        (_body(), "text/plain", 415, "UNSUPPORTED_MEDIA_TYPE"),
        (b"not-json", "application/json", 400, "INVALID_JSON"),
        (b"[]", "application/json", 422, "INVALID_REQUEST"),
        (b"{}", "application/json", 422, "INVALID_REQUEST"),
        (
            _body().replace(b'"2026-09-01T03:01:25Z"', b"1"),
            "application/json",
            422,
            "INVALID_REQUEST",
        ),
        (
            _body(decided_at_utc="2026-09-01T03:01:25"),
            "application/json",
            422,
            "INVALID_REQUEST",
        ),
        (
            _body(decided_at_utc="not-a-date"),
            "application/json",
            422,
            "INVALID_REQUEST",
        ),
        (
            _body(decision_type="UNKNOWN"),
            "application/json",
            422,
            "INVALID_REQUEST",
        ),
        (
            _body(decision_type="REJECT"),
            "application/json",
            422,
            "INVALID_REQUEST",
        ),
        (
            _body(decision_type="MODIFY", rationale="change", modified_maneuver={}),
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
    app, service = _app(_recommendation_set())

    status, _, response = _request(
        app,
        method="POST",
        path="/api/v1/controller-decisions",
        body=body,
        content_type=content_type,
    )

    assert status == expected_status
    assert json.loads(response)["error"]["code"] == expected_code
    assert service.revision == 0


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
    app, _ = _app()

    status, _, response = _request(
        app,
        method="POST",
        path="/api/v1/controller-decisions",
        content_length=content_length,
        stream=stream,
    )

    assert status == expected_status
    assert json.loads(response)["error"]["code"] == expected_code


def test_missing_set_and_recommendation_return_distinct_404_codes() -> None:
    app, service = _app(_recommendation_set())

    set_status, _, set_body = _post(app, _body("MISSING"))
    recommendation_status, _, recommendation_body = _post(
        app,
        _body(recommendation_id="RECOMMENDATION-MISSING"),
    )

    assert set_status == 404
    assert json.loads(set_body)["error"]["code"] == "RECOMMENDATION_SET_NOT_FOUND"
    assert recommendation_status == 404
    assert json.loads(recommendation_body)["error"]["code"] == "RECOMMENDATION_NOT_FOUND"
    assert service.revision == 0


def test_duplicate_decision_and_time_regression_return_409_without_extra_revision() -> None:
    first_set = _recommendation_set("A")
    second_set = _recommendation_set("B")
    app, service = _app(first_set, second_set)
    assert _post(app, _body("A"))[0] == 201

    duplicate_status, _, duplicate_body = _post(app, _body("A"))
    regression_status, _, regression_body = _post(
        app,
        _body("B", decided_at_utc="2026-09-01T03:01:24Z"),
    )

    assert duplicate_status == 409
    assert json.loads(duplicate_body)["error"]["code"] == "DECISION_STATE_CONFLICT"
    assert regression_status == 409
    assert json.loads(regression_body)["error"]["code"] == "DECISION_STATE_CONFLICT"
    assert service.revision == 1


def test_adapter_rejects_wrong_api_and_invalid_wsgi_text() -> None:
    with pytest.raises(TypeError, match="ControllerDecisionApiContract"):
        ControllerDecisionWsgiApp(object())  # type: ignore[arg-type]
    app, _ = _app()

    status, _, body = _request(app, method=object())

    assert status == 400
    assert json.loads(body)["error"]["code"] == "INVALID_ENVIRONMENT"
