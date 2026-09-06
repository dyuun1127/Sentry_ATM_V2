"""외부에 열었을 때 누가 조작할 수 있는가.

이 서버는 루프백 전용으로 설계됐다. 인증이 없고, 무엇보다 **세션이 하나**다 —
관제 콘솔과 시연 화면이 같은 세션을 본다. 두 화면을 붙여 놓기 위한 구조인데,
밖에 열면 뜻이 달라진다. 주소를 아는 사람이면 누구나 승인·수정·거부를 누를 수
있고, 발표 중에 모르는 사람이 회피안을 거부하면 그대로 반영된다.

그래서 여는 것과 **관람 전용**을 함께 둔다. 규칙 하나다.

    조작할 수 있는 요청 = 루프백에서 왔고, 중계된 흔적이 없는 것

발표자는 자기 노트북에서 `127.0.0.1` 로 직접 열므로 조작할 수 있다. 밖에서 온
사람은 읽기만 된다. 화면도 그에 맞춰 단추를 감춘다 — 눌렀는데 403 이 나는 것은
누르지 못하는 것보다 나쁘다.

**중계 흔적을 함께 보는 이유.** 터널(Cloudflare Tunnel, ngrok 등)을 쓰면 중계
프로세스가 이 서버에 붙으므로 원격 요청도 루프백에서 온 것처럼 보인다. 주소만
보면 전원이 발표자가 된다. 터널은 원 요청자를 헤더에 남기므로 그것이 있으면
중계된 것으로 본다.

이것은 **인증이 아니다.** 같은 기계에 접근할 수 있는 사람은 조작할 수 있고,
헤더를 지울 수 있는 중계자도 마찬가지다. 발표 중 우연한 조작을 막는 울타리이며,
공개 인터넷에 두어도 되는 근거가 아니다.
"""

from __future__ import annotations

from collections.abc import Iterable
from http import HTTPStatus

# 이 주소에서 온 요청만 발표자로 본다.
LOOPBACK_ADDRESSES = frozenset({"127.0.0.1", "::1", "localhost", ""})

# 중계를 거쳤다는 흔적. 하나라도 있으면 원 요청자가 따로 있다는 뜻이다.
FORWARDING_HEADERS = (
    "HTTP_X_FORWARDED_FOR",
    "HTTP_X_REAL_IP",
    "HTTP_FORWARDED",
    "HTTP_CF_CONNECTING_IP",
    "HTTP_X_FORWARDED_HOST",
)

# 읽기만 하는 메서드. 나머지는 전부 상태를 바꾼다.
READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

CONTROL_MODES = ("local", "any")
"""local — 루프백 직접 요청만 조작. any — 누구나 조작 (명시적으로 골라야 한다)."""


def is_operator(environ: dict[str, object], *, control: str = "local") -> bool:
    """이 요청이 발표자의 것인가."""
    if control == "any":
        return True
    address = environ.get("REMOTE_ADDR", "")
    if not isinstance(address, str) or address not in LOOPBACK_ADDRESSES:
        return False
    return not any(environ.get(header) for header in FORWARDING_HEADERS)


def _refusal_body() -> bytes:
    return (
        b'{"error":{"code":"VIEWER_ONLY","message":'
        b'"this session is open for viewing; only the local operator can command it"}}'
    )


class ViewerGuard:
    """읽기만 통과시키는 겉옷.

    막는 것은 메서드로 가른다. 명령 경로만 이름으로 골라 막으면 경로가 하나
    늘 때마다 함께 늘려야 하고, 늘리는 것을 잊으면 조용히 뚫린다.
    """

    __slots__ = ("_app", "_control")

    def __init__(self, app, *, control: str = "local") -> None:
        if control not in CONTROL_MODES:
            raise ValueError(f"control must be one of {list(CONTROL_MODES)}")
        self._app = app
        self._control = control

    @property
    def control(self) -> str:
        return self._control

    def __call__(self, environ: dict[str, object], start_response) -> Iterable[bytes]:
        method = environ.get("REQUEST_METHOD", "GET")
        method = method.upper() if isinstance(method, str) else ""
        if method in READ_METHODS or is_operator(environ, control=self._control):
            return self._app(environ, start_response)
        body = _refusal_body()
        start_response(
            f"{HTTPStatus.FORBIDDEN.value} {HTTPStatus.FORBIDDEN.phrase}",
            [
                ("Content-Type", "application/json; charset=utf-8"),
                ("Content-Length", str(len(body))),
                ("Cache-Control", "no-store"),
            ],
        )
        return [body]
