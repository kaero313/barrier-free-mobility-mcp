# Barrier-Free Mobility MCP

서울 지하철 교통약자 접근성 정보를 MCP tool로 제공하는 FastMCP 서버입니다.
휠체어, 유모차, 계단 또는 에스컬레이터 이용이 어려운 사용자의 이동 조건을 반영해
출발역에서 도착역까지의 접근성 위험도를 구조화된 결과로 반환합니다.

이 프로젝트는 단순 공공 API wrapper가 아닙니다. 핵심 tool은
`check_accessible_trip`이며, 공공 API 응답을 정규화한 뒤 deterministic risk engine으로
위험 점수, 위험 수준, 근거, 한계, 실패한 데이터 소스, 경로 후보를 계산합니다.

서버 내부에서는 LLM을 호출하지 않습니다. LLM은 MCP tool 결과를 해석하고 설명하는 역할만
맡고, 실제 판단은 백엔드 규칙 기반 엔진이 수행합니다.

## 프로젝트 자료

- 기술 블로그: [공공데이터로 교통약자 이동 MCP 서버를 만들어보자](https://kaero313.github.io/posts/mcp_3/)
- 상세 설계·운영 기록: [Barrier-Free Mobility MCP Notion 허브](https://torpid-icon-d8a.notion.site/Barrier-Free-Mobility-MCP-39f4054272b58145b90ed07cd4f38ce0)

## 설계 원칙

- 일반 길찾기보다 엘리베이터, 환승·출구 동선, 장애인화장실 근거를 우선합니다.
- 시설 존재와 사용자가 필요한 전체 동선 확인을 같은 의미로 판단하지 않습니다.
- 확인된 정보, 미확인 정보, 지원 범위 밖, API 실패를 구분합니다.
- `user_message`는 현재 결론과 출발 전 행동을 먼저 제공하고 기술 metadata는 뒤에 둡니다.
- 새로운 tool·API·운영 인프라는 구체적인 사용자 문제나 배포 요구가 있을 때만 추가합니다.

자세한 기준은 [제품 및 사용자 답변 원칙](docs/product-principles.md), 남은 작업은
[ROADMAP](ROADMAP.md)에서 관리합니다.

## 주요 기능

- 역명, 호선, 별칭 기반 역명 정규화
- 역사 내 편의시설 조회
- 엘리베이터 가동 상태 조회
- 장애인화장실 정보 조회
- 엘리베이터·장애인화장실 단독 자연어 질문 응답
- 출발역-도착역 경로 후보 조회
- mobility profile 기반 접근성 위험도 계산
- 일부 공공 API 실패 시 partial structured response 반환
- mock mode와 live API mode 분리

## 로컬 실행

```bash
uv sync --frozen
cp .env.example .env
uv run --frozen pytest
uv run --frozen ruff check .
.\scripts\start_local_mcp.ps1
```

기본값은 `APP_MODE=mock`입니다. 이 모드에서는 외부 공공 API를 호출하지 않고
`app/data/mock_responses`와 정적 YAML 데이터를 사용합니다.

## 실행 모드

- `APP_MODE=mock`: fixture와 mock response만 사용합니다. 테스트와 로컬 개발 기본 모드입니다.
- `APP_MODE=live`: 설정된 공공 API endpoint를 호출합니다. 일부 source가 실패하면 가능한 범위에서
  `PARTIAL`, `failed_sources`, `limitations`가 포함된 결과를 반환합니다.

## 역·노선 및 데이터 지원 범위

현재 역 registry는 1~8호선의 대표역·주요 환승역과 9호선 전 역을 역명, 호선,
station id, 운영기관으로 관리합니다. registry에 없는 역은 유사한 역으로 임의 확정하지 않고
역명과 호선을 다시 묻습니다.

연결된 서울교통공사 시설 데이터의 공개 범위는 1~8호선과 9호선 2·3단계 구간
(`언주`~`중앙보훈병원`)입니다. 9호선 1단계 구간(`개화`~`신논현`)은 역명과 경로
질문에는 사용할 수 있지만, 현재 연결된 편의시설·승강기·장애인화장실 데이터의 제공 범위
밖입니다. 이 경우 외부 시설 API를 호출한 뒤 빈 결과로 오해하지 않고 `UNSUPPORTED`로
표시합니다. 최단경로 API는 별도 조회 결과를 기준으로 판단합니다.

시설 조회 상태는 다음처럼 구분합니다.

- `NOT_FOUND`: 지원되는 데이터 소스를 정상 조회했지만 일치하는 시설이 없음
- `UNKNOWN`: API 실패 또는 정보 부족으로 확인하지 못함
- `UNSUPPORTED`: 해당 역·호선·운영기관이 현재 연결된 데이터 소스의 제공 범위 밖임

mock mode는 고정 fixture 검증용이므로 live coverage 제한을 적용하지 않습니다. 공식 데이터
범위 근거는 [서울교통공사 편의시설위치정보](https://www.data.go.kr/data/15143841/openapi.do)와
[서울교통공사 편의시설 현황](https://www.data.go.kr/data/15044443/fileData.do)을 참고합니다.

## 사용 방식 선택

이 MCP는 세 가지 방식으로 사용할 수 있습니다.

- 로컬 개발/개인 테스트: 사용자 PC에서 `APP_MODE=mock` 또는 `APP_MODE=live`로 실행합니다. live mode는 사용자가 직접 공공 API key를 설정해야 합니다.
- 제한된 외부 테스트: 운영자가 서버를 띄우고 `MCP_AUTH_MODE=static`과 Bearer token으로 `/mcp`를 보호합니다.
- hosted 운영: 운영자가 공공 API key를 서버 `.env`에만 보관하고, 일반 사용자는 HTTPS MCP URL만 LLM client에 등록합니다.

일반 사용자가 공공 API key 없이 테스트하게 하려면 hosted 운영이 필요합니다. Oracle Cloud VM과 Caddy HTTPS reverse proxy를 기준으로 하며 Redis는 선택 사항입니다. 상세 절차는
[Hosted Deployment Guide](docs/hosted-deployment.md)를 따릅니다.

live mode에는 API key와 endpoint URL이 필요합니다.

```env
PUBLIC_DATA_SERVICE_KEY=...
SEOUL_OPEN_API_KEY=...
ELEVATOR_STATUS_API_KEY=...
ELEVATOR_INFO_API_KEY=...
RESTROOM_API_KEY=...
FACILITY_API_URL=...
SHORTEST_ROUTE_API_URL=...
ELEVATOR_STATUS_API_URL=...
ELEVATOR_INFO_API_URL=...
RESTROOM_API_URL=...
```

API key는 config에서만 읽고, MCP tool 응답이나 로그에는 포함하지 않습니다.
1~2번 공공데이터포털 API는 `PUBLIC_DATA_SERVICE_KEY`를 사용합니다.
3~5번 서울 열린데이터광장 API는 각각 `ELEVATOR_STATUS_API_KEY`,
`ELEVATOR_INFO_API_KEY`, `RESTROOM_API_KEY`를 사용합니다.
`SEOUL_OPEN_API_KEY`는 세 API가 같은 key를 공유하는 경우에만 fallback으로 사용할 수 있습니다.

## MCP 인증

인증은 `MCP_AUTH_MODE=none|static|oidc`로 분리합니다.

- `none`: 로컬 개발과 mock test용이며 인증하지 않습니다.
- `static`: 제한된 외부 테스트용이며 운영자가 공유한 고정 Bearer token을 검증합니다.
- `oidc`: hosted 운영용이며 외부 OIDC 제공자가 발급한 JWT의 서명, 만료, issuer, audience,
  scope를 검증합니다.

기본값은 `none`입니다. 기존 환경의 `MCP_AUTH_ENABLED=true`도 계속 지원하며,
`MCP_AUTH_MODE`가 생략된 경우 `static`으로 해석합니다. 두 값이 모두 있으면
`MCP_AUTH_MODE`가 우선합니다.

ngrok 같은 HTTPS 터널이나 외부 LLM client에 `/mcp`를 열기 전에는 static Bearer token
인증을 켭니다. 이 값은 공공 API key와 별개의 MCP 접속용 secret입니다.

```env
MCP_AUTH_MODE=static
MCP_API_KEY=긴-랜덤-문자열
MCP_PUBLIC_BASE_URL=https://example.ngrok-free.app
MCP_REQUEST_BODY_LIMIT_ENABLED=true
MCP_MAX_REQUEST_BODY_BYTES=1048576
MCP_TOOL_INPUT_MAX_CHARS=120
MCP_RATE_LIMIT_ENABLED=true
MCP_RATE_LIMIT_PER_MINUTE=60
MCP_RATE_LIMIT_WINDOW_SECONDS=60
```

`MCP_AUTH_MODE=static`인데 `MCP_API_KEY`가 비어 있거나 placeholder 값이거나 32자보다
짧으면 서버가 시작되지 않습니다.

인증을 켠 서버를 테스트할 때는 클라이언트 스크립트에 token을 전달합니다.

```bash
uv run python scripts/test_mcp_client.py --api-key "긴-랜덤-문자열"
```

token 없이 호출하거나 잘못된 token을 전달하면 `/mcp` 요청은 401로 거부됩니다. `MCP_API_KEY`,
공공 API service key, `Authorization` header 값은 로그와 MCP 응답에 포함하지 않습니다.

hosted 운영에서 OIDC access token을 검증하려면 다음 값을 설정합니다.

```env
MCP_AUTH_MODE=oidc
MCP_PUBLIC_BASE_URL=https://mcp.example.com
MCP_OIDC_ISSUER_URL=https://identity.example.com
MCP_OIDC_JWKS_URL=https://identity.example.com/.well-known/jwks.json
MCP_OIDC_AUDIENCE=barrier-free-mobility-mcp
MCP_OIDC_ALGORITHM=RS256
MCP_OIDC_REQUIRED_SCOPES=mcp:read
MCP_OIDC_JWKS_SSRF_SAFE=true
```

OIDC 모드는 서버 시작 시 실제 JWKS를 호출하지 않습니다. 첫 인증 요청에서 공개키를 조회하고
FastMCP 내부 cache를 사용합니다. 대칭키 방식인 `HS*`는 허용하지 않으며 운영 issuer와 JWKS는
HTTPS URL이어야 합니다. localhost 통합 테스트만 HTTP를 허용합니다. 토큰에는 만료 시각 `exp`와
사용자 식별자 `sub`가 있어야 하며, 아직 유효하지 않은 `nbf` 토큰은 거부합니다.

MCP client는 다음 보호 리소스 metadata에서 authorization server와 scope를 확인할 수 있습니다.

```text
https://mcp.example.com/.well-known/oauth-protected-resource/mcp
```

이 서버는 OAuth 로그인 화면이나 사용자 계정을 직접 관리하지 않습니다. 인증 제공자가
MCP client와 호환되는 OAuth authorization flow와 client registration을 제공해야 하며,
provider별 client 설정은 실제 배포 단계에서 별도로 구성합니다.

외부 테스트용 운영 보안 설정도 함께 사용할 수 있습니다.

- `MCP_REQUEST_BODY_LIMIT_ENABLED=true`: 큰 요청 body를 413으로 거부합니다.
- `MCP_TOOL_INPUT_MAX_CHARS`: 역명, 출발지, 도착지 같은 text input 길이를 제한합니다.
- `MCP_RATE_LIMIT_ENABLED=true`: `/mcp`와 `/metrics`에 process-local rate limit을 적용합니다.
- `/health`는 rate limit 대상에서 제외되며, key 값 없이 보안 설정 상태만 표시합니다.

static 인증은 외부 테스트 보호용입니다. 상용 공개 서비스에서는 `oidc`와 함께 rate limit,
WAF, abuse 방어를 앞단에 둡니다.

## 운영 상태 확인

서버는 MCP endpoint 외에 `/health`, `/metrics`를 제공합니다.

```bash
curl.exe http://127.0.0.1:8000/health
curl.exe http://127.0.0.1:8000/metrics
```

`/health`는 `APP_MODE`, MCP 인증 활성화 여부, cache backend, public API 설정 누락 여부를
반환합니다. key나 endpoint URL 값은 반환하지 않고, 설정 여부만 boolean으로 표시합니다.

`/metrics`는 process-local in-memory counter입니다. 서버가 재시작되면 초기화됩니다. 포함되는
주요 값은 다음과 같습니다.

- MCP tool 호출 수와 error 수
- tool별 평균 latency
- public API 호출 수, error 수, 평균 latency
- cache `HIT`, `MISS`, `STALE` count
- fallback response count
- `AccessibilityResult.status` 분포

`MCP_AUTH_MODE`가 `static` 또는 `oidc`일 때 `/metrics`도 `/mcp`와 같은 방식으로 인증합니다.

```bash
curl.exe -H "Authorization: Bearer 긴-랜덤-문자열" http://127.0.0.1:8000/metrics
```

## Cache Backend

기본값은 `CACHE_BACKEND=memory`입니다. 로컬 개발과 mock mode에서는 이 설정이면 충분합니다.
memory cache는 process-local이라 서버가 재시작되면 초기화되고, 여러 서버 인스턴스 사이에서
공유되지 않습니다.

memory와 Redis cache 모두 fresh TTL 이후에는 `CACHE_STALE_TTL_SECONDS` 범위 안에서만 장애
fallback용 이전 응답을 유지합니다. 이 범위를 지난 값은 재사용하지 않습니다. cache hit 또는
stale fallback 응답의 기준 시각은 cache를 읽은 시각이 아니라 원본 API를 조회한 시각을 유지합니다.
Redis backend는 `redis.asyncio`를 사용하므로 MCP 요청의 event loop를 동기 Redis I/O로
막지 않습니다.

운영 또는 외부 테스트에서 공공 API 호출량과 일시 장애 영향을 줄이려면 Redis를 사용할 수 있습니다.

```env
CACHE_BACKEND=redis
REDIS_URL=redis://redis:6379/0
CACHE_STALE_TTL_SECONDS=86400
REDIS_SOCKET_TIMEOUT_SECONDS=2.0
REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS=2.0
```

live mode의 공공 API HTTP 연결은 애플리케이션 수명 동안 하나의 `httpx.AsyncClient` connection
pool을 공유합니다. 시설 전체 데이터는 source 단위로 한 번 cache한 뒤 역·호선별로 필터링하며,
동일 cache key의 동시 miss는 single-flight로 한 번만 외부 API를 호출합니다. 동시 요청 상한은
다음 값으로 조정할 수 있습니다.

```env
HTTP_MAX_CONNECTIONS=20
HTTP_MAX_KEEPALIVE_CONNECTIONS=10
HTTP_KEEPALIVE_EXPIRY_SECONDS=30
PUBLIC_API_PAGE_CONCURRENCY=4
FACILITY_QUERY_CONCURRENCY=4
```

retry는 timeout, HTTP 429, HTTP 5xx에만 적용합니다. 인증 오류나 잘못된 요청에 해당하는 다른
4xx 응답은 반복 호출하지 않습니다.

Docker Compose에서 Redis까지 함께 띄울 때는 profile을 켭니다.

```bash
docker compose --profile redis up --build
```

Redis가 연결되면 `/health`의 `dependencies.cache.status`가 `ok`로 표시됩니다. Redis가
꺼져 있거나 연결할 수 없으면 `unavailable`과 warning이 표시되지만, MCP tool은 cache miss처럼
처리하고 계속 응답합니다. Redis URL, password, API key 값은 `/health`, `/metrics`, MCP 응답에
포함하지 않습니다.

## 실제 공공 API 연결 순서

mock mode 검증이 끝난 뒤 live mode로 전환합니다. API key는 채팅이나 로그에 붙여넣지 말고
`.env`에 직접 입력합니다.

```env
APP_MODE=live
PUBLIC_DATA_SERVICE_KEY=...
SEOUL_OPEN_API_KEY=...
ELEVATOR_STATUS_API_KEY=...
ELEVATOR_INFO_API_KEY=...
RESTROOM_API_KEY=...
FACILITY_API_URL=...
SHORTEST_ROUTE_API_URL=...
ELEVATOR_STATUS_API_URL=...
ELEVATOR_INFO_API_URL=...
RESTROOM_API_URL=...
```

공공 API 문서의 파라미터명이 기본값과 다르면 `.env`에서 이름만 바꿉니다.

```env
FACILITY_STATION_PARAM=station
FACILITY_LINE_PARAM=line
ROUTE_ORIGIN_PARAM=origin
ROUTE_DESTINATION_PARAM=destination
ELEVATOR_STATUS_STATION_PARAM=station
ELEVATOR_STATUS_LINE_PARAM=line
ELEVATOR_INFO_STATION_PARAM=station
ELEVATOR_INFO_LINE_PARAM=line
RESTROOM_STATION_PARAM=station
RESTROOM_LINE_PARAM=line
```

endpoint URL이 path 방식이면 placeholder를 사용할 수 있습니다.

```env
FACILITY_API_URL=https://example.test/{service_key}/json/facility/{start_index}/{end_index}/{station}
```

실제 API 샘플은 아래 명령으로 수집합니다. 저장 전 알려진 key 문자열은 `[REDACTED]`로
치환됩니다.

```bash
uv run python scripts/collect_live_samples.py --station 홍대입구 --origin 홍대입구 --destination 삼성
```

샘플은 `tests/fixtures/live_samples`에 저장됩니다. 이 파일을 기준으로 normalizer를 보정하면
실제 API 필드명과 mock schema 사이의 차이를 안전하게 줄일 수 있습니다.

경로 API가 직관적인 지하철 경로와 다른 결과를 주는지 확인하려면 아래 smoke를 사용합니다.
이 명령은 최단경로 API만 호출하고, key나 endpoint URL은 출력하지 않습니다.

```bash
uv run python scripts/check_route_accuracy.py --case-set basic
uv run python scripts/check_route_accuracy.py --case-set basic --search-date "2026-06-10 09:30:00"
```

결과의 `status`가 `ISSUES`이면 환승 수, 노선, 금지된 환승역 등 기대값과 다른 부분을
확인합니다. 기본 pytest는 이 live smoke를 실행하지 않습니다.

## 배포 전 체크리스트

공개 repository나 배포 artifact를 만들기 전에 포함/제외 대상을 먼저 확인합니다.

포함 대상:

- `app/`, `scripts/`, `tests/`
- `pyproject.toml`, `uv.lock`
- `Dockerfile`, `docker-compose.yml`, `.env.example`, `.gitattributes`
- `.github/workflows/ci.yml`
- `docs/hosted-deployment.md`, `deploy/hosted/*.example`, `deploy/hosted/docker-compose.hosted.yml`
- `README.md`, `ROADMAP.md`, `AGENTS.md`

제외 대상:

- `.env`, `.env.*`
- `.venv/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`
- `.tmp-*`, `*.log`, local smoke output
- `dist/`, `build/`, `*.egg-info/`
- `codex_handoff.md`, `tests/fixtures/live_samples/`

배포 전 실행:

```bash
uv lock --check
uv run --frozen python scripts/check_release_safety.py
uv run --frozen pytest
uv run --frozen ruff check .
docker build -t barrier-free-mobility-mcp:local .
```

API key, service key, MCP bearer token은 `.env`에만 둡니다. 문서, fixture, 로그, 압축 파일,
Docker image build context에는 secret 값이 들어가지 않아야 합니다. `.dockerignore`는 image
build context를 줄이는 용도이며, `docker-compose.yml`의 `env_file: .env` 로컬 로딩은 그대로
유지합니다.

GitHub Actions는 push와 pull request에서 같은 lockfile로 테스트, Ruff, release safety,
Docker build를 실행합니다. Docker image는 runtime에 `uv`를 실행하지 않고 `/app/.venv`의
Python으로 MCP 서버를 시작합니다.

## MCP Tools

- `resolve_station(query: str)`
- `get_station_facilities(station: str, line: str | None = None)`
- `get_elevator_status(station: str, line: str | None = None)`
- `get_accessible_restroom(station: str, line: str | None = None)`
- `get_route_candidates(origin: str, destination: str)`
- `check_accessible_trip(origin: str, destination: str, mobility_profile: MobilityProfile)`
- `generate_accessibility_brief(origin: str, destination: str, mobility_profile: MobilityProfile)`
- `answer_accessibility_question(question: str)`

### 개별 조회 Tool 응답 버전

공공데이터를 직접 조회하는 아래 네 tool은 `schema_version=2` wrapper를 반환합니다.

- `get_station_facilities`
- `get_elevator_status`
- `get_accessible_restroom`
- `get_route_candidates`

버전 1에서는 정규화된 배열 자체가 응답이었지만, 버전 2에서는 기존 배열을 `.data`에 그대로
넣고 조회 완전성 metadata를 함께 반환합니다. tool 이름과 입력값은 유지되지만 응답 shape가
바뀌므로 기존 client는 배열 대신 `result.data`를 사용해야 합니다.

```json
{
  "schema_version": 2,
  "status": "PARTIAL",
  "outcome": "STALE",
  "data": [],
  "data_sources": [],
  "failed_sources": [],
  "limitations": []
}
```

`outcome`의 의미는 다음과 같습니다.

- `DATA`: 정상 조회 결과가 있음
- `EMPTY`: 지원되는 소스를 정상 조회했지만 일치하는 결과가 없음
- `PARTIAL`: 일부 데이터는 있으나 다른 소스가 실패하거나 미지원임
- `FAILED`: 조회 실패로 사용할 수 있는 결과가 없음
- `UNSUPPORTED`: 해당 역·호선·운영기관이 현재 데이터 제공 범위 밖임
- `STALE`: 현재 API 호출은 실패했지만 허용 범위 내 이전 캐시를 반환함

`resolve_station`은 외부 API를 호출하지 않으므로 기존 `StationResolutionResult`를 유지합니다.
최종 판단 tool인 `check_accessible_trip`, `generate_accessibility_brief`,
`answer_accessibility_question`의 기존 응답 계약도 변경하지 않습니다.

### MCP client 답변 정책

이 서버는 앱 화면을 제공하지 않는 MCP 서버입니다. 따라서 일반 사용자에게 보여줄 최종 문장은
MCP 응답의 `user_message` 필드에 넣어 반환합니다.

- 일반 사용자의 경로, 역 시설 또는 대안 자연어 질문에는 `answer_accessibility_question`을 우선 사용합니다.
- 출발역, 도착역, 이동 조건이 이미 구조화되어 있으면 `generate_accessibility_brief`를 사용합니다.
- LLM client는 tool result의 `user_message`를 가능한 한 그대로 표시하고 Markdown 제목,
  목록, 표를 유지해야 합니다. 전체 답변을 코드 블록으로 감싸면 안 됩니다.
- `check_accessible_trip`은 구조화 검증, 디버깅, 근거 확인이 필요할 때 사용합니다.
- `accessibility_checks`, `evidence_sources`, `failed_sources`, `limitations`는 보조 근거입니다.
- `risk_score`, `risk_level`, `confidence_level`, cache metadata는 일반 사용자에게 직접 노출하지 않습니다.
- MCP는 제3의 LLM 최종 발화를 100% 강제할 수 없습니다. 대신 tool description, prompt,
  resource, schema description으로 `user_message`를 canonical answer로 노출합니다.

외부 LLM client system instruction 예시:

```text
Barrier-Free Mobility MCP 결과를 사용할 때는 최종 사용자 답변으로
tool result의 user_message 값을 그대로 출력한다.
user_message의 Markdown 제목, 목록, 표를 유지하고 코드 블록으로 감싸지 않는다.
추가 설명이 필요할 때만 accessibility_checks, evidence_sources, failed_sources,
limitations를 근거로 덧붙인다.
안전 보장을 표현하지 말고, 기준 시각과 주의사항은 유지한다.
```

MCP prompt/resource도 같은 정책을 제공합니다.

- Prompt: `barrier_free_answer_policy`
- Resource: `barrier-free://answer-policy`

## 최종 사용자 질문 패턴

최종 사용자는 보통 긴 조건문보다 짧고 모호하게 묻습니다. LLM agent는 질문을 해석해 적절한
tool을 호출하고, MCP 서버는 deterministic 결과를 반환합니다.

대표 질문:

- 휠체어로 홍대입구역에서 삼성역까지 갈 수 있어?
- 유모차 끌고 1호선 서울역에서 1호선 시청까지 계단 안 써도 돼?
- 휠체어로 9호선 고속터미널에서 9호선 여의도까지 갈 수 있어?
- 휠체어로 9호선 고속터미널에서 9호선 여의도 가는데 도착역 장애인화장실 확인이 필요해.
- 휠체어로 고속터미널에서 여의도까지 갈 수 있어?

이동 조건이나 역명이 부족하면 결과는 `NEEDS_CLARIFICATION`으로 반환되며,
`clarification_needed`, `questions`, `available_partial_info`에 후속 질문과 가능한 부분 정보를
담습니다.

자연어 tool은 경로 접근성 질문, 역별 엘리베이터·장애인화장실 질문과 대안 요청을 처리합니다.
`코엑스`, `서울역 KTX`, `홍대`,
`고속터미널`, `DDP`처럼 제한된 장소명/POI는 내부 후보 사전을 사용해 가까운 역 후보를
안내합니다. 후보가 여러 개이면 서버가 임의로 고르지 않고 `NEEDS_CLARIFICATION`으로 어느 역
기준인지 묻습니다. 환승역 시설 질문은 `9호선 고속터미널`처럼 호선을 함께 받아야 하며,
단순 “화장실”은 장애인화장실을 의미하는지 확인 질문을 반환합니다.

시설 질문 예시:

- 강남역 엘베 고장났어?
- 2호선 삼성역 엘리베이터 어디 있어?
- 2호선 잠실역 장애인화장실 있어?
- 고속터미널역 엘리베이터 상태 알려줘.

대안 질문 예시:

- 강남역 엘베 고장났는데 다른 엘리베이터 있어?
- 휠체어로 홍대입구에서 삼성까지 환승 적은 대안 경로 알려줘.
- 엘리베이터 고장난 역 피해서 갈 수 있어?
- 현재 경로에서 승강기 문제 있는 역 있어?

같은 역의 시설 대안은 정상 상태와 위치가 모두 확인된 시설만 제안합니다. 경로 대안은
접근성 위험, 환승 횟수, 이동 시간 순서로 비교하며 공공 API가 반환한 후보 밖의 경로를
만들지 않습니다. MCP 서버는 이전 대화의 경로를 저장하지 않으므로 “현재 경로” 질문에는
출발역과 도착역을 다시 요청합니다.

## Sample Tool Input

```json
{
  "origin": "홍대입구",
  "destination": "삼성",
  "mobility_profile": {
    "wheelchair": true,
    "can_use_stairs": false,
    "can_use_escalator": false,
    "need_elevator_only": true,
    "avoid_many_transfers": true,
    "max_transfer_count": 1
  }
}
```

## 결과 구조

`check_accessible_trip`과 `generate_accessibility_brief`는 `AccessibilityResult`를 반환합니다.
`answer_accessibility_question`은 `AccessibilityQuestionResult`를 반환하며, 자연어 해석 결과와
필요 시 경로 `AccessibilityResult`를 `result`에, 시설 `FacilityQuestionResult`를
`facility_result`에 포함합니다. 대안 질문도 경로 대안은 `result`, 같은 역 시설 대안은
`facility_result`를 재사용합니다. 최종 문장은 모든 경우 최상위 `user_message`입니다.

주요 필드는 다음과 같습니다.

- `status`: `SUCCESS`, `PARTIAL`, `FAILED`, `NEEDS_CLARIFICATION`
- `risk_level`: `LOW`, `CAUTION`, `HIGH`, `UNKNOWN`
- `risk_score`: 0부터 100 사이의 deterministic score
- `selected_route`: 선택된 경로 후보
- `route_candidates`: 각 후보의 역별 접근성 근거와 보정 위험도를 비교한 순서의 경로 목록
- `risk_reasons`: 위험 점수 산정 근거
- `caution_points`: 이동 전 확인해야 할 주의사항
- `blocked_facilities`: 이용 불가 또는 점검 중인 시설
- `accessible_facilities`: 확인된 접근성 시설
- `confidence_level`: 현재 데이터 근거의 충분성. `HIGH`, `MEDIUM`, `LOW`
- `confidence_reasons`: 신뢰도 판단 근거
- `last_checked_at`: 결과에 사용된 출처 중 가장 최근 확인 시각
- `evidence_sources`: 사용한 API/fixture/cache 출처 요약
- `unverified_parts`: 실패, 오래된 캐시, mock fixture 등 확인하지 못한 부분
- `accessibility_checks`: 출발역, 환승역, 도착역 기준 엘리베이터 상태/위치와 화장실 여부
- `accessibility_checks.operator`: 역·호선 registry에서 보존한 운영기관 식별자
- `accessibility_checks.elevator_details`: 위치별 엘리베이터 상태, 운행구간, 상태·위치
  출처와 결합 방식을 담은 전체 근거 목록. 실시간·정적 레코드는 동일 시설 ID 또는 유일하게
  일치하는 exact 시설명일 때만 연결하며, 모호한 후보는 결합하지 않습니다.
- `accessibility_checks.*_verified`: 엘리베이터 설치, 호선 일치, 운행상태, 승강장-대합실,
  환승, 출구 동선 근거. `CONFIRMED`, `UNVERIFIED`, `NOT_APPLICABLE`, `FAILED` 중 하나입니다.
- `clarification_needed`: 짧거나 모호한 질문이라 추가 확인이 필요한지 여부
- `questions`: LLM agent가 사용자에게 물어볼 후속 질문
- `available_partial_info`: 추가 정보 없이도 안내 가능한 부분 정보
- `facility_result`: 시설 질문의 역·호선, 시설별 종합 상태, 전체 시설 목록, 조회 시각과 출처
- `evidence_sources.coverage_status`: 데이터 소스 지원 여부. `SUPPORTED`, `UNSUPPORTED`,
  `UNKNOWN` 중 하나이며 정상 빈 결과와 제공 범위 밖을 구분합니다.
- `safety_notice`: 현장 상태 변동 가능성에 대한 고정 안전 안내
- `user_message`: 일반 사용자에게 그대로 보여줄 canonical Markdown final answer
- `user_message_summary`: `judgement`, `headline`, `reasons`, `recommended_route`,
  `key_points`, `mobility_condition_summary`, `data_basis`, `notices`로 나뉜 사용자용 요약
- `failed_sources`: 실패한 공공 API 또는 데이터 source
- `limitations`: 결과 해석 시 고려해야 할 한계

개별 조회 tool의 `FacilityLookupResult`와 `RouteLookupResult`는 `status`, `outcome`, `data`,
`data_sources`, `failed_sources`, `limitations`를 공통으로 제공합니다. 빈 `.data`를 곧바로
“시설 없음”이나 “경로 없음”으로 해석하지 말고 반드시 `outcome`을 먼저 확인해야 합니다.

LLM client는 일반 사용자에게 `user_message`를 우선 그대로 보여주는 것을 권장합니다.
이동 가능 여부와 필요한 다음 행동은 MCP의 deterministic 판단 로직이 `user_message` 첫 부분에
직접 작성합니다. LLM client가 상세 JSON을 보고 별도의 안전 판단을 만들어내도록 맡기지 않습니다.
이 문장은 길찾기 앱처럼
전체 경유역이나 이동 시간을 강조하지 않고, 출발역/환승역/도착역의 엘리베이터 위치와 상태,
사용자 조건 때문에 필요한 확인 사항, 기준 시각, 주의사항을 제공합니다. 직행 경로에서는
출발역과 도착역을 반복하는 별도 추천 경로를 표시하지 않습니다. 역별 접근성은
`역 / 확인된 정보 / 추가 확인` 3열 표로 제공합니다. 답변 첫 부분에는 현재 결론과
가장 먼저 해야 할 행동을 한 번만 표시하고, 같은 근거를 별도 `이유`나 `출발 전 확인`
섹션에서 반복하지 않습니다. 추가 질문이 필요할 때도 한 번에 한 가지 정보만 요청합니다.
모든 공식 경로 후보는 후보에 포함된 역의 시설·출처·실패 정보만 사용해 같은 접근성 평가와
위험도 보정 단계를 거칩니다. 한 후보에서만 발생한 시설 조회 실패는 다른 후보의 판단에
섞지 않습니다. 공식 역 순서와 분기 topology 근거가 없으면 API에 없는 무환승 경로를
임의로 만들지 않습니다.
표를 지원하지 않는 client에서도 Markdown 원문만으로 내용을 읽을 수 있습니다.

신뢰도는 “안전 보장”이 아니라 현재 사용 가능한 데이터 근거가 얼마나 충분한지를 의미합니다.
예를 들어 `risk_level=LOW`라도 `safety_notice`는 항상 포함됩니다.

출처는 사용자 친화적인 데이터셋 이름과 조회 상태만 제공합니다. endpoint URL, service key,
bearer token, raw request parameter는 응답에 포함하지 않습니다.

```json
{
  "status": "SUCCESS",
  "risk_level": "CAUTION",
  "risk_score": 35,
  "user_message": "**출발 전에 확인이 필요합니다.**\n서울역과 시청역의 엘리베이터는 현재 운행 중으로 확인됐습니다. 다만 승강장에서 출구까지 엘리베이터만으로 이어지는지는 확인되지 않았습니다.\n**지금 할 일:** 서울역과 시청역 각 역무실에 \"승강장에서 출구까지 엘리베이터로만 이동할 수 있나요?\"라고 문의하세요.\n\n### 역별 확인 결과\n\n| 역 | 확인된 정보 | 추가 확인 |\n|---|---|---|\n| 출발역: 1호선 서울역 | 2번 출입구; 현재 운행 중 | 출구까지 연결 확인 필요 |\n| 도착역: 1호선 시청역 | 1,2번 출입구 사이; 현재 운행 중 | 승강장→대합실 연결 확인 필요 |\n\n### 기준 시각\n\n- 전체 조회 시각: 2026년 6월 10일 13:25.\n- 엘리베이터 위치·운행상태: 13:25 확인.\n\n### 주의사항\n\n> 엘리베이터 운행 상태는 바뀔 수 있으니 출발 직전 재확인하세요.",
  "accessibility_checks": [
    {
      "station": "서울역",
      "role": "origin",
      "elevator_status": "AVAILABLE",
      "elevator_location": "2번 출입구",
      "restroom_available": null,
      "notes": []
    },
    {
      "station": "시청",
      "role": "destination",
      "elevator_status": "AVAILABLE",
      "elevator_location": "1,2번 출입구 사이",
      "restroom_available": null,
      "notes": []
    }
  ],
  "last_checked_at": "2026-06-10T01:22:00Z",
  "evidence_sources": [
    {
      "source_name": "elevator_status",
      "display_name": "서울교통공사_교통약자_이용시설_승강기_가동현황",
      "source_type": "public_api",
      "cache_status": "MISS",
      "success": true,
      "note": "공공 API 조회 성공"
    }
  ],
  "safety_notice": "엘리베이터 운행 상태는 바뀔 수 있으니 출발 직전 재확인하세요."
}
```

## 테스트

```bash
uv run pytest
uv run ruff check .
```

로컬 MCP 서버를 직접 호출하려면 서버를 먼저 실행합니다.

```bash
.\scripts\start_local_mcp.ps1
```

다른 터미널에서 클라이언트 스크립트를 실행합니다.

```bash
uv run python scripts/test_mcp_client.py --tool generate_accessibility_brief --summary-only
```

최종 사용자 자연어 답변 계약을 확인하려면 `answer_accessibility_question`을 호출합니다. 구조화
입력 기반 계약을 확인하려면 `generate_accessibility_brief`를 호출합니다. 두 결과 모두
`user_message`가 LLM client가 그대로 표시해야 하는 canonical answer입니다.

```bash
uv run python scripts/test_mcp_client.py --tool answer_accessibility_question --summary-only
uv run python scripts/test_mcp_client.py --tool generate_accessibility_brief --summary-only
```

여러 대표 경로를 한 번에 확인하려면 coverage smoke를 실행합니다. 이 명령은 실행 중인 MCP
서버를 호출하며, 각 경로의 `status`, `risk_level`, `confidence_level`, `failed_sources`,
`headline`, payload 크기만 요약해 출력합니다.

```bash
uv run python scripts/test_mcp_client.py --case-set coverage
```

인증을 켠 서버에서는 같은 명령에 `--api-key`를 추가합니다.

```bash
uv run python scripts/test_mcp_client.py --case-set coverage --api-key "긴-랜덤-문자열"
```

실제 공공 API 기준의 답변 품질을 한 번에 점검하려면 live 품질 평가 스크립트를 실행합니다.
이 명령은 MCP 서버를 따로 켜지 않고 내부 service를 `APP_MODE=live`로 실행합니다. API key,
endpoint URL, raw request parameter는 출력하지 않고, 케이스별 상태, 판단 문구, 지연 시간,
payload 크기, 실패 source 수, 미확인 정보 수, 기준 시각 포함 여부만 요약합니다.
`facility_status` category를 선택하면 엘리베이터·장애인화장실 단독 질문만 평가할 수 있습니다.

```bash
uv run python scripts/evaluate_live_quality.py --case-set basic
uv run python scripts/evaluate_live_quality.py --case-set all --limit 10
uv run python scripts/evaluate_live_quality.py --category trip_accessibility --json
uv run python scripts/evaluate_live_quality.py --category facility_status --json
uv run python scripts/evaluate_live_quality.py --case-set basic --limit 5 --compare-cache
```

품질 이슈를 CI나 배포 전 수동 점검에서 실패로 보고 싶으면 `--strict`를 추가합니다.
`--compare-cache`는 같은 케이스를 cold/warm 순서로 두 번 실행해 전체 지연, 공공 API 호출 수,
cache hit/miss/stale 수를 함께 출력합니다. API key와 endpoint URL은 출력하지 않습니다.

자동 검사를 넘어 일반 사용자가 답변을 읽고 평가하는 사용성 리뷰 패킷도 생성할 수 있습니다.
기본 명령은 재현 가능한 mock 답변, 작성용 YAML 양식, 비개발자용 HTML 리뷰 폼을
`artifacts/usability/`에 만듭니다. `--open`을 사용하면 생성된 로컬 HTML을 기본
브라우저에서 엽니다.

```bash
uv run python scripts/generate_usability_review.py --mode mock --open
uv run python scripts/generate_usability_review.py --mode live --case-set all --limit 10
uv run python scripts/summarize_usability_feedback.py artifacts/usability/reviewer-01.json
```

HTML 폼은 `읽기 좋은 보기`에서 Markdown 표를 안전한 HTML 표로 표시하고 `MCP 원문`도
함께 제공합니다. 외부 네트워크를 호출하지 않으며 초안 또는 완료 JSON을 사용자 PC에만 저장합니다.
리뷰 점수는 자동으로 문장을 변경하거나 CI를 실패시키지 않습니다. 반복적으로 확인된 문제만
기존 질문 평가셋과 회귀 테스트에 반영합니다. 평가 방법, JSON 재개, 익명화 원칙은
[사용자 답변 사용성 리뷰 가이드](docs/usability-review-guide.md)를 참고합니다.

현재 테스트는 다음 범위를 검증합니다.

- station normalization
- station/line coverage cases
- mock trip coverage cases
- evidence/confidence fields
- status normalization
- facility/route normalizer
- risk scoring
- decision engine
- MCP tools mock mode
- partial API failure behavior
- HTTP adapter error wrapping
- API key 비노출

## Docker

```bash
cp .env.example .env
docker compose up --build
```

hosted 운영은 기본 Docker Compose와 분리된 예시를 사용합니다. 운영 서버에서는 실제 secret을
`deploy/hosted/.env.hosted`에만 넣고 commit하지 않습니다.

```bash
cp deploy/hosted/hosted.env.example deploy/hosted/.env.hosted
docker compose -f deploy/hosted/docker-compose.hosted.yml --env-file deploy/hosted/.env.hosted config
docker compose -f deploy/hosted/docker-compose.hosted.yml --env-file deploy/hosted/.env.hosted up -d --build
```

자세한 Oracle Cloud VM, Caddy HTTPS reverse proxy와 선택적 Redis 설정은
[Hosted Deployment Guide](docs/hosted-deployment.md)를 참고합니다.

## 주의사항

이 서버는 접근성 데이터를 기반으로 이동 전 확인해야 할 위험 구간을 점검합니다.
특정 경로의 안전한 이동 가능성을 보장하지 않습니다. 실제 이동 전에는 공식 안내,
역무실, 현장 시설 상태를 함께 확인해야 합니다.
