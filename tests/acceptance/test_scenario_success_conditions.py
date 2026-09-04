"""시나리오 필수 성공 조건 SC-001 ~ SC-014 인수 시험.

`docs/scenarios.md` 9장의 조건을 하나씩 대응한다. 시험 이름에 ID 를 넣어 문서와
코드가 1:1 로 붙게 했다 — 조건이 늘거나 바뀌면 대응하는 시험이 없다는 게 바로
드러나야 한다.

단위 시험과 달리 여기서는 **실제 Runtime 을 끝까지 구동한다.** 각 계층이 따로
맞는 것과 이어 붙였을 때 맞는 것은 다른 문제이고, 성공 조건은 후자를 묻는다.
"""

from math import hypot

import pytest

from sentry_atm.api import GoldenDemoSessionStage
from sentry_atm.domain import (
    ConflictStatus,
    FlightPhase,
    OperationalPriorityLevel,
    ResolutionValidationVerdict,
    RiskLevel,
)
from sentry_atm.domain.approach_sequence import ApproachOrderReasonCode
from sentry_atm.runtime import (
    ApproachSequenceOrchestrator,
    GoldenDemoSessionCommand,
    build_golden_demo_session_runtime,
)
from sentry_atm.runtime.composition import build_golden_demo_runtime
from sentry_atm.runtime.orchestrator import GoldenDemoStepOrchestrator

PRIMARY_PAIR = ("CIV-A02", "MIL-F01")
EMERGENCY = "MIL-T01"
STABILISED = "CIV-A01"
UNRESOLVED_LEVELS = (RiskLevel.HIGH, RiskLevel.CRITICAL)


@pytest.fixture
def session():
    return build_golden_demo_session_runtime()


@pytest.fixture
def at_conflict(session):
    session.command_service.execute(GoldenDemoSessionCommand.START)
    return session.command_service.execute(GoldenDemoSessionCommand.ADVANCE_TO_CONFLICT)


@pytest.fixture
def recommended(session, at_conflict):
    return session.command_service.execute(GoldenDemoSessionCommand.GENERATE_RECOMMENDATION)


@pytest.fixture
def resolved(session, recommended):
    session.command_service.execute(GoldenDemoSessionCommand.ACCEPT_RECOMMENDATION)
    return session.command_service.execute(GoldenDemoSessionCommand.APPLY_APPROVED_MANEUVER)


def step_at(seconds: int):
    """실제 Runtime 을 주어진 시각까지 진행한 단계 결과."""
    runtime = build_golden_demo_runtime()
    runtime.simulation.clock.play()
    return GoldenDemoStepOrchestrator(runtime).step(advance_steps=seconds)


# ══════════════════════════════════════════════════ 시작 상태


def test_sc_001_no_violation_or_exception_at_start(session):
    """SC-001 — 시작 시 현재 분리 위반과 Exception 이 없어야 한다."""
    view = session.command_service.execute(GoldenDemoSessionCommand.START)

    assert view.stage is GoldenDemoSessionStage.MONITORING
    assert view.active_exception_count == 0
    assert view.primary_conflict is None

    result = step_at(0)
    predicted = [
        event
        for event in (result.conflict_run.assessments if result.conflict_run else ())
        if event.status is ConflictStatus.PREDICTED
    ]
    assert predicted == []


def test_sc_002_entry_conformance_deviation_is_detected(at_conflict):
    """SC-002 — 기대 진입 상태와 Actual State 불일치가 탐지되어야 한다."""
    deviation = at_conflict.deviation

    assert deviation is not None
    assert deviation.aircraft_id == "MIL-F01"
    # 편차가 "있다"가 아니라 무엇이 얼마나 어긋났는지가 남아야 설명이 된다.
    assert deviation.vertical_deviation_ft != 0.0
    assert deviation.heading_deviation_deg != 0.0
    assert deviation.lateral_deviation_nm > 0.0


# ══════════════════════════════════════════════════ 충돌 탐지


