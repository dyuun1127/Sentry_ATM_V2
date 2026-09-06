"""밖으로 열었을 때 누가 조작할 수 있는가 (`ASM-045`).

이 서버는 인증이 없고 **세션이 하나**다. 밖에 열면 주소를 아는 사람이 승인·수정·
거부를 누를 수 있고, 발표 중에 그것이 그대로 반영된다. 그래서 여는 것과 관람
전용을 함께 둔다.
"""

from __future__ import annotations

import json
from io import BytesIO

import pytest

from sentry_atm.infrastructure.http.access import ViewerGuard, is_operator
from sentry_atm.infrastructure.http.server import LocalGoldenDemoServerSettings
from sentry_atm.infrastructure.http.web import GoldenDemoWebWsgiApp
from sentry_atm.runtime import build_golden_demo_session_runtime

COMMANDS = "/api/v1/golden-demo/session/commands"
ACCESS = "/api/v1/reference/access"


def _guarded(host: str = "0.0.0.0", control: str = "local"):
    settings = LocalGoldenDemoServerSettings(port=0, host=host, control=control)
    runtime = build_golden_demo_session_runtime()
    app = GoldenDemoWebWsgiApp(runtime.http_app, runtime, settings=settings)
    return ViewerGuard(app, control=control), app


def _call(app, method: str, path: str, address: str, **headers):
    body = json.dumps({"command": "START"}).encode() if method == "POST" else b""
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "REMOTE_ADDR": address,
        "CONTENT_TYPE": "application/json",
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": BytesIO(body),
        **headers,
    }
    captured: dict[str, str] = {}
    chunks = b"".join(app(environ, lambda status, _: captured.__setitem__("s", status)))
    return captured["s"], chunks


def test_default_bind_stays_on_loopback() -> None:
    """아무것도 주지 않고 띄우면 밖으로 새지 않는가.

    `--host` 는 명시적인 선택이어야 한다. 기본값이 조용히 넓어지면 발표 준비 중에
    열려 있는 줄 모르고 띄우게 된다.
    """
    settings = LocalGoldenDemoServerSettings(port=0)

    assert settings.host == "127.0.0.1"
    assert settings.external is False
    assert settings.control == "local"
    assert LocalGoldenDemoServerSettings(port=0, host="0.0.0.0").external is True


def test_settings_reject_a_control_mode_nobody_wrote() -> None:
    with pytest.raises(ValueError, match="control must be one of"):
        LocalGoldenDemoServerSettings(port=0, control="everyone")
    with pytest.raises(ValueError, match="host must be"):
        LocalGoldenDemoServerSettings(port=0, host="")


def test_only_the_local_operator_may_command() -> None:
    """밖에서 온 요청은 읽기만 된다."""
    guarded, _ = _guarded()

    operator, _ = _call(guarded, "POST", COMMANDS, "127.0.0.1")
    outsider, refusal = _call(guarded, "POST", COMMANDS, "203.0.113.9")

    assert operator.startswith("200")
    assert outsider.startswith("403")
    assert b"VIEWER_ONLY" in refusal

    # 읽기는 누구나 된다 — 그러라고 여는 것이다.
    for path in ("/", "/scenario", "/api/v1/golden-demo/session"):
        status, _ = _call(guarded, "GET", path, "203.0.113.9")
        assert status.startswith("200"), path


@pytest.mark.parametrize(
    "header",
    [
        "HTTP_X_FORWARDED_FOR",
        "HTTP_X_REAL_IP",
        "HTTP_FORWARDED",
        "HTTP_CF_CONNECTING_IP",
        "HTTP_X_FORWARDED_HOST",
    ],
)
def test_a_tunnelled_request_is_not_the_operator(header: str) -> None:
    """터널을 거친 요청은 루프백에서 온 것처럼 보인다.

    Cloudflare Tunnel 이나 ngrok 을 쓰면 중계 프로세스가 이 서버에 붙으므로
    원격 요청의 `REMOTE_ADDR` 이 `127.0.0.1` 이 된다. 주소만 보면 전원이
    발표자가 되고, 관람 전용이 통째로 무너진다.
    """
    guarded, _ = _guarded()

    status, refusal = _call(
        guarded, "POST", COMMANDS, "127.0.0.1", **{header: "203.0.113.9"}
    )

    assert status.startswith("403")
    assert b"VIEWER_ONLY" in refusal
    assert is_operator({"REMOTE_ADDR": "127.0.0.1", header: "203.0.113.9"}) is False


def test_control_any_is_an_explicit_way_to_hand_over_the_session() -> None:
    """누구나 조작하게 하려면 그렇게 말해야 한다.

    팀원이 원격에서 직접 몰아야 하는 경우가 있다. 그것을 막지는 않되, 기본으로
    두지 않는다 — 주소가 새면 시연을 남이 바꾼다.
    """
    guarded, _ = _guarded(control="any")

    status, _ = _call(guarded, "POST", COMMANDS, "203.0.113.9")

    assert status.startswith("200")


def test_screens_are_told_whether_they_may_command() -> None:
    """화면이 단추를 감출 수 있어야 한다.

    눌렀는데 403 이 나는 것은 누르지 못하는 것보다 나쁘다. 서버가 요청마다
    답하므로, 같은 화면이라도 어디서 열었느냐에 따라 답이 다르다.
    """
    guarded, _ = _guarded()

    _, local = _call(guarded, "GET", ACCESS, "127.0.0.1")
    _, remote = _call(guarded, "GET", ACCESS, "127.0.0.1", HTTP_X_FORWARDED_FOR="203.0.113.9")

    assert json.loads(local) == {"external": True, "control": "local", "operator": True}
    assert json.loads(remote) == {"external": True, "control": "local", "operator": False}


def test_a_loopback_only_server_treats_everyone_as_the_operator() -> None:
    """열지 않았으면 붙은 사람이 곧 발표자다. 관람 배지가 뜨면 안 된다."""
    _, app = _guarded(host="127.0.0.1")

    _, payload = _call(app, "GET", ACCESS, "127.0.0.1")

    assert json.loads(payload) == {
        "external": False,
        "control": "local",
        "operator": True,
    }
