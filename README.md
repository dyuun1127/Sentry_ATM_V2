# SENTRY ATM

SENTRY는 청주공항(RKTU) 중심 Terminal Simulation Area에서 미래 4DT를 예측하고, 미래 충돌과 비상 우선순위를 평가해 관제사에게 설명 가능한 대응 후보를 제공하는 Human-in-the-loop 항공교통 의사결정 지원 PoC다.

> 이 프로젝트는 실제 관제 시스템이 아니며, 실제 공역 책임·공식 분리기준·군 운용절차를 대체하지 않는다.

## 이 저장소에 대하여

이 저장소는 `sentry-atm` PoC 위에 **규정 엔진(`sentry_atm.regulation`)** 을 얹은 갈래다.
원본 PoC 는 분리기준·기종 제원을 명시적으로 라벨링된 가정값(`SIMULATION_ASSUMPTION`,
수평 5NM)으로 두고 구조를 먼저 세웠다. 이 갈래는 그 자리에 「항공교통관제절차」
(국토교통부고시 제2022-534호) 조항과 AIP RKTU 전사값을 넣는다.

| 계층 | 원본 PoC | 이 저장소 |
|---|---|---|
| 수평 분리 | 5 NM (`POC_TERMINAL_V1`) | **3 NM (고시 5-5-4 가) — 현재 기본값** |
| 기종 | 합성 3종 (`SYN-AIRLINER` 등) | **전사 16종, 후류등급을 도메인 개념으로 보유** |
| 활주로 | 도메인 개념 없음 | 출발·도착 자원 경합 (고시 3-9-6 / 3-10-3) |
| 체공 | 없음 | AIP 공고 장주 (고시 4-6-1 ~ 4-6-7) |
| 관할 이양 | 없음 | TWR → GCA → 상위섹터 → ACC (고시 2-1-15) |
| 좌표계 | 평균 반지름 구면 | WGS84 타원체 곡률반경 (쌍 거리 오차 22m → 1.9m) |

분리 판정의 기본값은 `sentry_atm.regulation.policy.active_separation_profile()` 이
정한다. 탐지기·위험평가기·세션 읽기모델이 모두 이 한 곳을 따르며, 다른 기준이
필요하면 여전히 생성자로 주입할 수 있다. 자세한 것은
[규정 엔진](docs/regulation.md).

`sentry_atm.regulation` 의 **결정론 판정 경로는 외부 의존성이 없다.** 학습(`predict`,
`mbe`)과 해석적 확률(`resolution`) 계층만 numpy·scipy·scikit-learn·torch 를 쓰며 그
임포트는 전부 함수 안에 있으므로, 본체의 "의존성 0개" 성질이 유지된다. 학습 계층이
필요하면 `pip install -e ".[learning]"` 로 설치한다.

## 현재 릴리스 상태

- 규정 계층 통합 및 `main` 반영 완료
- 전체 자동 테스트 `1506 passed`, Ruff 통과
- Golden Demo Release Preflight `5/5` 통과
- 실제 Loopback HTTP Multi-Path Regression `10/10` 통과
- 인터넷, Docker, PostgreSQL/PostGIS, Node.js 없이 로컬 실행 가능

## 두 개의 시나리오

`--scenario` 로 고른다. **기본값은 출격 시나리오(`sortie`)** 다.

| | `sortie` (기본) | `golden` |
|---|---|---|
| 항공기 | 15대, 동시 최대 5대 | 8대 |
| 길이 | 75분, 13단계 | 5분 |
| 내용 | 출격 → 비상복귀 → 우선착륙이 민항 도착 흐름과 같은 활주로·공역을 다툰다 | 단일 충돌 한 건의 판단 연쇄 |
| 쓰임 | **발표용** | **회귀 고정물** — `--check` 가 검사하는 대상 |

`golden` 은 값을 못박아 둔 계약이라 문서의 수치(8대, 28쌍, T+70 충돌 …)가 그대로
유지된다. `docs/` 아래 골든 데모 계약 문서들은 전부 이쪽을 설명한다.

## 두 개의 화면

발표는 화면 두 개를 나란히 띄워 진행한다. 서버는 하나다.

