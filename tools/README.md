# tools

`sentry_atm.regulation` 을 다루는 명령줄 도구. 서버나 웹 UI 없이 단독으로 돈다.

전부 `./.venv/Scripts/python.exe tools/<이름>.py` 로 실행하며, `--help` 가 인자를
설명한다. 학습·평가 계열은 `pip install -e ".[learning]"` 이 필요하다.

## 검증

| 도구 | 하는 일 |
|---|---|
| `validate_aip.py` | AIP 가 고시한 거리·방위 67건을 전사 좌표로 재계산해 대조한다. 코드에 박힌 상수가 아니라 전사값이 맞는지 보는 게이트다 |

## 학습·평가

| 도구 | 하는 일 |
|---|---|
| `train_predictor.py` | 물리 기준선 + 잔차 LSTM 학습. 훈련·검증·시험을 **항적 단위**로 70/15/15 분할한다 — 시점 단위로 나누면 같은 상황을 외운 것을 성능으로 착각한다. 지평별 물리 대비 개선율과 σ 보정을 함께 낸다 |
| `train_mbe.py` | 예외 판정 스코어러 학습. 무개입 롤아웃 결과를 라벨로 쓰고, 목표 상신율·주의 재현율에서 임계값을 유도한다 |
| `eval_ordering.py` | 착륙순서 최적화 평가. 순번 이동 제한별 이득과 단조 개선 보장을 확인한다 |

`models/` 의 `predictor.pt` 와 `mbe.pkl` 이 이 도구들의 산출물이다.

> **모델은 라이브러리 판에 묶인다.** `mbe.pkl` 은 scikit-learn 이 피클한 것이라
> 학습 때와 다른 판에서는 언피클이 깨질 수 있다(내부 모듈 경로가 바뀐다).
> 깨지면 `train_mbe.py` 를 다시 돌리면 된다 — 값을 손으로 맞추지 않는다.

## 시연 (콘솔 출력)

| 도구 | 하는 일 |
|---|---|
| `demo_sequencing.py` | 도착 시퀀싱과 비상기 우선권을 터미널에 표로 출력 |
| `demo_cdr.py` | 충돌 탐지·회피안 생성과 불확실성이 충돌확률에 미치는 영향 |

## 시나리오 내보내기

| 도구 | 하는 일 |
|---|---|
| `export_scenario.py` | 도착 시나리오 한 판을 JSON 으로 |
| `build_demo.py` | 후보 시드를 훑어 4막 구조가 뚜렷한 것을 골라 내보낸다 |
| `build_sortie_demo.py` | 출격→임무→비상복귀→우선착륙 13단계 소티 시나리오 |
| `build_terrain.py` | Natural Earth 해안선을 오프라인 배경으로 굽는다 |

산출물은 `artifacts/` 에 쌓인다.

> **이 JSON 을 읽는 콘솔은 아직 이 저장소에 없다.** 원래는 단독 SVG 스코프
> 콘솔이 소비했고, 이 저장소의 웹 UI(`infrastructure/http/static/`)는 다른
> 스키마를 쓴다. 어느 쪽으로 갈지 정해지기 전까지 산출물만 남긴다.

## 경로 규약

- 참조 데이터: `src/sentry_atm/regulation/reference/` — 패키지 안에 있어 저장소 배치와 무관하다
- 모델: `models/`
- 산출물: `artifacts/`
