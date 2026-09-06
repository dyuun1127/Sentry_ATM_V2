"""관제 스코프가 그릴 형상 — 전부 AIP 전사값인가.

여기서 지키려는 것은 좌표의 정확도가 아니라 **지어낸 값이 섞여 있지 않은가**다.
정확도는 `tools/validate_aip.py` 가 고시된 거리·방위 67건으로 따로 본다.
"""

from __future__ import annotations

from math import radians

from sentry_atm.api.geometry import airspace_geometry
from sentry_atm.regulation import data as regulation_data
from sentry_atm.regulation.geo import M_PER_NM, parse_latlon, vincenty_inverse

# ENR 2.1-6 「Jungwon Terminal Control Area」가 고시한 섹터. T17 은 청주 GCA 담당이고
# 나머지는 인접 기관이다. T17_UPPER 는 오산 TMA 항이 같은 폴리곤을 다시 고시한 것.
JUNGWON_TMA = {"T17", "T17_UPPER", "T18", "T19", "T20", "T21", "T22"}


def test_every_jungwon_tma_sector_has_a_transcribed_boundary() -> None:
    """중원 TMA 전체가 경계를 갖는가.

    한동안 T17 과 T19 만 폴리곤이 있었다. 나머지는 등급·고도·주파수만 있고
    경계가 없어 조용히 판정에서 빠졌고, 화면에도 담당 섹터 하나만 떴다 —
    그 바깥이 빈 곳처럼 보였지만 실제로는 인접 기관이 이어받는 공역이다.
    """
    blocks = {b["id"]: b for b in regulation_data.load().airspace.raw["tma"]["blocks"]}

    assert set(blocks) == JUNGWON_TMA

    for sector_id, block in blocks.items():
        if sector_id == "T17_UPPER":
            # 좌표를 다시 적지 않고 같은 도형을 가리킨다 — 두 벌이 되면 어긋난다.
            assert block["same_polygon_as"] == "T17"
            assert "polygon" not in block
            continue
        polygon = block.get("polygon")
        assert polygon, f"{sector_id} 에 경계가 없다"
        # 열린 고리로 저장한다. 닫는 점을 넣으면 ray casting 이 변을 두 번 센다.
        assert polygon[0] != polygon[-1], f"{sector_id} 가 닫힌 고리다"
        assert len(polygon) >= 3, f"{sector_id} 의 꼭짓점이 모자란다"
        for node in polygon:
            # AIP 표기 그대로 — 도분초 문자열이지 십진수가 아니다.
            assert node["lat"].endswith(("N", "S")), node
            assert node["lon"].endswith(("E", "W")), node


def test_scope_draws_the_whole_tma_and_marks_which_one_is_ours() -> None:
    """스코프가 인접 섹터까지 그리고, 담당 섹터를 구분해 주는가.

    어디까지가 우리 관할이고 어디부터가 남의 관할인지가 화면에 없으면
    「관할이 넘어간다」는 말을 그림으로 설명할 수 없다.
    """
    sectors = {block["id"]: block for block in airspace_geometry()["tma"]}

    assert set(sectors) == JUNGWON_TMA

    target = [sector_id for sector_id, block in sectors.items() if block["target"]]
    assert target == ["T17"], "담당 섹터는 T17 하나여야 한다"

    for sector_id, block in sectors.items():
        assert block["points"], f"{sector_id} 에 그릴 점이 없다"
        assert block["lower_ft"] < block["upper_ft"], sector_id

    # 같은 도형을 고도로 나눠 두 기관이 쓴다 (ENR 2.1 이 T17 을 두 번 고시한다).
    assert sectors["T17_UPPER"]["points"] == sectors["T17"]["points"]
    assert sectors["T17"]["unit"] == "CHEONGJU GCA"
    assert sectors["T17_UPPER"]["unit"] == "OSAN APP"
    assert sectors["T17"]["upper_ft"] == sectors["T17_UPPER"]["lower_ft"] == 6_500.0

    # 이름표는 환산값이 아니라 고시된 표기로 읽힌다.
    assert sectors["T17"]["label"] == (
        "T17 CHEONGJU GCA 1,000ft AGL~6,500ft AMSL Class D/E"
    )
    assert sectors["T22"]["label"] == "T22 JUNGWON APP 9,500ft AMSL~FL175 Class E"


