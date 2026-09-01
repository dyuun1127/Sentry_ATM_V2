# RKTU Local Coordinate System

## 1. 목적

외부 지도와 항적 데이터의 위도·경도를 Predictor, Conflict Detector 및 Simulation에서 사용할 RKTU 중심 Local x/y NM로 변환한다.

구현 위치:

```text
src/sentry_atm/geo/coordinate.py
```

## 2. 원점

제공된 RKTU AIP의 ARP 좌표를 사용한다.

```text
Latitude:  36°42'59"N = 36.7163888889°
Longitude: 127°29'57"E = 127.4991666667°
```

Local 좌표:

```text
RKTU ARP = (x=0 NM, y=0 NM)
East  = +x
West  = -x
North = +y
South = -y
```

## 3. 변환 방식

평균 지구 반지름 3,440.065 NM의 구면 지구를 사용한다. 위경도 지점을 구면 ECEF 단위 벡터로 변환한 뒤 RKTU ARP의 East-North-Up 기저에 투영한다.

```text
Geodetic latitude/longitude
        ↓ spherical ECEF
RKTU origin-relative vector
        ↓ ENU projection
Local x/y NM
```

역변환은 Local x/y와 구면 제약으로 near-side Up 성분을 복원한 뒤 위도·경도로 변환한다. 따라서 Terminal 범위에서는 Forward/Inverse 왕복이 안정적으로 일치한다.

## 4. 정확도와 제한

- 이 변환은 해커톤 PoC용 Local Tangent Plane이다.
- 30 NM 범위에서 구면의 Arc와 Tangent Projection 차이는 매우 작다.
- 구면 지구와 WGS84 타원체의 차이는 별도의 모델 오차로 남는다.
- 공식 항행·측량·관제 좌표 변환으로 사용하지 않는다.
- 지구 반대편처럼 원점에서 90도 이상 떨어진 점은 지원하지 않는다.
- 현재 변환은 수평 위치만 다루며 고도는 기존 ft 값을 별도로 보존한다.

실제 운영 수준의 정밀도가 필요해지면 동일 인터페이스 뒤에 WGS84 ENU 또는 검증된 측지 라이브러리 구현을 추가한다.

## 5. Domain Object

### GeodeticPosition

| 필드 | 단위 | 범위 |
|---|---|---|
| `latitude_deg` | degree | `[-90, 90]` |
| `longitude_deg` | degree | `[-180, 180]` |

### LocalPosition

| 필드 | 단위 | 방향 |
|---|---|---|
| `x_nm` | NM | East 양수 |
| `y_nm` | NM | North 양수 |

두 객체는 불변이며 NaN과 Infinity를 허용하지 않는다.

## 6. Public API

```python
from sentry_atm.geo import rktu_geodetic_to_local, rktu_local_to_geodetic

local = rktu_geodetic_to_local(36.75, 127.55)
geodetic = rktu_local_to_geodetic(local.x_nm, local.y_nm)
```

일반화된 다른 원점이 필요하면 `LocalTangentPlane`을 직접 생성한다.

## 7. 거리 계산 API

`geo.distance`는 좌표 변환과 같은 단위 정책을 사용하는 순수 계산 함수만 제공한다.

| 함수 | 입력 | 출력 | 계산 방식 |
|---|---|---|---|
| `horizontal_distance_nm` | LocalPosition 2개 | NM | Local x/y의 유클리드 거리 |
| `vertical_separation_ft` | 고도 2개 | ft | 고도 차이의 절댓값 |
| `geodetic_distance_nm` | GeodeticPosition 2개 | NM | 구면 Haversine 대권거리 |

```python
from sentry_atm.geo import horizontal_distance_nm, vertical_separation_ft

horizontal_nm = horizontal_distance_nm(aircraft_a, aircraft_b)
vertical_ft = vertical_separation_ft(aircraft_a_altitude, aircraft_b_altitude)
```

Simulation과 이후 Conflict 계산의 기본 수평거리는 Local x/y 거리다. 위경도 대권거리는 입력 자료 검증과 좌표 변환 교차 확인에 사용한다. 이 API는 거리만 반환하며 분리기준 충족 여부, CPA/TCPA 또는 충돌 판정은 수행하지 않는다.

## 8. 검증 조건

1. RKTU ARP는 `(0, 0)`이어야 한다.
2. 북쪽 지점은 `+y`, 동쪽 지점은 `+x`여야 한다.
3. 남쪽과 서쪽 지점은 각각 `-y`, `-x`여야 한다.
4. 30 NM Simulation Envelope의 Local→Geodetic→Local 오차가 테스트 허용치 이하여야 한다.
5. Geodetic→Local→Geodetic 왕복이 원래 위경도와 일치해야 한다.
6. 범위를 벗어난 위도·경도와 역변환 불가능 좌표는 거부해야 한다.
7. 모든 거리 함수는 영거리와 대칭성을 만족해야 한다.
8. 30 NM 범위의 Local 거리와 구면 대권거리는 모델 오차 허용치 안에서 일치해야 한다.
