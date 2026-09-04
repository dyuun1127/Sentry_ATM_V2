"""No-dependency end-to-end readiness check for the local Golden Demo."""

import json
from dataclasses import dataclass
from http.client import HTTPConnection
from numbers import Real
from threading import Thread
from wsgiref.simple_server import WSGIRequestHandler

from sentry_atm.infrastructure.http.server import (
    LocalGoldenDemoServerSettings,
    create_local_golden_demo_server,
)

_SESSION_PATH = "/api/v1/golden-demo/session"
_COMMAND_PATH = "/api/v1/golden-demo/session/commands"
_PLAYBACK_PATH = "/api/v1/golden-demo/playback"


class GoldenDemoRegressionFailure(RuntimeError):
    """Raised when one observable Golden Demo contract is not satisfied."""


@dataclass(frozen=True, slots=True)
class GoldenDemoRegressionCheckpoint:
    """One successfully verified browser-facing checkpoint."""

    code: str
    stage: str
    elapsed_seconds: float
    detail: str


@dataclass(frozen=True, slots=True)
class GoldenDemoRegressionReport:
    """Deterministic summary returned after a complete fresh Session run."""

    initial_session_id: str
    reset_session_id: str
    checkpoints: tuple[GoldenDemoRegressionCheckpoint, ...]