| 화면 | 주소 | 보는 사람 | 하는 일 |
|---|---|---|---|
| **관제 콘솔** | `http://127.0.0.1:8000/` | 관제사 (발표자) | 스코프·예외 큐·근거를 보고 **판단한다** |
| **시연 진행 화면** | `http://127.0.0.1:8000/scenario` | 청중 (빔프로젝터) | 단계와 근거 조항을 보여주고 **시계를 쥔다** |

관제 콘솔에는 재생 단추도 단계 바도 없다 — 실제 관제석에 없는 것은 두지 않는다.
시각을 움직이는 것은 시연 화면뿐이고, 관제사의 판단이 필요한 단계에서 스스로
멈춘다. 자세한 것은 [웹 UI](docs/web_ui.md)와 [발표 Runbook](docs/demo_runbook.md).

## 핵심 기능

1. RKTU ARP 기준 위경도와 Local x/y NM 좌표를 상호 변환한다 (WGS84 곡률반경).
2. UTC 결정론적 Clock에서 Playback 및 Synthetic 항공기를 재현한다.
3. 미래 4DT와 연속 상대운동 CPA/TCPA를 계산해 충돌을 탐지한다.
4. 고시 조항과 그에 붙은 조건까지 판정해 분리 최저치를 정한다.
5. 충돌 위험도와 작전 우선순위를 분리해 예외 Queue를 구성한다.
6. 대응 후보 생성, 격리 안전성 검증, 설명 가능한 추천 순위를 제공한다.
7. 관제사의 `ACCEPT`, `MODIFY`, `REJECT` 결정을 Audit하고 승인된 기동만 적용한다.
8. 적용 후 동일한 계산 경로로 충돌 해소 여부를 재검증한다.
9. 관제 콘솔과 시연 화면 두 화면에 계획·실제·예측 항적과 판단 근거를 시각화한다.

## 핵심 문서

**먼저 읽을 것**

- [발표 실행 Runbook](docs/demo_runbook.md) — 두 화면 띄우기, 13단계 진행, 실패 복구
- [규정 엔진](docs/regulation.md) — 고시·AIP를 코드로 옮긴 계층
- [PoC Assumption Register](docs/assumptions.md) — 공식 근거가 없는 값 전부

**계약 문서**

- [Golden Demo Scenario Contract](docs/scenarios.md)
- [Domain Data Model](docs/data_model.md)
- [RKTU Local Coordinate System](docs/coordinate_system.md)
- [Deterministic Simulation Clock](docs/simulation.md)
- [SQLite Persistence Contract](docs/persistence.md)
- [Baseline Trajectory Predictor](docs/prediction.md)
- [Predictive Conflict Contract](docs/conflict.md)
- [Risk and Operational Priority Contract](docs/risk_priority.md)
- [Deterministic Exception Queue Contract](docs/exception_queue.md)
- [Resolution Candidate Contract](docs/resolution.md)
- [Resolution Recommendation Contract](docs/recommendation.md)
- [Controller Decision Audit Contract](docs/controller_decision.md)
- [Golden Demo Runtime Composition](docs/runtime_composition.md)
- [Golden Demo Session Read API](docs/session_api.md)
- [Web UI](docs/web_ui.md)
- [Animated Golden Demo Contract](docs/animated_demo.md)

**운영**

- [Golden Demo Release Readiness](docs/release_readiness.md)
- [Final Release & Main Merge Checklist](docs/final_release.md)
- [명령줄 도구](tools/README.md)

## 요구 환경

- Python 3.12 이상
- Git
- Windows PowerShell 또는 호환 셸

## 개발환경 구성