def test_every_clickable_zone_carries_what_the_panel_shows() -> None:
    """눌렀을 때 띄울 것이 형상에 실려 오는가.

    화면이 고도 기준을 스스로 환산하거나 활동·관할을 채워 넣기 시작하면 전사
    데이터와 두 벌이 되고, 두 벌은 반드시 어긋난다. 관제사가 이 상자를 보고
    판단하므로 여기 뜬 것은 고시가 말한 것이어야 한다.

    포함 판정에 쓸 AMSL 환산값(`lower_ft`/`upper_ft`)과 사람이 읽을 고시 표기
    (`lower_label`/`upper_label`)를 함께 낸다 — 앞은 계산용, 뒤는 표시용이다.
    """
    geometry = airspace_geometry()

    zones = [
        *geometry["restricted"],
        *geometry["moa"],
        *geometry["neighbour_ctr"],
        *geometry["tma"],
    ]
    assert len(zones) == 3 + 5 + 1 + 7

    for zone in zones:
        assert zone["id"]
        assert zone["kind"]
        assert zone["points"], zone["id"]
        assert zone["lower_ft"] < zone["upper_ft"], zone["id"]
        assert zone["lower_label"] and zone["upper_label"], zone["id"]

    by_id = {zone["id"]: zone for zone in zones}

    # 제한구역은 무엇을 하는 곳인지가 핵심이다. 고도만 보여 주면 왜 피해야 하는지
    # 알 수 없다.
    gwaesan = by_id["RK R152"]
    assert gwaesan["name"] == "괴산"
    assert gwaesan["activity"] == "강하훈련"
    assert gwaesan["authority"] == "제13특수임무여단"
    assert gwaesan["radius_nm"] == 2.0
    assert gwaesan["upper_label"] == "2,100ft AMSL"

    # 원은 반경으로, 폴리곤은 꼭짓점으로 포함을 본다 — 화면이 둘을 갈라 쓴다.
    assert by_id["RK R152"]["centre"]
    assert "centre" not in by_id["MOA 3A"]

    # 등급이 무엇을 뜻하는지까지 실어 보낸다. Class D/E 회랑과 Class C 터미널이
    # 붙어 있어, 등급만으로는 분리를 제공하는지 알기 어렵다.
    assert by_id["T17"]["ifr_vfr_separation"] is False
    assert by_id["T18"]["ifr_vfr_separation"] is True
    assert by_id["T17"]["frequencies"] == [134.0, 265.75]


CHO = (36 + 43 / 60 + 4.9 / 3600, 127 + 29 / 60 + 38.7 / 3600)


def _range_and_radial(lat: float, lon: float) -> tuple[float, float]:
    """CHO VOR 기준 거리(NM)와 자기방위(VAR 9°W)."""
    metres, bearing, _ = vincenty_inverse(CHO[0], CHO[1], lat, lon)
    return metres / M_PER_NM, (bearing + 9.0) % 360.0


