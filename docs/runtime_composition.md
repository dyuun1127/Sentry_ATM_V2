# Golden Demo Runtime Composition

## 1. 범위

Phase 12-A는 지금까지 독립적으로 검증한 구성요소를 하나의 프로세스 한정 Golden Demo Runtime으로
조립한다. Composition은 객체 생성과 의존성 연결만 수행하며 Clock 재생, 예측·충돌 계산, 후보 생성,
관제사 결정 또는 Aircraft Runtime 변경을 시작하지 않는다.

```text
Golden Scenario Definition
          ↓ shared SimulationClock
Traffic Engine ─┬─ Rolling Prediction Scheduler
                ├─ Rolling Conflict Scheduler
                └─ Scenario Event Timeline

Risk + Priority → Exception Queue
                        ↓
Candidate Generator → Safety Validator → Recommendation Service
                                            ↓
                              InMemoryRecommendationCatalog
                                  ├─ Recommendation Read API
                                  └─ Controller Decision API → Audit Service
```

## 2. Composition Root

`build_golden_demo_runtime()`은 다음을 새 인스턴스로 생성한다.

- 8대 Golden Scenario와 Synthetic Traffic Simulation
- 같은 Clock을 공유하는 Prediction/Conflict Scheduler
- 서로 분리된 Risk 및 Operational Priority Evaluator
- Exception Queue Service
- Resolution Candidate Generator와 Isolated Safety Validator
- Recommendation Ranking Service와 process-local Recommendation Catalog
- Controller Decision Audit Service
- Exception Queue, Recommendation, Controller Decision의 In-process API와 WSGI Adapter

Factory 호출 직후 Clock은 `READY`이고 Scheduler Run, Queue Snapshot, Recommendation과 Controller
Decision은 모두 비어 있다. 반복 Factory 호출은 같은 경계 상태를 만들지만 내부 mutable Service는 서로
공유하지 않는다.

## 3. Recommendation Catalog

`InMemoryRecommendationCatalog`는 Recommendation Read API의 `RecommendationSetSource`와 Controller
Decision API의 `RecommendationSetLookup`을 동시에 구현한다.

- `publish`: ID를 덮어쓰지 않고 새 불변 Recommendation Set을 현재 결과로 지정
- `get_current_recommendation`: Presentation Read API용 최신 Set 조회
- `get_recommendation_set`: Controller Decision의 Source Identity 조회
- `reset`: 프로세스 한정 상태 제거

Set 생성 UTC는 현재 Set보다 이를 수 없다. 잘못된 입력, 중복 ID 또는 시간 역행은 Catalog를 변경하지
않는다. 이 Catalog는 Persistence가 아니며 프로세스 종료 후 복구되지 않는다.

## 4. Human-in-the-loop 경계

Runtime 조립은 `ACCEPT` Candidate를 Aircraft Runtime에 적용하지 않는다. Controller Decision Service와
HTTP Adapter는 Audit 상태만 소유하며, 실제 명령 적용기는 아직 Composition에 포함하지 않는다.
`MODIFY` 역시 재검증 전 적용되지 않는다.

## 5. Phase 12-B Deterministic Golden Demo Step

`GoldenDemoStepOrchestrator.step(advance_steps)`은 Clock이 `RUNNING`일 때 다음 순서로 한 번의 불변
`GoldenDemoStepResult`를 만든다.

1. 명시한 Tick만큼 Clock 진행 후 Traffic Snapshot 수집 (`0`이면 현재 T+0 평가)
2. 새로 due가 된 Scenario Event Poll
3. 현재 5초 Slot이 due이면 Prediction 및 Conflict Run 실행
4. 새 Conflict Run의 전체 Pair에 대해 Conflict Risk 평가
5. 모든 활성 Aircraft에 대해 Scenario Event 기반 Operational Priority 평가
6. Risk/Priority 결과로 Exception Queue Snapshot 갱신

Step ID는 `GOLDEN-STEP-<tick_count 12자리>`이며 같은 Tick에 두 번째 Step을 허용하지 않는다. 5초
Scheduler Slot이 아닌 Step에서도 Priority와 Queue는 갱신하지만 Prediction/Conflict/Risk 출력은 비어
있다.