class _QuietWsgiRequestHandler(WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        """Keep the readiness report free from per-request access logs."""


def run_golden_demo_regression(
    *,
    timeout_seconds: float = 3.0,
) -> GoldenDemoRegressionReport:
    """Exercise UI assets and every command through a real loopback socket."""

    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, Real):
        raise TypeError("timeout_seconds must be a positive number")
    normalized_timeout = float(timeout_seconds)
    if normalized_timeout <= 0.0:
        raise ValueError("timeout_seconds must be greater than zero")

    # 시나리오를 명시한다. 이것은 **골든 데모** 회귀이므로 서버 기본값을 따라가면
    # 기본값이 바뀌는 순간 다른 시나리오를 검사하게 되고, 그 사실이 검사 이름에는
    # 드러나지 않는다.
    server = create_local_golden_demo_server(
        LocalGoldenDemoServerSettings(port=0, scenario="golden")
    )
    server.RequestHandlerClass = _QuietWsgiRequestHandler
    worker = Thread(target=server.serve_forever, name="golden-demo-check", daemon=True)
    worker.start()
    connection = HTTPConnection(
        "127.0.0.1",
        server.server_port,
        timeout=normalized_timeout,
    )
    try:
        checkpoints: list[GoldenDemoRegressionCheckpoint] = []
        _verify_ui_assets(connection)
        playback = _get_json(connection, _PLAYBACK_PATH)
        _require(playback.get("frame_count") == 301, "playback must contain 301 frames")
        _require(playback.get("aircraft_count") == 8, "playback must contain 8 aircraft")
        playback_contract = _mapping(playback, "contract")
        _require(
            playback_contract.get("duration_seconds") == 300.0,
            "playback duration must be 300 seconds",
        )
        playback_frames = playback.get("frames")
        _require(
            isinstance(playback_frames, list) and len(playback_frames) == 301,
            "playback frame payload must be complete",
        )
        _require(
            playback_frames[70].get("cue_ids") == ["CUE-T070-CONFLICT"],
            "playback T+70 conflict cue is required",
        )
        ready = _get_json(connection, _SESSION_PATH)
        _require_session(ready, expected_stage="READY", expected_elapsed=0.0)
        initial_session_id = _text(ready, "session_id")
        checkpoints.append(
            _checkpoint(
                "UI_READY",
                ready,
                "UI shell, assets and 301 playback frames available",
            )
        )

        monitoring = _post_command(connection, "START")
        _require_session(monitoring, expected_stage="MONITORING", expected_elapsed=0.0)
        checkpoints.append(_checkpoint("MONITORING", monitoring, "8 tracks under monitoring"))

        conflict = _post_command(connection, "ADVANCE_TO_CONFLICT")
        _require_session(conflict, expected_stage="CONFLICT_DETECTED", expected_elapsed=70.0)
        conflict_evidence = _mapping(conflict, "primary_conflict")
        _require(
            conflict_evidence.get("aircraft_ids") == ["CIV-A02", "MIL-F01"],
            "primary conflict pair must be CIV-A02 / MIL-F01",
        )
        _require(conflict_evidence.get("status") == "PREDICTED", "conflict must be predicted")
        _require(conflict_evidence.get("risk_level") == "HIGH", "conflict risk must be HIGH")
        deviation = _mapping(conflict, "deviation")
        _require(deviation.get("aircraft_id") == "MIL-F01", "MIL-F01 deviation is required")
        _require(
            deviation.get("vertical_deviation_ft") == -1_600.0,
            "entry vertical deviation must be -1,600 ft",
        )
        _require(
            deviation.get("lateral_deviation_nm") == 2.1,
            "entry lateral deviation must be 2.1 NM",
        )
        checkpoints.append(
            _checkpoint(
                "CONFLICT",
                conflict,
                "CIV-A02 / MIL-F01 | HIGH | predicted loss of separation",
            )
        )

        recommended = _post_command(connection, "GENERATE_RECOMMENDATION")
        _require_session(
            recommended,
            expected_stage="RECOMMENDATION_AVAILABLE",
            expected_elapsed=75.0,
        )
        recommendation = _primary_recommendation(recommended)
        safety = _mapping(recommendation, "safety")
        _require(safety.get("verdict") == "SAFE", "primary candidate must be SAFE")
        comparisons = tuple(
            _mapping_value(item) for item in _list(recommended, "candidate_comparisons")
        )
        _require(
            tuple(item.get("candidate_id") for item in comparisons)
            == ("CAND-A", "CAND-B", "CAND-C", "CAND-D", "CAND-E"),
            "candidate comparison must contain CAND-A through CAND-E",
        )
        verdict_by_id = {item["candidate_id"]: item.get("verdict") for item in comparisons}
        _require(
            verdict_by_id
            == {
                "CAND-A": "SAFE",
                "CAND-B": "UNSAFE",
                "CAND-C": "INEFFECTIVE",
                "CAND-D": "UNSAFE",
                "CAND-E": "UNSAFE",
            },
            "candidate verdict matrix does not match the Golden Demo contract",
        )
        baseline_conflict_id = _text(_mapping(recommended, "primary_conflict"), "conflict_id")
        checkpoints.append(
            _checkpoint("RECOMMENDATION", recommended, "CAND-A | altitude 9,000 ft | SAFE")
        )

        accepted = _post_command(connection, "ACCEPT_RECOMMENDATION")
        _require_session(accepted, expected_stage="DECISION_ACCEPTED", expected_elapsed=90.0)
        decision_log = _mapping(accepted, "controller_decision")
        entries = _list(decision_log, "entries")
        _require(bool(entries), "controller decision audit entry is required")
        _require(
            _mapping_value(entries[-1]).get("decision_type") == "ACCEPT",
            "controller decision must be ACCEPT",
        )
        accepted_altitude_ft = _aircraft_altitude(accepted, "MIL-F01")
        checkpoints.append(
            _checkpoint("DECISION", accepted, "ACCEPT audited | runtime not yet commanded")
        )

        resolved = _post_command(connection, "APPLY_APPROVED_MANEUVER")
        _require_session(resolved, expected_stage="CONFLICT_RESOLVED", expected_elapsed=90.0)
        revalidation = _mapping(resolved, "revalidation")
        _require(revalidation.get("resolved") is True, "post-action conflict must be resolved")
        _require(revalidation.get("conflict_status") == "SAFE", "post-action status must be SAFE")
        _require(revalidation.get("risk_level") == "LOW", "post-action risk must be LOW")
        _require(
            revalidation.get("before_altitude_ft") == accepted_altitude_ft,
            "accepted state must remain unchanged until application",
        )
        _require(
            _aircraft_altitude(resolved, "MIL-F01") == 9_000.0,
            "approved MIL-F01 altitude must be applied",
        )
        _require(
            _text(_mapping(resolved, "primary_conflict"), "conflict_id")
            == baseline_conflict_id,
            "original conflict evidence must remain stable after application",
        )
        checkpoints.append(
            _checkpoint("REVALIDATION", resolved, "applied 9,000 ft | SAFE / LOW / RESOLVED")
        )

        reset = _post_command(connection, "RESET")
        _require_session(reset, expected_stage="READY", expected_elapsed=0.0)
        _require(reset.get("run_number") == 1, "reset must increment the Run number")
        _require(reset.get("primary_conflict") is None, "reset must clear conflict evidence")
        _require(reset.get("revalidation") is None, "reset must clear revalidation evidence")
        reset_session_id = _text(reset, "session_id")
        _require(reset_session_id != initial_session_id, "reset must create a new Session ID")
        checkpoints.append(_checkpoint("RESET", reset, "new clean Run ready"))

        _run_to_recommendation(connection)
        modified = _post_command(
            connection,
            "MODIFY_RECOMMENDATION",
            fields={
                "rationale": "Golden Demo safe modified path",
                "modified_maneuver": _altitude_maneuver_payload(8_800.0),
            },
        )
        _require_session(modified, expected_stage="DECISION_MODIFIED", expected_elapsed=90.0)
        modified_entry = _latest_decision_entry(modified)
        _require(modified_entry.get("decision_type") == "MODIFY", "safe path must audit MODIFY")
        _require(
            modified_entry.get("authorizes_application") is False,
            "MODIFY Audit must not directly authorize application",
        )
        modified_before_altitude = _aircraft_altitude(modified, "MIL-F01")

        modified_safe = _post_command(connection, "REVALIDATE_MODIFIED_MANEUVER")
        _require_session(
            modified_safe,
            expected_stage="MODIFICATION_REVALIDATED",
            expected_elapsed=90.0,
        )
        safe_evidence = _mapping(modified_safe, "modified_revalidation")
        _require(safe_evidence.get("verdict") == "SAFE", "8,800 ft modification must be SAFE")
        _require(
            safe_evidence.get("safe_to_apply") is True,
            "SAFE modification must open the application gate",
        )
        _require(
            _aircraft_altitude(modified_safe, "MIL-F01") == modified_before_altitude,
            "isolated modified validation must not change Aircraft Runtime",
        )

        modified_applied = _post_command(
            connection,
            "APPLY_VALIDATED_MODIFIED_MANEUVER",
        )
        _require_session(
            modified_applied,
            expected_stage="CONFLICT_RESOLVED",
            expected_elapsed=90.0,
        )
        modified_post_action = _mapping(modified_applied, "revalidation")
        _require(
            modified_post_action.get("application_source") == "REVALIDATED_MODIFICATION",
            "post-action evidence must identify the modified application source",
        )
        _require(
            modified_post_action.get("source_modified_revalidation_step_id")
            == safe_evidence.get("revalidation_step_id"),
            "modified application must reference its exact Revalidation",
        )
        _require(
            bool(modified_post_action.get("authorization_id")),
            "modified application must include an Authorization ID",
        )
        _require(
            modified_post_action.get("resolved") is True,
            "safe modified application must resolve the primary conflict",
        )
        _require(
            modified_post_action.get("conflict_status") == "SAFE"
            and modified_post_action.get("risk_level") == "LOW"
            and modified_post_action.get("source_exception_status") == "RESOLVED",
            "safe modified post-action evidence must be SAFE / LOW / RESOLVED",
        )
        _require(
            abs(
                float(_number(modified_post_action, "horizontal_separation_nm"))
                - 2.3
            )
            < 1e-9
            and abs(
                float(_number(modified_post_action, "vertical_separation_ft"))
                - 1_591.6666666667
            )
            < 1e-9,
            "safe modified post-action CPA must match the Golden calibration",
        )
        _require(
            _aircraft_altitude(modified_applied, "MIL-F01") == 8_800.0,
            "authorized modified altitude must be applied",
        )
        _require(
            _latest_decision_entry(modified_applied).get("decision_type") == "MODIFY",
            "modified application must preserve the original Audit decision",
        )
        checkpoints.append(
            _checkpoint(
                "MODIFY_SAFE",
                modified_applied,
                "8,800 ft | isolated SAFE | authorized | SAFE / LOW / RESOLVED",
            )
        )

        reset = _post_command(connection, "RESET")
        _require_clean_reset(reset, expected_run_number=2)
        _run_to_recommendation(connection)
        _post_command(
            connection,
            "MODIFY_RECOMMENDATION",
            fields={
                "rationale": "Golden Demo unsafe modified path",
                "modified_maneuver": _altitude_maneuver_payload(7_200.0),
            },
        )
        modified_unsafe = _post_command(connection, "REVALIDATE_MODIFIED_MANEUVER")
        _require_session(
            modified_unsafe,
            expected_stage="MODIFICATION_REVALIDATED",
            expected_elapsed=90.0,
        )
        unsafe_evidence = _mapping(modified_unsafe, "modified_revalidation")
        _require(
            unsafe_evidence.get("verdict") == "UNSAFE",
            "7,200 ft modification must be UNSAFE",
        )
        _require(
            unsafe_evidence.get("safe_to_apply") is False,
            "UNSAFE modification must keep the application gate closed",
        )
        _require(
            unsafe_evidence.get("rule_violation_ids")
            == ["POC-MINIMUM-CANDIDATE-ALTITUDE-V1"],
            "unsafe modification must preserve minimum-altitude Rule evidence",
        )
        unsafe_before_altitude = _aircraft_altitude(modified_unsafe, "MIL-F01")
        blocked = _post_command(
            connection,
            "APPLY_VALIDATED_MODIFIED_MANEUVER",
            expected_status=409,
        )
        blocked_error = _mapping(blocked, "error")
        _require(
            blocked_error.get("code") == "SESSION_STATE_CONFLICT",
            "unsafe application must return SESSION_STATE_CONFLICT",
        )
        unchanged = _get_json(connection, _SESSION_PATH)
        _require_session(
            unchanged,
            expected_stage="MODIFICATION_REVALIDATED",
            expected_elapsed=90.0,
        )
        _require(unchanged.get("application_step_id") is None, "blocked path must not apply")
        _require(
            _aircraft_altitude(unchanged, "MIL-F01") == unsafe_before_altitude,
            "blocked modified application must not change Aircraft Runtime",
        )
        checkpoints.append(
            _checkpoint(
                "MODIFY_BLOCKED",
                unchanged,
                "7,200 ft | minimum-altitude Rule | HTTP 409 | runtime unchanged",
            )
        )

        reset = _post_command(connection, "RESET")
        _require_clean_reset(reset, expected_run_number=3)
        _run_to_recommendation(connection)
        rejected = _post_command(
            connection,
            "REJECT_RECOMMENDATION",
            fields={"rationale": "Golden Demo explicit rejection path"},
        )
        _require_session(rejected, expected_stage="DECISION_REJECTED", expected_elapsed=90.0)
        rejected_entry = _latest_decision_entry(rejected)
        _require(rejected_entry.get("decision_type") == "REJECT", "path must audit REJECT")
        _require(
            rejected_entry.get("authorizes_application") is False,
            "REJECT must not authorize application",
        )
        _require(rejected.get("application_step_id") is None, "REJECT path must not apply")
        _require(rejected.get("modified_revalidation") is None, "REJECT must not revalidate")
        _require(rejected.get("revalidation") is None, "REJECT must not recalculate traffic")
        checkpoints.append(
            _checkpoint("REJECT", rejected, "REJECT audited | no validation or application")
        )

        final_reset = _post_command(connection, "RESET")
        _require_clean_reset(final_reset, expected_run_number=4)
        reset_session_id = _text(final_reset, "session_id")
        return GoldenDemoRegressionReport(
            initial_session_id=initial_session_id,
            reset_session_id=reset_session_id,
            checkpoints=tuple(checkpoints),
        )
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        worker.join(timeout=normalized_timeout)
        if worker.is_alive():
            raise GoldenDemoRegressionFailure("local check server did not stop cleanly")


