import json
from datetime import UTC, datetime, timedelta
from io import BytesIO

import pytest

from sentry_atm.api import InProcessRecommendationApi
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
from sentry_atm.infrastructure.http import RecommendationWsgiApp

EVALUATED_AT = datetime(2026, 9, 1, 3, 1, 15, tzinfo=UTC)
GENERATED_AT = EVALUATED_AT + timedelta(seconds=5)


class _Source:
    def __init__(self, current):
        self.current = current

    def get_current_recommendation(self):
        return self.current


def _outcome() -> ResolutionRecommendationSet:
    candidate = ResolutionCandidate(
        candidate_id="CAND-A",
        target_aircraft_id="MIL-F01",
        maneuver=AltitudeManeuver(9_000),
        objective=ResolutionObjective.VERTICAL_SEPARATION,
        effective_from_utc=EVALUATED_AT,
        cost=CandidateCostEstimate(operational_cost_score=10),
    )
    conflict = ConflictEvent(
        conflict_id="CONFLICT-CAND-A",
        pair=ConflictPair("CIV-A02", "MIL-F01"),
        status=ConflictStatus.SAFE,
        evaluated_at_utc=EVALUATED_AT,
        closest_approach_time_utc=EVALUATED_AT + timedelta(seconds=120),
        minimum_separation=SeparationMinimum(1.356, 1_016.25),
        rule_profile_id="POC_TERMINAL_V1",
    )
    validation = CandidateSafetyValidationResult(
        validation_result_id="VALIDATION-CAND-A",
        candidate_id="CAND-A",
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
        recommendation_id="RECOMMENDATION-CAND-A",
        rank=1,
        candidate=candidate,
        validation_result=validation,
        generated_at_utc=GENERATED_AT,
        reason_codes=tuple(RecommendationReasonCode),
        explanation="Validated safe: set altitude to 9000.0 ft",
    )
    return ResolutionRecommendationSet(
        recommendation_set_id="RECOMMENDATION-SET-001",
        source_exception_id="EXCEPTION-001",
        source_candidate_batch_id="BATCH-001",
        source_validation_run_id="SAFETY-RUN-001",
        generated_at_utc=GENERATED_AT,
        ranking_policy_id="POC_RECOMMENDATION_V1",
        availability=RecommendationAvailability.AVAILABLE,
        recommendations=(recommendation,),
    )


def _request(
    app: RecommendationWsgiApp,
    *,
    method: object = "GET",
    path: object = "/api/v1/recommendations/current",
    query: object = "",
) -> tuple[int, dict[str, str], bytes]:
    captured: dict[str, object] = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = headers

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "CONTENT_TYPE": "application/json",
        "CONTENT_LENGTH": "0",
        "wsgi.input": BytesIO(),
    }
    response_body = b"".join(app(environ, start_response))
    status_code = int(str(captured["status"]).split(maxsplit=1)[0])
    headers = dict(captured["headers"])  # type: ignore[arg-type]
    return status_code, headers, response_body


def test_get_returns_204_before_current_recommendation_exists() -> None:
    app = RecommendationWsgiApp(InProcessRecommendationApi(_Source(None)))

    status, headers, body = _request(app)

    assert status == 204
    assert headers == {"Content-Length": "0", "Cache-Control": "no-store"}
    assert body == b""


def test_get_returns_deterministic_recommendation_json() -> None:
    app = RecommendationWsgiApp(InProcessRecommendationApi(_Source(_outcome())))

    status, headers, body = _request(app)
    repeated = _request(app)[2]
    payload = json.loads(body)

    assert status == 200
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert headers["Content-Length"] == str(len(body))
    assert headers["Cache-Control"] == "no-store"
    assert body == repeated
    assert payload["availability"] == "AVAILABLE"
    assert payload["primary_recommendation_id"] == "RECOMMENDATION-CAND-A"
    assert payload["recommendations"][0]["candidate_id"] == "CAND-A"
    assert payload["recommendations"][0]["maneuver"]["target_altitude_ft"] == 9_000
    assert payload["recommendations"][0]["safety"]["verdict"] == "SAFE"


@pytest.mark.parametrize(
    ("method", "path", "expected_status", "expected_code", "allow"),
    [
        ("GET", "/missing", 404, "ROUTE_NOT_FOUND", None),
        (
            "POST",
            "/api/v1/recommendations/current",
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
    app = RecommendationWsgiApp(InProcessRecommendationApi(_Source(None)))

    status, headers, body = _request(app, method=method, path=path)

    assert status == expected_status
    assert json.loads(body)["error"]["code"] == expected_code
    assert headers.get("Allow") == allow
    assert headers["Cache-Control"] == "no-store"


def test_query_parameters_are_rejected() -> None:
    app = RecommendationWsgiApp(InProcessRecommendationApi(_Source(None)))

    status, _, body = _request(app, query="include=unsafe")

    assert status == 400
    assert json.loads(body)["error"]["code"] == "INVALID_QUERY"


def test_adapter_rejects_wrong_api_and_invalid_wsgi_text() -> None:
    with pytest.raises(TypeError, match="RecommendationApiContract"):
        RecommendationWsgiApp(object())  # type: ignore[arg-type]
    app = RecommendationWsgiApp(InProcessRecommendationApi(_Source(None)))

    status, _, body = _request(app, method=object())

    assert status == 400
    assert json.loads(body)["error"]["code"] == "INVALID_ENVIRONMENT"
