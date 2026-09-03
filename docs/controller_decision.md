# Controller Decision Audit Contract

## 1. 범위

Phase 11-A는 관제사가 하나의 SAFE Recommendation에 내린 `ACCEPT`, `MODIFY`, `REJECT` 결정을
타입 안전한 불변 Audit Domain으로 기록한다. Decision 생성은 승인된 명령의 실제 적용, Aircraft
Runtime 변경 또는 Conflict 재평가를 수행하지 않는다.

```text
ResolutionRecommendation(SAFE)
             ↓
ControllerDecisionAuditEntry
    ├─ ACCEPT → 후속 적용 허가, 아직 미적용
    ├─ MODIFY → 변경 기동 기록, 재검증 필요
    └─ REJECT → 적용 없음
             ↓
ControllerDecisionAuditLog
```

## 2. Controller Decision

`ControllerDecisionAuditEntry`는 다음을 함께 보존한다.

- Decision ID와 Source Recommendation Set ID
- 변경되지 않은 `ResolutionRecommendation`과 Candidate/Validation Evidence
- Decision Type과 timezone-aware UTC 결정시각
- 개인 이름이 아닌 Controller Position ID
- 선택적인 Rationale
- `MODIFY`일 때만 존재하는 변경 Maneuver

결정시각은 Recommendation 생성시각보다 이를 수 없다. Entry는 Recommendation 객체를 복제하거나
변경하지 않고 그대로 참조한다.

## 3. Decision별 불변조건

### 3.1 `ACCEPT`

- 추천된 SAFE Candidate를 그대로 선택한다.
- 변경 Maneuver를 포함할 수 없다.
- `authorizes_application=True`지만 Entry 생성만으로 Runtime에 적용하지 않는다.
- `approved_candidate`는 원본 Recommendation Candidate를 반환한다.

### 3.2 `MODIFY`

- Rationale과 실제로 달라진 Action Maneuver가 필수다.
- `NO_ACTION` 또는 추천과 동일한 Maneuver는 허용하지 않는다.
- 기존 Target Aircraft는 Recommendation에서 유지한다.
- `requires_revalidation=True`이며 적용을 허가하지 않는다.

변경 기동은 새로운 Candidate로 조립해 Safety Validation을 다시 통과해야 한다. Controller가
수정했다는 이유만으로 안전하다고 간주하지 않는다.

### 3.3 `REJECT`

- Rationale이 필수다.
- 변경 Maneuver를 포함할 수 없다.
- Candidate 적용을 허가하지 않는다.

## 4. Audit Log

`ControllerDecisionAuditLog`는 Decision Entry를 결정 UTC와 Decision ID 순으로 보존하는 불변
Snapshot이다. `revision`은 1부터 시작하며 Service가 성공적으로 Decision을 추가할 때만 증가한다.

- Decision ID, Recommendation Set ID와 Recommendation ID는 각각 고유하다.
- 하나의 Recommendation Set에는 최대 하나의 최종 Controller Decision만 존재한다.
- Log 생성시각은 포함된 모든 결정시각보다 이르지 않다.
- `accepted_entries`, `modified_entries`, `rejected_entries`, `latest_entry`를 파생 View로 제공한다.

Controller Position ID는 Audit 책임 위치를 나타내는 비개인 식별자다. 실제 개인 식별정보를 저장소나
데모 Payload에 기록하지 않는다 (`ASM-033`, `ASM-039`).

## 5. Golden Demo Mapping

T+85 Recommendation에서 관제사가 `CAND-A`를 선택하면 `ACCEPT` Entry가 생성되고 Candidate A가
후속 적용 가능 대상으로 노출된다. 이 시점까지 T+75 원본 Aircraft State와 Runtime은 변하지 않는다.
실제 적용과 적용 후 재평가는 후속 단계의 책임이다.

Phase 15-B Golden Demo UI에서는 같은 Primary Recommendation에 `MODIFY` 또는 `REJECT`도 선택할 수
있다. 수정 기동과 Rationale 또는 거절 Rationale은 기존 Audit Entry에 기록되며, 어느 경우도 Runtime
적용 권한을 만들지 않는다. 수정 결과의 Safety 재검증은 Audit 기록과 분리된 후속 단계다.