def print_golden_demo_regression_report(report: GoldenDemoRegressionReport) -> None:
    """Print a stable, presentation-friendly readiness report."""

    if not isinstance(report, GoldenDemoRegressionReport):
        raise TypeError("report must be a GoldenDemoRegressionReport")
    for item in report.checkpoints:
        print(
            f"[PASS] {item.code:<14} {item.stage:<24} "
            f"T+{item.elapsed_seconds:05.1f}  {item.detail}"
        )
    print(f"SENTRY ATM DEMO CHECK PASSED ({len(report.checkpoints)} checkpoints)")


def _verify_ui_assets(connection: HTTPConnection) -> None:
    html = _get_bytes(connection, "/", expected_content_type="text/html; charset=utf-8")
    css = _get_bytes(
        connection,
        "/assets/app.css",
        expected_content_type="text/css; charset=utf-8",
    )
    script = _get_bytes(
        connection,
        "/assets/app.js",
        expected_content_type="text/javascript; charset=utf-8",
    )
    _require(b"data-conflict-explainability" in html, "explainability UI is missing")
    _require(b"data-decision-actions" in html, "operator decision controls are missing")
    _require(
        b"data-modified-revalidation" in html,
        "modified revalidation evidence panel is missing",
    )
    _require(b".conflict-explainability" in css, "explainability styles are missing")
    _require(b".decision-form" in css, "operator decision styles are missing")
    _require(b"renderConflictExplainability" in script, "explainability renderer is missing")
    _require(b"MODIFY_RECOMMENDATION" in script, "Modify workflow is missing")
    _require(b"REJECT_RECOMMENDATION" in script, "Reject workflow is missing")
    _require(
        b"REVALIDATE_MODIFIED_MANEUVER" in script,
        "modified Maneuver revalidation workflow is missing",
    )
    _require(
        b"APPLY_VALIDATED_MODIFIED_MANEUVER" in script,
        "validated modified Maneuver application workflow is missing",
    )


