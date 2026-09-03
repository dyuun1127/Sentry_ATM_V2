# Golden Demo 실행 Runbook

## 1. 목적과 범위

이 문서는 발표용 노트북에서 SENTRY ATM Golden Demo를 사전 검증하고 실행하는 고정 절차다. 대상은
process-local 단일 Session이며 외부 네트워크, Docker, PostgreSQL/PostGIS 또는 Node.js가 필요하지 않다.
이 데모는 실제 관제 시스템이 아닌 RKTU Terminal Simulation Area PoC다.

## 2. 발표 전 자동 점검

저장소 루트의 VS Code PowerShell Terminal에서 다음 명령을 실행한다.

```powershell
.\.venv\Scripts\python.exe -m sentry_atm.infrastructure.http --check
```

이 명령은 운영 서버와 별도의 임시 loopback Port를 사용하고 자동으로 종료한다. 실제 HTTP를 통해 다음
계약을 순서대로 검증한다.

1. UI HTML/CSS/JavaScript와 Explainability 자산 응답
2. `READY`에서 8대 초기 Traffic
3. `MONITORING` 시작
4. T+70 `CIV-A02 / MIL-F01` HIGH 충돌 탐지
5. T+75 `CAND-A`, 9,000 ft, SAFE 후보 생성
6. T+90 관제사 `ACCEPT` Audit 기록과 적용 전 Runtime 불변
7. 승인 기동 적용 후 SAFE/LOW/RESOLVED 및 원 충돌 증거 보존
8. Reset 후 새 Run ID와 빈 증거 상태

T+70 Checkpoint에서는 `MIL-F01`의 진입 고도·침로·수평·시간 편차도 확인하고, T+75 Checkpoint에서는
CAND-A~E 전체 판정 행렬이 Golden Scenario Contract와 일치하는지 검증한다.

정상 종료 기준은 마지막 줄이다.

```text
SENTRY ATM DEMO CHECK PASSED (7 checkpoints)
```

`[FAIL]`이 한 줄이라도 있으면 발표 서버를 시작하지 말고 5절의 복구 절차를 따른다.

## 3. 발표 서버 실행

자동 점검이 통과한 같은 Terminal에서 실행한다.

```powershell
.\.venv\Scripts\python.exe -m sentry_atm.infrastructure.http --port 8000
```

다음 문구가 출력되면 브라우저에서 `http://127.0.0.1:8000/`을 연다.

```text
SENTRY ATM Golden Demo API: http://127.0.0.1:8000
Press Ctrl+C to stop.
```

발표가 끝나면 해당 Terminal에서 `Ctrl+C`를 눌러 서버를 종료한다. 외부 장치에서 접속할 수 있도록
Host를 변경하는 기능은 제공하지 않는다.

## 4. 발표 시연 순서와 설명 포인트

| 순서 | 화면 동작 | 확인할 화면 증거 | 발표 핵심 문장 |
|---:|---|---|---|
| 1 | `감시 시작` | 8대 Traffic, `MONITORING` | 같은 입력은 같은 시각과 상태로 재현된다. |
| 2 | `충돌 시점으로 진행` | T+70, 붉은 충돌쌍과 연결선, HIGH 75 | 현재 거리가 아니라 미래 CPA/TCPA를 계산한다. |
| 3 | `대응 후보 생성` | 2.30 NM / 500 ft 기준선, SAFE 후보 | 후보 생성과 안전성 검증은 분리돼 있다. |
| 4 | `추천안 승인 기록` | Decision `ACCEPT`, 적용 전 상태 | 사람의 승인 기록만으로 Aircraft Runtime은 바뀌지 않는다. |
| 5 | `승인 기동 적용` | 9,000 ft 적용, 1,792 ft, LOW/RESOLVED | 승인된 기동만 적용하고 같은 계산기로 다시 검증한다. |
| 6 | `새 Run 시작` | `READY`, Run 번호 증가 | 모든 파생 결과를 지우고 동일 시나리오를 다시 시작한다. |

브라우저 육안 회귀 확인 항목:

- 설명 가능성 Panel은 충돌 전에는 보이지 않고 충돌 탐지 후 나타난다.
- 원 충돌은 `BEFORE · PREDICTED CPA`로 유지된다.
- 추천 단계는 `AFTER · VALIDATED CANDIDATE`이며 실제 적용 결과로 표현되지 않는다.
- 최종 단계는 `AFTER · POST-ACTION REVALIDATION`과 `SEPARATION RESTORED`를 표시한다.
- Radar의 `CIV-A02`, `MIL-F01` Marker와 연결선이 붉게 강조된다.
- 새로고침 후에도 backend의 현재 Stage와 동일한 화면이 복원된다.
- 별도 Reset Run에서 `기동 수정` 후 `수정 기동 격리 검증`을 누르면 기본 8,800 ft 수정안은
  `SAFE · NOT YET APPLIED`와 계산된 CPA 증거를 표시하고 실제 Aircraft 고도는 바뀌지 않는다. 이어서
  `SAFE 수정 기동 재승인·적용`을 누른 뒤에만 고도가 8,800 ft로 바뀌고 `AUTHORIZED · APPLIED`와
  SAFE/LOW/RESOLVED가 표시된다.
- 별도 Reset Run에서 `추천안 거절`은 근거를 Audit에 표시하고 기동 적용 버튼을 노출하지 않는다.

## 5. 실패 복구 절차

| 증상 | 확인 | 조치 |
|---|---|---|
| Python 경로 오류 | 현재 위치가 저장소 루트인지 확인 | `cd`로 프로젝트 루트 이동 후 다시 실행 |
| `.venv` 없음 | `.venv\Scripts\python.exe` 존재 여부 확인 | Python 3.12+로 가상환경을 만들고 개발 의존성 설치 |
| `--check` 실패 | 첫 `[FAIL]` 메시지 확인 | `pytest`, `ruff` 실행 후 실패 원인 수정; 통과 전 발표 금지 |
| Port 8000 사용 중 | PowerShell에서 `netstat -ano \| Select-String ':8000'` | 서버를 종료하거나 `--port 8001`처럼 다른 loopback Port 사용 |
| `API OFFLINE` | 서버 Terminal이 실행 중인지 확인 | 페이지를 닫지 말고 서버 재실행 후 새로고침 |
| 잘못된 Stage | 우측 상단 `RESET RUN` 확인 | Reset 후 `감시 시작`부터 고정 순서 재실행 |
| 화면 배율 문제 | 브라우저 Zoom과 창 크기 확인 | Zoom 100%, 가로 1280px 이상 권장 |

자동 점검 외 전체 개발 회귀 검사는 다음과 같다.

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest
```

## 6. 발표 직전 체크리스트

- 최신 발표 대상 Commit인지 `git status --short --branch`로 확인했다.
- 자동 점검 7개 Checkpoint가 모두 통과했다.
- Wi-Fi를 끈 상태에서도 화면이 정상적으로 열린다.
- 브라우저 Zoom 100%와 발표 해상도에서 핵심 Panel이 읽힌다.
- Golden Demo를 Reset부터 최종 Revalidation까지 한 번 실행했다.
- Backup Port와 서버 재실행 명령을 발표자 메모에 기록했다.
- 화면의 `POC · NOT FOR OPERATIONAL USE` 고지가 보인다.
