# Golden Demo Web UI

## 1. 범위

Phase 14-A는 Golden Demo backend를 심사·설명할 수 있는 최소 Dashboard Shell을 제공한다. 별도 Node.js,
Frontend Framework 또는 CDN 없이 Python Package에 포함된 HTML/CSS/JavaScript를 같은 Local Server에서
제공한다.

## 2. Route와 자산

| Route | Content-Type | 역할 |
|---|---|---|
| `/`, `/index.html` | `text/html; charset=utf-8` | Dashboard Shell |
| `/assets/app.css` | `text/css; charset=utf-8` | Layout, Radar, Responsive Theme |
| `/assets/app.js` | `text/javascript; charset=utf-8` | Session GET과 View 투영 |

`GoldenDemoWebWsgiApp`은 위 Route만 직접 처리하고 모든 `/api/...` 및 알 수 없는 Route를 기존
`GoldenDemoSessionWsgiApp`에 위임한다. 따라서 UI를 추가해도 Session Command/API 계약은 변하지 않는다.

## 3. 화면 구성

- RKTU Terminal Area와 UTC Simulation 상태 Header
- Traffic, Active Exception, 경과시간과 Human-in-the-loop 상태 Metric
- RKTU ARP Local x/y NM 기반 Tactical View
- 8대 Aircraft State Table
- Exception Queue와 Decision Support Empty State
- READY부터 CONFLICT_RESOLVED까지 Deterministic Timeline
- Session ID와 비운영 PoC 고지

Phase 14-A의 JavaScript는 `GET /api/v1/golden-demo/session`으로 초기 상태를 읽는다. Aircraft Marker와
표를 DOM API와 `textContent`로 생성하며 API 문자열을 HTML로 삽입하지 않는다.

Phase 14-B는 Session Stage를 backend의 고정 Command와 일대일로 연결한다.

| 현재 Stage | Primary Command |
|---|---|
| `READY` | `START` |
| `MONITORING` | `ADVANCE_TO_CONFLICT` |
| `CONFLICT_DETECTED` | `GENERATE_RECOMMENDATION` |
| `RECOMMENDATION_AVAILABLE` | Decision Card의 `ACCEPT`, `MODIFY`, `REJECT` |
| `DECISION_ACCEPTED` | `APPLY_APPROVED_MANEUVER` |
| `DECISION_MODIFIED` | `REVALIDATE_MODIFIED_MANEUVER` |
| `MODIFICATION_REVALIDATED` | `RESET` |
| `DECISION_REJECTED` | `RESET` |
| `CONFLICT_RESOLVED` | `RESET` |

요청 중에는 새로고침·Primary·Reset Control을 모두 잠근다. 성공 응답은 Traffic, Queue,
Recommendation, Decision과 Revalidation Panel 전체에 즉시 투영한다. 409 응답 시 최신 Session을 다시
조회해 화면과 backend를 동기화한다.

Phase 14-C는 backend가 계산한 `primary_conflict` 증거를 설명 가능성 영역에 투영한다. 화면에서
충돌쌍, CPA/TCPA, 수평·수직 분리값과 PoC 기준 대비 비율, Risk Score/Level, Rule/Policy Profile과
Reason Code를 함께 제시한다. Tactical View에서는 해당 두 항공기를 붉은 Marker와 연결선으로 강조한다.

추천 생성 전에는 적용 후 결과를 `NOT YET VALIDATED`로 명시한다. 추천 생성 후에는 Safety Validator가
검증한 Primary Candidate 결과를, 승인 기동 적용 후에는 Post-action Revalidation 결과를 원래 충돌
증거와 나란히 표시한다. 따라서 후보 검증을 실제 적용 결과처럼 표현하지 않으며, Human-in-the-loop
경계를 유지한다.

Phase 15-A는 T+60 이후 Planned-vs-Actual Entry Conformance Panel을 표시한다. 예상 Entry Point,
고도·침로와 실제 값, 수평·수직·시간 편차를 같이 보여 편차가 미래 충돌로 이어지는 흐름을 설명한다.
Resolution 이후에는 CAND-A~E 전체를 한 표에 표시하며 다음 결과를 구분한다.

- `CAND-A`: 원 충돌 해소, `SAFE`, 추천 후보
- `CAND-B`: 원 충돌은 해소하지만 `MIL-F02`와 2차 충돌, `UNSAFE`
- `CAND-C`: 원 충돌 미해소, `INEFFECTIVE`
- `CAND-D`: 원 충돌 미해소 및 최저고도 Rule 위반, `UNSAFE`
- `CAND-E`: No-action 원 충돌 지속, `UNSAFE`

표는 Safety Validator의 결과를 표시할 뿐 후보를 선택하거나 Runtime에 적용하지 않는다.

Phase 15-B는 Recommendation 단계의 Decision Support Card에 `ACCEPT`, `MODIFY`, `REJECT`를 함께
노출한다. `MODIFY` Form은 Maneuver Type과 프로젝트 내부 단위의 목표값, Rationale을 받고 `REJECT`는
Rationale만 받는다. Browser 기본 Form 검증과 backend 고정 Schema/Domain 검증을 모두 통과해야 Audit이
기록된다. 완료 후에는 Decision Type, 변경 기동 또는 적용 불가 상태, Rationale을 같은 Card에서 보여준다.

`ACCEPT`만 다음 `APPLY_APPROVED_MANEUVER`를 허용한다. `MODIFY`는 먼저 `REVALIDATION REQUIRED`로
표시하고 격리 검증 Command만 제공한다. 검증 뒤에는 판정, CPA, 2차 충돌·성능·Rule 증거와
`SAFE · NOT YET APPLIED` 또는 `BLOCKED` Gate를 표시한다. `REJECT`는 `NO MANEUVER AUTHORIZED`로
표시하고 새 Run 외의 실행 Control을 제공하지 않는다.

## 4. 보안·접근성 경계

- `default-src 'self'` 기반 Content Security Policy
- `nosniff`, `no-referrer`, `no-store` Header
- 외부 Font, Script, Image 및 Analytics 없음
- 한국어 문서 언어, Skip Link, Landmark, Table Header, 상태 `aria-live`
- 작은 화면 대응과 `prefers-reduced-motion` 지원

## 5. 현재 제한사항

- 지도는 실제 항법 Chart가 아닌 RKTU ARP 중심 PoC Local Coordinate View다.
- 안전성 검증 결과가 SAFE인 Golden Demo Primary Recommendation만 Decision 대상으로 사용한다.
- SAFE로 격리 재검증된 수정 기동의 재승인·실제 적용은 후속 Phase 범위다.
- UI는 Process-local 단일 Session만 읽고 Browser 상태를 영속화하지 않는다.

## 6. 다음 단계

Phase 14-D는 `python -m sentry_atm.infrastructure.http --check` 명령으로 임시 loopback Server에서 UI
자산과 전체 Session Command 흐름을 검증한다. 실제 브라우저의 반응형 Layout과 화면 배율은
[`demo_runbook.md`](demo_runbook.md)의 발표 전 육안 점검표로 확인한다. 별도 Browser Automation
Dependency는 Runtime에 추가하지 않는다.
