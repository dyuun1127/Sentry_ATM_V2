import json
import runpy
from http.client import HTTPConnection
from threading import Thread

import pytest

from sentry_atm.infrastructure.http import demo_check as demo_check_module
from sentry_atm.infrastructure.http import server as server_module
from sentry_atm.infrastructure.http.demo_check import (
    GoldenDemoRegressionFailure,
    GoldenDemoRegressionReport,
)
from sentry_atm.infrastructure.http.server import (
    LocalGoldenDemoServerSettings,
    create_local_golden_demo_server,
    main,
    run_local_golden_demo_check,
    run_local_golden_demo_server,
)


def test_settings_fix_host_to_loopback_and_validate_port() -> None:
    settings = LocalGoldenDemoServerSettings(port=0)

    assert settings.host == "127.0.0.1"
    assert settings.port == 0

    for invalid in (-1, 65_536, True, 8000.0, "8000"):
        with pytest.raises(ValueError, match="port must be an integer"):
            LocalGoldenDemoServerSettings(port=invalid)  # type: ignore[arg-type]


def test_server_handles_real_loopback_get_and_command_requests() -> None:
    server = create_local_golden_demo_server(LocalGoldenDemoServerSettings(port=0))
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
    try:
        assert server.server_address[0] == "127.0.0.1"

        connection.request("GET", "/")
        response = connection.getresponse()
        ui = response.read()
        assert response.status == 200
        assert response.getheader("Content-Type") == "text/html; charset=utf-8"
        assert b"SENTRY ATM" in ui

        connection.request("GET", "/api/v1/golden-demo/session")
        response = connection.getresponse()
        ready = json.loads(response.read())
        assert response.status == 200
        assert response.getheader("Cache-Control") == "no-store"
        assert ready["stage"] == "READY"

        body = json.dumps({"command": "START"})
        connection.request(
            "POST",
            "/api/v1/golden-demo/session/commands",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        started = json.loads(response.read())
        assert response.status == 200
        assert started["stage"] == "MONITORING"
        assert started["elapsed_seconds"] == 0.0
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)

    assert not worker.is_alive()


class _InterruptingServer:
    server_address = ("127.0.0.1", 8123)
    server_port = 8123

    def __init__(self) -> None:
        self.entered = False
        self.exited = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *args):
        self.exited = True

    def serve_forever(self) -> None:
        raise KeyboardInterrupt


def test_run_reports_bound_url_and_closes_after_interrupt(monkeypatch, capsys) -> None:
    fake_server = _InterruptingServer()
    captured_settings = None

    def create(settings):
        nonlocal captured_settings
        captured_settings = settings
        return fake_server

    monkeypatch.setattr(server_module, "create_local_golden_demo_server", create)

    result = run_local_golden_demo_server(LocalGoldenDemoServerSettings(port=8123))

    assert result == 0
    assert captured_settings == LocalGoldenDemoServerSettings(port=8123)
    assert fake_server.entered is True
    assert fake_server.exited is True
    output = capsys.readouterr().out
    assert "http://127.0.0.1:8123" in output
    assert "stopped" in output


def test_cli_accepts_only_valid_tcp_port(monkeypatch) -> None:
    captured_settings = None

    def run(settings):
        nonlocal captured_settings
        captured_settings = settings
        return 0

    monkeypatch.setattr(server_module, "run_local_golden_demo_server", run)

    assert main(["--port", "8124"]) == 0
    assert captured_settings == LocalGoldenDemoServerSettings(port=8124)

    with pytest.raises(SystemExit) as non_integer:
        main(["--port", "invalid"])
    assert non_integer.value.code == 2

    with pytest.raises(SystemExit) as out_of_range:
        main(["--port", "0"])
    assert out_of_range.value.code == 2


def test_cli_check_mode_runs_readiness_check_instead_of_server(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(server_module, "run_local_golden_demo_check", lambda: calls.append(1) or 0)
    monkeypatch.setattr(
        server_module,
        "run_local_golden_demo_server",
        lambda settings: pytest.fail(f"unexpected server run: {settings}"),
    )

    assert main(["--check"]) == 0
    assert calls == [1]


def test_readiness_check_cli_reports_success_and_failure(monkeypatch, capsys) -> None:
    report = GoldenDemoRegressionReport("RUN-0", "RUN-1", ())
    printed = []
    monkeypatch.setattr(demo_check_module, "run_golden_demo_regression", lambda: report)
    monkeypatch.setattr(
        demo_check_module,
        "print_golden_demo_regression_report",
        printed.append,
    )

    assert run_local_golden_demo_check() == 0
    assert printed == [report]

    def fail():
        raise GoldenDemoRegressionFailure("broken checkpoint")

    monkeypatch.setattr(demo_check_module, "run_golden_demo_regression", fail)

    assert run_local_golden_demo_check() == 1
    assert "[FAIL] broken checkpoint" in capsys.readouterr().out


def test_module_entrypoint_exits_with_main_result(monkeypatch) -> None:
    monkeypatch.setattr(server_module, "main", lambda: 7)

    imported = runpy.run_module(
        "sentry_atm.infrastructure.http.__main__",
        run_name="sentry_atm.infrastructure.http._entrypoint_test",
    )
    with pytest.raises(SystemExit) as exit_result:
        runpy.run_module("sentry_atm.infrastructure.http.__main__", run_name="__main__")

    assert imported["main"] is server_module.main
    assert exit_result.value.code == 7