Clock Reset을 감지하면 Orchestrator의 결과와 process-local Queue, Recommendation Catalog 및 Controller
Decision Audit 상태를 지운다. 다시 같은 Step 순서를 실행하면 동일 결과를 만든다. 영속 Audit 삭제를
의미하지 않으며 현재 Composition에는 영속 Runtime Audit 저장소가 없다.

## 6. Human-in-the-loop 보존

Step은 Resolution Candidate, Recommendation 또는 Controller Decision을 만들지 않는다. 특히 T+60
Conflict/Exception이 계산되어도 Aircraft Runtime은 Scenario Truth 외에 변경되지 않는다.

## 7. Phase 12-C Deterministic Golden Demo Resolution Step

`GoldenDemoResolutionOrchestrator.resolve()`는 최신 Step이 정확히 T+75이고 현재 Clock과 일치할 때만
다음 순서로 실행한다.

1. 활성 `CIV-A02 / MIL-F01` HIGH/CRITICAL Conflict Exception 하나 선택
2. Pair의 현재 State와 source-labelled Performance Profile로 Candidate A~E 생성
3. Candidate별 복제 State에 기동을 적용하고 8대 전체 Traffic으로 격리 Safety Validation
4. SAFE Action만 결정론적으로 Ranking
5. 완성된 Recommendation Set을 process-local Catalog에 Publish

Golden Calibration 결과는 `CAND-A`만 SAFE이며, `CAND-B`는 `MIL-F02`와 2차 Conflict를 만들어
UNSAFE, `CAND-C`는 INEFFECTIVE, `CAND-D`는 Rule 위반으로 UNSAFE, `CAND-E`는 충돌이 남는
NO_ACTION 기준선이다. 결과는 Source Step, Exception, Candidate Batch, Validation Run과 Recommendation
Set Identity를 모두 보존한다.

Runtime 계산은 T+75에서 원자적으로 완료되며 데모 UI가 Candidate, Validation, Recommendation을
T+75/T+80/T+85에 단계적으로 공개하는 Presentation Timeline과는 구분된다. Resolve는 Controller
Decision을 만들거나 Aircraft Runtime을 변경하지 않는다. 같은 Tick의 중복 실행을 거부하고 Clock
Reset 후 같은 입력을 재생하면 동일한 결과를 만든다.

PoC Performance Profile은 SQLAlchemy가 필요 없는 `sentry_atm.reference_data`에 정의하고 SQLite Seed와
Runtime이 같은 불변 객체를 사용한다.

## 8. Phase 12-D Deterministic Golden Demo Controller Decision Step

`GoldenDemoControllerDecisionOrchestrator.accept()`는 T+75 Resolution이 존재하고 최신 Step과 Clock이
정확히 T+90일 때만 실행한다. Catalog의 현재 Recommendation Set이 Resolution Source와 같은 객체인지
확인하고, Primary `CAND-A`를 `RKTU-DEMO-CONTROLLER` Position의 `ACCEPT`로 Decision Service에
기록한다.

`GoldenDemoControllerDecisionResult`는 T+90 Step, T+75 Resolution, 선택 Recommendation,
Decision Entry 및 Audit Log Revision을 함께 보존한다. 같은 Tick의 중복 Decision을 거부하고 Clock
Reset 시 process-local Audit과 Orchestrator 결과를 비운 뒤 같은 순서를 동일하게 재생한다.

`ACCEPT` Entry의 `authorizes_application=true`는 후속 기동 적용 허가를 의미한다. 이 Step은 Candidate의
9,000 ft 기동을 Aircraft Runtime에 적용하거나 Prediction/Conflict를 재계산하지 않는다. 따라서 감사
기록 직전과 직후의 T+90 Traffic Snapshot은 동일하다.

## 9. 다음 단계

Phase 12-E는 감사된 `ACCEPT`만 입력으로 받아 승인된 `CAND-A` 기동을 명시적으로 적용하고, 새 Actual
State와 Predicted 4DT, 전체 Traffic Conflict를 다시 계산해 최초 Conflict 해소 증거를 남긴다.
