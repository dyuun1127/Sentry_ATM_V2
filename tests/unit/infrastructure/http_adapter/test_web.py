import re
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


def test_both_screens_show_why_a_command_was_refused() -> None:
    """서버가 거부한 이유를 화면에 남기는가.

    서버는 본문에 사유를 담아 보낸다. 그것을 버리고 상태 코드만 보여 주면
    화면에 「HTTP 409」만 남고, 관제사는 무엇이 잘못됐는지 알 길이 없다.
    """
    app = GoldenDemoWebWsgiApp(build_golden_demo_session_runtime().http_app)

    for path in ("/assets/app.js", "/assets/scenario.js"):
        _, _, script = _request(app, path=path)
        assert b"async function refusalReason(response)" in script, path
        assert b"function explainRefusal(message)" in script, path
        assert b"body?.error?.message" in script, path
        # 번역하지 못한 사유는 원문 그대로 보여 준다 — 삼키면 사라진다.
        assert b"return message;" in script, path
        # 명령을 보내는 곳이 그 사유를 쓰는지 본다. 조회(`get`)는 거부 본문이
        # 없으므로 상태 코드로 남겨 둔다.
        start = script.index(b"async function post(")
        end = script.index(b"async function refusalReason(")
        assert b"await refusalReason(response)" in script[start:end], path


def test_console_polling_does_not_block_controller_decisions() -> None:
    """1초마다 도는 읽기가 관제사의 판단을 막으면 안 된다.

    폴링이 `state.busy` 를 잡으면 그것과 겹친 순간에 승인 단추가 조용히 아무
    일도 하지 않는다. 눌렀는데 반응이 없는 것은 관제 화면에서 가장 나쁜 종류의
    고장이다.
    """
    app = GoldenDemoWebWsgiApp(build_golden_demo_session_runtime().http_app)

    _, _, script = _request(app, path="/assets/app.js")

    body = script[script.index(b"async function refresh(") : script.index(b"function follow()")]
    # 판단 중이면 읽지 않는다. 그러나 읽기가 판단을 막지는 않는다.
    assert b"if (state.busy) return;" in body
    assert b"state.busy = true;" not in body
    # 상황이 바뀌면 지난 메시지를 지운다.
    assert b"previousStage" in body
    assert b'say("")' in body


def test_console_offers_both_aircraft_symbol_styles() -> None:
    """항적 기호를 두 방식 중에 고를 수 있는가.

    관제 표시 관행에도 두 갈래가 있고, 어느 쪽이 읽기 쉬운지는 화면 크기와 보는
    사람에 따라 다르다. 한쪽을 지우면 비교할 수 없으므로 둘 다 남긴다.
    """
    app = GoldenDemoWebWsgiApp(build_golden_demo_session_runtime().http_app)

    _, _, body = _request(app)
    _, _, script = _request(app, path="/assets/app.js")

    assert b'id="symbols"' in body
    assert b'const SYMBOL_STYLES = ["circle", "shape"]' in script
    assert b"function drawAircraftBody(group, aircraft, sx, sy)" in script

    # 원형은 원 하나, 기호는 삼각형·사각형. 진행방향 선은 두 방식 모두에 있다.
    start = script.index(b"function drawAircraftBody(")
    end = script.index("/* 서버가 쓰는 심각도".encode(), start)
    drawn = script[start:end]
    assert b'"circle"' in drawn
    assert b'"path"' in drawn
    assert b'"rect"' in drawn
    assert b'class: "ac-vec"' in script

    # 고른 방식은 이 브라우저에 남는다. 저장이 막힌 환경에서도 화면은 떠야 한다.
    assert b"localStorage.getItem(SYMBOL_STORAGE_KEY)" in script
    assert b"function loadSymbolStyle()" in script
    assert script.count(b"} catch {") >= 2


def test_scope_paints_every_aircraft_it_draws() -> None:
    """스코프에 그린 항적이 실제로 보이는가.

    몸통 채움색은 스코프 바탕과 같은 검정이다. 색을 입히는 규칙이 하나도 맞지
    않으면 SVG 기본값인 `stroke: none` 이 남고, 검은 바탕에 검은 원이 된다 —
    항적이 화면에서 조용히 사라진다.

    실제로 그런 적이 있었다. 스코프는 `severity.css`(영문)를 이름표로 붙이는데
    스타일시트는 `severity.ko`(우리말)를 찾고 있었다. 선택자가 한 번도 맞지
    않아 비상 항적을 뺀 전부가 안 보였고, 시험 1491개가 이것을 놓쳤다.

    그래서 두 가지를 함께 못박는다. 이름표 낱말이 한 벌인가, 그리고 그 한 벌이
    다 어긋나도 무엇인가는 그려지는가.
    """
    app = GoldenDemoWebWsgiApp(build_golden_demo_session_runtime().http_app)

    _, _, script = _request(app, path="/assets/app.js")
    _, _, sheet = _request(app, path="/assets/app.css")

    # 선택자가 물고 있는 이름표는 severity.css 한 벌뿐이다. 보이는 우리말
    # 이름(severity.ko)을 이름표로 쓰면 번역을 손보는 순간 색이 끊긴다.
    # 사람이 읽는 글자에는 그대로 severity.ko 를 쓴다 — 그쪽은 막지 않는다.
    assert b"dataset.level = severity.css;" in script
    assert b"dataset.level = severity.ko" not in script

    levels = {value.decode() for value in re.findall(rb'\[data-level="([^"]+)"\]', sheet)}
    assert levels, "위험도 색 규칙이 사라졌다"
    vocabulary = {"normal", "caution", "danger", "emerg"}
    assert levels <= vocabulary, f"스타일시트가 모르는 등급 이름을 쓴다: {levels - vocabulary}"

    # 규칙이 하나도 안 맞아도 테두리는 남는다.
    body_rule = sheet[sheet.index(b".ac-body {") : sheet.index(b".ac-vec {")]
    assert b"stroke: var(--normal)" in body_rule


