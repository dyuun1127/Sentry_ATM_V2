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

## 6. Deterministic Recommendation Ranking Service

Phase 10-B의 `DeterministicRecommendationRankingService`는 다음 입력을 사용한다.

- 하나의 `ResolutionCandidateBatch`
- 그 Batch ID를 참조하고 모든 Candidate 결과를 정확히 한 번 포함하는
  `ResolutionSafetyValidationRun`
- 시스템 현재시간이 아닌 명시적인 timezone-aware UTC 생성시각
- 교체 가능한 `RecommendationRankingProfile`

Validation은 Candidate 생성보다 이를 수 없고 Recommendation은 Validation보다 이를 수 없다. 입력
Candidate나 Validation Result를 변경하지 않으며 같은 입력은 같은 ID, Rank와 설명을 생성한다.

### 6.1 `POC_RECOMMENDATION_V1` 순서

SAFE Action Candidate만 다음 Tuple의 오름차순으로 정렬한다.

1. `operational_cost_score`
2. `estimated_delay_seconds`
3. `estimated_path_extension_nm`
4. `candidate_id`

가중치를 숨겨 합산하지 않고 원래 비용 필드를 그대로 비교한다. 기본 Profile은 주 추천을 포함해 최대
3개까지 보존한다. 이는 안전성보다 비용을 우선한다는 뜻이 아니며 Safety Filter를 통과한 후보 사이의
표시 순서일 뿐이다.

### 6.2 설명과 Golden 결과

서비스는 Maneuver 목표값, 5가지 긍정 안전 근거와 Candidate Cost를 안정적인 설명문으로 만든다.
Heading, Altitude, Speed, Entry Delay와 Sequence Change를 각각 타입에 맞게 표현한다.

Phase 9-E Golden Batch와 Validation Run을 입력하면 실제 결과는 다음과 같다.

| Rank | Candidate | Target | 결과 |
|---:|---|---|---|
| 1 | `CAND-A` | `MIL-F01` | 9,000 ft 목표, `AVAILABLE` |

`CAND-B`는 2차 Conflict, `CAND-C`는 1차 Conflict 지속, `CAND-D`는 Rule 위반,
`CAND-E`는 기준선이므로 모두 자동으로 제외된다. Candidate ID별 예외 분기는 사용하지 않는다.

## 7. 다음 단계

Phase 10-C는 Recommendation Set을 UI와 HTTP Adapter가 사용할 수 있는 JSON 호환 Read Model/API
계약으로 변환하되 Domain Source of Truth와 관제사 결정을 분리한다.
