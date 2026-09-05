from io import BytesIO

import pytest

from sentry_atm.infrastructure.http import GoldenDemoWebWsgiApp
from sentry_atm.runtime import build_golden_demo_session_runtime

SCENARIO_PATH = "/api/v1/reference/scenario"


def _request(
    app: GoldenDemoWebWsgiApp,
    *,
    method: object = "GET",
    path: object = "/",
    body: bytes = b"",
    content_type: str = "application/json",
) -> tuple[int, dict[str, str], bytes]:
    captured: dict[str, object] = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = headers

    response_body = b"".join(
        app(
            {
                "REQUEST_METHOD": method,
                "PATH_INFO": path,
                "QUERY_STRING": "",
                "CONTENT_TYPE": content_type,
                "CONTENT_LENGTH": str(len(body)),
                "wsgi.input": BytesIO(body),
            },
            start_response,
        )
    )
    status_code = int(str(captured["status"]).split(maxsplit=1)[0])
    headers = dict(captured["headers"])  # type: ignore[arg-type]
    return status_code, headers, response_body


def test_root_serves_accessible_ui_shell_with_security_headers() -> None:
    runtime = build_golden_demo_session_runtime()
    app = GoldenDemoWebWsgiApp(runtime.http_app)

    status, headers, body = _request(app)

    assert status == 200
    assert headers["Content-Type"] == "text/html; charset=utf-8"
    assert headers["Content-Length"] == str(len(body))
    assert headers["Cache-Control"] == "no-store"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'self'" in headers["Content-Security-Policy"]

    # 완전한 문서여야 한다. 조각으로 내보내면 언어·문자셋·뷰포트가 빠지고
    # 브라우저가 호환 모드로 그린다.
    assert b"<!doctype html>" in body
    assert b'<html lang="ko">' in body
    assert b'<meta charset="utf-8" />' in body
    assert b"SENTRY ATM" in body
    assert b"skip-link" in body

    # 관제사가 판단하는 자리들.
    for marker in (
        b"data-primary-command",
        b"data-conflict-explainability",
        b"data-deviation-panel",
        b"data-candidate-panel",
        b"data-decision-actions",
        b"data-decision-form",
        b"data-modified-type",
        b"data-modified-revalidation",
    ):
        assert marker in body, marker

    # 스코프 계층. 배경과 항적이 각각 자기 그룹을 가져야 지우고 다시 그릴 수 있다.
    for layer in (b'id="g-terrain"', b'id="g-airspace"', b'id="g-traffic"', b'id="g-links"'):
        assert layer in body, layer

    # 관제 화면처럼 생긴 것을 관제 화면이 아니라고 말해 주는 것은 화면 자신뿐이다.
    assert "POC · NOT FOR OPERATIONAL USE".encode() in body

    assert b"/assets/app.css" in body
    assert app.api_app is runtime.http_app


def test_console_carries_no_demo_transport() -> None:
    """관제 화면에 시연용 조작부가 있으면 안 된다.

    실제 관제 화면에 「13단계 이동」이나 재생 배속 단추가 있을 수 없다. 시계는
    시연 진행 화면이 쥐고 이 화면은 따라간다.
    """
    app = GoldenDemoWebWsgiApp(build_golden_demo_session_runtime().http_app)

    _, _, body = _request(app)
    _, _, script = _request(app, path="/assets/app.js")

    for absent in (b'id="play"', b'id="rates"', b'id="track"', b'id="steps"'):
        assert absent not in body, absent
    # 시계를 미는 명령은 이 화면의 것이 아니다.
    assert b'"ADVANCE"' not in script
    assert b'"ADVANCE_TO_CONFLICT"' not in script

    # 대신 시계를 누가 쥐는지 적어 둔다.
    assert b'href="/scenario"' in body

    # 따라가려면 주기적으로 읽어야 한다.
    assert b"async function refresh(" in script
    assert b"function follow()" in script


