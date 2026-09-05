# Animated Golden Demo Contract

> **범위 안내 — 이 문서는 골든 데모(`--scenario golden`)를 설명한다.**
> 골든 데모는 값을 못박아 둔 **회귀 고정물**이고 `--check` 가 검사하는 대상이라,
> 여기 적힌 수치(8대, T+70 충돌 …)는 그대로 유지된다. 발표에서 실제로 돌리는 것은
> 기본값인 **출격 시나리오(`--scenario sortie`, 15대 75분 13단계)** 이며, 그쪽
> 진행은 [`demo_runbook.md`](demo_runbook.md)에 있다.


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

- Phase 17-A: Playback Contract와 Storyboard — 구현 완료
- Phase 17-B: 결정론적 1초 Aircraft Frame 생성 및 Read API — 구현 완료
- Phase 17-C: Radar Marker/Trail의 연속 브라우저 애니메이션 — 구현 완료
- Phase 17-D: PLAY/PAUSE, 배속, Timeline, 자동 일시정지 제어 — 구현 완료

Phase 17-C에서 Radar 애니메이션이 연결되었고 Phase 17-D에서 전체 조작 계약이 완성되었다.

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

## 8. Radar Marker와 Trail 렌더링

Phase 17-C는 Playback API를 화면 최초 진입 시 한 번 조회하고 `requestAnimationFrame`으로 인접한
1초 Frame 사이의 위치·고도·속도·침로를 선형 보간한다. 침로는 0/360도 경계를 최단 방향으로
보간하며, 충돌·Risk·추천 판단은 브라우저에서 다시 계산하지 않는다.

각 항공기 Marker DOM과 SVG Polyline은 최초 한 번 생성한 뒤 위치와 최근 30초 좌표만 갱신한다.
따라서 매 Render마다 Marker 전체를 다시 만드는 깜빡임을 피하고, Civil/Military/Conflict 색상도
기존 관제 화면 규칙과 동일하게 유지한다. `READY`에서는 T+0 Frame을 표시하고 `START` 후에는 계약의
기본 속도로 연속 재생한다. Checkpoint 명령으로 단계가 바뀌면 해당 Session 시각에 맞춰 즉시
동기화한다. PLAY/PAUSE·배속·Timeline·Cue 자동 정지는 Phase 17-D에서 제공한다.

## 9. Playback Control과 Cue 자동 정지

Phase 17-D는 API 계약의 `duration_seconds`, `default_rate`, `supported_rates`, `cues`를 그대로 읽어
PLAY/PAUSE, 1x·2x·4x 배속, T+0~T+300 Scrubber와 Cue Marker를 구성한다. Scrubber 또는 Cue Marker를
선택하면 실제 Session Runtime은 변경하지 않고 Radar Frame만 미리 보며, 다음 Session 명령 결과가
도착하면 권위 있는 Session 시각으로 다시 동기화한다.

재생이 `auto_pause=true` Cue를 통과하면 반드시 Cue의 정확한 시각을 먼저 렌더링한 후 정지한다.
T+70과 T+75는 각각 기존 `ADVANCE_TO_CONFLICT`, `GENERATE_RECOMMENDATION` 명령과 자동 연결되어
화면의 Conflict/Recommendation Evidence도 같은 시각으로 갱신된다. T+75의 관제사 결정 지점에서는
Accept/Modify/Reject가 완료되기 전 PLAY를 비활성화한다. T+240과 T+260은 현재 Playback Frame과
Cue 설명을 정확히 정지해 보여주며, 후속 비상운영 Domain 단계에서 전용 관제사 흐름과 연결한다.