def _run_to_recommendation(connection: HTTPConnection) -> dict[str, object]:
    monitoring = _post_command(connection, "START")
    _require_session(monitoring, expected_stage="MONITORING", expected_elapsed=0.0)
    conflict = _post_command(connection, "ADVANCE_TO_CONFLICT")
    _require_session(conflict, expected_stage="CONFLICT_DETECTED", expected_elapsed=70.0)
    recommended = _post_command(connection, "GENERATE_RECOMMENDATION")
    _require_session(
        recommended,
        expected_stage="RECOMMENDATION_AVAILABLE",
        expected_elapsed=75.0,
    )
    return recommended


def _altitude_maneuver_payload(target_altitude_ft: float) -> dict[str, object]:
    return {
        "maneuver_type": "ALTITUDE",
        "target_heading_deg": None,
        "target_altitude_ft": target_altitude_ft,
        "target_ground_speed_kt": None,
        "delay_seconds": None,
        "target_sequence_position": None,
    }


def _latest_decision_entry(payload: dict[str, object]) -> dict[str, object]:
    entries = _list(_mapping(payload, "controller_decision"), "entries")
    _require(bool(entries), "controller decision audit entry is required")
    return _mapping_value(entries[-1])


def _require_clean_reset(payload: dict[str, object], *, expected_run_number: int) -> None:
    _require_session(payload, expected_stage="READY", expected_elapsed=0.0)
    _require(
        payload.get("run_number") == expected_run_number,
        f"reset must increment Run number to {expected_run_number}",
    )
    for key in (
        "primary_conflict",
        "controller_decision",
        "modified_revalidation",
        "revalidation",
    ):
        _require(payload.get(key) is None, f"reset must clear {key}")
    _require(payload.get("application_step_id") is None, "reset must clear application")


