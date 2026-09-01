# SENTRY Golden Demo Scenario Contract

## 1. 문서 정보

- 시나리오 ID: `RKTU_GOLDEN_DEMO_V1`
- 시나리오명: RKTU Terminal Predictive ATC - Mixed Traffic Conflict and Emergency Recovery
- 상태: Phase 0-A 기준안
- 버전: 1.0
- 기준일: 2026-09-01
- 관련 문서: `docs/assumptions.md`

이 문서는 SENTRY PoC가 최종 데모에서 반드시 보여주어야 하는 입력, 사건, 판단, 관제사 개입 및 결과를 정의한다. 구체적인 운동 값은 후속 Phase의 수학 검증 과정에서 조정할 수 있지만, 시나리오의 의미와 성공 조건은 임의로 변경하지 않는다.

## 2. 한 문장 정의

청주공항 중심 Terminal Simulation Area에서 계획과 다르게 진입한 군용기와 민항기의 미래 충돌을 현재 시점에서 예측해 안전한 대응안을 관제사에게 추천하고, 이후 비상 복귀 항공기가 발생하면 전체 접근 순서를 안전하게 재구성한다.

## 3. 증명할 핵심 가치

1. 현재 분리 위반이 발생하기 전에 미래 위험을 탐지한다.
2. Planned, Actual, Predicted 4DT를 서로 구분한다.
3. 위험도와 운항 우선순위를 별도로 계산한다.
4. 여러 대응 후보를 전체 Traffic과 함께 재시뮬레이션한다.
5. 첫 충돌뿐 아니라 2차 충돌과 안전 규칙도 확인한다.
6. AI는 추천만 제공하고 관제사가 최종 결정한다.
7. 승인된 기동을 적용한 후 충돌 해소 여부를 다시 검증한다.
8. 정상 Traffic은 자동 감시하고 주의가 필요한 예외만 강조한다.

## 4. System Boundary

### 4.1 포함 범위

- RKTU ARP를 중심으로 한 가상의 Terminal Simulation Area (`ASM-002`~`ASM-004`)
- Sector 진입부터 최종접근 안정화 또는 Sector 이탈까지의 비행
- 하나의 가상 `Terminal Radar Controller`가 담당하는 Traffic (`ASM-005`)
- 민항기와 군용기가 혼재한 접근, 출발 및 통과 Traffic
- 예상 Sector 진입 상태와 실제 진입 상태의 비교
- 미래 항적 예측, 충돌 탐지, 위험 및 우선순위 평가
- 대응 후보 생성, 재시뮬레이션 및 안전성 검증
- 관제사의 Accept, Modify, Reject 의사결정

### 4.2 제외 범위

- 전국 공역과 여러 관제기관의 실제 운영구조 복제
- 실제 Jungwon TMA 또는 Cheongju CTR 전체의 책임 범위 주장
- Tower 관제, 활주로 점유 및 지상 이동 (`ASM-007`)
- MCRC를 항공교통관제기관으로 모델링하는 것 (`ASM-006`)
- 실제 군 폐쇄망, 군 레이더 및 C4I 연동
- AI가 조종사 또는 항공기에 직접 명령하는 기능
- 실시간 STT, FF-ICE 전체 구현 및 전국 Handoff
- 실제 군용기 민감 성능과 실제 군 Callsign

## 5. 행위자

### 5.1 사람

`Terminal Radar Controller`는 시스템의 유일한 최종 의사결정자다. 시스템의 추천을 Accept, Modify 또는 Reject할 수 있다.

### 5.2 시스템

- Traffic Monitor: 현재 Aircraft State와 계획 이탈을 감시한다.
- Trajectory Predictor: 현재 상태로부터 미래 4DT를 산출한다.
- Conflict Detector: 미래 항적의 분리, CPA 및 TCPA를 평가한다.
- Risk Engine: 충돌의 긴급성과 심각도를 평가한다.
- Priority Engine: 비상 및 운항 조건에 따른 처리 우선순위를 평가한다.
- Resolution Engine: 제한된 관제 기동 후보를 생성하고 재시뮬레이션한다.
- Rule Engine: 분리, 고도, 공역 및 성능 규칙을 검증한다.
- Recommendation Service: 안전한 후보와 설명을 관제사에게 제공한다.

## 6. 등장 항공기

