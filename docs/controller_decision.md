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
Snapshot이다.

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

## 6. 다음 단계

Phase 11-B는 Decision ID와 Audit Log Revision을 결정론적으로 관리하는 Controller Decision Service를
구현하고, Recommendation Set당 중복 결정을 거부한다.
