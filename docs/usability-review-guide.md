# 사용자 답변 사용성 리뷰 가이드

이 가이드는 Barrier-Free Mobility MCP의 `user_message`를 실제 사용자 관점에서 검토하는
절차를 설명합니다. 자동 테스트나 live 품질 검사는 형식 오류를 찾지만, 문장이 실제 이동
결정에 도움이 되는지는 사람이 직접 읽고 평가해야 합니다.

## 1. 리뷰 패킷 생성

재현 가능한 답변을 먼저 검토하려면 mock mode를 사용합니다.

```powershell
uv run python scripts/generate_usability_review.py --mode mock --open
```

실제 공공 API 기준 답변은 live mode로 생성합니다. 공공 API key는 기존 `.env`에서만 읽으며
리뷰 문서에는 저장하지 않습니다.

```powershell
uv run python scripts/generate_usability_review.py --mode live --case-set all --limit 10
```

기본 출력 위치는 `artifacts/usability/`입니다.

- `usability-review-{mode}.md`: 질문과 MCP 답변을 읽는 리뷰 패킷
- `usability-feedback-{mode}.yaml`: 점수와 문제 표시를 작성하는 양식
- `usability-review-{mode}.html`: 비개발자가 브라우저에서 평가하는 로컬 폼

생성된 파일은 local artifact이며 Git과 Docker build context에서 제외됩니다.

HTML 폼은 한 화면에 질문 하나를 표시합니다. 5개 점수와 문제 표시, 자유 의견을 작성한 뒤
`초안 JSON 내보내기` 또는 `완료 JSON 내보내기`를 선택합니다. 완료 JSON은 모든 케이스의
점수가 입력돼야 내보낼 수 있습니다. 외부 CDN이나 서버를 호출하지 않으며 데이터는 사용자가
내보낸 로컬 파일에만 저장됩니다.

`읽기 좋은 보기`는 canonical Markdown의 제목, 목록, 역별 접근성 표를 안전한 HTML로
표시합니다. `MCP 원문`에서는 실제 LLM client가 받는 문자열을 그대로 확인할 수 있습니다.
두 보기의 정보 내용은 같으며, 표가 없는 client에서도 원문을 읽을 수 있어야 합니다.

## 2. 평가 기준

모든 항목은 1~5점으로 평가합니다.

- `1`: 이해하거나 사용하기 어렵고 큰 수정이 필요함
- `2`: 핵심 정보가 부족하거나 오해 가능성이 큼
- `3`: 일부 도움이 되지만 추가 설명이나 정리가 필요함
- `4`: 실제 사용에 충분하며 작은 개선만 필요함
- `5`: 명확하고 간결하며 바로 행동을 결정하는 데 도움이 됨

평가 항목:

- `understandability`: 전문 용어 없이 이해할 수 있는가
- `actionability`: 출발 여부나 재확인 행동을 결정할 수 있는가
- `uncertainty_clarity`: 확인된 정보와 미확인 정보가 구분되는가
- `accessibility_relevance`: 길찾기보다 접근성 정보가 중심인가
- `brevity`: 핵심 정보를 유지하면서 불필요하게 길지 않은가

문제가 발견되면 양식의 `flags`에 리뷰 문서에 표시된 식별자를 추가합니다. 자유 의견에는
구체적인 개선 방향만 작성하고 이름, 이메일, 장애 진단명, 개인 이동 기록은 넣지 않습니다.

## 3. 리뷰 파일 관리

HTML 폼의 `리뷰어 식별자`에는 실명이 아닌 임의 식별자를 사용합니다. 중간에 멈출 때는 초안
JSON을 내보내고, 다음에 같은 HTML의 `저장한 JSON 불러오기`에서 선택해 이어서 작성합니다.
답변 fingerprint가 달라진 JSON은 현재 리뷰에 불러올 수 없습니다.

```powershell
uv run python scripts/generate_usability_review.py --mode mock --open
```

브라우저 폼을 사용할 수 없는 경우 생성된 YAML을 복사해 직접 작성할 수도 있습니다. JSON과
YAML은 같은 schema를 사용합니다. 빈 점수가 있거나 허용되지 않은 flag가 있으면 집계 도구가
파일 위치와 필드명만 표시하고 종료합니다.

```powershell
uv run python scripts/summarize_usability_feedback.py artifacts/usability/reviewer-01.json
uv run python scripts/summarize_usability_feedback.py artifacts/usability/reviewer-*.json --json
```

집계 결과에는 평균, 4점 미만 응답 수, 문제 flag 횟수, 답변 fingerprint 버전 수만 포함됩니다.
자유 의견 원문은 다시 출력하지 않습니다.

## 4. 코드 반영 원칙

리뷰 점수만으로 `user_message`를 자동 변경하지 않습니다.

1. 반복적으로 낮은 점수나 같은 flag가 나온 케이스를 확인합니다.
2. 자유 의견에서 공통 문제를 사람이 검토합니다.
3. 승인된 문제를 `tests/fixtures/user_question_cases.yaml`의 기대 조건으로 옮깁니다.
4. 문장 builder를 수정하고 회귀 테스트를 추가합니다.
5. 새 답변 fingerprint로 같은 케이스를 다시 검토합니다.

최소 10개 실제 또는 준실제 리뷰를 수집하기 전에는 “사용자 검증 완료”로 표시하지 않습니다.