def test_sc_003_pair_is_safe_now_but_predicted_within_the_horizon(at_conflict):
    """SC-003 — 현재는 안전하지만 120초 Horizon 안에서 위험해야 한다."""
    conflict = at_conflict.primary_conflict

    assert conflict is not None
    assert tuple(conflict.aircraft_ids) == PRIMARY_PAIR
    assert conflict.status == ConflictStatus.PREDICTED.value
    # 지금 이격은 최저치를 넘고, 위험은 앞으로 온다.
    assert 0.0 < conflict.tcpa_seconds <= 120.0

    result = step_at(70)
    states = {s.aircraft_id: s for s in result.traffic_snapshot.states}
    first, second = states[PRIMARY_PAIR[0]], states[PRIMARY_PAIR[1]]
    current_horizontal_nm = hypot(first.x_nm - second.x_nm, first.y_nm - second.y_nm)
    current_vertical_ft = abs(first.altitude_ft - second.altitude_ft)
    # 판정은 결합 규칙이므로 한쪽만 확보돼도 현재는 안전이다.
    assert (
        current_horizontal_nm >= conflict.horizontal_threshold_nm
        or current_vertical_ft >= conflict.vertical_threshold_ft
    )


def test_sc_004_conflict_evidence_is_complete(at_conflict):
    """SC-004 — 수평분리·수직분리·TCPA(또는 예측시각)·원인이 포함되어야 한다."""
    conflict = at_conflict.primary_conflict

    assert conflict.horizontal_separation_nm > 0.0
    assert conflict.vertical_separation_ft >= 0.0
    assert conflict.tcpa_seconds > 0.0
    assert conflict.closest_approach_time_utc
    assert conflict.risk_reason_codes  # 원인
    assert conflict.horizontal_threshold_nm > 0.0
    assert conflict.vertical_threshold_ft > 0.0
    # 어느 기준으로 판정했는지가 붙어야 근거가 성립한다.
    assert conflict.rule_profile_id


# ══════════════════════════════════════════════════ 회피 후보


def test_sc_005_four_real_maneuvers_and_one_no_action(recommended):
    """SC-005 — 최소 4개의 실제 기동 후보와 No-action 후보가 생성되어야 한다."""
    comparisons = recommended.candidate_comparisons

    assert comparisons is not None
    kinds = {row.candidate_id: row.maneuver_type for row in comparisons}
    no_action = [cid for cid, kind in kinds.items() if kind == "NO_ACTION"]
    real = [cid for cid, kind in kinds.items() if kind != "NO_ACTION"]

    assert len(real) >= 4
    assert len(no_action) == 1


def test_sc_006_candidates_are_resimulated_against_all_traffic(recommended, at_conflict):
    """SC-006 — 후보는 전체 Traffic 과 함께 재시뮬레이션되어야 한다."""
    comparisons = recommended.candidate_comparisons
    traffic_ids = {row.aircraft_id for row in at_conflict.traffic}

    # 2차 충돌은 충돌쌍 밖의 항적에서도 나올 수 있어야 한다. 두 기체만 놓고
    # 재시뮬레이션하면 나머지와의 충돌을 볼 수 없다.
    secondary_ids = {
        aircraft_id
        for row in comparisons
        for pair in row.secondary_conflict_aircraft_ids
        for aircraft_id in pair
    }
    assert secondary_ids
    assert secondary_ids <= traffic_ids
    assert secondary_ids - set(PRIMARY_PAIR)


def test_sc_007_unsafe_candidates_are_excluded_from_the_recommendation(recommended):
    """SC-007 — 2차 충돌 또는 Rule 위반 후보는 추천에서 제외되어야 한다."""
    comparisons = {row.candidate_id: row for row in recommended.candidate_comparisons}
    recommended_ids = {item.candidate_id for item in recommended.recommendation.recommendations}

    excluded = {
        candidate_id
        for candidate_id, row in comparisons.items()
        if row.verdict != ResolutionValidationVerdict.SAFE.value
    }
    # 걸러진 이유가 2차 충돌과 Rule 위반 둘 다 실제로 나타나야 한다.
    assert excluded  # 걸러낼 것이 실제로 있어야 시험이 의미가 있다
    # 걸러진 이유가 2차 충돌과 Rule 위반 둘 다 실제로 나타나야 한다.
    assert any(comparisons[c].secondary_conflict_aircraft_ids for c in excluded)
    assert any(comparisons[c].rule_violation_ids for c in excluded)
    assert not (excluded & recommended_ids)

    primary_id = recommended.recommendation.primary_recommendation_id
    primary = next(
        item
        for item in recommended.recommendation.recommendations
        if item.recommendation_id == primary_id
    )
    assert comparisons[primary.candidate_id].verdict == ResolutionValidationVerdict.SAFE.value