@pytest.mark.parametrize(
    ("path", "content_type", "content"),
    [
        ("/index.html", "text/html; charset=utf-8", b"SENTRY ATM"),
        ("/assets/app.css", "text/css; charset=utf-8", b".ac-trail"),
        (
            "/assets/app.js",
            "text/javascript; charset=utf-8",
            b"/api/v1/golden-demo/session",
        ),
        ("/scenario", "text/html; charset=utf-8", b"13\xeb\x8b\xa8\xea\xb3\x84"),
        ("/assets/scenario.css", "text/css; charset=utf-8", b".now-name"),
        ("/assets/scenario.js", "text/javascript; charset=utf-8", b"AWAITS_CONTROLLER"),
    ],
)
def test_static_assets_have_exact_content_types(
    path: str,
    content_type: str,
    content: bytes,
) -> None:
    app = GoldenDemoWebWsgiApp(build_golden_demo_session_runtime().http_app)

    status, headers, body = _request(app, path=path)

    assert status == 200
    assert headers["Content-Type"] == content_type
    assert content in body


def test_ui_assets_include_every_controller_decision_and_busy_boundary() -> None:
    """관제사가 화면에서 낼 수 있어야 하는 판단이 전부 있는가.

    하나라도 빠지면 그 판단은 화면에서 할 수 없고, 사람이 판단한다는 주장이
    그만큼 좁아진다.
    """
    app = GoldenDemoWebWsgiApp(build_golden_demo_session_runtime().http_app)

    _, _, script = _request(app, path="/assets/app.js")

    for command in (
        b'"GENERATE_RECOMMENDATION"',
        b'"ACCEPT_RECOMMENDATION"',
        b'"MODIFY_RECOMMENDATION"',
        b'"REJECT_RECOMMENDATION"',
        b'"REVALIDATE_MODIFIED_MANEUVER"',
        b'"APPLY_VALIDATED_MODIFIED_MANEUVER"',
        b'"APPLY_APPROVED_MANEUVER"',
    ):
        assert command in script, command

    # 중복 제출 경계. 없으면 한 번의 판단이 두 번 기록될 수 있다.
    assert b"if (state.busy) return;" in script
    # 거부당한 이유를 삼키지 않는다.
    assert b'say(String(error.message || error), "bad")' in script
    assert b"function renderConflictExplainability(session)" in script
    assert b"session?.primary_conflict" in script
    assert b"function renderDeviation(deviation)" in script
    assert b"function renderCandidateComparisons(candidates)" in script
    assert b"function modifiedManeuver(altitudeFt)" in script
    assert b"COMMAND_BY_STAGE.BLOCKED_MODIFICATION" in script


def test_ui_assets_draw_the_scope_from_reference_geometry_and_leave_trails() -> None:
    """스코프가 배경 형상과 항적 자취를 그리는가.

    자취가 없으면 현재 위치와 속도벡터만 남아 선회 중인지 직진 중인지 읽을 수
    없다. 배경 형상은 서버에서 받아야 화면과 판정이 같은 공역을 본다.
    """
    app = GoldenDemoWebWsgiApp(build_golden_demo_session_runtime().http_app)

    _, _, script = _request(app, path="/assets/app.js")
    _, _, stylesheet = _request(app, path="/assets/app.css")

    assert b'const GEOMETRY = "/api/v1/reference/geometry"' in script
    assert b'const SCENARIO = "/api/v1/reference/scenario"' in script
    assert b'const ADVISORY = "/api/v1/advisory"' in script
    assert b"function recordTrails()" in script
    assert b"TRAIL_POINTS" in script
    assert b".ac-trail" in stylesheet

    # 좌표 변환은 서버와 같은 타원체를 써야 한다. 평균 반지름으로 근사하면
    # 배경과 항적이 어긋난다.
    assert b"WGS84_F = 1 / 298.257223563" in script
    assert b"function curvatureRadiiNm(latDeg)" in script


def test_console_type_scale_is_defined_in_one_place() -> None:
    """글씨 크기가 흩어져 있으면 화면 전체를 키울 수 없다.

    예전에는 40곳 넘게 흩어진 px 값이었다. 하나를 키우면 옆의 것과 어긋나고,
    관제사가 읽기에 작다는 말에 손댈 자리를 찾을 수 없었다.
    """
    app = GoldenDemoWebWsgiApp(build_golden_demo_session_runtime().http_app)

    _, _, stylesheet = _request(app, path="/assets/app.css")

    for name in (b"--fs-2xs", b"--fs-xs", b"--fs-sm", b"--fs-md", b"--fs-lg", b"--fs-clock"):
        assert name in stylesheet, name
    # 스케일 밖의 날 px 값이 남아 있으면 그것만 안 따라 커진다.
    import re

    raw = re.findall(rb"font-size:\s*([\d.]+px)", stylesheet)
    assert raw == [], raw


