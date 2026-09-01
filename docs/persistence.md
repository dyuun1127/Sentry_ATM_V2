# SQLite Persistence Contract

## 1. 목적과 범위

SENTRY의 해커톤 PoC는 별도 DB Server 없이 하나의 SQLite 파일을 사용한다. 핵심 계산은
`sentry_atm.domain` 객체만 사용하고, Application은 `sentry_atm.ports.repositories`의
Protocol을 통해 데이터를 저장하고 조회한다.

Phase 3-C 구현 범위:

- SQLAlchemy 2 기반 SQLite Table Mapping
- `data/sentry_atm.db` 기본 파일 경로
- 반복 실행 가능한 Schema 초기화
- `AircraftRepository`, `AircraftStateRepository` Adapter
- RKTU Local x/y NM과 파생 WGS84 위경도 저장
- 실제 임시 SQLite 파일을 사용하는 Integration Test

Docker, PostgreSQL Server, 계정, 비밀번호, PostGIS, GeoAlchemy 및 Psycopg는 사용하지 않는다.

## 2. DB 파일과 초기화

기본 경로:

```text
data/sentry_atm.db
```

초기화 명령:

```powershell
.\.venv\Scripts\python.exe -m sentry_atm.infrastructure.persistence init
```

PoC Reference Data 적재:

```powershell
.\.venv\Scripts\python.exe -m sentry_atm.infrastructure.persistence seed
```

`seed`는 Schema를 먼저 초기화한 뒤 누락된 Synthetic Aircraft Type과 Performance Profile만
추가한다. 동일 ID가 이미 있으면 사용자가 검토하거나 수정한 값을 덮어쓰지 않는다.

경로 변경:

```powershell
.\.venv\Scripts\python.exe -m sentry_atm.infrastructure.persistence init --path tmp/demo.db
```

Application에서는 `SENTRY_DB_PATH` 환경변수로 같은 값을 지정할 수 있다. `.db`, `.db-shm`,
`.db-wal` 파일은 Git에서 제외한다.

## 3. 초기 Table

SQLite는 PostgreSQL Schema를 지원하지 않으므로 물리 Schema 분리 대신 Table과 Repository의
책임을 유지한다.

| 영역 | Table | 현재 상태 |
|---|---|---|
| Reference | `aircraft_type` | Table과 Repository 구현 |
| Reference | `aircraft_performance_profile` | Table과 Repository 구현 |
| Reference | `aircraft` | Table과 Repository 구현 |
| Traffic | `aircraft_state` | Table과 Repository 구현 |
| Intent | `flight` | Domain만 구현, Table 후속 |
| Intent | `trajectory`, `trajectory_point` | Domain만 구현, Table 후속 |
| Analytics | `prediction_run` | Domain만 구현, Table 후속 |

`AircraftMetadata.performance_class`는 DB의 `performance_profile_id`로 명시적으로 Mapping한다.

## 4. 시간 저장 정책

SQLite는 PostgreSQL `TIMESTAMPTZ`와 같은 형식을 제공하지 않으므로 `UTCDateTime` Adapter를
사용한다.

- Domain 입력은 timezone-aware datetime만 허용한다.
- KST 등 다른 timezone은 저장 전에 UTC로 변환한다.
- DB에는 `2026-09-01T03:00:00.000000Z` 형태의 고정 길이 ISO-8601 문자열로 저장한다.
- 조회 시 timezone-aware UTC datetime으로 복원한다.
- 고정 길이 UTC 문자열이므로 시간 정렬과 범위 검색 순서가 유지된다.

## 5. 좌표 저장 정책

- Predictor와 Simulation의 기준값은 RKTU ARP Local `x_nm`, `y_nm`다.
- SQLite에는 `x_nm`, `y_nm`, `latitude_deg`, `longitude_deg`를 숫자 컬럼으로 저장한다.
- 위경도는 기존 RKTU Geo Adapter가 Local 좌표에서 계산한다.
- 거리, CPA/TCPA 및 공역 계산은 DB SQL이 아니라 검증된 Python Domain/Geo 코드가 담당한다.
- `latitude_deg`, `longitude_deg`에는 유효 범위 Check Constraint를 적용한다.

향후 대규모 공간검색이 실제 병목으로 측정되면 Repository 구현체만 PostgreSQL/PostGIS로
교체할 수 있다.

## 6. 제약조건과 Index

- `aircraft.aircraft_id`: Primary Key
- `aircraft.icao24`: Unique
- `aircraft_state`: unique `(aircraft_id, timestamp_utc, source)`
- `aircraft_state`: index `(aircraft_id, timestamp_utc)`
- Aircraft Type과 Aircraft State Foreign Key 활성화
- Heading, Ground Speed, Emergency 조합, 위경도 범위 Check Constraint
- `aircraft_state`는 append-only

SQLite는 Foreign Key 적용이 기본적으로 꺼질 수 있으므로 Engine 연결마다
`PRAGMA foreign_keys=ON`을 실행한다.

## 7. Transaction 책임

Repository는 `flush()`까지만 수행한다. `commit()`과 `rollback()`은 Use Case 또는 호출자가
결정한다. 여러 Aircraft State나 향후 Prediction Aggregate를 한 Transaction으로 묶을 수 있도록
Repository 내부에서 임의 Commit을 수행하지 않는다.

## 8. 구현된 Repository

- `SqlAlchemyAircraftTypeRepository`
  - `get`
  - `list_all`
  - `upsert`
- `SqlAlchemyAircraftPerformanceProfileRepository`
  - `get`
  - `list_all`
  - `upsert`
- `SqlAlchemyAircraftRepository`
  - `get`
  - `list_all`
  - `upsert`
- `SqlAlchemyAircraftStateRepository`
  - `append`
  - `append_many`
  - `latest_at_or_before`
  - `list_between`

`list_between`은 시작과 종료시각을 모두 포함하고 UTC 오름차순으로 반환한다.

## 9. 현재 제한사항과 다음 순서

- 동시 다중 Process Write 부하는 목표 범위가 아니다.
- DB 내부 공간 Polygon 연산은 지원하지 않는다.
- 자동 Migration 도구는 아직 도입하지 않는다. 현재 초기 Table은 `create_all()`로 생성한다.
- Flight, Trajectory, PredictionRun은 각 기능 Phase에서 Table과 Adapter를 함께 추가한다.
- 초기 Reference Data는 `ASM-013`의 시뮬레이션 가정이며 실제 기종 성능자료가 아니다.
