import json
from datetime import UTC, datetime, timedelta, timezone

import pytest

from sentry_atm.api import (
    ControllerDecisionApiContract,
    ControllerDecisionManeuverModel,
    ControllerDecisionReadModelMapper,
    InProcessControllerDecisionApi,
    RecommendationSetLookup,
    SubmitControllerDecisionRequest,
)
from sentry_atm.controller_decision import DeterministicControllerDecisionService
from sentry_atm.domain import (
    AltitudeManeuver,
    CandidateCostEstimate,
    CandidateSafetyValidationResult,
    ConflictEvent,
    ConflictPair,
    ConflictStatus,
    ControllerDecisionType,
    NoActionManeuver,
    RecommendationAvailability,
    RecommendationReasonCode,
    ResolutionCandidate,
    ResolutionManeuverType,
    ResolutionObjective,
    ResolutionRecommendation,
    ResolutionRecommendationSet,
    ResolutionValidationReasonCode,
    ResolutionValidationVerdict,
    SeparationMinimum,
)

EVALUATED_AT = datetime(2026, 9, 1, 3, 1, 15, tzinfo=UTC)
RECOMMENDED_AT = EVALUATED_AT + timedelta(seconds=5)
DECIDED_AT = RECOMMENDED_AT + timedelta(seconds=5)


def _recommendation_set() -> ResolutionRecommendationSet:
    candidate = ResolutionCandidate(
        candidate_id="CAND-A",
        target_aircraft_id="MIL-F01",
        maneuver=AltitudeManeuver(9_000),
        objective=ResolutionObjective.VERTICAL_SEPARATION,
        effective_from_utc=EVALUATED_AT,
        cost=CandidateCostEstimate(operational_cost_score=10),
    )
    conflict = ConflictEvent(
        conflict_id="CONFLICT-A",
        pair=ConflictPair("CIV-A02", "MIL-F01"),
        status=ConflictStatus.SAFE,
        evaluated_at_utc=EVALUATED_AT,
        closest_approach_time_utc=EVALUATED_AT + timedelta(seconds=120),
        minimum_separation=SeparationMinimum(1.356, 1_016.25),
        rule_profile_id="POC_TERMINAL_V1",
    )
    validation = CandidateSafetyValidationResult(
        validation_result_id="VALIDATION-A",
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
        recommendation_id="RECOMMENDATION-A",
        rank=1,
        candidate=candidate,
        validation_result=validation,
        generated_at_utc=RECOMMENDED_AT,
        reason_codes=tuple(RecommendationReasonCode),
        explanation="Validated safe recommendation",
    )
    return ResolutionRecommendationSet(
        recommendation_set_id="RECOMMENDATION-SET-A",
        source_exception_id="EXCEPTION-A",
        source_candidate_batch_id="BATCH-A",
        source_validation_run_id="RUN-A",
        generated_at_utc=RECOMMENDED_AT,
        ranking_policy_id="POC_RECOMMENDATION_V1",
        availability=RecommendationAvailability.AVAILABLE,
        recommendations=(recommendation,),
    )


class _Lookup:
    def __init__(self, value):
        self.value = value
        self.requested_ids = []

    def get_recommendation_set(self, recommendation_set_id):
        self.requested_ids.append(recommendation_set_id)
        return self.value


def _request(**overrides) -> SubmitControllerDecisionRequest:
    values = {
        "recommendation_set_id": "RECOMMENDATION-SET-A",
        "recommendation_id": "RECOMMENDATION-A",
        "decision_type": ControllerDecisionType.ACCEPT,
        "decided_at_utc": DECIDED_AT,
        "controller_position_id": "RKTU-DEMO-CONTROLLER",
    }
    values.update(overrides)
    return SubmitControllerDecisionRequest(**values)


@pytest.mark.parametrize(
    ("maneuver_type", "field_name", "value", "expected"),
    [
        ("HEADING", "target_heading_deg", 190, 190.0),
        ("ALTITUDE", "target_altitude_ft", 9_500, 9_500.0),
        ("SPEED", "target_ground_speed_kt", 220, 220.0),
        ("ENTRY_DELAY", "delay_seconds", 30, 30.0),
        ("SEQUENCE_CHANGE", "target_sequence_position", 2, 2),
    ],
)
def test_maneuver_model_normalizes_every_supported_action(
    maneuver_type,
    field_name,
    value,
    expected,
) -> None:
    model = ControllerDecisionManeuverModel(
        maneuver_type=maneuver_type,
        **{field_name: value},
    )

    assert model.maneuver_type.value == maneuver_type
    assert getattr(model, field_name) == expected
    assert model.to_domain().maneuver_type is model.maneuver_type
    payload = model.to_dict()
    assert payload[field_name] == expected
    assert json.loads(json.dumps(payload))["maneuver_type"] == maneuver_type


def test_maneuver_model_rejects_no_action_missing_extra_and_invalid_domain() -> None:
    with pytest.raises(ValueError, match="action Maneuver"):
        ControllerDecisionManeuverModel(ResolutionManeuverType.NO_ACTION)
    with pytest.raises(ValueError, match="requires only"):
        ControllerDecisionManeuverModel(ResolutionManeuverType.HEADING)
    with pytest.raises(ValueError, match="requires only"):
        ControllerDecisionManeuverModel(
            ResolutionManeuverType.HEADING,
            target_heading_deg=190,
            target_altitude_ft=9_000,
        )
    with pytest.raises(TypeError, match="supported action"):
        ControllerDecisionManeuverModel.from_domain(NoActionManeuver())