def test_console_scope_zooms_with_the_wheel_and_pans_by_drag() -> None:
    """스코프를 휠로 확대하고 끌어서 옮길 수 있는가.

    프리셋 범위만으로는 보려는 곳이 화면 구석에 있을 때 할 수 있는 것이 없다.
    확대는 커서 아래 지점을 붙잡아야 한다 — 화면 가운데 기준이면 보려던 항적이
    확대할수록 밖으로 밀려난다.
    """
    app = GoldenDemoWebWsgiApp(build_golden_demo_session_runtime().http_app)

    _, _, script = _request(app, path="/assets/app.js")
    _, _, stylesheet = _request(app, path="/assets/app.css")

    assert b"function wireScopeNavigation()" in script
    assert b'"wheel"' in script
    assert b"function nmAt(screenX, screenY)" in script
    assert b"MIN_RANGE_NM" in script and b"MAX_RANGE_NM" in script
    # 확대 뒤 커서 아래 지점을 제자리에 두는 보정.
    assert b"state.view.cx += anchorX - afterX" in script
    # 끌기와 항적 선택을 가른다.
    assert b"DRAG_SLOP_PX" in script
    assert b"if (state.dragged) return;" in script
    # 길을 잃었을 때 돌아오는 수단.
    assert b"function recentre()" in script
    assert b'"dblclick"' in script
    assert b"touch-action: none" in stylesheet


def test_scenario_screen_owns_the_clock_and_waits_for_the_controller() -> None:
    """시연 진행 화면이 시계를 쥐고, 판단이 필요하면 스스로 멈추는가.

    멈추지 않으면 상신된 안이 검증된 시각과 관제사가 승인하는 시각이 벌어지고,
    그 사이 교통은 계속 움직인다.
    """
    app = GoldenDemoWebWsgiApp(build_golden_demo_session_runtime().http_app)

    _, _, body = _request(app, path="/scenario")
    _, _, script = _request(app, path="/assets/scenario.js")
    _, _, stylesheet = _request(app, path="/assets/scenario.css")

    assert b"<!doctype html>" in body
    assert b'<html lang="ko">' in body
    assert b'id="play"' in body
    assert b'id="rates"' in body
    assert b'id="track"' in body
    assert b"data-reset-command" in body
    assert "POC · NOT FOR OPERATIONAL USE".encode() in body
    # 관제 콘솔로 건너갈 수 있어야 한다.
    assert b'href="/"' in body

    # 시계를 미는 명령은 이쪽에 있다.
    for command in (b'"START"', b'"ADVANCE"', b'"RESET"'):
        assert command in script, command

    # 세션 시작 여부는 서버가 안다 — 콘솔과 같은 규칙이다.
    assert b"function needsStart()" in script
    assert b'stage === "READY"' in script

    # 판단이 필요한 단계에서 멈춘다.
    assert b"const AWAITS_CONTROLLER" in script
    assert b"function pauseIfControllerNeeded()" in script
    assert b"RECOMMENDATION_AVAILABLE" in script
    # 멈춰 있는 동안에도 콘솔의 판단을 알아채야 한다.
    assert b"function watchWhilePaused()" in script

    # 청중이 읽는 화면이므로 큰 글씨가 필요하다.
    assert b".now-name" in stylesheet
    assert b"clamp(30px" in stylesheet


def test_scenario_endpoint_carries_the_act_structure() -> None:
    """13단계는 네 막으로 묶여야 시연을 보는 쪽이 어디쯤인지 안다."""
    import json

    from sentry_atm.runtime import build_sortie_session_runtime

    sortie = build_sortie_session_runtime()
    _, _, body = _request(GoldenDemoWebWsgiApp(sortie.http_app, sortie), path=SCENARIO_PATH)
    payload = json.loads(body)

    acts = payload["acts"]
    assert [act["n"] for act in acts] == [1, 2, 3, 4]
    assert [act["name"] for act in acts] == ["평시", "출격", "비상복귀", "우선착륙"]
    # 막은 빈틈 없이 이어지고 마지막은 시나리오 끝까지 간다.
    for previous, current in zip(acts, acts[1:], strict=False):
        assert previous["t1"] == current["t0"]
    assert acts[-1]["t1"] == round(payload["duration_seconds"], 1)
    # 모든 단계가 어느 막엔가 속한다.
    covered = [n for act in acts for n in act["steps"]]
    assert sorted(covered) == [step["n"] for step in payload["steps"]]


