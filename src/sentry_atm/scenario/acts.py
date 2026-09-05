"""13단계를 네 막으로 묶는다.

단계 열세 개를 그대로 늘어놓으면 시연을 보는 쪽이 지금 어디쯤인지 가늠하지
못한다. 막은 그 열세 개에 얼개를 준다 — 평시에서 출격, 비상복귀, 우선착륙으로
이어지는 흐름이 한 눈에 보인다.

각 막의 `headline` 은 그 구간에서 **무엇을 보여 주려는지**다. 시연에서 말로
설명할 한 문장을 화면이 대신 들고 있는 것이며, 단계 이름과 달리 주장이다.

이 표는 오프라인 도구에만 있었고 산출물 JSON 에 구워져 콘솔로 갔다. 실시간
화면은 그 JSON 을 거치지 않으므로 API 로 받아야 한다. 도구에 남겨 두고 한 벌을
더 만들면 두 화면이 서로 다른 막을 그리게 된다.
"""

from __future__ import annotations

# (막 번호, 이름, 속한 단계, 이 구간의 주장, 무슨 일이 일어나는가)
ACT_GROUPS: tuple[tuple[int, str, tuple[int, ...], str, str], ...] = (
    (
        1,
        "평시",
        (1, 2),
        "민항과 군이 같은 활주로를 나눠 쓴다",
        "시간표에 맞춰 도착·출발이 교대로 활주로를 쓰고, 작전지역이 지정된다.",
    ),
    (
        2,
        "출격",
        (3, 4, 5, 6),
        "출격 비용은 도착 흐름에서 치러진다",
        "전투기가 민항 슬롯 사이로 이륙해 SID 를 타고 나가며 관제권이 순차 이양된다.",
    ),
    (
        3,
        "비상복귀",
        (7, 8, 9, 10),
        "판단이 필요한 것만 근거와 함께 상신한다",
        "TCAS 미장착 전투기가 비상 선언, 최단 복귀경로가 도착 흐름과 경합한다.",
    ),
    (
        4,
        "우선착륙",
        (11, 12, 13),
        "순번이 아니라 물리적 최단 도달시각",
        "공고 체공장주로 민항을 붙들고 비상기를 먼저 내린 뒤 순서를 재구성한다.",
    ),
)


def acts_from_steps(steps, *, shift_s: float = 0.0, end_s: float | None = None) -> list[dict]:
    """단계 목록을 막으로 묶는다.

    `shift_s` 는 단계 시각이 아직 옮겨지지 않았을 때 쓴다. 이미 시나리오 원점
    기준이면 0 이다 — 두 번 옮기면 막이 통째로 밀린다.
    """
    by_number = {step.n: step for step in steps}
    out: list[dict] = []
    for number, name, members, headline, text in ACT_GROUPS:
        found = [by_number[m] for m in members if m in by_number]
        if not found:
            continue
        out.append(
            {
                "n": number,
                "name": name,
                "t0": round(min(step.t_s for step in found) + shift_s, 1),
                "t1": 0.0,
                "headline": headline,
                "text": text,
                "steps": [step.n for step in found],
            }
        )
    # 각 막의 끝은 다음 막의 시작이다. 마지막 막만 시나리오 끝까지 간다.
    last = end_s if end_s is not None else max((a["t0"] for a in out), default=0.0)
    for index, act in enumerate(out):
        act["t1"] = round(out[index + 1]["t0"] if index + 1 < len(out) else last, 1)
    return out


__all__ = ["ACT_GROUPS", "acts_from_steps"]
