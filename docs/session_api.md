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
- 적용 전후 고도, Post-apply Prediction/Conflict Run과 원 Conflict의 SAFE/LOW/RESOLVED 요약

모든 중첩 객체는 기존 Queue, Recommendation 및 Decision Read Model을 재사용한다. `to_dict()`는 tuple,
Enum과 중첩 DTO를 list/string/dict 등 JSON Primitive로 변환한다.

## 4. Reset

Clock Reset 후 Orchestrator Chain의 파생 결과와 승인 Anchor가 제거되면 API는 새 Run 번호의 `READY`
Session을 반환한다. Traffic은 Golden Scenario 초기 8대 상태이고 Queue, Recommendation, Decision과
Revalidation은 비어 있다.

## 5. 현재 제한사항

- Phase 13-A에는 실행 Command와 HTTP Adapter가 없다.
- Session ID와 결과는 프로세스 재시작 후 복구되지 않는다.
- Authentication, authorization, streaming과 다중 동시 Session을 제공하지 않는다.
- Trajectory Point 전체와 Candidate A~E 전체 검증표는 아직 Session 요약에 포함하지 않는다.

## 6. 다음 단계

Phase 13-B는 허용된 Golden Demo Checkpoint만 순서대로 실행하는 Session Command Service를 추가한다.
Read API와 Command를 분리하고 임의 Tick, 중복 승인 또는 승인 전 적용을 허용하지 않는다.