def test_reference_and_advisory_endpoints_serve_json() -> None:
    """스코프 배경과 규정 권고가 API 로 나오는가."""
    runtime = build_golden_demo_session_runtime()
    app = GoldenDemoWebWsgiApp(runtime.http_app, runtime)

    for path in ("/api/v1/reference/geometry", "/api/v1/reference/scenario"):
        status, headers, body = _request(app, path=path)
        assert status == 200, path
        assert headers["Content-Type"] == "application/json; charset=utf-8"
        assert body.startswith(b"{")

    # 권고는 단계가 한 번이라도 계산된 뒤에 값이 생긴다. 그 전에는 빈 객체다.
    status, headers, body = _request(app, path="/api/v1/advisory")
    assert status == 200
    assert headers["Content-Type"] == "application/json; charset=utf-8"


def test_scenario_endpoint_describes_the_running_scenario() -> None:
    """돌고 있는 시나리오를 말해야 한다.

    늘 소티를 돌려주면 골든 데모를 돌면서 74분짜리 시간축과 13단계를 그리게
    되고, 화면이 무엇을 보여 주는지 스스로 틀리게 말한다.
    """
    import json

    from sentry_atm.runtime import build_sortie_session_runtime

    golden = build_golden_demo_session_runtime()
    _, _, body = _request(GoldenDemoWebWsgiApp(golden.http_app, golden), path=SCENARIO_PATH)
    payload = json.loads(body)
    assert payload["scenario_id"] == "RKTU_GOLDEN_DEMO_V1"
    assert payload["duration_seconds"] == 300.0

    sortie = build_sortie_session_runtime()
    _, _, body = _request(GoldenDemoWebWsgiApp(sortie.http_app, sortie), path=SCENARIO_PATH)
    payload = json.loads(body)
    assert payload["scenario_id"] == "RKTU_SORTIE_V1"
    assert payload["duration_seconds"] > 3_600.0
    assert len(payload["steps"]) == 13


def test_advisory_is_absent_without_a_runtime() -> None:
    """런타임 없이 감싸면 권고 경로만 세션 API 로 넘어간다 — 나머지는 그대로 돈다."""
    app = GoldenDemoWebWsgiApp(build_golden_demo_session_runtime().http_app)

    status, _, _ = _request(app, path="/api/v1/advisory")

    assert status == 404


def test_head_and_method_boundaries_are_explicit() -> None:
    app = GoldenDemoWebWsgiApp(build_golden_demo_session_runtime().http_app)
    get_status, get_headers, get_body = _request(app, path="/assets/app.css")

    head_status, head_headers, head_body = _request(
        app,
        method="HEAD",
        path="/assets/app.css",
    )
    post_status, post_headers, post_body = _request(app, method="POST")

    assert get_status == head_status == 200
    assert head_body == b""
    assert head_headers["Content-Length"] == str(len(get_body))
    assert get_headers["Content-Length"] == head_headers["Content-Length"]
    assert post_status == 405
    assert post_headers["Allow"] == "GET, HEAD"
    assert post_body == b"use GET or HEAD"


def test_api_routes_delegate_to_same_session_app() -> None:
    runtime = build_golden_demo_session_runtime()
    app = GoldenDemoWebWsgiApp(runtime.http_app)

    status, headers, body = _request(app, path="/api/v1/golden-demo/session")
    missing_status, missing_headers, missing_body = _request(app, path="/missing")

    assert status == 200
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert b'"stage":"READY"' in body
    assert missing_status == 404
    assert missing_headers["Content-Type"] == "application/json; charset=utf-8"
    assert b'"code":"ROUTE_NOT_FOUND"' in missing_body


def test_adapter_validates_dependency_and_wsgi_environment() -> None:
    with pytest.raises(TypeError, match="GoldenDemoSessionWsgiApp"):
        GoldenDemoWebWsgiApp(object())  # type: ignore[arg-type]

    app = GoldenDemoWebWsgiApp(build_golden_demo_session_runtime().http_app)
    path_status, _, path_body = _request(app, path=object())
    method_status, _, method_body = _request(app, method=object())

    assert path_status == 400
    assert path_body == b"invalid WSGI environment"
    assert method_status == 400
    assert method_body == b"invalid WSGI environment"
