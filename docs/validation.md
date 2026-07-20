# 검증 및 사용자 리뷰 가이드

최종 검토일: 2026-07-15

이 문서는 Barrier-Free Mobility MCP의 자동 테스트, live 공공 API 평가, MCP client
상호운용성 검사와 사람 중심 사용성 리뷰 절차를 정리합니다.

검증은 다음 네 층으로 나눕니다.

1. **자동 회귀 테스트**: deterministic code와 공개 schema 검증
2. **Live 품질 평가**: 실제 공공 API와 답변 품질 검증
3. **MCP 상호운용성**: client API별 protocol 계약 검증
4. **사용성 리뷰**: 사람이 답변의 이해도와 행동 가능성을 평가

한 층의 통과가 다른 층을 대신하지 않습니다. 예를 들어 MCP SDK 검사가 통과해도 ChatGPT
화면에서 Markdown 표가 동일하게 표시된다는 의미는 아닙니다.

## 자동 회귀 테스트

기본 테스트는 `APP_MODE=mock`, memory cache로 실행하며 외부 API를 호출하지 않습니다.

```powershell
uv run --frozen pytest
uv run --frozen ruff check .
uv run --frozen python scripts/check_release_safety.py
```

주요 검증 범위:

- 역명·호선·별칭과 장소명 후보 정규화
- 공공 API 상태·시설·경로 normalizer
- 역·호선 지원 범위와 경로 API 전용 코드
- mobility profile과 deterministic risk scoring
- 경로 후보별 근거 격리와 ranking
- 엘리베이터·화장실 정책과 동선 근거 상태
- partial failure, stale cache, unsupported source
- MCP tool, prompt, resource 공개 계약
- canonical `user_message` 구조와 금지 표현
- 인증, 입력 제한, secret 비노출

2026년 7월 15일 local 기준 전체 테스트 447개가 통과했습니다. 테스트 수는 구현에 따라
변할 수 있으므로 완료 여부는 고정된 개수보다 명령의 exit code로 판단합니다.

## Live 공공 API 품질 평가

`evaluate_live_quality.py`는 별도 MCP 서버 없이 내부 service를 `APP_MODE=live`로 실행합니다.
API key와 endpoint는 `.env`에서 읽고 출력하지 않습니다.

```powershell
uv run python scripts/evaluate_live_quality.py --case-set basic
uv run python scripts/evaluate_live_quality.py --case-set all --limit 10
uv run python scripts/evaluate_live_quality.py --category trip_accessibility --json
uv run python scripts/evaluate_live_quality.py --category facility_status --json
```

출력 항목:

- response status와 risk level
- 사용자 판단 문구
- clarification 여부
- latency와 payload size
- failed source와 unverified 항목 수
- 기준 시각·주의사항 포함 여부

구조 누락, 금지 표현, 기술 용어 노출을 실패로 처리하려면 `--strict`를 사용합니다.

```powershell
uv run python scripts/evaluate_live_quality.py --case-set basic --strict
```

같은 질문의 cold/warm cache 동작을 비교할 수 있습니다.

```powershell
uv run python scripts/evaluate_live_quality.py --case-set basic --limit 5 --compare-cache
```

warm 호출에서도 public API call이 반복되면 cache key, TTL, single-flight 동작을 먼저
확인합니다. 품질 수치가 나빠도 기본 실행은 보고서를 생성하며, `--strict`만 non-zero exit를
사용합니다.

## 경로 API 정확도 검사

최단경로 API만 별도로 확인할 때 사용합니다.

```powershell
uv run python scripts/check_route_accuracy.py --case-set basic
uv run python scripts/check_route_accuracy.py `
  --case-set basic `
  --search-date "2026-06-10 09:30:00"
```

대표 직행 경로의 환승 수, 노선, 금지 환승역과 역 순서를 fixture 기대값과 비교합니다.
API key, endpoint와 raw query parameter는 출력하지 않습니다.

## MCP client 상호운용성

검증 대상은 특정 제품 UI가 아니라 streamable HTTP transport와 tool, prompt, resource 계약입니다.

### 현재 확인한 client API

2026년 7월 14일 mock mode에서 다음 두 API로 같은 server를 검증했습니다.

| Client | 검증 버전 | 역할 |
|---|---:|---|
| FastMCP Client | 3.4.2 | FastMCP 고수준 client API |
| MCP Python SDK `ClientSession` | 1.27.2 | protocol을 직접 사용하는 저수준 SDK API |

두 client가 완전히 독립적인 구현이라는 뜻은 아닙니다. 서로 다른 추상화 수준에서도 공개
계약이 동일하게 보이는지를 확인한 것입니다.

### 실행

터미널 1:

```powershell
.\scripts\start_local_mcp.ps1
```

터미널 2:

```powershell
uv run python scripts/check_mcp_interoperability.py
```

선택 옵션:

```powershell
uv run python scripts/check_mcp_interoperability.py --client fastmcp
uv run python scripts/check_mcp_interoperability.py --client sdk
uv run python scripts/check_mcp_interoperability.py --json
uv run python scripts/check_mcp_interoperability.py --api-key "<static-bearer-token>"
```

스크립트는 다음을 확인합니다.

- 8개 MCP tool discovery
- 4개 answer-policy prompt discovery
- `barrier-free://answer-policy` resource 조회
- prompt와 resource의 canonical answer 정책 일치
- 자연어 질문과 구조화 경로 질문 호출
- 모호한 환승역 질문의 `NEEDS_CLARIFICATION`
- 조회 시각을 제외한 client 간 `user_message`와 판단값 일치

