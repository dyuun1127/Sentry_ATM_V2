"""체계 전체가 쓰는 활성 분리 프로파일.

탐지기·위험평가기·세션 읽기모델이 각자 기본값을 들고 있으면, 한 곳만 바꿨을 때
서로 다른 기준으로 판정하게 된다. 실제로 `ConflictRiskEvaluator` 는 사건의
`rule_profile_id` 가 자기 프로파일과 다르면 거부하므로, 그 불일치는 조용한 오차가
아니라 즉시 실패로 나타난다.

그래서 **활성 프로파일을 한 곳에서 정하고 나머지가 그것을 따른다.** 주입은 그대로
가능하며, 주입하지 않았을 때의 기본값만 여기서 결정된다.
"""

from __future__ import annotations

from functools import lru_cache

from .separation import RegulatorySeparationProfile, build


@lru_cache(maxsize=1)
def active_separation_profile() -> RegulatorySeparationProfile:
    """현재 적용 중인 분리 최저치.

    고시 「항공교통관제절차」(국토교통부고시 제2022-534호)에 근거한다. 전사 데이터를
    읽어야 하므로 한 번만 만들어 재사용한다 — 매 호출마다 파일을 읽으면 판정 경로가
    파일 입출력에 묶인다.
    """
    return build()


def reset_cache() -> None:
    """참조 데이터를 바꿔 다시 읽어야 할 때 (시험용)."""
    active_separation_profile.cache_clear()