Phase 15-C는 해당 Audit Entry를 입력으로 수정 기동과 `NO_ACTION` 기준선을 T+90 Traffic 복사본에서
격리 검증한다. 결과가 SAFE여도 원 `MODIFY` Entry를 `ACCEPT`로 바꾸거나 Runtime을 적용하지 않는다.
따라서 Audit의 불변성과 사람의 최종 적용 권한 경계를 그대로 유지한다.

## 6. Phase 11-B Deterministic Controller Decision Service

`DeterministicControllerDecisionService`는 하나의 `ResolutionRecommendationSet`과 그 안의
Recommendation ID를 입력받아 다음을 원자적으로 수행한다.

1. Recommendation이 입력 Set에 실제로 포함되는지 확인한다.
2. Set에 기존 최종 Decision이 없는지 확인한다.
3. UTC, Revision, Source Identity로 Decision ID와 Audit Log ID를 결정론적으로 생성한다.
4. 불변 Audit Entry를 누적한 새 Audit Log Snapshot을 발행한다.

동일한 초기상태와 입력 순서는 같은 ID와 Audit Log를 만든다. 동일 Recommendation Set에 대한 두
번째 `ACCEPT`, `MODIFY`, `REJECT`는 모두 거부하며 실패한 요청은 Revision이나 현재 Log를 바꾸지
않는다. 결정시각은 이전 Log보다 이를 수 없다.

Service의 메모리 상태는 현재 프로세스 범위의 최소 구현이다. Persistence, HTTP Command Adapter,
인증·인가, Runtime 적용은 포함하지 않는다.

## 7. Phase 11-C Controller Decision Command/API Contract

`SubmitControllerDecisionRequest`는 Recommendation Set/Recommendation ID, Decision Type, UTC,
Controller Position, Rationale와 선택적 변경 Maneuver를 운송 계층과 독립적으로 검증한다. 변경 Maneuver는
nullable 고정 Schema를 사용하며 Domain Action Maneuver로 명시적으로 변환된다.

`InProcessControllerDecisionApi`는 `RecommendationSetLookup`에서 요청된 불변 Set을 조회하고 Phase
11-B Service에 결정을 위임한다. 응답은 `ControllerDecisionAuditLogReadModel`로 변환되며 다음 정보를
포함한다.

- Audit Log ID, Revision, 생성 UTC, 최신 Decision ID
- Decision/Recommendation/Candidate Identity
- `ACCEPT`, `MODIFY`, `REJECT`, Rationale와 Controller Position
- 변경 Maneuver, `authorizes_application`, `requires_revalidation`

응답은 JSON 호환 Primitive만 노출한다. API 계약은 Recommendation 객체, Aircraft Runtime 또는
Service 내부 상태를 클라이언트에 노출하지 않는다.

## 8. Phase 11-D Minimal WSGI HTTP Adapter

`ControllerDecisionWsgiApp`은 다음 두 Endpoint만 제공한다.

- `POST /api/v1/controller-decisions`: 고정 JSON Command를 제출하고 `201 Created` 반환
- `GET /api/v1/controller-decisions/current`: 현재 Audit Log를 반환하며 아직 없으면 `204 No Content`

Adapter는 16 KiB Body 제한, `application/json`, 정확한 Content-Length, UTF-8 JSON Object와 고정
Command/Maneuver 필드를 검증한다. Response는 결정론적 Key 순서와 `Cache-Control: no-store`를 사용한다.

오류는 Route/Method/Query/Media Type/JSON/Schema/Not Found/State Conflict를 구분한 4xx Code로
반환한다. 실패한 요청은 Decision Service Revision을 변경하지 않는다. 이 최소 Adapter는 인증·인가,
TLS, CSRF 방어, Rate Limit 또는 실제 운영 배포 구성을 제공하지 않는다.

## 9. 다음 단계

Phase 12-A는 현재까지 분리된 Simulation, Prediction, Conflict, Risk, Priority, Exception Queue,
Resolution, Recommendation 및 Controller Decision 구성요소를 Golden Demo Runtime으로 조립한다.
`ACCEPT` 적용과 `MODIFY` 재검증은 조립 시에도 명시적으로 분리한다.