def test_request_normalizes_identifiers_enum_rationale_and_utc() -> None:
    kst = timezone(timedelta(hours=9))
    request = _request(
        recommendation_set_id=" RECOMMENDATION-SET-A ",
        recommendation_id=" RECOMMENDATION-A ",
        decision_type="ACCEPT",
        decided_at_utc=DECIDED_AT.astimezone(kst),
        controller_position_id=" RKTU-DEMO-CONTROLLER ",
        rationale=" Nominal safe option selected ",
    )

    assert request.recommendation_set_id == "RECOMMENDATION-SET-A"
    assert request.recommendation_id == "RECOMMENDATION-A"
    assert request.decision_type is ControllerDecisionType.ACCEPT
    assert request.decided_at_utc == DECIDED_AT
    assert request.controller_position_id == "RKTU-DEMO-CONTROLLER"
    assert request.rationale == "Nominal safe option selected"


def test_accept_submission_returns_json_ready_audit_response() -> None:
    service = DeterministicControllerDecisionService()
    lookup = _Lookup(_recommendation_set())
    api = InProcessControllerDecisionApi(service, lookup)

    view = api.submit(_request())

    assert isinstance(lookup, RecommendationSetLookup)
    assert isinstance(api, ControllerDecisionApiContract)
    assert lookup.requested_ids == ["RECOMMENDATION-SET-A"]
    assert view.revision == 1
    assert view.latest_decision_id == view.entries[0].decision_id
    entry = view.entries[0]
    assert entry.decision_type == "ACCEPT"
    assert entry.decided_at_utc == "2026-09-01T03:01:25.000000Z"
    assert entry.authorizes_application
    assert not entry.requires_revalidation
    assert entry.modified_maneuver is None
    payload = view.to_dict()
    assert payload["entries"][0]["candidate_id"] == "CAND-A"  # type: ignore[index]
    assert json.loads(json.dumps(payload))["revision"] == 1
    assert api.get_current() == view


def test_modify_submission_maps_maneuver_and_requires_revalidation() -> None:
    api = InProcessControllerDecisionApi(
        DeterministicControllerDecisionService(),
        _Lookup(_recommendation_set()),
    )
    maneuver = ControllerDecisionManeuverModel(
        maneuver_type=ResolutionManeuverType.HEADING,
        target_heading_deg=190,
    )

    view = api.submit(
        _request(
            decision_type=ControllerDecisionType.MODIFY,
            rationale="Use a smaller vector for adjacent traffic",
            modified_maneuver=maneuver,
        )
    )

    entry = view.entries[0]
    assert entry.modified_maneuver == maneuver
    assert entry.requires_revalidation
    assert not entry.authorizes_application
    assert entry.to_dict()["modified_maneuver"]["target_heading_deg"] == 190  # type: ignore[index]


def test_missing_or_invalid_lookup_result_does_not_mutate_service() -> None:
    service = DeterministicControllerDecisionService()
    missing_api = InProcessControllerDecisionApi(service, _Lookup(None))
    with pytest.raises(KeyError, match="unknown recommendation_set_id"):
        missing_api.submit(_request())

    invalid_api = InProcessControllerDecisionApi(service, _Lookup("set"))
    with pytest.raises(TypeError, match="unsupported"):
        invalid_api.submit(_request())

    assert service.revision == 0
    assert service.last_audit_log is None


def test_api_and_mapper_reject_wrong_boundary_types() -> None:
    service = DeterministicControllerDecisionService()
    lookup = _Lookup(_recommendation_set())
    with pytest.raises(TypeError, match="DeterministicControllerDecisionService"):
        InProcessControllerDecisionApi("service", lookup)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="RecommendationSetLookup"):
        InProcessControllerDecisionApi(service, object())  # type: ignore[arg-type]

    api = InProcessControllerDecisionApi(service, lookup)
    with pytest.raises(TypeError, match="SubmitControllerDecisionRequest"):
        api.submit("request")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="ControllerDecisionAuditLog"):
        ControllerDecisionReadModelMapper.map("log")  # type: ignore[arg-type]


def test_invalid_request_and_domain_decision_leave_service_unchanged() -> None:
    with pytest.raises(TypeError, match="ControllerDecisionManeuverModel"):
        _request(modified_maneuver="maneuver")
    with pytest.raises(ValueError, match="timezone-aware"):
        _request(decided_at_utc=DECIDED_AT.replace(tzinfo=None))

    service = DeterministicControllerDecisionService()
    api = InProcessControllerDecisionApi(service, _Lookup(_recommendation_set()))
    with pytest.raises(ValueError, match="MODIFY.*rationale"):
        api.submit(
            _request(
                decision_type=ControllerDecisionType.MODIFY,
                modified_maneuver=ControllerDecisionManeuverModel(
                    ResolutionManeuverType.HEADING,
                    target_heading_deg=190,
                ),
            )
        )

    assert service.revision == 0


def test_get_current_returns_none_before_first_decision() -> None:
    api = InProcessControllerDecisionApi(
        DeterministicControllerDecisionService(),
        _Lookup(_recommendation_set()),
    )

    assert api.get_current() is None
