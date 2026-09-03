# Animated Golden Demo Contract

## 1. 목표

Phase 17-A는 기존 Checkpoint Dashboard를 T+0부터 T+300까지 연속 재생되는 관제 콘솔로 확장하기
위한 시간축과 상호작용 계약을 정의한다. 이 단계는 계약과 Storyboard만 고정하며 실제 Frame API와
브라우저 애니메이션은 Phase 17-B~D에서 구현한다.

## 2. 설계 원칙

- Python Simulation Engine이 항공기 위치와 모든 판단 결과의 유일한 기준이다.
- Frame은 Simulation의 1초 상태를 사용하고 브라우저는 두 Frame 사이의 화면 위치만 보간한다.
- 브라우저는 충돌, Risk, Priority 또는 후보 안전성을 독립적으로 계산하지 않는다.
- 화면은 최대 60 FPS로 렌더링하고 시나리오는 `1x`, `2x`, `4x`로 재생할 수 있다.
- Pause나 재생속도 변경은 Simulation 결과를 바꾸지 않는다.
- 관제사 결정이 필요한 지점에서는 반드시 자동으로 일시정지한다.
- 승인되지 않은 추천이나 수정 기동은 이후 Frame에 반영하지 않는다.

## 3. Storyboard

| 시각 | Cue | 화면 동작 | 자동 정지 | 관제사 입력 |
|---:|---|---|:---:|:---:|
| T+0 | `PLAYBACK_STARTED` | 8대 Traffic 감시 및 연속 이동 시작 | 아니요 | 없음 |
| T+60 | `ENTRY_DEVIATION` | `MIL-F01` 진입 편차 경고와 계획/실제 편차 표시 | 아니요 | 없음 |
| T+70 | `CONFLICT_DETECTED` | `CIV-A02 / MIL-F01` 강조, CPA/TCPA와 연결선 표시 | 예 | 없음 |
| T+75 | `RECOMMENDATION_AVAILABLE` | CAND-A~E 비교와 추천 근거 표시 | 예 | ACCEPT/MODIFY/REJECT |
| T+90 | `POST_ACTION_REVALIDATION` | 승인 기동 적용 결과와 충돌 해소 증거 표시 | 예 | 없음 |
| T+240 | `EMERGENCY_DECLARED` | `MIL-T01` 비상 선언과 Exception Queue 최상위 이동 | 예 | 비상 복귀안 결정 |
| T+260 | `RECOVERY_COMPLETE` | 안전 복귀, 정상 순서 및 미해결 HIGH/CRITICAL 없음 | 예 | 없음 |

T+260 이후에는 T+300까지 안정화된 Traffic을 재생하고 시나리오 완료 상태를 유지한다.

## 4. 재생 계약

`build_golden_demo_playback_contract()`가 다음 값을 단일 기준으로 제공한다.

| 항목 | 값 |
|---|---:|
| 전체 길이 | 300초 |
| Simulation Frame 간격 | 1초 |
| 목표 화면 Render | 60 FPS |
| 기본 배속 | 1x |
| 지원 배속 | 1x, 2x, 4x |
| 자동 정지 | T+70, 75, 90, 240, 260 |

모든 Cue는 Stable ID, 타입, 경과시각, 화면 Label, 자동 정지 여부와 관제사 입력 필요 여부를
JSON-ready 구조로 제공한다.

## 5. 화면 구성

- 상단: Scenario 시각, UTC/KST, PLAY/PAUSE, 배속, RESET
- 중앙 Radar: 항공기 Marker, Callsign, Trail, 계획/실제/예측 항적
- 하단 Timeline: T+0~T+300 진행 상태와 Cue Marker
- 우측 Evidence: Conflict, Risk, Priority, Candidate, Decision, Revalidation
- 주요 Cue: 화면 강조와 설명용 자동 일시정지

## 6. Phase 경계

- Phase 17-A: Playback Contract와 Storyboard — 현재 단계
- Phase 17-B: 결정론적 1초 Aircraft Frame 생성 및 Read API — 구현 완료
- Phase 17-C: Radar Marker/Trail의 연속 브라우저 애니메이션
- Phase 17-D: PLAY/PAUSE, 배속, Timeline, 자동 일시정지 제어

Phase 17-A 완료만으로 현재 Dashboard가 움직이지는 않는다. 애니메이션이 사용자에게 보이는 완료
시점은 Phase 17-C이며 전체 조작 계약 완료 시점은 Phase 17-D다.

## 7. Playback Read API

Phase 17-B는 활성 Session과 분리된 Simulation 복사본에서 T+0부터 T+300까지 양 끝을 포함한
301개 Frame을 생성한다. 각 Frame은 순서 인덱스, 경과시간, UTC 시각, Cue ID와 8대 항공기의
위치·고도·속도·침로·비행단계·비상 상태를 포함한다.

```http
GET /api/v1/golden-demo/playback
```

응답은 `contract`, `frame_count`, `aircraft_count`, `frames`를 포함하며 동일 프로세스에서는 생성된
불변 Read Model을 재사용한다. Playback 조회는 활성 Session의 Clock, Traffic, Decision 또는 Audit을
변경하지 않는다. 브라우저는 Phase 17-C에서 이 1초 Frame 사이의 화면 좌표만 보간한다.
