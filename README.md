# SENTRY ATM

SENTRY는 청주공항(RKTU) 중심 Terminal Simulation Area에서 미래 4DT를 예측하고, 미래 충돌과 비상 우선순위를 평가해 관제사에게 설명 가능한 대응 후보를 제공하는 Human-in-the-loop 항공교통 의사결정 지원 PoC다.

> 이 프로젝트는 실제 관제 시스템이 아니며, 실제 공역 책임·공식 분리기준·군 운용절차를 대체하지 않는다.

## 현재 상태

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
- Modify/Reject Decision UI: 아직 구현하지 않음

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

## Golden Demo API 실행

별도 Web Framework 없이 Python 표준 라이브러리 서버를 로컬 Loopback에 실행한다.

발표 전 전체 Golden Demo 계약을 먼저 자동 점검한다.

```powershell
.\.venv\Scripts\python.exe -m sentry_atm.infrastructure.http --check
```

```powershell
.\.venv\Scripts\python.exe -m sentry_atm.infrastructure.http
```

브라우저에서 `http://127.0.0.1:8000`을 열면 Golden Demo Dashboard가 표시된다. 다른 로컬 Port가
필요하면 `--port 8123`처럼 지정한다.
서버를 종료하려면 `Ctrl+C`를 누른다. 외부 장치에서 접속할 수 있도록 Bind하는 기능은 제공하지 않는다.

## 테스트 및 정적 검사

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
```

## 현재 프로젝트 구조

```text
.
├─ docs/
│  ├─ assumptions.md
│  ├─ data_model.md
│  ├─ scenarios.md
│  └─ simulation.md
├─ src/
│  └─ sentry_atm/
│     ├─ domain/
│     ├─ geo/
│     ├─ infrastructure/
│     ├─ simulation/
│     └─ __init__.py
├─ tests/
│  └─ unit/
│     ├─ domain/
│     ├─ geo/
│     ├─ simulation/
│     └─ test_package.py
├─ .gitattributes
├─ .gitignore
├─ AGENTS.md
├─ pyproject.toml
└─ README.md
```

디렉터리는 Phase별 최소 구현에 맞춰 필요한 시점에 추가한다. 빈 모듈을 미리 대량 생성하지 않는다.

## 개발 원칙

1. 요구사항 확인, 설계, 최소 구현, 실행, 테스트, 결과 확인 순서로 진행한다.
2. Planned, Actual, Predicted Trajectory를 구분한다.
3. Prediction, Conflict, Risk, Rule, Resolution 책임을 분리한다.
4. 내부 시간은 timezone-aware UTC를 사용한다.
5. 내부 계산 단위는 NM, ft, kt, ft/min, degree를 사용한다.
6. 모든 비공식 값은 Assumption 또는 Config로 명시한다.
7. AI 추천은 관제사의 승인 전까지 Aircraft Runtime을 변경하지 않는다.
8. 실제 군 레이더 항적, 민감 성능, 실제 군 Callsign을 저장소에 포함하지 않는다.
