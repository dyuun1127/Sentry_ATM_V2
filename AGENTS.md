# SENTRY ATM Repository Instructions

## Scope

이 저장소는 RKTU 중심 Terminal Simulation Area를 대상으로 하는 Predictive ATC 의사결정 지원 PoC다. 실제 자율 관제 시스템이나 실제 관제기관 운영구조의 복제를 목표로 하지 않는다.

## Working Agreement

1. 한 번에 현재 Phase의 최소 기능만 구현한다.
2. 요구사항 확인, 설계, 최소 구현, 실행, 테스트, 결과 확인 순서를 지킨다.
3. 다음 Phase를 시작하기 전에 현재 Phase의 완료조건과 테스트 결과를 확인한다.
4. 큰 구조 변경, 파일 삭제 및 데이터 삭제는 사전에 제안하고 승인받는다.
5. 실제 군 관련 비공개 데이터, 실제 군 Callsign, 인증정보 및 개인정보를 커밋하지 않는다.

## Architecture Rules

1. OpenSky Adapter와 Domain 및 Predictor를 분리한다.
2. Predictor와 Conflict Detector를 분리한다.
3. Conflict, Risk, Priority를 서로 다른 결과로 모델링한다.
4. AI/Prediction과 deterministic Rule Engine을 분리한다.
5. Candidate Generation과 Safety Validation을 분리한다.
6. Simulation Engine과 UI를 분리한다.
7. Playback Aircraft와 Synthetic Aircraft Runtime을 분리한다.
8. CSV 또는 외부 API Schema를 Domain 곳곳에서 직접 참조하지 않는다.

## Domain Policies

- Time: timezone-aware UTC internally, KST only for presentation
- Distance: NM
- Altitude: ft
- Horizontal speed: kt
- Vertical speed: ft/min
- Heading: degree, 0 North and 90 East
- Coordinates: RKTU ARP local x/y, East +x and North +y
- Sources: at least `OPENSKY` and `SYNTHETIC`

공식 근거가 없는 값은 `docs/assumptions.md` 또는 Config에 명시한다. PoC 임계값을 모든 상황에 적용되는 공식 기준으로 표현하지 않는다.

## Human-in-the-loop

Recommendation은 관제사의 Accept, Modify 또는 Reject 이전에 Aircraft Runtime을 변경할 수 없다. 시스템은 추천 근거와 후보 적용 전후 결과를 제공해야 한다.

## Verification

변경 후 최소한 다음을 실행한다.

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
```

테스트가 없는 기능은 완료로 간주하지 않는다.

## Git

- 기능별로 목적이 분명한 작은 커밋을 만든다.
- `git add .` 대신 변경한 파일을 명시적으로 스테이징한다.
- Commit 전 staged diff와 테스트 결과를 확인한다.
- 참고 PDF, HWP 및 원본 데이터는 사용자가 명시적으로 결정하기 전까지 스테이징하지 않는다.