def _get_bytes(
    connection: HTTPConnection,
    path: str,
    *,
    expected_content_type: str,
) -> bytes:
    connection.request("GET", path, headers={"Accept": "*/*"})
    response = connection.getresponse()
    body = response.read()
    _require(response.status == 200, f"GET {path} returned HTTP {response.status}")
    _require(
        response.getheader("Content-Type") == expected_content_type,
        f"GET {path} returned an unexpected Content-Type",
    )
    return body


def _get_json(connection: HTTPConnection, path: str) -> dict[str, object]:
    connection.request("GET", path, headers={"Accept": "application/json"})
    return _read_json_response(connection, operation=f"GET {path}")


def _post_command(
    connection: HTTPConnection,
    command: str,
    *,
    fields: dict[str, object] | None = None,
    expected_status: int = 200,
) -> dict[str, object]:
    body = json.dumps(
        {"command": command, **(fields or {})},
        separators=(",", ":"),
    ).encode()
    connection.request(
        "POST",
        _COMMAND_PATH,
        body=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        },
    )
    return _read_json_response(
        connection,
        operation=f"command {command}",
        expected_status=expected_status,
    )


def _read_json_response(
    connection: HTTPConnection,
    *,
    operation: str,
    expected_status: int = 200,
) -> dict[str, object]:
    response = connection.getresponse()
    body = response.read()
    _require(
        response.status == expected_status,
        f"{operation} returned HTTP {response.status}; expected {expected_status}",
    )
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GoldenDemoRegressionFailure(f"{operation} returned invalid JSON") from error
    _require(isinstance(payload, dict), f"{operation} must return a JSON object")
    return payload