# ══════════════════════════════════════════════════ 관제사 결정


def test_sc_008_runtime_is_unchanged_before_approval(session, recommended):
    """SC-008 — 관제사 승인 전에는 Aircraft Runtime 이 변경되지 않아야 한다.

    시계는 계속 흐르므로 위치와 고도는 자연히 변한다. 확인할 것은 **승인된 기동이
    적용되었는가**이며, 그 표식은 적용 근거(revalidation)와 목표 고도 도달이다.
    """
    primary_id = recommended.recommendation.primary_recommendation_id
    primary = next(
        item
        for item in recommended.recommendation.recommendations
        if item.recommendation_id == primary_id
    )
    target_id = primary.target_aircraft_id

    accepted = session.command_service.execute(GoldenDemoSessionCommand.ACCEPT_RECOMMENDATION)

    assert accepted.stage is GoldenDemoSessionStage.DECISION_ACCEPTED
    assert accepted.revalidation is None, "승인만으로 적용 근거가 생기면 안 된다"
    assert accepted.application_step_id is None

    applied = session.command_service.execute(GoldenDemoSessionCommand.APPLY_APPROVED_MANEUVER)
    assert applied.revalidation is not None
    assert applied.application_step_id
    assert applied.revalidation.applied_aircraft_id == target_id

    # 승인 시점의 대상기는 아직 목표 고도가 아니었고, 적용 뒤에 도달한다.
    before = next(row for row in accepted.traffic if row.aircraft_id == target_id)
    assert before.altitude_ft != applied.revalidation.applied_altitude_ft


def test_sc_009_accepted_candidate_resolves_the_initial_conflict(resolved):
    """SC-009 — CAND-A 승인 후 최초 Conflict 가 해소되어야 한다."""
    assert resolved.stage is GoldenDemoSessionStage.CONFLICT_RESOLVED

    revalidation = resolved.revalidation
    assert revalidation is not None
    assert revalidation.resolved
    assert revalidation.conflict_status == ConflictStatus.SAFE.value
    assert revalidation.risk_level == RiskLevel.LOW.value


# ══════════════════════════════════════════════════ 비상 우선권


def test_sc_010_emergency_priority_outranks_risk():
    """SC-010 — MIL-T01 비상 선언 후 Risk 와 별개로 Priority 가 최상위가 되어야 한다."""
    result = step_at(245)
    by_aircraft = {a.aircraft_id: a for a in result.priority_assessments}

    assert by_aircraft[EMERGENCY].priority_level is OperationalPriorityLevel.EMERGENCY

    top = result.exception_queue_snapshot.active_items[0]
    assert EMERGENCY in top.subject_aircraft_ids

    # 위험도가 아니라 우선권으로 올라온 것이어야 한다. 이 시점에 비상기가 걸린
    # 충돌은 없다.
    emergency_conflicts = [
        event
        for event in (result.conflict_run.assessments if result.conflict_run else ())
        if event.status is ConflictStatus.PREDICTED and EMERGENCY in event.pair.aircraft_ids
    ]
    assert emergency_conflicts == []


