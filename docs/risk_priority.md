# Risk and Operational Priority Domain Contract

## 1. 범위

Phase 7-A는 Conflict Risk와 운항 우선순위를 서로 다른 불변 Domain 결과로 정의한다. Phase 7-B는
`ConflictEvent`와 현재 Aircraft State까지 발생한 Scenario Event를 점수·Level로 변환하는
결정론적 Evaluator를 제공한다. Exception Queue 정렬 및 Runtime 변경은 포함하지 않는다.

```text
ConflictEvent ──> ConflictRiskAssessment
Scenario Event ──> OperationalPriorityAssessment
```

Risk는 Aircraft Pair의 미래 분리 위험을 의미하고 Priority는 한 Aircraft의 운영상 처리 필요도를
의미한다. 군용 Category 자체는 Priority 상승 조건이 아니며 두 Score를 하나로 합치지 않는다.

## 2. Level과 이유 코드

### 2.1 Conflict Risk

| Level | 의미 |
|---|---|
| `LOW` | 예측 Conflict가 없거나 충분한 여유가 있음 |
| `MEDIUM` | 잠정 근접 범위에 들어 추가 감시가 필요함 |
| `HIGH` | 예측 Horizon 안에서 분리기준 위반이 예상됨 |
| `CRITICAL` | 현재 또는 매우 임박한 분리기준 위반 |

`RiskReasonCode`는 예측 Conflict 없음, 근접 임계값, 예측 분리손실, 수평·수직 기준 침범,
짧은 TCPA 및 즉시 분리손실을 안정적인 직렬화 값으로 표현한다.

### 2.2 Operational Priority

| Level | 의미 |
|---|---|
| `ROUTINE` | 정상 운항 |
| `ATTENTION` | 진입 조건 불일치 등 확인 필요 |
| `URGENT` | 즉시 처리가 필요한 비상 외 운항 상태를 위해 예약 |
| `EMERGENCY` | 선언된 비상상황 |

`PriorityReasonCode`는 정상 운항, 진입 조건 불일치, 비상 선언 및 추상화된 Aircraft Condition을
표현한다. 실제 군 작전 우선순위나 민감한 비상절차를 모델링하지 않는다.

## 3. 평가 결과

`ConflictRiskAssessment`는 다음 값을 보존한다.

- Risk Assessment ID와 원본 Conflict ID
- 정규화된 `ConflictPair`
- timezone-aware UTC 평가시각
- 0~100 Risk Score와 `RiskLevel`
- TCPA
- 적용 분리기준 대비 수평·수직 최소분리 비율
- 중복 없는 한 개 이상의 `RiskReasonCode`
- 적용한 Risk Policy Profile ID

분리 비율은 `예상 최소분리 / 적용 임계값`이다. 1.0 미만은 해당 축의 기준 안쪽이라는 뜻이다.

`OperationalPriorityAssessment`는 다음 값을 보존한다.

- Priority Assessment ID와 Aircraft ID
- timezone-aware UTC 평가시각
- 0~100 Priority Score와 `OperationalPriorityLevel`
- 중복 없는 한 개 이상의 `PriorityReasonCode`
- 적용한 Priority Policy Profile ID
- 판단의 근거가 된 중복 없는 Scenario Event ID

정상 `ROUTINE` 결과는 Source Event 없이 생성할 수 있다. Score와 Level의 일치 여부 및 이벤트별
판정은 Phase 7-B Evaluator가 정책 Profile을 사용해 보장한다.

## 4. 잠정 PoC Policy Profile

### 4.1 `POC_RISK_V1`

| 항목 | 값 |
|---|---:|
| Critical TCPA | 30초 |
| High TCPA | 120초 |
| Medium 수평 비율 | 1.25 |
| Medium 수직 비율 | 1.25 |
| LOW / MEDIUM / HIGH / CRITICAL Score | 0 / 40 / 75 / 100 |

비율과 시간은 `ASM-024`의 잠정 PoC 입력이다. 공식 분리기준이나 보편적인 Risk 기준이 아니다.

### 4.2 `POC_OPERATIONAL_PRIORITY_V1`

| 조건 | Score | Level |
|---|---:|---|
| 정상 운항 | 0 | `ROUTINE` |
| 진입 조건 불일치 | 40 | `ATTENTION` |
| 비상 선언 | 100 | `EMERGENCY` |

이 매핑은 `ASM-035`의 Golden Demo용 잠정값이다. Conflict Risk는 이 Priority Score를 올리지 않으며
`URGENT`는 후속 검증된 비상 외 운항 규칙을 위해 예약한다.

## 5. Phase 7-B 결정론적 Evaluator

### 5.1 Conflict Risk

`ConflictRiskEvaluator`는 Event의 Rule Profile ID와 `ConflictStatus`를 주입된
`SeparationRuleProfile`로 다시 검증한 뒤 다음 순서로 평가한다.

| 조건 | Level | 기본 Score |
|---|---|---:|
| `PREDICTED`, TCPA 0~30초 | `CRITICAL` | 100 |
| `PREDICTED`, TCPA 30초 초과~120초 | `HIGH` | 75 |
| `PREDICTED`, TCPA 120초 초과 | `MEDIUM` | 40 |
| `SAFE`, 수평·수직 비율 모두 1.25 미만 | `MEDIUM` | 40 |
| 그 외 `SAFE` | `LOW` | 0 |

정확히 TCPA 0초인 `PREDICTED` 결과는 `IMMEDIATE_SEPARATION_LOSS` 이유를 남긴다. Score와
시간·비율 기준은 `RiskPolicyProfile`에서 교체할 수 있다.

### 5.2 Operational Priority

`OperationalPriorityEvaluator`는 평가할 `AircraftState`의 UTC 시각보다 늦은 이벤트와 다른
Aircraft 대상 이벤트를 제외한다. 입력 순서와 관계없이 Event 시각과 ID로 정렬한 뒤 다음 우선순위를
적용한다.

1. State 또는 활성 Event에 비상 선언이 있으면 `EMERGENCY`
2. 활성 진입 조건 불일치가 있으면 `ATTENTION`
3. 그 외는 `ROUTINE`

비상과 진입 이탈이 동시에 있으면 비상 Score/Level을 사용하되 두 원인과 Source Event ID를 모두
보존한다. Conflict Risk는 Operational Priority 입력으로 사용하지 않는다.

### 5.3 Golden Demo 결과

| 시각 | 대상 | Risk | Priority |
|---|---|---|---|
| T+70 | `CIV-A02` / `MIL-F01` | `HIGH` / 75 | - |
| T+70 | `MIL-F01` | - | `ATTENTION` / 40 |
| T+240 | `MIL-T01` | 별도 결과 | `EMERGENCY` / 100 |

Clock Reset과 동일 입력은 같은 Assessment ID, Score, Level과 Reason Code를 생성한다.

## 6. 다음 단계 경계

Phase 8-A는 Risk와 Priority 결과를 타입이 다른 Exception 항목으로 변환하고, Emergency Priority,
Risk Level, TCPA 및 안정적인 ID를 사용해 결정론적 Queue를 구성한다.