def test_minimum_altitude_chart_vertices_sit_where_the_chart_says() -> None:
    """AD 2-16 의 꼭짓점이 고시한 라디얼·거리에 실제로 앉는가.

    차트는 경계를 「24 NM/050°」처럼 VOR 라디얼로 적고, 그 옆에 도분초 좌표를
    함께 준다. 우리가 전사한 것은 좌표 쪽이다 — 라디얼 값은 VOR 이 교정된 시점의
    자기편차를 따라 계산값과 3~5° 어긋나기 때문이다.

    그래서 이 시험은 좌표가 **이름이 말하는 자리에 있는지**를 본다. 이름을
    `R24_050` 처럼 지었으므로, 옮겨 적다 한 줄이 밀리면 여기서 걸린다.
    """
    chart = regulation_data.load().msa

    assert len(chart.vertices) == 23

    offsets: dict[str, float] = {}
    for name, node in chart.vertices.items():
        radius_text, radial_text = name.lstrip("R").split("_")
        nm, mag = _range_and_radial(parse_latlon(node["lat"]), parse_latlon(node["lon"]))
        # 차트는 호의 이름을 내림으로 적는다 (14.9 NM 점이 「14 NM」 호 위에 있다).
        assert abs(nm - float(radius_text)) < 1.2, f"{name}: {nm:.1f} NM"
        # 방위는 각도가 아니라 **거리**로 본다. 라디얼 값은 5° 단위로 반올림돼
        # 있고 VOR 교정 편차까지 얹히므로, 4 NM 점에서는 그 합이 12° 가 되지만
        # 옆으로는 1 NM 도 벌어지지 않는다. 각도로 재면 안쪽 점이 늘 걸린다.
        offset_deg = (mag - float(radial_text) + 180) % 360 - 180
        offsets[name] = offset_deg
        assert radians(abs(offset_deg)) * nm < 2.0, (
            f"{name}: 옆으로 {radians(abs(offset_deg)) * nm:.2f} NM"
        )


    # 남은 차이는 라디얼마다 다르다 (남쪽 -1.3° ~ 북동쪽 +4.6°). 한 방향으로
    # 쏠린 것이 아니므로 「상수 편차」로 설명할 수 없고, 라디얼별 VOR 정렬 차이와
    # 5° 반올림이 섞인 결과로 본다. 어느 쪽이든 옆으로 2 NM 을 넘지 않는다.


def test_minimum_altitude_chart_is_display_only() -> None:
    """이 자료가 판정으로 새어 들어가지 않았는가.

    최저고도를 판정에 넣으면 어떤 회피안이 살아남는지가 달라진다. 발표 직전에
    조용히 바뀌면 안 되므로, **판정 계층이 이 자료를 읽지 않는다**는 것을 못박는다.
    넣기로 결정하면 이 시험을 먼저 고치게 된다 — 그때 시연 전체를 다시 돌린다.
    """
    from pathlib import Path

    chart = regulation_data.load().msa
    assert "표시 전용" in chart.raw["_scope"]

    root = Path(__file__).resolve().parents[3] / "src" / "sentry_atm"
    judging = [
        root / "resolution",
        root / "conflict",
        root / "risk",
        root / "regulation" / "rules.py",
        root / "regulation" / "separation.py",
    ]
    for target in judging:
        files = target.rglob("*.py") if target.is_dir() else [target]
        for path in files:
            assert "msa" not in path.read_text(encoding="utf-8"), path


def test_scope_gets_the_chart_boundaries_obstacles_and_numbers() -> None:
    """스코프가 그릴 형상으로 나오는가.

    원호는 잘게 나눠 보낸다 — 두 점을 직선으로 이으면 24 NM 호에서 눈에 보이게
    꺾인다. 장애물 좌표와 표고는 AIP AD 2.10 전사값이다.
    """
    chart = airspace_geometry()["msa"]

    assert len(chart["lines"]) == 15
    assert len(chart["altitudes"]) == 10
    assert len(chart["obstacles"]) == 3

    arcs = [line for line in chart["lines"] if line["kind"] == "arc"]
    radials = [line for line in chart["lines"] if line["kind"] == "radial"]
    assert arcs and radials
    # 호는 촘촘하고, 라디얼은 두세 점이면 족하다.
    assert max(len(line["points"]) for line in arcs) > 10
    assert max(len(line["points"]) for line in radials) <= 3

    by_id = {item["id"]: item for item in chart["obstacles"]}
    assert by_id["RKTUOB001"]["elevation_ft"] == 1962
    assert by_id["RKTUOB003"]["elevation_ft"] == 1828

    # 저온보정값은 있는 것만 싣는다. 없는 자리를 0 으로 채우면 화면이 0 을 그린다.
    cold = [item["low_temperature_ft"] for item in chart["altitudes"]]
    assert None in cold and 5100 in cold
