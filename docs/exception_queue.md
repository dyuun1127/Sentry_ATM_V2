# Deterministic Exception Queue Domain Contract

## 1. 범위

Phase 8-A는 Risk와 Operational Priority 결과를 관제사에게 제시할 타입 안전한 Exception 항목과
결정론적 Queue Snapshot으로 정의한다. Phase 8-B는 Assessment에서 안정적인 ID의 Item을
생성·갱신·확인·해결·재개하는 상태 기반 Service를 추가한다. UI 상태 관리는 포함하지 않는다.

```text
ConflictRiskAssessment ───────> ConflictExceptionItem
OperationalPriorityAssessment ─> OperationalPriorityExceptionItem
                                      ↓
                              ExceptionQueueSnapshot
```

## 2. Exception 항목

두 Source를 하나의 선택 필드 모델로 합치지 않는다.

### 2.1 `ConflictExceptionItem`

- 안정적인 Exception ID
- 원본 `ConflictRiskAssessment`
- 최초 Open UTC와 마지막 Update UTC
- `OPEN`, `ACKNOWLEDGED`, `RESOLVED` 상태
- Pair Aircraft ID, Risk Score와 TCPA 파생값

### 2.2 `OperationalPriorityExceptionItem`

- 안정적인 Exception ID
- 원본 `OperationalPriorityAssessment`
- 최초 Open UTC와 마지막 Update UTC
- `OPEN`, `ACKNOWLEDGED`, `RESOLVED` 상태
- 단일 Aircraft ID와 Priority Score 파생값

Source Assessment 평가시각은 Item의 Open UTC와 Update UTC 사이에 있어야 하며 Update UTC는
Open UTC보다 이를 수 없다. 이 계약은 Source 결과를 복사해 서로 다른 값으로 변하는 것을 막는
동시에 Assessment 이후 Acknowledge 시각을 기록할 수 있게 한다.

## 3. 잠정 Queue Policy

`POC_EXCEPTION_QUEUE_V1`의 교차 타입 순서는 다음과 같다 (`ASM-036`). 작은 Rank가 앞선다.

| Rank | 항목 |
|---:|---|
| 0 | `EMERGENCY` Operational Priority |
| 1 | `CRITICAL` Conflict Risk |
| 2 | `URGENT` Operational Priority |
| 3 | `HIGH` Conflict Risk |
| 4 | `ATTENTION` Operational Priority |
| 5 | `MEDIUM` Conflict Risk |
| 6 | `ROUTINE` Operational Priority |
| 7 | `LOW` Conflict Risk |

이는 Golden Demo를 위한 잠정 표시 순서이며 실제 관제 우선순위 기준이 아니다. 비상 항공기를 Queue
상단에 표시해도 검증 없이 경로 또는 순서를 자동 변경하지 않는다.

전체 정렬 키는 다음 순서다.

```text
resolved 여부
→ 교차 타입 Rank
→ acknowledged 여부
→ Conflict TCPA 오름차순
→ Score 내림차순
→ Exception ID 사전순
```

`ACKNOWLEDGED`는 같은 심각도 안에서만 `OPEN` 뒤에 위치하므로 더 낮은 심각도의 미확인 항목이
비상항목을 앞지르지 않는다. `RESOLVED`는 활성 항목 뒤에 보존한다.

## 4. Queue Snapshot

`ExceptionQueueSnapshot`은 다음 값을 보존한다.

- Queue Snapshot ID
- timezone-aware UTC 생성시각
- 적용한 `ExceptionQueuePolicy`
- 입력 순서와 무관하게 정렬된 불변 Item Tuple

Exception ID와 Source Assessment ID는 Snapshot 안에서 각각 고유해야 하고 Item Update 시각은
Snapshot 생성시각보다 늦을 수 없다. `active_items`는 `RESOLVED`를 제외하고 `top_item`은 첫 활성
항목 또는 `None`을 반환한다.

## 5. Lifecycle Service

`ExceptionQueueService`는 다음 규칙으로 Source Assessment를 적용한다.

- Conflict는 정렬된 Aircraft Pair를 길이 접두어로 인코딩하고, Priority는 Aircraft ID를 사용해
  안정적이며 모호하지 않은 Exception ID를 만든다.
- `LOW` Risk와 `ROUTINE` Priority는 새 Item을 만들지 않는다.
- 활성 Assessment가 처음 도착하면 `OPEN`으로 생성한다.
- 활성 Assessment가 갱신되면 최초 Open 시각과 `ACKNOWLEDGED` 상태를 보존한다.
- 같은 Subject의 `LOW` 또는 `ROUTINE` Assessment가 도착하면 `RESOLVED`로 전환한다.
- `RESOLVED` Subject가 다시 활성화되면 새 Open 시각과 `OPEN` 상태로 재개한다.
- 입력에서 누락된 Subject는 해결로 추정하지 않고 기존 상태를 보존한다.