프로젝트 루트에서 다음 명령을 실행한다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev,persistence]"
```

## 빠른 실행

별도 Web Framework 없이 Python 표준 라이브러리 서버를 로컬 Loopback에 실행한다.

발표 전 전체 Golden Demo 계약을 먼저 자동 점검한다. 다음 두 성공 문구와 종료 코드 `0`을 확인한다.

```powershell
.\.venv\Scripts\python.exe -m sentry_atm.infrastructure.http --check
```

```text
SENTRY ATM RELEASE PREFLIGHT PASSED (5 checks)
SENTRY ATM DEMO CHECK PASSED (10 checkpoints)
```

점검이 통과하면 서버를 시작한다.

```powershell
.\.venv\Scripts\python.exe -m sentry_atm.infrastructure.http
```

브라우저에서 `http://127.0.0.1:8000` (관제 콘솔)과 `http://127.0.0.1:8000/scenario`
(시연 진행 화면)를 각각 연다. 다른 Port가 필요하면 `--port 8123`, 골든 데모를 보려면
`--scenario golden` 을 준다. 종료는 `Ctrl+C`다. 외부 장치에서 접속할 수 있도록
Bind하는 기능은 제공하지 않는다.

> **정적 자산은 서버가 메모리에 물고 있다.** `app.css`·`app.js` 를 고쳤으면 새로고침이
> 아니라 **서버를 다시 띄워야** 반영된다.

### 밖에서 보게 하기

기본은 루프백 전용이라 이 기계에서만 열린다. `--host` 로 **명시했을 때만** 밖으로
열린다.

```powershell
.\.venv\Scripts\python.exe -m sentry_atm.infrastructure.http --host 0.0.0.0
```

열리는 순간 **밖에서 온 요청은 읽기만 된다.** 발표자는 자기 노트북에서
`http://127.0.0.1:8000` 으로 직접 열어 조작하고, 밖에서 본 사람은 같은 화면을
보되 단추가 없다 (「관람 모드」 배지가 뜬다).

| | 조작 | 보기 |
|---|---|---|
| 이 기계의 `127.0.0.1` | O | O |
| 다른 기계 · 터널 경유 | **X** (`403 VIEWER_ONLY`) | O |

팀원이 원격에서 직접 몰아야 하면 `--control any` 로 그 울타리를 걷을 수 있다.
기본으로 두지 않는다 — 주소가 새면 시연을 남이 바꾼다.

> **이것은 인증이 아니다.** 세션이 하나이고 로그인이 없다. 발표 중 우연한 조작을
> 막는 울타리이며, 공개 인터넷에 두어도 되는 근거가 아니다. 까닭과 한계는
> [`ASM-045`](docs/assumptions.md)에 있다.

### 출격 시나리오 13단계

| 막 | 단계 | 이 막이 말하는 것 |
|---|---|---|
| 1. 평시 | 1–2 | 민항과 군이 같은 활주로를 나눠 쓴다 |
| 2. 출격 | 3–6 | 출격 비용은 도착 흐름에서 치러진다 |
| 3. 비상복귀 | 7–10 | 판단이 필요한 것만 근거와 함께 상신한다 |
| 4. 우선착륙 | 11–13 | 순번이 아니라 물리적 최단 도달시각 |

각 단계의 근거 조항과 판단 지점은 시연 진행 화면이 함께 보여준다. 9단계에서
화면이 스스로 멈추고 관제사의 판단을 기다린다.

### 골든 데모 흐름 (`--scenario golden`)

| 단계 | 화면과 시스템 동작 |
|---|---|
| 감시 시작 | T+0, 8대 Traffic을 동일한 초기 상태로 재현 |
| 충돌 시점 진행 | T+70, `CIV-A02 / MIL-F01` 미래 충돌과 HIGH 위험 표시 |
| 대응 후보 생성 | T+75, CAND-A~E의 적용 전 안전성 비교와 추천 생성 |
| 관제사 결정 | T+90, ACCEPT/MODIFY/REJECT와 판단 근거 Audit |
| 승인 기동 적용 | 승인된 기동만 Runtime에 반영하고 CPA·위험도 재검증 |
| Run Reset | 파생 상태를 제거하고 깨끗한 `READY` Session 재생성 |

## 로컬 SQLite DB 초기화

별도 서버, 계정 또는 Docker 없이 프로젝트 루트에서 실행한다. **데모 실행에는 필요하지
않다** — 세션은 메모리 안에서 돌고, 이 DB는 참조자료 영속화 계약을 보이기 위한 것이다.

```powershell
.\.venv\Scripts\python.exe -m sentry_atm.infrastructure.persistence init
```

