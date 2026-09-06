"""데이터 계층 — data/*.json 로더.

설계 원칙: 공역·절차·분리기준의 어떤 수치도 코드에 하드코딩하지 않는다.
AIRAC 개정 시 data/ 의 JSON만 교체하면 되도록 접근자만 제공한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from .geo import LocalFrame, parse_latlon

# 참조 데이터는 패키지 안에 둔다. 저장소 배치가 바뀌어도 따라오게 하기 위해서다.
DATA_DIR = Path(__file__).resolve().parent / "reference"


def _pt(node: dict) -> tuple[float, float]:
    """{"lat": ..., "lon": ...} 노드를 십진도 (위도, 경도) 로."""
    return parse_latlon(node["lat"]), parse_latlon(node["lon"])


@dataclass(frozen=True)
class Waypoint:
    name: str
    lat: float
    lon: float
    source: str = ""


@dataclass(frozen=True)
class Runway:
    name: str
    true_brg: float
    length_m: float
    thr_lat: float
    thr_lon: float
    thr_elev_ft: float


class Procedures:
    """procedures.json 접근자."""

    def __init__(self, raw: dict):
        self.raw = raw

    @cached_property
    def waypoints(self) -> dict[str, Waypoint]:
        out: dict[str, Waypoint] = {}
        for name, node in self.raw["waypoints"].items():
            lat, lon = _pt(node)
            out[name] = Waypoint(name, lat, lon, node.get("_source", ""))
        # 항행안전시설 중 좌표가 있는 것도 픽스처럼 조회 가능하게 둔다.
        for name, node in self.raw["navaids"].items():
            if "lat" in node:
                lat, lon = _pt(node)
                out[name] = Waypoint(name, lat, lon, node.get("_source", ""))
        return out

    @cached_property
    def runways(self) -> dict[str, Runway]:
        out = {}
        for name, node in self.raw["runways"].items():
            lat, lon = _pt(node["thr"])
            out[name] = Runway(
                name, node["true_brg"], node["length_m"], lat, lon, node["thr_elev_ft"]
            )
        return out

    @cached_property
    def arp(self) -> tuple[float, float]:
        return _pt(self.raw["aerodrome"]["arp"])

    @property
    def mag_var(self) -> float:
        """서편차 (양수). RKTU = 9.0"""
        return self.raw["_meta"]["mag_var_deg_west"]

    def fix(self, name: str) -> Waypoint:
        return self.waypoints[name]

    def iap(self, ident: str) -> dict:
        return self.raw["iap"][ident]

    def star(self, ident: str) -> dict:
        return self.raw["star"][ident]

    def sid(self, ident: str) -> dict:
        return self.raw["sid"][ident]


class Fleet:
    """aircraft.json 접근자 — 기종 제원과 시퀀싱 파라미터."""

    def __init__(self, raw: dict):
        self.raw = raw

    def wake_cat(self, actype: str, default: str = "중형") -> str:
        """기종 → 후류 등급 (고시 5-5-4 사·아항 등급)."""
        return self.raw["types"].get(actype, {}).get("wake_cat", default)

    def final_gs_kt(self, actype: str, wake_cat: str | None = None) -> float:
        """최종접근 지상속도.

        기종별 값이 우선이고 없으면 등급 기본값을 쓴다. 등급과 속도는 상관이 없다 —
        전투기는 소형 등급이면서 민항 중형기보다 빠르다.
        """
        t = self.raw["types"].get(actype)
        if t and "final_gs_kt" in t:
            return t["final_gs_kt"]
        cat = wake_cat or (t or {}).get("wake_cat") or "중형"
        return self.raw["categories"][cat]["final_gs_kt"]

    def runway_occupancy_s(self, actype: str, wake_cat: str | None = None) -> float:
        """활주로 점유시간 (추정값)."""
        t = self.raw["types"].get(actype)
        if t and "runway_occupancy_s" in t:
            return t["runway_occupancy_s"]
        cat = wake_cat or (t or {}).get("wake_cat")
        if cat and cat in self.raw["categories"]:
            return self.raw["categories"][cat]["runway_occupancy_s"]
        return self.raw["sequencing"]["runway_occupancy_default_s"]

    def srs_cat(self, actype: str) -> str:
        """동일활주로 분리(SRS) 범주. 고시 3-9-6 주기 가 — **군 공항** 기준.

        청주는 민·군 공용이지만 군 공항이므로 민간전용공항 기준(주기 나)을 쓰지 않는다.
        결과적으로 헬기를 뺀 전 기종이 CAT III 로 묶여 거리 최저치가 6,000ft 로
        일괄 적용된다 — 이 공항에서 SRS 범주는 기종을 구분하지 못한다.
        """
        return self.raw["types"].get(actype, {}).get("srs_cat", "CAT_III")

    def departure_roll_s(self, actype: str, wake_cat: str | None = None) -> float:
        """이륙활주 시작부터 활주로 종단 통과까지 (추정값).

        고시 3-9-6 가항의 '활주로 종단을 통과' 판정에 쓴다.
        """
        t = self.raw["types"].get(actype)
        if t and "departure_roll_s" in t:
            return t["departure_roll_s"]
        cat = wake_cat or (t or {}).get("wake_cat") or "중형"
        return self.raw["categories"][cat]["departure_roll_s"]

    def initial_climb_kt(self, actype: str, wake_cat: str | None = None) -> float:
        """SID 구간 대표 상승속도.

        상승률은 여기서 주지 않는다 — AIP 가 고시한 SID 상승구배(ft/NM)에 이 속도를
        곱해 산출한다. 지어낸 상승률로 절차 고도제한을 어기지 않기 위해서다.
        """
        t = self.raw["types"].get(actype)
        if t and "initial_climb_kt" in t:
            return t["initial_climb_kt"]
        cat = wake_cat or (t or {}).get("wake_cat") or "중형"
        return self.raw["categories"][cat]["initial_climb_kt"]

    def has_tcas(self, actype: str) -> bool:
        """TCAS 장착 여부. 미장착 기종은 지상 관제가 유일한 안전망이다."""
        return bool(self.raw["types"].get(actype, {}).get("tcas", True))

    def is_military(self, actype: str) -> bool:
        return self.raw["types"].get(actype, {}).get("operator") == "military"

    def is_rotorcraft(self, actype: str) -> bool:
        return bool(self.raw["types"].get(actype, {}).get("rotorcraft", False))

    def spec(self, actype: str) -> dict:
        return self.raw["types"].get(actype, {})

    @property
    def sequencing(self) -> dict:
        return self.raw["sequencing"]


class Airspace:
    """airspace.json 접근자."""

    def __init__(self, raw: dict):
        self.raw = raw

    @cached_property
    def target_sector(self) -> dict:
        """대상 섹터(T17) 정의."""
        for b in self.raw["tma"]["blocks"]:
            if b.get("is_target_sector"):
                return b
        raise KeyError("is_target_sector 로 표시된 블록이 없다")

    @cached_property
    def sector_polygon(self) -> list[tuple[float, float]]:
        """대상 섹터 폴리곤 — (위도, 경도) 리스트."""
        return [_pt(p) for p in self.target_sector["polygon"]]

    # --- 분리기준 (고시) ---

    @property
    def sep_horizontal_nm(self) -> float:
        """T17 적용 레이더 수평 분리 최저치. 고시 5-5-4."""
        return self.raw["separation"]["radar_horizontal"]["within_40nm_of_asr_nm"]

    @property
    def sep_final_nm(self) -> float:
        """최종접근진로상 활주로 10NM 이내. 고시 5-5-4."""
        return self.raw["separation"]["radar_horizontal"]["final_approach_within_10nm_nm"]

    @property
    def sep_vertical_ft(self) -> float:
        """FL410 이하 수직분리. 고시 4-5-1."""
        return self.raw["separation"]["vertical"]["below_fl410_ft"]

    @property
    def altitude_ladder_ft(self) -> list[int]:
        """T17 상한 때문에 3층만 쓰는 배정고도 사다리."""
        return self.raw["assigned_altitudes"]["ladder_ft"]

    @property
    def handoff_alt_ft(self) -> float:
        """관제이양 고도 (T17 상한)."""
        return self.raw["handoff"]["t17_upper_ft_amsl"]

    # 항적난기류 최저치는 조건부라 단순 조회로 노출하지 않는다.
    # 고시 5-5-4 사(비행 중)와 아(동일 활주로 착륙)는 적용 조건이 다르고
    # 아항은 사항에 "부가하여" 적용되므로, 판정은 rules.RuleBook 이 담당한다.

    def wake_table(self, kind: str) -> dict[str, float]:
        """원표 조회 — "in_flight" 또는 "landing". 판정이 아니라 표 자체가 필요할 때만."""
        return self.raw["separation"]["wake_turbulence"][kind]["minima_nm"]


@dataclass
class MinimumAltitudeChart:
    """msa.json 접근자 — AD 2-16 최저고도 차트.

    **표시 전용이다.** 회피안 검증의 최저고도는 여전히 `ASM-037` 의 잠정값을 쓴다.
    여기 값을 판정에 넣으면 어떤 후보가 살아남는지가 달라지므로, 넣을 때는 시연
    전체를 다시 돌려 확인해야 한다. 그 전까지는 화면에만 그린다.
    """

    raw: dict

    @property
    def vertices(self) -> dict:
        return self.raw["vertices"]

    @property
    def boundaries(self) -> list:
        return self.raw["boundaries"]

    @property
    def minimum_altitudes(self) -> list:
        return self.raw["minimum_altitudes"]

    @property
    def obstacles(self) -> list:
        return self.raw["obstacles"]


@dataclass
class Dataset:
    """공역 + 절차 + 기종을 묶은 단일 진입점."""

    airspace: Airspace
    procedures: Procedures
    fleet: Fleet
    msa: MinimumAltitudeChart

    @cached_property
    def frame(self) -> LocalFrame:
        """공항 기준점(ARP) 중심 국지 평면 좌표계."""
        lat, lon = self.procedures.arp
        return LocalFrame(lat, lon)


def load(data_dir: Path | str | None = None) -> Dataset:
    """data/ 에서 공역·절차·기종을 읽어 Dataset 으로."""
    d = Path(data_dir) if data_dir else DATA_DIR

    def _read(name: str) -> dict:
        return json.loads((d / name).read_text(encoding="utf-8"))

    return Dataset(
        Airspace(_read("airspace.json")),
        Procedures(_read("procedures.json")),
        Fleet(_read("aircraft.json")),
        MinimumAltitudeChart(_read("msa.json")),
    )
