# Final Release & Main Merge Checklist

## 1. 목적

Phase 16-B는 Golden Demo 기능 구현을 종료하고 작업 브랜치를 `main`에 합치기 전에 필요한 증거와
절차를 고정한다. 이 판정은 로컬 발표용 PoC의 소프트웨어 릴리스 준비 상태이며 실제 항공 운용 또는
보안 인증이 아니다.

## 2. 병합 전 자동 판정

원격 정보를 먼저 갱신한 다음 작업 브랜치에서 실행한다.

```powershell
git fetch origin
.\.venv\Scripts\python.exe -m sentry_atm.infrastructure.release
```

자동 판정은 다음 8개 항목을 검사한다.

| Check | 완료 조건 |
|---|---|
| `BRANCH` | `origin/main`보다 앞선 릴리스 Commit이 존재함 |
| `BASE` | 현재 HEAD가 최신 `origin/main`의 후손임 |
| `WORKTREE` | 추적 또는 Staging 중인 미커밋 변경이 없음 |
| `ARTIFACTS` | PDF/HWP 등 참고문서는 추적되지 않고 새 소스 누락도 없음 |
| `UPSTREAM` | 로컬 HEAD와 현재 원격 작업 브랜치가 일치함 |
| `RUFF` | 전체 정적 검사가 통과함 |
| `PYTEST` | 전체 테스트가 통과함 |
| `DEMO` | Release Preflight 5개와 실제 HTTP Checkpoint 10개가 통과함 |

아래 문구와 종료 코드 `0`이 최종 Go 조건이다.

```text
SENTRY ATM MAIN MERGE READY (8 checks)
```

참고 PDF, HWP, DOCX, PPTX, XLS/XLSX는 로컬에 미추적 상태로 둘 수 있다. 반대로 `.py`, `.md`,
HTML/CSS/JavaScript 등 새 프로젝트 파일이 미추적이면 구현 누락 가능성이 있으므로 판정에 실패한다.

## 3. 검토 및 병합 절차

자동 판정이 통과한 뒤 GitHub에서 `phase12/runtime-composition` → `main` Pull Request를 만든다.

1. 변경 기준이 `main`, 비교 대상이 `phase12/runtime-composition`인지 확인한다.
2. Phase 6~16의 변경 파일과 Commit 이력이 모두 표시되는지 확인한다.
3. 실제 군 비공개 자료, Callsign, 인증정보, PDF/HWP 원본이 없는지 다시 확인한다.
4. 자동 판정 결과를 PR 설명에 기록한다.
5. 병합 직전에 원격 변경이 생겼다면 `git fetch origin`부터 다시 실행한다.
6. 검토 후 PR을 `main`에 병합한다. 이번 Phase에서는 자동 병합하지 않는다.

병합 후 로컬 확인 명령은 다음과 같다.

```powershell
git switch main
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m sentry_atm.infrastructure.http --check
```

## 4. 발표 패키지 기준

- 발표 대상 Commit hash를 발표자 메모에 기록한다.
- [Golden Demo 실행 Runbook](demo_runbook.md)의 고정 순서대로 리허설한다.
- 인터넷, Docker, PostgreSQL/PostGIS, Node.js 없이 동작하는지 확인한다.
- 브라우저는 `http://127.0.0.1:8000/`, Zoom 100%, 가로 1280px 이상을 사용한다.
- Port 충돌에 대비해 `--port 8001` 명령을 준비한다.
- 화면의 `POC · NOT FOR OPERATIONAL USE` 고지를 유지한다.

## 5. 알려진 제한사항

- 단일 사용자·단일 프로세스·메모리 내 Session을 전제로 한다.
- RKTU 중심 Synthetic/Playback Golden Scenario이며 실제 레이더 Feed가 아니다.
- 예측은 결정론적 Baseline이며 공식 BADA 성능 인증 모델이 아니다.
- 충돌·위험·우선순위 임계값은 PoC Assumption이지 공식 관제 기준이 아니다.
- 추천 후보는 제한된 수직 기동 집합이며 관제사 승인 전 Runtime을 바꾸지 않는다.
- 인증, 권한관리, 외부 공개 Bind, 장기 Audit 저장, 다중 사용자 동시성은 범위 밖이다.
- Preflight는 브라우저 화면 배율·해상도와 발표 장비 전체 상태를 자동 검증하지 않는다.

## 6. No-Go와 복구

`[FAIL]`이 출력되면 병합하지 않는다. 메시지에 따라 미커밋 파일을 정리하거나 원격 작업 브랜치에
Push하고, 테스트 또는 Demo 실패를 수정한 뒤 2절 명령을 처음부터 다시 실행한다. 이미 공개된
`main` 이력은 강제 Push로 되돌리지 않고 후속 수정 Commit 또는 GitHub의 Revert 절차를 사용한다.