def _require_session(
    payload: dict[str, object],
    *,
    expected_stage: str,
    expected_elapsed: float,
) -> None:
    _require(payload.get("stage") == expected_stage, f"expected Stage {expected_stage}")
    _require(
        payload.get("elapsed_seconds") == expected_elapsed,
        f"expected elapsed_seconds={expected_elapsed:.1f}",
    )
    _require(payload.get("traffic_count") == 8, "expected exactly 8 Golden Demo aircraft")


def _checkpoint(
    code: str,
    payload: dict[str, object],
    detail: str,
) -> GoldenDemoRegressionCheckpoint:
    return GoldenDemoRegressionCheckpoint(
        code=code,
        stage=_text(payload, "stage"),
        elapsed_seconds=float(_number(payload, "elapsed_seconds")),
        detail=detail,
    )


def _primary_recommendation(payload: dict[str, object]) -> dict[str, object]:
    recommendation_set = _mapping(payload, "recommendation")
    primary_id = _text(recommendation_set, "primary_recommendation_id")
    recommendations = _list(recommendation_set, "recommendations")
    match = next(
        (
            _mapping_value(item)
            for item in recommendations
            if _mapping_value(item).get("recommendation_id") == primary_id
        ),
        None,
    )
    if match is None:
        raise GoldenDemoRegressionFailure("primary recommendation is missing")
    return match


def _aircraft_altitude(payload: dict[str, object], aircraft_id: str) -> float:
    traffic = _list(payload, "traffic")
    match = next(
        (
            _mapping_value(item)
            for item in traffic
            if _mapping_value(item).get("aircraft_id") == aircraft_id
        ),
        None,
    )
    if match is None:
        raise GoldenDemoRegressionFailure(f"aircraft {aircraft_id} is missing")
    return float(_number(match, "altitude_ft"))


def _mapping(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise GoldenDemoRegressionFailure(f"{key} must be an object")
    return value


def _mapping_value(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise GoldenDemoRegressionFailure("list entry must be an object")
    return value


def _list(payload: dict[str, object], key: str) -> list[object]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise GoldenDemoRegressionFailure(f"{key} must be a list")
    return value


def _text(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise GoldenDemoRegressionFailure(f"{key} must be non-empty text")
    return value


def _number(payload: dict[str, object], key: str) -> Real:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, Real):
        raise GoldenDemoRegressionFailure(f"{key} must be numeric")
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GoldenDemoRegressionFailure(message)