| Aircraft ID | 성능 등급 | Source | 시나리오 역할 |
|---|---|---|---|
| `CIV-A01` | `AIRLINER` | `SYNTHETIC` | 접근 순서 1번, 최종접근 안정화 상태 |
| `CIV-A02` | `AIRLINER` | `SYNTHETIC` | `MIL-F01`과 미래 충돌 |
| `CIV-A03` | `AIRLINER` | `SYNTHETIC` | 후속 접근 Traffic |
| `CIV-D01` | `AIRLINER` | `SYNTHETIC` | 출발 또는 통과 Traffic |
| `MIL-F01` | `FAST_JET` | `SYNTHETIC` | Sector 진입 조건 불일치 |
| `MIL-F02` | `FAST_JET` | `SYNTHETIC` | 정상 복귀 및 2차 충돌 검증 Traffic |
| `MIL-T01` | `TRANSPORT` | `SYNTHETIC` | 후반부 비상 우선 복귀 |
| `MIL-T02` | `TRANSPORT` | `SYNTHETIC` | 정상 군 수송기 Traffic |

초기 Golden Demo는 재현성을 위해 8대의 항공기를 모두 Synthetic으로 구성한다 (`ASM-010`, `ASM-015`). 실제 군 기종 대신 성능 등급을 사용하며 (`ASM-012`), OpenSky Playback은 동일 Domain Model을 사용하는 후속 입력 Adapter로 추가한다 (`ASM-011`).

## 7. 초기 조건

- 시뮬레이션 시각은 timezone-aware UTC로 시작한다 (`ASM-008`).
- 8대의 항공기는 모두 Simulation Area 내부 또는 진입 경계에 존재한다.
- 시작 시점에는 현재 분리 위반과 미래 Conflict가 없다.
- 모든 항공기의 상태는 `NORMAL`이다.
- Exception Queue는 비어 있다.
- 모든 항공기는 Planned Trajectory와 현재 Actual State를 가진다.
- Predictor는 30, 60, 120초 Horizon을 지원한다 (`ASM-016`).

## 8. 시나리오 진행

시각은 재현 가능한 데모를 위한 기준값이다. Simulation Tick과 Prediction 갱신 주기는 `ASM-017`을 따르며, 후속 운동학 검증에서 이벤트 시각을 수 초 범위로 조정할 수 있다 (`ASM-022`).

### 8.1 T+0초 - 정상 혼합 교통

시스템은 8대의 Traffic을 감시하지만 경고를 생성하지 않는다.

기대 화면:

```text
Traffic count: 8
Active exceptions: 0
System state: NORMAL
```

### 8.2 T+60초 - MIL-F01 Sector 진입 조건 불일치

상류 Sector에서 기대한 진입 상태는 다음과 같다.

```text
Expected entry point: ENTRY-A
Expected altitude: 9,000 ft
Expected heading: 210 deg
Expected time: T+60 sec
```

실제 진입 상태는 다음과 같다.

```text
Actual altitude: 7,400 ft
Lateral deviation: 2.1 NM
Time deviation: +25 sec
```

시스템은 `ENTRY_CONFORMANCE_DEVIATION`을 생성한다. 이는 기관 간 Handoff 전체를 구현하는 것이 아니라, 기대 진입 상태와 실제 상태의 불일치를 나타낸다 (`ASM-020`). `ENTRY-A`는 공식 Fix가 아닌 Synthetic 지점이다 (`ASM-021`).

### 8.3 T+70초 - 미래 충돌 탐지

Actual State를 반영해 Rolling Prediction을 갱신하면 `MIL-F01`과 `CIV-A02`의 미래 충돌이 탐지된다.

목표 출력:

```text
Conflict pair: MIL-F01 / CIV-A02
Current state: SAFE
Time to predicted conflict: approximately 90 sec
Predicted horizontal separation: approximately 2.3 NM
Predicted vertical separation: approximately 500 ft
Risk level: HIGH
```

설명에는 다음 원인을 포함한다.

- Sector 진입 고도 불일치
- Planned Trajectory 이탈
- 상승 또는 강하 항적 수렴
- 높은 Closing Speed

정확한 분리 수치는 후속 Phase에서 검증하지만 (`ASM-022`), 현재는 안전하고 예측 Horizon 안에서만 위험하다는 관계는 유지해야 한다. Conflict 판정은 교체 가능한 Rule Profile을 사용하며 단일 임계값을 공식 보편 기준으로 하드코딩하지 않는다 (`ASM-018`).

### 8.4 T+75초 - 대응 후보 생성

| Candidate ID | 대상 | 기동 |
|---|---|---|
| `CAND-A` | `MIL-F01` | 9,000 ft로 상승 후 유지 |
| `CAND-B` | `MIL-F01` | 우측 20도 침로 변경 |
| `CAND-C` | `CIV-A02` | 속도 30 kt 감소 |
| `CAND-D` | `CIV-A02` | 1,000 ft 추가 강하 |
| `CAND-E` | 없음 | 조작 없음 |

