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
