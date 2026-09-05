"""Same-origin static Web UI shell around the Golden Demo Session API.

스코프 배경 형상도 여기서 낸다. 공역·활주로·픽스·지형은 시나리오와 무관하고
시간에 따라 변하지 않으므로, 세션 API 의 매 초 갱신되는 읽기 모델에 실어 보내면
같은 30 KB 를 초당 한 번씩 다시 보내게 된다. 한 번 받아 두고 쓰는 것이 맞다.
"""

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from http import HTTPStatus
from importlib.resources import files

from sentry_atm.infrastructure.http.session import GoldenDemoSessionWsgiApp
from sentry_atm.scenario import GOLDEN_DEMO_SCENARIO_ID
from sentry_atm.scenario.sortie_builder import SORTIE_SCENARIO_ID

type StartResponse = Callable[[str, list[tuple[str, str]]], object]
type WsgiResponse = Iterable[bytes]

_STATIC_PACKAGE = "sentry_atm.infrastructure.http"
_GEOMETRY_PATH = "/api/v1/reference/geometry"
_SCENARIO_PATH = "/api/v1/reference/scenario"
_ADVISORY_PATH = "/api/v1/advisory"
_SECURITY_HEADERS = (
    ("Cache-Control", "no-store"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    (
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
        "base-uri 'none'; frame-ancestors 'none'",
    ),
)


@dataclass(frozen=True, slots=True)
class _StaticAsset:
    body: bytes
    content_type: str


class GoldenDemoWebWsgiApp:
    """Serve the UI shell and delegate every non-static route to the Session API."""

    __slots__ = ("_api_app", "_assets", "_session_runtime")

    def __init__(self, api_app: GoldenDemoSessionWsgiApp, session_runtime=None) -> None:
        if not isinstance(api_app, GoldenDemoSessionWsgiApp):
            raise TypeError("api_app must be a GoldenDemoSessionWsgiApp")
        self._api_app = api_app
        # 규정 권고를 내려면 현재 단계 결과가 필요하고, 그것은 세션 읽기 모델이
        # 아니라 런타임이 들고 있다. 없으면 권고 경로만 404 가 된다 — 나머지
        # 화면은 그대로 동작해야 하므로 필수로 두지 않는다.
        self._session_runtime = session_runtime
        self._assets = _load_assets()

    @property
    def api_app(self) -> GoldenDemoSessionWsgiApp:
        return self._api_app

    def _scenario_asset(self) -> _StaticAsset:
        """지금 돌고 있는 시나리오의 시간축과 짚을 지점."""
        scenario_id = self._running_scenario_id()
        cached = _scenario_cache.get(scenario_id)
        if cached is None:
            payload = (
                _golden_scenario_payload()
                if scenario_id == GOLDEN_DEMO_SCENARIO_ID
                else _sortie_scenario_payload()
            )
            cached = _StaticAsset(
                json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                "application/json; charset=utf-8",
            )
            _scenario_cache[scenario_id] = cached
        return cached

    def _running_scenario_id(self) -> str:
        runtime = self._session_runtime
        if runtime is None:
            return SORTIE_SCENARIO_ID
        return runtime.runtime.definition.scenario_id

    def _advisory_asset(self) -> _StaticAsset | None:
        """지금 이 시점에 고시가 말하는 것 — 관할·활주로 순서·체공·복귀경로.

        캐시하지 않는다. 시각이 바뀌면 답이 바뀌기 때문이다.
        """
        runtime = self._session_runtime
        if runtime is None:
            return None
        step = runtime.step_orchestrator.last_result
        if step is None:
            return _StaticAsset(b"{}", "application/json; charset=utf-8")

        from sentry_atm.runtime import (
            ApproachSequenceOrchestrator,
            RegulatoryAdvisoryOrchestrator,
        )

        advisory = RegulatoryAdvisoryOrchestrator().advise(step)
        run = ApproachSequenceOrchestrator().resequence(step)
        payload = {
            "step_id": advisory.step_id,
            "control_units": [
                {
                    "aircraft_id": unit.aircraft_id,
                    "unit": unit.unit,
                    "altitude_ft": unit.altitude_ft,
                    "lateral": unit.lateral,
                }
                for unit in advisory.control_units
            ],
            "runway_slots": [
                {
                    "aircraft_id": slot.aircraft_id,
                    "position": slot.position,
                    "operation": slot.operation,
                    "distance_to_threshold_nm": slot.distance_to_threshold_nm,
                    "required_gap_seconds": slot.required_gap_seconds,
                    "binding": slot.binding,
                    "clauses": list(slot.clauses),
                }
                for slot in advisory.runway_slots
            ],
            "holdings": [
                {
                    "aircraft_id": hold.aircraft_id,
                    "fix": hold.fix,
                    "level_ft": hold.level_ft,
                    "circuits": hold.circuits,
                    "delay_seconds": hold.delay_seconds,
                    "phraseology": hold.phraseology,
                }
                for hold in advisory.holdings
            ],
            "recovery_route": (
                {
                    "aircraft_id": advisory.recovery_route.aircraft_id,
                    "fixes": list(advisory.recovery_route.fixes),
                    "total_nm": advisory.recovery_route.total_nm,
                    "detour_nm": advisory.recovery_route.detour_nm,
                    "clearance": advisory.recovery_route.clearance,
                }
                if advisory.recovery_route
                else None
            ),
            "approach_order": list(run.result.recommended_order) if run else [],
            "stabilised": list(run.result.stabilised_aircraft_ids) if run else [],
            "emergency_aircraft_id": run.result.emergency_aircraft_id if run else None,
        }
        return _StaticAsset(
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def __call__(
        self,
        environ: dict[str, object],
        start_response: StartResponse,
    ) -> WsgiResponse:
        path = environ.get("PATH_INFO", "/")
        if not isinstance(path, str):
            return _text_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                b"invalid WSGI environment",
            )
        if path == _GEOMETRY_PATH:
            asset = _geometry_asset()
        elif path == _SCENARIO_PATH:
            asset = self._scenario_asset()
        elif path == _ADVISORY_PATH:
            asset = self._advisory_asset()
        else:
            asset = self._assets.get(path)
        if asset is None:
            return self._api_app(environ, start_response)

        method = environ.get("REQUEST_METHOD", "GET")
        if not isinstance(method, str):
            return _text_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                b"invalid WSGI environment",
            )
        method = method.upper()
        if method not in {"GET", "HEAD"}:
            return _text_response(
                start_response,
                HTTPStatus.METHOD_NOT_ALLOWED,
                b"use GET or HEAD",
                extra_headers=(("Allow", "GET, HEAD"),),
            )
        return _asset_response(
            start_response,
            asset,
            include_body=method == "GET",
        )


