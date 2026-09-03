from io import BytesIO

import pytest

from sentry_atm.infrastructure.http import GoldenDemoWebWsgiApp
from sentry_atm.runtime import build_golden_demo_session_runtime


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
    assert b'<html lang="ko">' in body
    assert b"SENTRY ATM" in body
    assert b"data-aircraft-layer" in body
    assert b"data-primary-command" in body
    assert b"data-reset-command" in body
    assert b"data-decision-card" in body
    assert b"data-conflict-explainability" in body
    assert b"data-conflict-overlay" in body
    assert b"/assets/app.css" in body
    assert app.api_app is runtime.http_app


@pytest.mark.parametrize(
    ("path", "content_type", "content"),
    [
        ("/index.html", "text/html; charset=utf-8", b"SENTRY ATM"),
        ("/assets/app.css", "text/css; charset=utf-8", b".aircraft-track"),
        (
            "/assets/app.js",
            "text/javascript; charset=utf-8",
            b"/api/v1/golden-demo/session/commands",
        ),
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


def test_ui_assets_include_every_fixed_session_command_and_busy_boundary() -> None:
    app = GoldenDemoWebWsgiApp(build_golden_demo_session_runtime().http_app)

    _, _, script = _request(app, path="/assets/app.js")

    for command in (
        b'command: "START"',
        b'command: "ADVANCE_TO_CONFLICT"',
        b'command: "GENERATE_RECOMMENDATION"',
        b'command: "ACCEPT_RECOMMENDATION"',
        b'command: "APPLY_APPROVED_MANEUVER"',
        b'command: "RESET"',
    ):
        assert command in script
    assert b"if (requestBusy || !command)" in script
    assert b"error.status === 409" in script
    assert b"function renderConflictExplainability(session)" in script
    assert b"session.primary_conflict" in script


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