기본 DB 파일은 `data/sentry_atm.db`에 생성되며 Git에는 업로드되지 않는다. 다른 위치가 필요하면
`--path`를 지정한다.

```powershell
.\.venv\Scripts\python.exe -m sentry_atm.infrastructure.persistence init --path tmp/demo.db
```

Aircraft Type 15종과 Performance Profile 3종을 추가하려면 실행한다. 기존에 같은 ID가
있으면 덮어쓰지 않는다.

```powershell
.\.venv\Scripts\python.exe -m sentry_atm.infrastructure.persistence seed
```

## 명령줄 도구

`tools/` 에 규정 엔진을 다루는 도구가 있다. 서버나 웹 UI 없이 단독으로 돈다 —
AIP 정합성 검증, 예측기·예외 스코어러 학습과 평가, 시퀀싱 시연, 시나리오 내보내기.
자세한 것은 [tools/README.md](tools/README.md).

```powershell
.\.venv\Scripts\python.exe tools/validate_aip.py       # AIP 전사값 67건 대조
.\.venv\Scripts\python.exe tools/train_predictor.py    # 물리 + 잔차 LSTM 학습
.\.venv\Scripts\python.exe tools/train_mbe.py          # 예외 스코어러 학습
```

학습·평가 도구는 `pip install -e ".[learning]"` 이 필요하다.

