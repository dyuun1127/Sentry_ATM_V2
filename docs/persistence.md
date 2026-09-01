# PostgreSQL + PostGIS Persistence Contract

## 1. 목적과 현재 범위

SENTRY의 영속성 계층은 Domain과 PostgreSQL/PostGIS를 직접 결합하지 않는다. 핵심 계산은
`sentry_atm.domain` 객체만 사용하고, `sentry_atm.ports.repositories`의 Protocol을 통해
저장소를 호출한다. SQLAlchemy 모델, SQL 문법, PostGIS Geometry는 후속 Infrastructure
Adapter 내부에만 둔다.

현재 단계는 다음 항목까지 구현한다.

- DB 독립 Domain 객체
- 동기식 Repository Interface
- PostgreSQL/PostGIS 논리 스키마 및 공간 데이터 정책

아직 구현하지 않는 항목은 DB 연결, ORM Mapping, Migration, 운영용 인증정보다.

## 2. 한 DB, 영역별 Schema

9개의 물리 DB를 만들지 않고 하나의 PostgreSQL Database 안에서 책임별 Schema를 나눈다.

| Schema | 초기 책임 | 후속 확장 |
|---|---|---|
| `reference` | `aircraft_type`, `aircraft_performance_profile`, `aircraft` | 공역, 제한구역, 절차, 규칙 |
| `intent` | `flight`, `trajectory`, `trajectory_point` | SID/STAR/Approach Intent |
| `traffic` | `aircraft_state` | 수집 배치와 원본 추적 |
| `analytics` | `prediction_run`, 예측 Trajectory 연결 | Conflict, Risk |
| `decision` | 현재 없음 | Recommendation, Controller Action Audit |

Schema 분리는 접근권한과 이름 충돌을 줄이기 위한 논리 경계다. 분산 DB나 Microservice 경계를
뜻하지 않는다.

## 3. Domain과 초기 Table Mapping

| Domain | Table | 저장 정책 |
|---|---|---|
| `AircraftType` | `reference.aircraft_type` | 공개 기종 분류, `type_code` unique |
| `AircraftPerformanceProfile` | `reference.aircraft_performance_profile` | 출처 필수, 원자료 원문은 저장하지 않음 |
| `AircraftMetadata` | `reference.aircraft` | 시스템 내부 `aircraft_id` PK |
| `AircraftState` | `traffic.aircraft_state` | append-only |
| `Flight` | `intent.flight` | 비행 수명주기 |
| `Trajectory` | `intent.trajectory`, `intent.trajectory_point` | Planned/Actual/Predicted 구분 |
| `PredictionRun` | `analytics.prediction_run` | 모델명·버전·입력시각·설정 ID 보존 |

`AircraftMetadata.performance_class`는 초기에는 Performance Profile의 논리 연결 키로 사용한다.
실제 DB Adapter에서는 명시적인 Foreign Key 컬럼명 `performance_profile_id`로 Mapping한다.

## 4. 시간과 공간 저장 정책

### 4.1 시간

- 모든 시각 컬럼은 `TIMESTAMPTZ`를 사용한다.
- Application과 Domain은 timezone-aware UTC만 전달한다.
- DB Session timezone도 UTC로 고정한다.
- 화면에서만 KST로 변환한다.

### 4.2 좌표

- 시뮬레이션과 Predictor의 기준값은 기존 Domain 정책대로 RKTU ARP Local `x_nm`, `y_nm`다.
- 항공기 상태에는 `x_nm`, `y_nm`, `altitude_ft`를 수치 컬럼으로 보존한다.
- 지도 표시와 공간 검색이 필요할 때 Adapter가 위경도로 변환해
  `geometry(Point, 4326)` 컬럼에도 기록한다.
- 정적 공역, 제한구역, 절차 선은 WGS84 `geometry(..., 4326)`로 저장하고 GiST Index를 둔다.
- Local 좌표와 Geometry의 변환 책임은 Domain이 아니라 기존 Geo Adapter에 둔다.

같은 위치를 두 표현으로 저장하므로 PostgreSQL Adapter 통합 테스트에서 왕복 오차와 동기화를
검증해야 한다. 원본 좌표, 변환 방법 및 좌표계 식별자를 함께 기록한다.

## 5. 핵심 제약조건과 Index

- `traffic.aircraft_state`: unique `(aircraft_id, timestamp_utc, source)`
- `traffic.aircraft_state`: index `(aircraft_id, timestamp_utc DESC)`
- `intent.trajectory_point`: unique `(trajectory_id, sequence_no)`
- `intent.trajectory_point`: unique `(trajectory_id, timestamp_utc)`
- `analytics.prediction_run`: index `(input_timestamp_utc DESC)`
- 공간 컬럼: GiST Index
- Aircraft State, Prediction 결과, Controller Action은 원칙적으로 append-only

Repository의 `list_between`은 양 끝 시각을 포함하고 UTC 오름차순으로 반환하도록 Adapter에서
고정한다. 여러 행을 저장하는 `PredictionRun.save`와 Trajectory 저장은 하나의 Transaction으로
처리한다.

## 6. Repository Interface

구현 위치는 `src/sentry_atm/ports/repositories.py`다.

- `AircraftRepository`
- `AircraftTypeRepository`
- `AircraftPerformanceProfileRepository`
- `AircraftStateRepository`
- `FlightRepository`
- `TrajectoryRepository`
- `PredictionRunRepository`

현재 PoC는 호출 흐름과 테스트를 단순하게 유지하기 위해 동기식 Interface를 사용한다. 실제
PostgreSQL Adapter도 먼저 동기식 SQLAlchemy Session으로 구현하고, 비동기 API가 필요하다는
측정 근거가 생길 때 별도 Async Port를 추가한다.

## 7. 다음 구현 순서

1. 개발용 PostgreSQL/PostGIS Docker Compose와 환경변수 예시를 추가한다.
2. SQLAlchemy 및 Alembic 의존성을 고정한다.
3. 위 Schema와 Table을 첫 Migration으로 생성한다.
4. Domain↔ORM Mapper와 Repository Adapter를 하나씩 구현한다.
5. 실제 PostGIS Container를 사용하는 Integration Test를 작성한다.
6. Golden Scenario Fixture만 적재하고 Raw BADA/OpenSky 원본은 계속 Git에서 제외한다.

비밀번호와 접속 문자열은 `.env`에 두고 `.env.example`에는 이름만 제공한다. Migration에는
민감 자료나 대용량 원본 데이터를 포함하지 않는다.