_geometry_cache: _StaticAsset | None = None


def _geometry_asset() -> _StaticAsset:
    """스코프 배경. 시나리오와 무관하므로 한 번 만들어 두고 돌려준다."""
    global _geometry_cache
    if _geometry_cache is None:
        from sentry_atm.api.geometry import scope_geometry

        _geometry_cache = _StaticAsset(
            json.dumps(scope_geometry(), ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
        )
    return _geometry_cache


_scenario_cache: dict[str, _StaticAsset] = {}


def _sortie_scenario_payload() -> dict:
    """13단계와 시나리오 길이.

    재생 API 도 같은 큐를 들고 있지만 프레임 4,484 개가 함께 실려 3.7 MB 가 된다.
    실시간 콘솔은 시계를 직접 돌리므로 그 프레임이 필요 없다.
    """
    from sentry_atm.scenario.sortie_builder import (
        SORTIE_DEFAULT_AREA,
        build_sortie_plan,
    )

    plan_area = SORTIE_DEFAULT_AREA
    plan = build_sortie_plan()
    start = plan.definition.start_time_utc
    # 마지막 단계가 아니라 마지막 항공기가 빠지는 시각까지가 시나리오다.
    last_exit = max(
        (window[1] - start).total_seconds()
        for item in plan.definition.aircraft
        for window in item.presence
    )
    from sentry_atm.scenario.acts import acts_from_steps

    payload = {
        "scenario_id": plan.definition.scenario_id,
        "duration_seconds": last_exit,
        "operating_area_id": plan_area,
        # 단계 시각은 이미 시나리오 원점 기준이므로 다시 옮기지 않는다.
        "acts": acts_from_steps(plan.steps, end_s=last_exit),
        "steps": [
            {
                "n": step.n,
                "t_s": step.t_s,
                "name": step.name,
                "detail": step.detail,
                "clauses": list(step.clauses),
            }
            for step in plan.steps
        ],
    }
    return payload


def _golden_scenario_payload() -> dict:
    """골든 데모는 13단계짜리 대본이 아니라 다섯 개의 검문소다.

    소티의 단계 목록을 그대로 쓰면 시간축이 74분으로 잡히고 짚을 지점이 전부
    화면 밖에 놓인다. 시나리오가 다르면 시간축도 짚을 지점도 다르다.
    """
    from sentry_atm.api.playback import build_golden_demo_playback_contract

    contract = build_golden_demo_playback_contract()
    return {
        "scenario_id": contract.scenario_id,
        "duration_seconds": contract.duration_seconds,
        "operating_area_id": None,
        # 골든 데모는 막으로 나뉘지 않는다 — 다섯 검문소짜리 대본이다.
        "acts": [],
        "steps": [
            {
                "n": index + 1,
                "t_s": cue.offset_seconds,
                "name": cue.label,
                "detail": "",
                "clauses": [],
            }
            for index, cue in enumerate(contract.cues)
        ],
    }


def _load_assets() -> dict[str, _StaticAsset]:
    root = files(_STATIC_PACKAGE).joinpath("static")
    index = _StaticAsset(
        root.joinpath("index.html").read_bytes(),
        "text/html; charset=utf-8",
    )
    scenario = _StaticAsset(
        root.joinpath("scenario.html").read_bytes(),
        "text/html; charset=utf-8",
    )
    return {
        "/": index,
        "/index.html": index,
        # 시연 진행 화면. 관제 콘솔과 같은 세션을 보되 시계는 이쪽이 쥔다.
        "/scenario": scenario,
        "/scenario.html": scenario,
        "/assets/scenario.css": _StaticAsset(
            root.joinpath("scenario.css").read_bytes(),
            "text/css; charset=utf-8",
        ),
        "/assets/scenario.js": _StaticAsset(
            root.joinpath("scenario.js").read_bytes(),
            "text/javascript; charset=utf-8",
        ),
        "/assets/app.css": _StaticAsset(
            root.joinpath("app.css").read_bytes(),
            "text/css; charset=utf-8",
        ),
        "/assets/app.js": _StaticAsset(
            root.joinpath("app.js").read_bytes(),
            "text/javascript; charset=utf-8",
        ),
    }


def _asset_response(
    start_response: StartResponse,
    asset: _StaticAsset,
    *,
    include_body: bool,
) -> WsgiResponse:
    start_response(
        "200 OK",
        [
            ("Content-Type", asset.content_type),
            ("Content-Length", str(len(asset.body))),
            *_SECURITY_HEADERS,
        ],
    )
    return (asset.body,) if include_body else ()


def _text_response(
    start_response: StartResponse,
    status: HTTPStatus,
    body: bytes,
    *,
    extra_headers: tuple[tuple[str, str], ...] = (),
) -> WsgiResponse:
    start_response(
        f"{status.value} {status.phrase}",
        [
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Content-Length", str(len(body))),
            *_SECURITY_HEADERS,
            *extra_headers,
        ],
    )
    return (body,)
