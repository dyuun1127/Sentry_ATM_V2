"""관제 스코프가 그릴 형상 — 전부 AIP 전사값인가.

여기서 지키려는 것은 좌표의 정확도가 아니라 **지어낸 값이 섞여 있지 않은가**다.
정확도는 `tools/validate_aip.py` 가 고시된 거리·방위 67건으로 따로 본다.
"""

from __future__ import annotations

from sentry_atm.api.geometry import airspace_geometry
from sentry_atm.regulation import data as regulation_data

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
