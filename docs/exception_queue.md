# Deterministic Exception Queue Domain Contract

## 1. 범위

Phase 8-A는 Risk와 Operational Priority 결과를 관제사에게 제시할 타입 안전한 Exception 항목과
결정론적 Queue Snapshot으로 정의한다. Assessment에서 Item을 생성·갱신·종료하는 Assembler와
UI 상태 관리는 포함하지 않는다.

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

## 5. 다음 단계 경계

Phase 8-B는 Phase 7 결과에서 안정적인 Exception ID를 생성하고, LOW/ROUTINE 제외 정책과 기존
Item의 Open·Acknowledge·Resolve 수명주기를 적용해 Queue Snapshot을 만드는 Service를 구현한다.