## 테스트 및 정적 검사

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
```

현재 기준 결과는 Ruff 통과, `1506 passed`다. 발표 전 점검과 병합 절차는
[Golden Demo Release Readiness](docs/release_readiness.md)와
[Final Release & Main Merge Checklist](docs/final_release.md)를 따른다.

> `%TEMP%` 가 쓰기 불가한 경로로 잡혀 있으면 pytest 가 임시 폴더를 만들지 못해
> `PermissionError` 로 무더기 오류가 난다. 그럴 때는 `--basetemp` 를 준다.

## 현재 프로젝트 구조

```text
.
├─ artifacts/                  # 내보낸 시나리오 JSON
├─ docs/                       # 계약·가정·Runbook
├─ models/                     # 학습 산출물 (predictor.pt, mbe.pkl)
├─ tools/                      # 규정 엔진 명령줄 도구
├─ src/
│  └─ sentry_atm/
│     ├─ domain/               # 항공기·충돌·위험·추천·결정 계약
│     ├─ ports/                # 저장소 인터페이스
│     ├─ geo/                  # RKTU 좌표 및 거리 계산
│     ├─ regulation/           # 고시·AIP 규정 엔진 (분리·활주로·체공·이양·경로)
│     ├─ simulation/           # Clock과 Aircraft Runtime
│     ├─ scenario/             # 골든 데모·출격 시나리오 조립
│     ├─ prediction/           # 4DT 예측과 Rolling Scheduler
│     ├─ conflict/             # CPA/TCPA 및 충돌 탐지
│     ├─ risk/                 # 위험도 평가
│     ├─ priority/             # 작전 우선순위 평가
│     ├─ exception_queue/      # 관제 예외 Queue Lifecycle
│     ├─ resolution/           # 후보 생성과 격리 검증
│     ├─ recommendation/       # 설명 가능한 후보 순위
│     ├─ controller_decision/  # Human-in-the-loop 결정 Audit
│     ├─ api/                  # 읽기모델·명령 계약
│     ├─ runtime/              # 세션 조립과 Orchestrator
│     ├─ infrastructure/
│     │  ├─ http/              # WSGI API, 두 화면, 자동 Demo 점검
│     │  └─ persistence/       # SQLite Adapter
│     └─ reference_data.py     # 기종·성능 참조자료
├─ tests/
│  ├─ unit/
│  ├─ integration/
│  └─ acceptance/
├─ .gitattributes
├─ .gitignore
├─ AGENTS.md
├─ pyproject.toml
└─ README.md
```

## 현재 범위와 제한

- 단일 사용자·단일 프로세스·메모리 내 Session을 전제로 한다.
- 항적은 공개 자료를 참고한 Synthetic/Playback 데이터이며 실제 군 레이더 Feed가 아니다.
- 예측 및 성능 Profile은 결정론적 PoC Baseline이며 공식 BADA 인증 모델이 아니다.
- 규정 판정은 고시·AIP 전사값을 따르지만, 공식 인증을 받은 관제 판정이 아니다.
  공식 근거가 없는 값은 전부 [`docs/assumptions.md`](docs/assumptions.md)에 있다.
- 민항 시간표는 합성값이다 (`ASM` 에 출처를 명시).
- 외부 공개 Bind 는 `--host` 로 명시했을 때만 열리며, 그때 밖에서 온 요청은
  읽기만 된다 (`ASM-045`). **인증은 아니다** — 세션이 하나이고 로그인이 없다.
- 인증, 다중 사용자 동시성, 장기 Audit 저장은 현재 범위에 포함하지 않는다.

## 개발 원칙

1. 요구사항 확인, 설계, 최소 구현, 실행, 테스트, 결과 확인 순서로 진행한다.
2. Planned, Actual, Predicted Trajectory를 구분한다.
3. Prediction, Conflict, Risk, Rule, Resolution 책임을 분리한다.
4. 내부 시간은 timezone-aware UTC를 사용한다.
5. 내부 계산 단위는 NM, ft, kt, ft/min, degree를 사용한다.
6. 모든 비공식 값은 Assumption 또는 Config로 명시한다.
7. AI 추천은 관제사의 승인 전까지 Aircraft Runtime을 변경하지 않는다.
8. 실제 군 레이더 항적, 민감 성능, 실제 군 Callsign을 저장소에 포함하지 않는다.

## 구현 이력

Phase 0~17 로 골든 데모 계약을 세운 뒤, 규정 계층과 출격 시나리오를 얹고 관제
콘솔을 다시 지었다. 단계별 기록은 `git log` 에 있다.

<details>
<summary>Phase 0 ~ 17 (골든 데모 계약)</summary>

- Phase 0-A: Golden Demo Scenario Contract 작성 완료
- Phase 0-B: Python 프로젝트 및 테스트 기반 구성 완료
- Phase 0-C: UTC·단위·Enum·최소 Aircraft/Trajectory Domain 구현 완료
- Phase 1-A: RKTU ARP 기반 위경도↔Local x/y NM 변환 구현 완료
- Phase 1-B: Local 수평거리·고도 수직분리·위경도 대권거리 구현 완료
- Phase 2-A: UTC 기반 Deterministic Simulation Clock 구현 완료
- Phase 2-B: Clock 기반 OPENSKY Playback Aircraft Runtime 구현 완료
- Phase 2-C: Constant Motion 기반 Synthetic Aircraft Runtime 구현 완료
- Phase 3-A: 공유 Clock 기반 다중 항공기 Traffic Simulation Engine 구현 완료
- Phase 3-B: Aircraft Performance Profile 및 Persistence Contract 구현 완료
- Phase 3-C: SQLite Persistence Foundation 구현 완료
- Phase 3-D: Aircraft Type/Performance Profile SQLite Adapter 구현 완료
- Phase 3-E: Synthetic Reference Data Seed 구현 완료
- Phase 4-A: Constant-Velocity Baseline Trajectory Predictor 구현 완료
- Phase 4-B: Multi-Aircraft Prediction Run 구현 완료
- Phase 4-C: Deterministic Rolling Prediction Scheduler 구현 완료
- Phase 4-D: PredictionRun SQLite Persistence 구현 완료
- Phase 5-A: Golden Demo Scenario Foundation 구현 완료
- Phase 5-B: Deterministic Scenario Event Timeline 구현 완료
- Phase 6-A: Conflict Domain 및 Separation Rule Contract 구현 완료
- Phase 6-B: Continuous Relative-Motion CPA/TCPA 구현 완료
- Phase 6-C: Deterministic Pairwise Conflict Detector 구현 완료
- Phase 6-D: Deterministic Rolling Conflict Integration 구현 완료
- Phase 6-E: Golden Demo Conflict Calibration 구현 완료
- Phase 7-A: Risk & Operational Priority Domain Contract 구현 완료
- Phase 7-B: Deterministic Risk & Priority Evaluators 구현 완료
- Phase 8-A: Deterministic Exception Queue Domain 구현 완료
- Phase 8-B: Deterministic Exception Queue Lifecycle Service 구현 완료
- Phase 8-C: Exception Queue Read Model/API Contract 구현 완료
- Phase 8-D: Minimal WSGI HTTP Adapter 구현 완료
- Phase 9-A: Resolution Candidate Domain Contract 구현 완료
- Phase 9-B: Deterministic Resolution Candidate Generator 구현 완료
- Phase 9-C: Resolution Safety Validation Domain 구현 완료
- Phase 9-D: Isolated Resolution Safety Validator 구현 완료
- Phase 9-E: Golden Resolution Calibration 구현 완료
- Phase 10-A: Resolution Recommendation Domain Contract 구현 완료
- Phase 10-B: Deterministic Recommendation Ranking Service 구현 완료
- Phase 10-C: Recommendation Read Model/API Contract 구현 완료
- Phase 10-D: Minimal Recommendation WSGI HTTP Adapter 구현 완료
- Phase 11-A: Controller Decision Audit Domain 구현 완료
- Phase 11-B: Deterministic Controller Decision Service 구현 완료
- Phase 11-C: Controller Decision Command/API Contract 구현 완료
- Phase 11-D: Minimal Controller Decision WSGI HTTP Adapter 구현 완료
- Phase 12-A: Golden Demo Runtime Composition Foundation 구현 완료
- Phase 12-B: Deterministic Golden Demo Step Orchestrator 구현 완료
- Phase 12-C: Deterministic Golden Demo Resolution Step 구현 완료
- Phase 12-D: Deterministic Golden Demo Controller Decision Step 구현 완료
- Phase 12-E: Approved Maneuver Application & Post-action Revalidation 구현 완료
- Phase 13-A: Golden Demo Session Read Model/API 구현 완료
- Phase 13-B: Deterministic Golden Demo Session Command Service 구현 완료
- Phase 13-C: Minimal Golden Demo Session WSGI HTTP Adapter 구현 완료
- Phase 13-D: Loopback-only Local Golden Demo HTTP Server 구현 완료
- Phase 14-A: Golden Demo Web UI Shell 구현 완료
- Phase 14-B: Deterministic Demo Command Controls 구현 완료
- Phase 14-C: Conflict & Resolution Explainability Visualization 구현 완료
- Phase 14-D: Demo Runbook & End-to-End Regression 구현 완료
- Phase 15-A: Planned-vs-Actual Deviation & Candidate Comparison UI 구현 완료
- Phase 15-B: Accept/Modify/Reject Operator Workflow 구현 완료
- Phase 15-C: Modified Maneuver Isolated Revalidation 구현 완료
- Phase 15-D: Validated Modified Maneuver Application 구현 완료
- Phase 15-E: Multi-Path Golden Demo Regression 구현 완료
- Phase 16-A: Demo Release Preflight 구현 완료
- Phase 16-B: Release Documentation & Main Merge Readiness 구현 완료
- Phase 17-A: Animated Demo Playback Contract & Storyboard 구현 완료
- Phase 17-B: Deterministic Aircraft Frames & Playback Read API 구현 완료
- Phase 17-C: Radar Marker & Trail Continuous Animation 구현 완료
- Phase 17-D: Playback Controls, Timeline & Cue Auto-pause 구현 완료

</details>

<details>
<summary>규정 계층 이후</summary>

- 규정 엔진 이식 — 분리·활주로·체공·관할 이양·복귀 경로를 고시 조항으로 판정
- 활성 분리 프로파일 단일화 — 탐지기·위험평가기·읽기모델이 한 곳을 따른다
- WGS84 곡률반경 좌표 변환 — 쌍 거리 오차 22m → 1.9m
- 출격 시나리오 — 15대 75분 13단계, 4막 구조
- 판단 연쇄 일반화 — 시각·후보를 못박지 않고 임의 시나리오에서 동작
- 관제 콘솔 재작성 — 관제 스코프 중심, 실시간 API
- 시연 진행 화면 분리 — 시계를 쥐고, 판단이 필요한 단계에서 자동으로 멈춘다

</details>