### 8.5 T+80초 - 후보 재시뮬레이션과 Rule 검증

| Candidate | 1차 충돌 | 2차 위험 또는 규칙 | 기대 판정 |
|---|---|---|---|
| `CAND-A` | 해소 | 없음 | `SAFE` |
| `CAND-B` | 해소 | `MIL-F02`와 2차 근접 | `UNSAFE` |
| `CAND-C` | 분리 부족 | 없음 | `INEFFECTIVE` |
| `CAND-D` | 해소 가능 | 최저고도 Rule 위반 | `UNSAFE` |
| `CAND-E` | 지속 | 해당 없음 | `UNSAFE` |

후속 구현에서는 위 결과가 실제 운동 계산으로 재현되도록 초기 상태를 조정해야 하며, 판정을 하드코딩해서는 안 된다.

### 8.6 T+85초 - 관제사 추천

시스템은 안전한 후보 `CAND-A`를 다음과 같이 추천한다.

```text
Recommended aircraft: MIL-F01
Recommended maneuver: Climb to and maintain 9,000 ft
Reason: Resolves the predicted conflict without creating a secondary conflict and is feasible for the configured performance class
Expected result: Horizontal or vertical separation restored
```

추천 화면은 반드시 `Accept`, `Modify`, `Reject` 선택지를 제공할 수 있는 모델을 가진다.

### 8.7 T+90초 - 관제사 Accept 및 재검증

관제사가 `CAND-A`를 Accept하기 전에는 Aircraft Runtime이 변경되지 않는다. Accept 이후에만 승인된 기동을 `MIL-F01`에 적용한다.

적용 후 시스템은 다음 순서로 재평가한다.

1. Actual State 갱신
2. Predicted 4DT 재계산
3. 전체 Traffic Pair 재검사
4. Rule 재검증
5. Conflict 상태 갱신

목표 상태 전이는 다음과 같다.

```text
HIGH -> MONITORING -> RESOLVED
```

### 8.8 T+240초 - MIL-T01 비상 우선 복귀

다음 이벤트를 발생시킨다.

```text
event_type: EMERGENCY_DECLARED
target_aircraft: MIL-T01
emergency_type: PRIORITY_RETURN
reason_category: AIRCRAFT_CONDITION
```

시스템은 `MIL-T01`의 Priority를 최상위로 올리고 전체 Traffic을 다시 평가한다. 비상 이벤트는 민감한 실제 상황이 아닌 PoC 추상화다 (`ASM-025`). 비상 항공기도 검증되지 않은 직선 경로로 즉시 보내지 않으며, 주변 Traffic과의 미래 충돌을 먼저 확인한다 (`ASM-026`).

### 8.9 T+245초 - 접근 순서 재평가

기존 순서:

```text
1. CIV-A01
2. CIV-A02
3. MIL-F02
4. CIV-A03
5. MIL-T01
```

추천 순서:

```text
1. CIV-A01
2. MIL-T01
3. CIV-A02
4. MIL-F02
5. CIV-A03
```

`CIV-A01`은 이미 최종접근에 안정화된 상태이므로 무리하게 이탈시키지 않는다. 이 결정은 단순 Priority 값만이 아니라 현재 비행단계와 늦은 기동의 위험을 함께 고려한 결과로 설명한다 (`ASM-023`, `ASM-026`).

### 8.10 T+250초 - 주변 Traffic 조정 추천

| 항공기 | 추천 조치 |
|---|---|
| `MIL-T01` | 검증된 비상 우선 복귀 경로 유지 |
| `CIV-A02` | 30 kt 감속 |
| `MIL-F02` | Terminal 진입 지연 또는 침로 Vector |
| `CIV-A03` | 현재 후속 순서 유지 |

모든 조치는 전체 Traffic과 함께 재시뮬레이션하고 Rule Engine을 통과해야 한다.

### 8.11 T+260초 이후 - 승인, 최종접근 안정화 및 정상 흐름 복구

관제사 승인 후 조치를 Runtime에 적용한다. `MIL-T01`이 안전한 최종접근 상태에 도달하고 Tower 이양 준비가 완료되면 비상 처리 구간을 종료한다.

이후 지연된 Traffic을 재평가하고 정상 접근 순서를 복구한다. 실제 착륙과 Tower 관제는 시뮬레이션하지 않는다.

## 9. 필수 성공 조건