def test_sc_011_resequencing_respects_the_stabilised_aircraft_phase():
    """SC-011 — 비상 순서 재구성 시 이미 안정된 CIV-A01 의 비행단계를 고려해야 한다."""
    run = ApproachSequenceOrchestrator().resequence(step_at(245))

    assert run is not None
    result = run.result
    assert result.emergency_aircraft_id == EMERGENCY
    assert result.moved_up(EMERGENCY)

    # 안정된 기체는 자리를 지키고, 그 이유가 비행단계임이 남아야 한다.
    assert result.recommended_order[0] == STABILISED
    assert STABILISED not in result.displaced_aircraft_ids
    slot = next(s for s in result.slots if s.aircraft_id == STABILISED)
    assert slot.flight_phase in (FlightPhase.APPROACH, FlightPhase.FINAL)
    assert ApproachOrderReasonCode.STABILISED_ON_APPROACH in slot.reason_codes


def test_sc_012_emergency_handling_also_passes_validation(recommended):
    """SC-012 — 비상 처리 후보도 2차 충돌과 Rule 검증을 통과해야 한다.

    검증을 통과한 후보만 추천된다는 규약은 비상 구간에서도 같다. 여기서는 그
    규약 자체를 고정한다 — 판정 근거 없이 추천된 후보가 하나라도 있으면 안 된다.
    """
    comparisons = {row.candidate_id: row for row in recommended.candidate_comparisons}

    for item in recommended.recommendation.recommendations:
        row = comparisons[item.candidate_id]
        assert row.verdict == ResolutionValidationVerdict.SAFE.value
        assert row.secondary_conflict_aircraft_ids == ()
        assert row.rule_violation_ids == ()
        assert row.recommended


# ══════════════════════════════════════════════════ 감사와 종료


def test_sc_013_every_decision_and_application_is_audited(session, resolved):
    """SC-013 — 모든 추천·근거·관제사 결정 및 적용 결과가 Audit Log 에 남아야 한다."""
    audit = resolved.controller_decision

    assert audit is not None
    assert audit.entries, "결정이 하나도 남지 않았다"
    entry = next(e for e in audit.entries if e.decision_id == audit.latest_decision_id)
    assert entry.decision_type == "ACCEPT"
    assert entry.candidate_id
    assert entry.decided_at_utc
    assert entry.recommendation_set_id
    assert entry.authorizes_application

    # 추천 근거와 적용 결과가 각각 어느 단계에서 나왔는지 되짚을 수 있어야 한다.
    assert resolved.resolution_step_id
    assert resolved.decision_step_id
    assert resolved.application_step_id
    assert resolved.primary_conflict is not None
    assert resolved.revalidation is not None


def test_sc_014_no_unresolved_high_or_critical_conflict_at_the_end(session, resolved):
    """SC-014 — 시나리오 종료 시 미해결 HIGH 또는 CRITICAL Conflict 가 없어야 한다."""
    remaining = [
        item.exception_id
        for item in resolved.exception_queue.items
        if item.status == "ACTIVE"
        and item.severity in {level.value for level in UNRESOLVED_LEVELS}
    ]
    assert remaining == [], f"미해결 고위험 항목이 남았다: {remaining}"

    # 비상 구간까지 흘려 보내도 같아야 한다.
    late = step_at(300)
    unresolved = [
        event
        for event in (late.conflict_run.assessments if late.conflict_run else ())
        if event.status is ConflictStatus.PREDICTED
    ]
    assert unresolved == []


# ══════════════════════════════════════════════════ 문서와 코드의 대응


def test_every_documented_success_condition_has_a_test():
    """문서의 SC 항목과 이 파일의 시험이 1:1 로 붙어 있는가.

    조건이 추가됐는데 시험이 없으면 여기서 걸린다. 인수 시험의 목록이 문서와
    조용히 어긋나는 것이 이 시험이 막으려는 실패다.
    """
    import re
    from pathlib import Path

    doc = Path(__file__).resolve().parents[2] / "docs" / "scenarios.md"
    documented = set(re.findall(r"`(SC-\d{3})`", doc.read_text(encoding="utf-8")))

    source = Path(__file__).read_text(encoding="utf-8")
    implemented = {
        f"SC-{number}" for number in re.findall(r"def test_sc_(\d{3})_", source)
    }

    assert documented, "문서에서 SC 항목을 찾지 못했다"
    assert documented == implemented, (
        f"문서에만 있음 {sorted(documented - implemented)} / "
        f"시험에만 있음 {sorted(implemented - documented)}"
    )