def test_console_lets_the_controller_open_an_airspace() -> None:
    """공역을 눌러 그 공역의 고시 정보를 볼 수 있는가.

    채움이 없는 도형은 SVG 가 칠해진 곳에서만 클릭을 받는다. 그래서 1px 파선
    위를 정확히 찍어야 잡히는데, 그것은 사실상 못 누르는 것이다. 보이지 않는
    굵은 선을 겹쳐 깔아 경계 근처를 받게 한다.

    안쪽까지 받는 것은 작은 구역뿐이다. 큰 섹터가 안쪽을 받으면 나중에 그려지는
    쪽이 위에 오므로, 그 위에 겹친 제한구역·훈련공역 클릭을 전부 삼킨다.
    """
    app = GoldenDemoWebWsgiApp(build_golden_demo_session_runtime().http_app)

    _, _, body = _request(app)
    _, _, script = _request(app, path="/assets/app.js")
    _, _, sheet = _request(app, path="/assets/app.css")

    assert b'id="zone-card"' in body
    assert b'id="zone"' in body
    assert b"function drawZone()" in script
    assert b"function selectable(parent, shape, zone, kind, inside)" in script

    # 잡는 도형은 보이지 않되 굵어야 한다.
    hit_rule = sheet[sheet.index(b".hit {") : sheet.index(b".zone-sel {")]
    assert b"stroke: transparent" in hit_rule
    assert b"fill: none" in hit_rule
    assert b"pointer-events: all" in hit_rule  # .hit.area — 작은 구역만

    # 섹터는 경계선만, 작은 구역은 안쪽까지.
    start = script.index(b"for (const sector of geometry.tma")
    end = script.index("// --- 거리 링".encode(), start)
    assert b'selectable(airspace, shape, sector, "tma", false)' in script[start:end]
    assert b'selectable(airspace, shape, zone, "restricted", true)' in script
    assert b'selectable(airspace, shape, zone, "moa", true)' in script

    # 화면을 민 끝의 클릭은 선택이 아니다.
    assert script.count(b"if (state.dragged) return;") >= 2

    # 공역과 항적은 한 번에 하나만 고른다.
    assert b"if (state.zone) state.selected = null;" in script
    assert b"if (state.selected) state.zone = null;" in script


def test_both_screens_go_read_only_for_a_viewer() -> None:
    """밖에서 연 화면은 조작 단추를 감추는가.

    막는 것은 서버가 한다 (`test_access.py`). 화면이 하는 일은 **왜 단추가
    없는지 말해 주는 것**이다 — 없는 것과 고장난 것은 다르고, 눌렀는데 403 이
    나는 것은 누르지 못하는 것보다 나쁘다.
    """
    app = GoldenDemoWebWsgiApp(build_golden_demo_session_runtime().http_app)

    _, _, console = _request(app)
    _, _, scenario = _request(app, path="/scenario")
    _, _, console_script = _request(app, path="/assets/app.js")
    _, _, scenario_script = _request(app, path="/assets/scenario.js")

    # 관람 배지는 두 화면 모두에 있고, 기본은 감춰져 있다.
    for body in (console, scenario):
        assert b'id="viewer"' in body
        assert b'class="viewer"' in body
        assert "POC · NOT FOR OPERATIONAL USE".encode() in body

    for script in (console_script, scenario_script):
        assert b'const ACCESS = "/api/v1/reference/access";' in script
        assert b"function applyAccess(access)" in script
        # 서버가 답을 못 주면 조작할 수 있는 것으로 본다 — 루프백 전용일 때
        # 화면이 멋대로 잠기면 발표가 멈춘다.
        assert b"access.operator !== false : true" in script

    # 콘솔은 판단 단추를, 시연 화면은 시계 단추를 감춘다.
    assert b"[data-primary-command], [data-decision-actions]" in console_script
    assert b'$("play").hidden = true;' in scenario_script


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