| ID | 성공 조건 |
|---|---|
| `SC-001` | 시작 시 현재 분리 위반과 Exception이 없어야 한다. |
| `SC-002` | 기대 진입 상태와 Actual State 불일치가 탐지되어야 한다. |
| `SC-003` | `MIL-F01`과 `CIV-A02`는 현재 안전하지만 120초 Horizon 안에서 위험해야 한다. |
| `SC-004` | Conflict 결과에 수평분리, 수직분리, TCPA 또는 예측시각과 원인이 포함되어야 한다. |
| `SC-005` | 최소 4개의 실제 기동 후보와 No-action 후보가 생성되어야 한다. |
| `SC-006` | 후보는 전체 Traffic과 함께 재시뮬레이션되어야 한다. |
| `SC-007` | 2차 충돌 또는 Rule 위반 후보는 추천에서 제외되어야 한다. |
| `SC-008` | 관제사 승인 전에는 Aircraft Runtime이 변경되지 않아야 한다. |
| `SC-009` | `CAND-A` 승인 후 최초 Conflict가 해소되어야 한다. |
| `SC-010` | `MIL-T01` 비상 선언 후 Risk와 별개로 Priority가 최상위가 되어야 한다. |
| `SC-011` | 비상 순서 재구성 시 이미 안정된 `CIV-A01`의 비행단계를 고려해야 한다. |
| `SC-012` | 비상 처리 후보도 2차 충돌과 Rule 검증을 통과해야 한다. |
| `SC-013` | 모든 추천, 근거, 관제사 결정 및 적용 결과가 Audit Log에 남아야 한다. |
| `SC-014` | 시나리오 종료 시 미해결 `HIGH` 또는 `CRITICAL` Conflict가 없어야 한다. |

## 10. 실패 조건

- 현재 분리 위반이 발생한 뒤에야 최초 경고가 생성된다.
- Planned, Actual, Predicted Trajectory를 구분할 수 없다.
- 후보 판정이 재시뮬레이션 없이 고정값으로 결정된다.
- 첫 충돌만 해소하고 세 번째 항공기와의 2차 충돌을 확인하지 않는다.
- 관제사 승인 전에 항공기 기동이 자동 적용된다.
- 비상 항공기를 검증 없이 무조건 직선 경로로 보낸다.
- `MIL-T01`의 Priority와 Conflict Risk를 같은 값으로 처리한다.
- PoC 임계값을 모든 공역에 적용되는 공식 기준으로 설명한다.
- MCRC 또는 AI를 최종 항공교통관제 권한자로 표현한다.

## 11. 필수 출력 데이터

- 현재 Aircraft State 및 Aircraft Metadata
- Planned, Actual, Predicted Trajectory
- 계획 대비 수평, 수직, 시간 편차
- Conflict Pair, CPA, TCPA 및 최소 분리
- Risk Score, Risk Level 및 주요 원인
- Priority Score, Priority Level 및 주요 원인
- Resolution Candidate별 예상 결과와 비용
- Rule Evaluation 결과와 실패 이유
- Recommendation 설명과 Before/After 비교
- Controller Decision과 적용 시각
- 적용 후 Conflict Resolution 검증 결과

## 12. 보조 Validation Scenario

Golden Demo와 별도로 다음 원자적 시나리오를 후속 Phase의 단위 및 통합 테스트로 구현한다.

| ID | 목적 |
|---|---|
| `VAL-HEAD-ON` | 동일 고도 정면 접근의 CPA/TCPA 검증 |
| `VAL-CROSSING` | 90도 교차 수렴 검증 |
| `VAL-VERTICAL-SAFE` | 수평 위치는 가깝지만 수직 분리로 안전한 경우 |
| `VAL-DIVERGING` | 현재 가깝지만 서로 멀어지는 Traffic의 오경보 방지 |
| `VAL-CLIMB-CONVERGENCE` | 순항기 아래에서 상승하는 항공기 검증 |
| `VAL-DESCENT-CONVERGENCE` | 순항기 위에서 강하하는 항공기 검증 |
| `VAL-SECONDARY-CONFLICT` | 첫 회피가 세 번째 항공기와 충돌하는 경우 |
| `VAL-EMERGENCY-PRIORITY` | 낮은 Conflict Risk와 높은 Emergency Priority의 분리 검증 |

## 13. 변경 관리

다음 항목은 Scenario Contract 변경으로 간주하므로 문서 버전을 올리고 변경 이유를 기록해야 한다.

- 시스템 사용자 또는 최종 결정권자 변경
- Simulation Area의 의미 변경
- Golden Demo의 핵심 항공기 또는 사건 제거
- 관제사 승인 이전 자동 기동 허용
- 성공 조건 `SC-001`부터 `SC-014`까지의 의미 변경

운동학 검증에 따른 초기 좌표, 속도, 이벤트 시각 및 예상 분리 수치 조정은 핵심 의미가 유지되는 한 마이너 변경으로 관리한다.
