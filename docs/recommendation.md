# Resolution Recommendation Contract

## 1. 범위

Phase 10-A는 Safety Validation을 통과한 Resolution Candidate를 관제사에게 제시하기 위한 불변
Domain 계약을 정의한다. 실제 순위 계산, 설명문 생성, 관제사 Accept/Modify/Reject 처리와 Aircraft
Runtime 적용은 아직 포함하지 않는다.

```text
ResolutionCandidate + CandidateSafetyValidationResult(SAFE)
                         ↓
               ResolutionRecommendation
                         ↓
              ResolutionRecommendationSet
                 ├─ Primary rank 1
                 └─ Alternatives rank 2..N
```

Recommendation은 자동 관제 명령이 아니다. 관제사 결정 전에는 Candidate 또는 Aircraft Runtime을
변경하지 않는다 (`ASM-028`, `ASM-038`).

## 2. 추천 가능 조건

`ResolutionRecommendation`은 다음 조건을 모두 만족해야 한다.

- Candidate는 `NO_ACTION`이 아닌 실행 후보다.
- Validation Result가 같은 Candidate ID를 참조한다.
- Validation Verdict가 `SAFE`다.
- Recommendation 생성시각은 Candidate 적용시각과 Safety 평가시각보다 이르지 않다.
- 순위는 1부터 시작하는 양의 정수다.

따라서 `UNSAFE`, `INEFFECTIVE`, `NO_ACTION`은 Domain 생성 시점에 거부된다. 화면이나 후속 Service가
이 조건을 다시 추론할 필요가 없다.

## 3. 설명 가능한 긍정 근거

추천에는 다음 Reason Code를 모두 보존한다.

| Reason Code | 의미 |
|---|---|
| `VALIDATED_SAFE` | Safety Validator가 SAFE로 판정함 |
| `PRIMARY_CONFLICT_RESOLVED` | 원래 Conflict Pair가 해소됨 |
| `NO_SECONDARY_CONFLICT` | 전체 Traffic 재평가에서 2차 Conflict가 없음 |
| `PERFORMANCE_FEASIBLE` | 대상 Aircraft Performance Envelope 안에 있음 |
| `NO_RULE_VIOLATION` | 구성된 Rule 위반이 없음 |

Reason Code는 안전성 증거이고 비용 순위의 근거는 아니다. Phase 10-B Ranking Policy는 Candidate의
Cost를 별도 입력으로 사용하고, 사람이 읽을 수 있는 `explanation`을 생성한다.

## 4. Recommendation Set

`ResolutionRecommendationSet`은 하나의 Exception, Candidate Batch와 Validation Run을 출처 ID로
연결한다. 모든 추천은 같은 UTC 생성시각을 가지며 Rank는 1부터 빠짐없이 이어져야 한다. Candidate,
Validation Result와 Recommendation ID는 각각 고유하다.

- `primary_recommendation`: Rank 1 또는 `None`
- `alternatives`: Rank 2 이후의 불변 Tuple
- `has_recommendation`: 추천 존재 여부
- `AVAILABLE`: 한 개 이상의 SAFE 추천 존재
- `NO_SAFE_CANDIDATE`: 추천 Tuple이 비어 있으며 관제사 수동 검토가 필요한 결과

안전 후보가 없을 때 임의의 차선 후보를 추천하지 않고 명시적인 빈 결과를 반환한다.

## 5. Golden Demo 기대 Mapping

Phase 9-E 계산 결과에서는 `CAND-A`만 `SAFE`이므로 Phase 10-B의 Golden Recommendation Set은
`CAND-A` 하나를 Rank 1로 포함해야 한다. `CAND-B`부터 `CAND-E`까지는 추천 대상이 될 수 없다.
이 Mapping은 Phase 10-A Domain에 하드코딩하지 않는다.

## 6. 다음 단계

Phase 10-B는 Candidate Batch와 같은 Validation Run을 입력받아 SAFE Action Candidate만 추출하고,
교체 가능한 비용 정책으로 결정론적 Rank와 설명문을 계산한다.
