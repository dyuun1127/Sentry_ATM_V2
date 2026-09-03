# SENTRY ATM

SENTRY는 청주공항(RKTU) 중심 Terminal Simulation Area에서 미래 4DT를 예측하고, 미래 충돌과 비상 우선순위를 평가해 관제사에게 설명 가능한 대응 후보를 제공하는 Human-in-the-loop 항공교통 의사결정 지원 PoC다.

> 이 프로젝트는 실제 관제 시스템이 아니며, 실제 공역 책임·공식 분리기준·군 운용절차를 대체하지 않는다.

## 현재 릴리스 상태

- Phase 0~16 구현 및 `main` 통합 완료
- Golden Demo Release Preflight `5/5` 통과
- 실제 Loopback HTTP Multi-Path Regression `10/10` 통과
- 전체 자동 테스트 `826 passed`
- 인터넷, Docker, PostgreSQL/PostGIS, Node.js 없이 로컬 실행 가능

## 핵심 기능

1. RKTU ARP 기준 위경도와 Local x/y NM 좌표를 상호 변환한다.
2. UTC 결정론적 Clock에서 Playback 및 Synthetic 항공기 8대를 재현한다.
3. 미래 4DT와 연속 상대운동 CPA/TCPA를 계산해 충돌을 탐지한다.
4. 충돌 위험도와 작전 우선순위를 분리해 예외 Queue를 구성한다.
5. 대응 후보 생성, 격리 안전성 검증, 설명 가능한 추천 순위를 제공한다.
6. 관제사의 `ACCEPT`, `MODIFY`, `REJECT` 결정을 Audit하고 승인된 기동만 적용한다.
7. 적용 후 동일한 계산 경로로 충돌 해소 여부를 재검증한다.
8. 단일 화면 Golden Demo에서 계획·실제·예측 항적과 판단 근거를 시각화한다.

## 구현 이력

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

## 핵심 문서

- [Golden Demo Scenario Contract](docs/scenarios.md)
- [PoC Assumption Register](docs/assumptions.md)
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
- [Golden Demo Web UI](docs/web_ui.md)
- [Golden Demo 실행 Runbook](docs/demo_runbook.md)
- [Golden Demo Release Readiness](docs/release_readiness.md)
- [Final Release & Main Merge Checklist](docs/final_release.md)
- [Animated Golden Demo Contract](docs/animated_demo.md)

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

## 로컬 SQLite DB 초기화

별도 서버, 계정 또는 Docker 없이 프로젝트 루트에서 실행한다.

```powershell
.\.venv\Scripts\python.exe -m sentry_atm.infrastructure.persistence init
```

기본 DB 파일은 `data/sentry_atm.db`에 생성되며 Git에는 업로드되지 않는다. 다른 위치가 필요하면
`--path`를 지정한다.

```powershell
.\.venv\Scripts\python.exe -m sentry_atm.infrastructure.persistence init --path tmp/demo.db
```

세 가지 Synthetic Category의 초기 Aircraft Type과 Performance Profile을 추가하려면 실행한다.
기존에 같은 ID가 있으면 덮어쓰지 않는다.

```powershell
.\.venv\Scripts\python.exe -m sentry_atm.infrastructure.persistence seed
```

## Golden Demo 빠른 실행

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

브라우저에서 `http://127.0.0.1:8000`을 열면 Golden Demo Dashboard가 표시된다. 다른 로컬 Port가
필요하면 `--port 8123`처럼 지정한다.
서버를 종료하려면 `Ctrl+C`를 누른다. 외부 장치에서 접속할 수 있도록 Bind하는 기능은 제공하지 않는다.

### Golden Demo 흐름

