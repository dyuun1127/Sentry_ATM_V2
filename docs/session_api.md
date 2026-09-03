# Golden Demo Session Read API

## 1. 범위

Phase 13-A는 T+0부터 승인 적용 후 T+90까지의 분리된 backend 결과를 프론트엔드가 한 번에 읽을 수
있는 JSON 호환 Session View로 조합한다. 이 API는 Clock을 진행하거나 Resolution, Decision 또는
Application을 실행하지 않는다.

## 2. 단계

`GoldenDemoSessionStage`는 완료된 증거를 다음 우선순위로 평가한다.

1. Application Result 존재 → `CONFLICT_RESOLVED`
2. Controller Decision Result 존재 → `DECISION_ACCEPTED`
3. Resolution Result 존재 → `RECOMMENDATION_AVAILABLE`
4. 최신 Step에 HIGH/CRITICAL Risk 존재 → `CONFLICT_DETECTED`
5. 최신 Step에 ROUTINE이 아닌 Priority 존재 → `DEVIATION_DETECTED`
6. Step 존재 → `MONITORING`
7. Step 없음 → `READY`

단계는 별도로 수정하거나 저장하지 않으므로 실제 backend evidence보다 앞선 화면 상태를 만들 수 없다.

## 3. Session 응답

`GoldenDemoSessionReadModel`은 다음 정보를 제공한다.

- Scenario ID, process-local Run 번호와 Session ID
- Clock 상태, Simulation UTC와 경과 초
- 현재 Stage와 Step/Resolution/Decision/Application ID
- 8대 Traffic의 Metadata, 위치 NM, 고도 ft, 속도 kt, Heading, 수직속도와 운항 상태
- 해결 항목을 포함한 현재 Exception Queue와 활성 개수
- 현재 Recommendation Set과 Controller Decision Audit Log
- HIGH/CRITICAL 원 충돌의 항공기쌍, CPA/TCPA, 분리기준 대비 비율, Risk Score/Reason/Profile 증거
- 적용 전후 고도, Post-apply Prediction/Conflict Run과 원 Conflict의 SAFE/LOW/RESOLVED 요약

모든 중첩 객체는 기존 Queue, Recommendation 및 Decision Read Model을 재사용한다. `to_dict()`는 tuple,
Enum과 중첩 DTO를 list/string/dict 등 JSON Primitive로 변환한다.

## 4. Reset

Clock Reset 후 Orchestrator Chain의 파생 결과와 승인 Anchor가 제거되면 API는 새 Run 번호의 `READY`
Session을 반환한다. Traffic은 Golden Scenario 초기 8대 상태이고 Queue, Recommendation, Decision과
Revalidation은 비어 있다.

## 5. Phase 13-B Session Command Service

`GoldenDemoSessionCommandService.execute()`는 다음 Command만 제공한다.

| Command | 요구 Stage/시각 | 완료 Stage/시각 |
|---|---|---|
| `START` | `READY`, T+0 | `MONITORING`, T+0 |
| `ADVANCE_TO_CONFLICT` | `MONITORING`, T+0 | `CONFLICT_DETECTED`, T+70 |
| `GENERATE_RECOMMENDATION` | `CONFLICT_DETECTED`, T+70 | `RECOMMENDATION_AVAILABLE`, T+75 |
| `ACCEPT_RECOMMENDATION` | `RECOMMENDATION_AVAILABLE`, T+75 | `DECISION_ACCEPTED`, T+90 |
| `APPLY_APPROVED_MANEUVER` | `DECISION_ACCEPTED`, T+90 | `CONFLICT_RESOLVED`, T+90 |
| `RESET` | 모든 Stage | 새 `READY`, T+0 Run |

서비스는 caller가 임의 `advance_steps`나 Decision 내용을 전달하게 하지 않는다. 현재 Stage 또는 경과시각이
다르면 Orchestrator 호출 전에 거부하며, 성공하면 즉시 새 Session Read Model을 반환한다.

`build_golden_demo_session_runtime()`은 Core Runtime, Step/Resolution/Decision/Application Orchestrator,
Read API와 Command Service를 하나의 독립된 process-local Container로 조립하지만 Command를 자동으로
실행하지 않는다.

