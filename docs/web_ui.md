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
| `RECOMMENDATION_AVAILABLE` | `ACCEPT_RECOMMENDATION` |
| `DECISION_ACCEPTED` | `APPLY_APPROVED_MANEUVER` |
| `CONFLICT_RESOLVED` | `RESET` |

요청 중에는 새로고침·Primary·Reset Control을 모두 잠근다. 성공 응답은 Traffic, Queue,
Recommendation, Decision과 Revalidation Panel 전체에 즉시 투영한다. 409 응답 시 최신 Session을 다시
조회해 화면과 backend를 동기화한다.

## 4. 보안·접근성 경계

- `default-src 'self'` 기반 Content Security Policy
- `nosniff`, `no-referrer`, `no-store` Header
- 외부 Font, Script, Image 및 Analytics 없음
- 한국어 문서 언어, Skip Link, Landmark, Table Header, 상태 `aria-live`
- 작은 화면 대응과 `prefers-reduced-motion` 지원

## 5. 현재 제한사항

- 지도는 실제 항법 Chart가 아닌 RKTU ARP 중심 PoC Local Coordinate View다.
- Modify/Reject 및 Recommendation 선택 UI는 아직 제공하지 않는다. Golden Demo Primary 후보의 고정
  Accept 흐름만 사용한다.
- UI는 Process-local 단일 Session만 읽고 Browser 상태를 영속화하지 않는다.

## 6. 다음 단계

다음 단계는 Golden Demo 전 구간의 화면 전환을 재검증하고 Conflict Risk, 추천 근거, 적용 전후 결과를
심사자가 더 빠르게 비교할 수 있도록 설명 가능성 시각화를 보강한다.
