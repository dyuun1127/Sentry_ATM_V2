"""규정 기반 분리 최저치 어댑터.

PoC 는 수평 5NM 을 `ASM-018 PROVISIONAL POC ASSUMPTION` 으로 명시해 두고 구조를
먼저 세웠다. 이 모듈이 그 자리에 「항공교통관제절차」(국토교통부고시 제2022-534호)의
실제 값을 넣는다.

`SeparationRuleProfile` 을 상속하는 이유는, 기존 코드가 `isinstance` 로 프로파일을
검증하고 `horizontal_threshold_nm` 을 직접 읽는 곳이 있기 때문이다. 상속하면 그
경로가 그대로 동작하면서 `classify` 만 쌍별 판정으로 바뀐다 — 호출부를 넓게 고치지
않고 판정 근거만 교체하는 방식이다.

**고정 프로파일과 다른 점**은 최저치가 쌍에 따라 달라진다는 것이다. 고시 5-5-8 은
편대비행에 추가분리를 요구하고, 5-5-4 차는 중량등급 조건이 맞을 때만 감축을
허용한다. 그래서 `thresholds_for` 가 두 항적을 받는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sentry_atm.domain.conflict import SeparationRuleProfile

from .data import Dataset, load
from .rules import RuleBook
from .state import AircraftState as RegulatoryState

# 고시 값을 코드에 두지 않는다. 아래 두 상수는 어느 조항에서 왔는지를 적어 두는
# 라벨일 뿐이고, 실제 수치는 전부 airspace.json 전사값에서 읽는다.
PROFILE_ID = "GOSI_2022_534_TERMINAL_V1"
SOURCE_REFERENCE = "MOLIT NOTICE 2022-534 5-5-4 / 4-5-1 / 5-5-8"


def _as_regulatory_state(state: object) -> RegulatoryState | None:
    """`sentry_atm` 항적을 규정 엔진이 읽을 수 있는 형태로.

    규정 판정에 필요한 것은 후류등급과 편대 여부뿐이다(위치는 이미 CPA 계산에서
    쓰였다). 어느 쪽도 없으면 None 을 돌려주고, 호출부는 기본 최저치를 쓴다 —
    없는 정보를 있는 척 채우지 않는다.
    """
    if state is None:
        return None
    wake = getattr(state, "wake_category", None)
    if wake is None:
        return None
    return RegulatoryState(
        callsign=str(getattr(state, "aircraft_id", "UNKNOWN")),
        lat=0.0,
        lon=0.0,
        alt_ft=float(getattr(state, "altitude_ft", 0.0) or 0.0),
        track_deg=float(getattr(state, "heading_deg", 0.0) or 0.0),
        gs_kt=float(getattr(state, "ground_speed_kt", 0.0) or 0.0),
        wake_cat=str(wake),
        is_formation=bool(getattr(state, "is_formation", False)),
    )


@dataclass(frozen=True, slots=True)
class RegulatorySeparationProfile(SeparationRuleProfile):
    """고시에서 최저치를 끌어오는 분리 프로파일.

    기본값(`horizontal_threshold_nm`, `vertical_threshold_ft`)은 조건이 붙지 않는
    기본 최저치이고, `thresholds_for` 가 쌍별 조건을 반영한 값을 낸다.
    """

    rules: RuleBook | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        # `super()` 의 무인자 형태를 쓰지 않는다. `slots=True` 데이터클래스는 클래스
        # 객체를 새로 만들기 때문에 `__class__` 셀이 원래 클래스를 가리켜 어긋난다.
        SeparationRuleProfile.__post_init__(self)
        if self.rules is None:
            raise ValueError("rules must be a RuleBook")
        if not isinstance(self.rules, RuleBook):
            raise TypeError("rules must be a RuleBook")

    # ------------------------------------------------------------------

    def thresholds_for(
        self,
        first: object | None = None,
        second: object | None = None,
    ) -> tuple[float, float]:
        """이 쌍에 적용할 (수평 NM, 수직 ft).

        두 항적의 후류등급을 알 수 없으면 조건 없는 기본 최저치를 쓴다. 모르는
        값을 기본값으로 메워 조건부 감축을 적용하면 실제보다 좁은 기준으로
        판정하게 되므로, 정보가 없을 때는 넓은 쪽에 선다.
        """
        a = _as_regulatory_state(first)
        b = _as_regulatory_state(second)
        if a is None or b is None:
            return self.horizontal_threshold_nm, self.vertical_threshold_ft
        standard = self.rules.separation_standard(a, b)
        return standard.horizontal_nm, standard.vertical_ft

    def clauses_for(
        self,
        first: object | None = None,
        second: object | None = None,
    ) -> tuple[str, ...]:
        """판정에 쓰인 근거 조항 — 관제사에게 상신할 때 붙인다."""
        a = _as_regulatory_state(first)
        b = _as_regulatory_state(second)
        if a is None or b is None:
            return ("5-5-4 가", "4-5-1")
        return self.rules.separation_standard(a, b).clauses


def build(dataset: Dataset | None = None) -> RegulatorySeparationProfile:
    """전사 데이터에서 규정 프로파일을 만든다."""
    ds = dataset or load()
    rules = RuleBook(ds)
    separation = ds.airspace.raw["separation"]
    return RegulatorySeparationProfile(
        profile_id=PROFILE_ID,
        horizontal_threshold_nm=separation["radar_horizontal"]["within_40nm_of_asr_nm"],
        vertical_threshold_ft=separation["vertical"]["below_fl410_ft"],
        source_reference=SOURCE_REFERENCE,
        rules=rules,
    )