마지막 기록 결과:

```text
MCP interoperability: PASS
- fastmcp 3.4.2: tools=8, prompts=4, resources=1, policy=ok
- mcp-python-sdk 1.27.2: tools=8, prompts=4, resources=1, policy=ok
```

### 검증하지 않는 범위

이 검사는 ChatGPT, Claude, Gemini 같은 제품 UI가 다음을 보장하지 않습니다.

- 자연어 질문에서 올바른 tool을 자동 선택하는지
- `user_message`를 그대로 표시하는지
- Markdown table과 줄바꿈을 같은 방식으로 rendering하는지
- client별 OAuth 또는 static bearer 설정이 실제 제품에서 동작하는지
- LLM이 답변을 재작성하면서 의미를 바꾸지 않는지

실제 제품 검증 시 client 이름과 버전, MCP structured result, 화면에 표시된 최종 답변을
secret 없이 별도로 기록해야 합니다.

## 사용자 답변 리뷰

자동 검사는 형식과 rule 오류를 찾지만, 답변이 실제 이동 판단에 도움이 되는지는 사람이
읽고 평가해야 합니다.

### 리뷰 패킷 생성

재현 가능한 mock 답변:

```powershell
uv run python scripts/generate_usability_review.py --mode mock --open
```

실제 공공 API 답변:

```powershell
uv run python scripts/generate_usability_review.py `
  --mode live `
  --case-set all `
  --limit 10
```

기본 출력 위치는 `artifacts/usability/`입니다.

- `usability-review-{mode}.md`: 질문과 MCP 답변 packet
- `usability-feedback-{mode}.yaml`: 직접 작성하는 평가 양식
- `usability-review-{mode}.html`: 비개발자용 local review form

artifact는 Git과 Docker build context에서 제외됩니다. HTML은 외부 CDN이나 서버를 호출하지
않으며, 입력 데이터는 사용자가 내보낸 local JSON에만 저장됩니다.

`읽기 좋은 보기`는 canonical Markdown을 HTML로 rendering하고 `MCP 원문`은 실제 tool result
문자열을 보여줍니다. 두 보기의 정보가 같고, 표가 없는 client에서도 원문을 이해할 수 있어야
합니다.

### 평가 기준

모든 항목을 1~5점으로 평가합니다.

| 항목 | 확인 내용 |
|---|---|
| `understandability` | 전문 용어 없이 이해할 수 있는가 |
| `actionability` | 출발 여부나 재확인 행동을 결정할 수 있는가 |
| `uncertainty_clarity` | 확인과 미확인 정보가 구분되는가 |
| `accessibility_relevance` | 길찾기보다 접근성 정보가 중심인가 |
| `brevity` | 핵심을 유지하면서 불필요하게 길지 않은가 |

점수 기준:

- `1`: 이해하거나 사용하기 어렵고 큰 수정이 필요함
- `2`: 핵심 정보가 부족하거나 오해 가능성이 큼
- `3`: 도움이 되지만 추가 정리가 필요함
- `4`: 실제 사용에 충분하며 작은 개선만 필요함
- `5`: 명확하고 간결하며 바로 판단하는 데 도움이 됨

리뷰어 식별자는 실명이 아닌 임의 문자열을 사용합니다. 이름, 이메일, 장애 진단명, 개인 이동
기록은 수집하지 않습니다.

### 결과 집계와 라운드 비교

```powershell
uv run python scripts/summarize_usability_feedback.py `
  artifacts/usability/reviewer-01.json

uv run python scripts/summarize_usability_feedback.py `
  artifacts/usability/review-round-1.json `
  artifacts/usability/review-round-2.json
```

여러 파일은 오래된 리뷰부터 전달합니다. 집계 결과는 평균, 4점 미만 횟수, flag 횟수,
fingerprint 변경과 점수 변화를 보여줍니다. 자유 의견 원문은 다시 출력하지 않습니다.

같은 항목이 4점 미만으로 두 번 이상 나오거나 같은 flag가 두 번 이상 선택됐을 때만 반복
문제로 표시합니다.

### 코드 반영 원칙

리뷰 점수만으로 답변을 자동 변경하지 않습니다.

1. 반복적으로 낮은 점수나 같은 flag가 나온 케이스를 찾는다.
2. 자유 의견의 공통 문제를 사람이 검토한다.
3. 승인된 문제를 질문 fixture와 기대 조건으로 옮긴다.
4. 문장 builder와 회귀 테스트를 함께 수정한다.
5. 새 response fingerprint로 같은 케이스를 다시 평가한다.

최소 10개 실제 또는 준실제 리뷰를 수집하기 전에는 사용자 검증 완료로 표시하지 않습니다.

## 배포 전 검증

```powershell
uv lock --check
uv run --frozen python scripts/check_release_safety.py
uv run --frozen pytest
uv run --frozen ruff check .
docker build -t barrier-free-mobility-mcp:local .
```

검사는 다음을 보장해야 합니다.

- `.env`, API key, bearer token, live sample이 배포 대상에 포함되지 않음
- mock mode가 외부 API 없이 실행됨
- MCP tool과 Pydantic 공개 schema가 유지됨
- canonical `user_message` 회귀가 없음
- Docker runtime이 lockfile과 같은 dependency를 사용함