| 단계 | 화면과 시스템 동작 |
|---|---|
| 감시 시작 | T+0, 8대 Traffic을 동일한 초기 상태로 재현 |
| 충돌 시점 진행 | T+70, `CIV-A02 / MIL-F01` 미래 충돌과 HIGH 위험 표시 |
| 대응 후보 생성 | T+75, CAND-A~E의 적용 전 안전성 비교와 추천 생성 |
| 관제사 결정 | T+90, ACCEPT/MODIFY/REJECT와 판단 근거 Audit |
| 승인 기동 적용 | 승인된 기동만 Runtime에 반영하고 CPA·위험도 재검증 |
| Run Reset | 파생 상태를 제거하고 깨끗한 `READY` Session 재생성 |

## 테스트 및 정적 검사

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
```

최종 `main` 통합 시점의 기준 결과는 Ruff 통과, `826 passed`다. 발표 전 점검과 병합 절차는
[Golden Demo Release Readiness](docs/release_readiness.md)와
[Final Release & Main Merge Checklist](docs/final_release.md)를 따른다.

## 현재 프로젝트 구조

```text
.
├─ docs/
│  ├─ scenarios.md             # Golden Demo 계약
│  ├─ assumptions.md           # PoC 가정과 비공식 임계값
│  ├─ demo_runbook.md          # 발표 실행·복구 절차
│  └─ final_release.md         # 최종 검증·병합 체크리스트
├─ src/
│  └─ sentry_atm/
│     ├─ domain/               # 항공기·충돌·위험·추천·결정 계약
│     ├─ geo/                  # RKTU 좌표 및 거리 계산
│     ├─ simulation/           # Clock과 Aircraft Runtime
│     ├─ prediction/           # 4DT 예측과 Rolling Scheduler
│     ├─ conflict/             # CPA/TCPA 및 충돌 탐지
│     ├─ risk/                 # 위험도 평가
│     ├─ priority/             # 작전 우선순위 평가
│     ├─ exception_queue/      # 관제 예외 Queue Lifecycle
│     ├─ resolution/           # 후보 생성과 격리 검증
│     ├─ recommendation/       # 설명 가능한 후보 순위
│     ├─ controller_decision/  # Human-in-the-loop 결정 Audit
│     ├─ runtime/              # Golden Demo 조립과 Orchestrator
│     ├─ infrastructure/
│     │  ├─ http/              # WSGI API, Web UI, 자동 Demo 점검
│     │  └─ persistence/       # SQLite Adapter
│     └─ __init__.py
├─ tests/
│  ├─ unit/
│  └─ integration/
├─ migrations/                # SQLite Schema Migration
├─ .gitattributes
├─ .gitignore
├─ AGENTS.md
├─ pyproject.toml
└─ README.md
```

## 현재 범위와 제한

- Golden Demo는 단일 사용자·단일 프로세스·메모리 내 Session을 전제로 한다.
- 항적은 공개 자료를 참고한 Synthetic/Playback 데이터이며 실제 군 레이더 Feed가 아니다.
- 예측 및 성능 Profile은 결정론적 PoC Baseline이며 공식 BADA 인증 모델이 아니다.
- 충돌·위험·우선순위 임계값은 시연 가정이며 공식 관제 기준이 아니다.
- 인증, 외부 공개 Bind, 다중 사용자 동시성, 장기 Audit 저장은 현재 범위에 포함하지 않는다.

## 개발 원칙

1. 요구사항 확인, 설계, 최소 구현, 실행, 테스트, 결과 확인 순서로 진행한다.
2. Planned, Actual, Predicted Trajectory를 구분한다.
3. Prediction, Conflict, Risk, Rule, Resolution 책임을 분리한다.
4. 내부 시간은 timezone-aware UTC를 사용한다.
5. 내부 계산 단위는 NM, ft, kt, ft/min, degree를 사용한다.
6. 모든 비공식 값은 Assumption 또는 Config로 명시한다.
7. AI 추천은 관제사의 승인 전까지 Aircraft Runtime을 변경하지 않는다.
8. 실제 군 레이더 항적, 민감 성능, 실제 군 Callsign을 저장소에 포함하지 않는다.