## 6. Phase 13-C Minimal WSGI HTTP Adapter

`GoldenDemoSessionWsgiApp`은 다음 Endpoint만 제공한다.

- `GET /api/v1/golden-demo/session`: 현재 Session JSON, 항상 `200 OK`
- `POST /api/v1/golden-demo/session/commands`: `{"command":"START"}` 형태의 고정 Command 실행 후
  새 Session JSON, 성공 시 `200 OK`

두 Endpoint는 Query를 거부한다. POST는 `application/json`, 정확한 Content-Length, UTF-8 JSON Object,
정확히 하나의 `command` 필드와 16 KiB Body 제한을 검증한다. 응답 JSON은 Key를 정렬하고 공백을
제거해 동일 상태에서 같은 bytes를 만들며 `Cache-Control: no-store`를 사용한다.

오류 응답은 `{"error":{"code":"...","message":"..."}}` 구조다.

- `400`: 잘못된 WSGI 환경, Query, Content-Length, Body 길이 또는 JSON
- `404`: 없는 Route
- `405`: 허용되지 않은 Method와 `Allow` Header
- `409 SESSION_STATE_CONFLICT`: 순서·Stage·Checkpoint 시각 위반
- `413`: 16 KiB Body 초과
- `415`: JSON이 아닌 Media Type
- `422`: Body Schema 또는 Command 값 오류

Read API와 Command API는 반드시 같은 Application Orchestrator를 사용해야 하며 Session Runtime Factory가
WSGI App까지 함께 조립한다.

## 7. Phase 13-D Local Golden Demo HTTP Server

다음 명령은 새로운 process-local Session Runtime 하나를 만들고 WSGI App을 실행한다. Phase 14-A부터
Root Route는 Golden Demo Web UI Shell을 제공한다.

```powershell
.\.venv\Scripts\python.exe -m sentry_atm.infrastructure.http
```

기본 Bind는 `127.0.0.1:8000`이며 CLI는 `--port`만 허용한다. `--port`는 `1..65535` 범위이고 Host는
외부 Interface로 변경할 수 없다. Python 표준 라이브러리 `wsgiref.simple_server`를 사용하므로 별도
Runtime Dependency가 없다. `Ctrl+C`로 종료하면 Listening Socket을 닫는다.

테스트용 Factory 호출에서는 운영체제가 빈 Port를 선택하도록 Port `0`을 허용하지만 CLI에서는
허용하지 않는다. 실제 Loopback Socket을 통한 GET/POST 테스트로 WSGI Adapter와 동일 Session State가
연결되는지 확인한다.

## 8. 현재 제한사항

- 개발·Golden Demo용 단일 프로세스 Server이며 Production 배포 구성이 아니다.
- TLS, 외부 Interface Bind와 다중 Worker를 제공하지 않는다.
- Session ID와 결과는 프로세스 재시작 후 복구되지 않는다.
- Authentication, authorization, streaming과 다중 동시 Session을 제공하지 않는다.
- Trajectory Point 전체와 Candidate A~E 전체 검증표는 아직 Session 요약에 포함하지 않는다.

## 9. Phase 14-C Explainability Projection

`primary_conflict`는 최신 Step의 HIGH/CRITICAL Risk 중 Risk Score 내림차순, TCPA 오름차순,
Conflict ID 오름차순으로 기준 충돌을 선택한다. Resolution이 생성된 뒤에는 Source Exception의 평가를
사용하므로 이후 T+90 Step이나 승인 기동으로 화면의 원 충돌 근거가 바뀌지 않는다. READY·MONITORING과
같이 조치 가능한 Risk가 없는 Stage에서는 `null`이다.

이 필드는 원 충돌 증거이며 `revalidation`과 의미가 다르다. `primary_conflict`는 승인 전 기준선을,
`revalidation`은 승인 기동을 실제 Runtime에 적용한 후의 결과를 나타낸다. UI는 둘을 BEFORE/AFTER로
비교하되, 적용 전 Candidate Safety는 `VALIDATED CANDIDATE`로 별도 표기한다.
