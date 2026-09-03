# Golden Demo Release Readiness

## 1. 목적

Phase 16-A는 발표 서버를 시작하기 전에 실행 환경과 전체 Golden Demo 계약을 한 명령으로 확인하는
Go/No-Go 경계다. 실제 운영 인증이나 항공 안전 인증을 의미하지 않으며 로컬 PoC 발표 준비 상태만
판정한다.

```powershell
.\.venv\Scripts\python.exe -m sentry_atm.infrastructure.http --check
```

## 2. Release Preflight

다중 경로 시나리오를 실행하기 전에 다음 5개 항목을 빠르게 확인한다.

| Check | 완료 조건 |
|---|---|
| `PYTHON` | 실행 중인 Python이 3.12 이상 |
| `PACKAGE` | SENTRY ATM 패키지와 버전을 읽을 수 있음 |
| `ASSETS` | `index.html`, `app.css`, `app.js`가 패키지에 포함되고 비어 있지 않음 |
| `OFFLINE` | 패키지 UI 자산에 외부 HTTP/CDN URL이 없음 |
| `LOOPBACK` | 서버 Host가 `127.0.0.1`로 고정됨 |

Preflight가 실패하면 `[FAIL]` 한 줄과 종료 코드 `1`을 반환하고 HTTP 시나리오 회귀는 실행하지 않는다.

## 3. Multi-Path Regression

Preflight 이후 실제 임시 Loopback Socket에서 10개 Checkpoint를 검증한다. 기본 ACCEPT 흐름과 Reset,
SAFE MODIFY 재승인·적용, UNSAFE MODIFY HTTP 409 차단, REJECT 무적용을 서로 다른 Run으로 실행하고
마지막에 Run 4의 깨끗한 READY 상태를 확인한다.

## 4. Go/No-Go 기준

다음 두 줄이 모두 출력되고 프로세스 종료 코드가 `0`일 때만 발표 서버를 시작한다.

```text
SENTRY ATM RELEASE PREFLIGHT PASSED (5 checks)
SENTRY ATM DEMO CHECK PASSED (10 checkpoints)
```

하나라도 실패하면 발표를 진행하지 않고 첫 `[FAIL]` 메시지를 해결한 뒤 전체 명령을 처음부터 다시
실행한다. 소스 수정 뒤에는 별도로 `ruff`와 전체 `pytest`도 통과해야 한다.

## 5. 현재 경계

- 네트워크 단절 상태의 로컬 단일 프로세스 발표 환경을 대상으로 한다.
- OS 전체 상태, 브라우저 배율, 화면 해상도와 포트 충돌은 Runbook의 육안 점검이 필요하다.
- SQLite 데이터는 Golden Demo 실행의 필수 조건이 아니다.
- Preflight 통과는 실제 관제 운용 적합성이나 보안 인증을 의미하지 않는다.