`acknowledge`는 원본 Assessment를 바꾸지 않고 Item 상태와 Update 시각만 변경한다. 이미 확인한
항목에 대한 같은 요청은 멱등적으로 처리하고, 해결된 항목은 다시 확인할 수 없다.

각 변경은 `QUEUE-{UTC timestamp}-{revision}` 형식의 불변 Snapshot을 만든다. Revision은 같은
시각에 여러 조작이 있어도 ID 충돌을 막으며 `reset` 이후 동일 입력은 동일 Snapshot을 재현한다.
모든 Refresh Assessment는 Snapshot 생성시각에 평가된 값이어야 하고 서비스 시간은 역행할 수 없다.

## 6. Golden Demo 검증

- `T+0`: 28개 Pair가 모두 LOW이고 8대가 모두 ROUTINE이므로 활성 Queue가 비어 있다.
- `T+70`: `MIL-F01 / CIV-A02` HIGH Conflict가 최상위이고 `MIL-F01` ATTENTION이 뒤따른다.
- `T+240`: `MIL-T01` EMERGENCY Priority가 전체 Queue 최상위다.

## 7. Read Model과 API 계약

Phase 8-C는 Domain 객체를 외부 표현에 직접 노출하지 않는 다음 계약을 정의한다.

- Conflict와 Operational Priority를 구분하는 타입별 Read Model
- RFC 3339 UTC 문자열, Enum 문자열과 JSON Array로 직렬화되는 안정 필드
- Snapshot ID, 정책 ID, 활성 건수, 최상위 Exception ID와 정책 순서의 Item 목록
- 기본 조회에서는 `RESOLVED` 제외, 명시적인 `include_resolved` 조회에서만 이력 포함
- `get_current`와 `acknowledge` 동작을 정의한 동기식 `ExceptionQueueApiContract`
- HTTP/Desktop Adapter 이전에 동일 계약을 검증하는 `InProcessExceptionQueueApi`

아직 Snapshot이 생성되지 않았으면 `get_current`는 `None`을 반환한다. 확인 요청은 안정 ID와
timezone-aware 시각을 요구한다. 알 수 없는 ID는 `KeyError`, 해결 상태나 시간 역행은 `ValueError`로
구분해 후속 HTTP Adapter가 각각 404, 409 또는 422 응답으로 명시적으로 변환할 수 있게 한다.

HTTP 표현은 다음과 같으며 Phase 8-C 자체는 서버를 실행하거나 네트워크 포트를 열지 않는다.

```text
GET  /api/v1/exception-queue?include_resolved=false
POST /api/v1/exceptions/{exception_id}/acknowledgements
```

## 8. Minimal HTTP Adapter

Phase 8-D의 `ExceptionQueueWsgiApp`은 Python 표준 WSGI 서버 또는 호환 서버에 연결할 수 있는
실제 HTTP 경계를 제공한다. 외부 웹 프레임워크 의존성은 추가하지 않는다.

### 8.1 Endpoint

| Method | Path | 결과 |
|---|---|---|
| `GET` | `/api/v1/exception-queue` | 현재 활성 Queue JSON, 미생성 시 `204` |
| `GET` | `/api/v1/exception-queue?include_resolved=true` | 해결 이력을 포함한 Queue JSON |
| `POST` | `/api/v1/exceptions/{exception_id}/acknowledgements` | 항목 확인 후 최신 Queue JSON |

확인 요청 Body는 다음 한 필드만 허용한다.

```json
{"acknowledged_at_utc":"2026-09-01T03:01:11Z"}
```

응답은 JSON UTF-8이며 항상 `Cache-Control: no-store`를 사용한다. 현재 상태 전달은 결정론적 조회
Polling 방식이다. Polling 간격은 프론트엔드 Phase에서 정하고, SSE/WebSocket은 항공기 수와 갱신주기
측정 결과가 필요할 때만 추가한다.

### 8.2 오류 계약

- `400`: 잘못된 Query, Content-Length 또는 JSON
- `404`: 존재하지 않는 Route나 Exception ID
- `405`: 허용되지 않은 Method이며 `Allow` Header 제공
- `409`: 해결된 항목 확인 또는 서비스 시간 역행
- `413`: 16 KiB를 초과하는 Body
- `415`: JSON이 아닌 Content-Type
- `422`: 필드 구조, RFC 3339 시각 또는 Domain 요청 검증 실패

Adapter는 서버를 자동 실행하거나 포트를 열지 않는다. 향후 Composition Root가 Simulation,
`ExceptionQueueService`, API와 WSGI Server를 조립한다. CORS는 배포 Origin이 확정되기 전에는
허용하지 않으며 같은 Origin 또는 Reverse Proxy 구성을 기본으로 한다.

## 9. 다음 단계 경계

Phase 9는 Queue 최상위 Conflict를 입력으로 받는 `Resolution Candidate Domain`부터 시작한다.
HTTP Runtime Composition과 프론트엔드는 핵심 추천·검증 흐름이 완성된 뒤 연결한다. Queue API는
Aircraft Runtime을 직접 변경하지 않는다.
