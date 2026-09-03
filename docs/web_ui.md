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

JavaScript는 `GET /api/v1/golden-demo/session`만 호출한다. Aircraft Marker와 표를 DOM API와
`textContent`로 생성하며 API 문자열을 HTML로 삽입하지 않는다. 새로고침 버튼도 같은 Read API만 다시
호출한다.

## 4. 보안·접근성 경계

- `default-src 'self'` 기반 Content Security Policy
- `nosniff`, `no-referrer`, `no-store` Header
- 외부 Font, Script, Image 및 Analytics 없음
- 한국어 문서 언어, Skip Link, Landmark, Table Header, 상태 `aria-live`
- 작은 화면 대응과 `prefers-reduced-motion` 지원

## 5. 현재 제한사항

- 지도는 실제 항법 Chart가 아닌 RKTU ARP 중심 PoC Local Coordinate View다.
- Command Button, 단계 진행, 추천 상세와 승인 Control은 아직 연결하지 않는다.
- UI는 Process-local 단일 Session만 읽고 Browser 상태를 영속화하지 않는다.

## 6. 다음 단계

Phase 14-B는 backend가 허용한 다음 고정 Command만 활성화하고, 요청 중 중복 입력 방지·409 오류 표시·
단계별 Exception/Recommendation/Decision Panel 갱신을 구현한다.
