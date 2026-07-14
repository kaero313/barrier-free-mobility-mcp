# Hosted Deployment Guide

이 문서는 일반 사용자가 공공 API key 없이 MCP URL만 등록해 테스트할 수 있도록
Barrier-Free Mobility MCP를 hosted 서버로 운영하는 절차를 정리한다.

기본 기준은 Oracle Cloud VM + Docker Compose + Caddy HTTPS reverse proxy다.
단일 instance는 memory cache로 충분하며 Redis는 여러 instance가 cache를 공유해야 할 때만
선택한다. Render, Fly.io, Railway 같은 PaaS도 가능하지만, 이 문서는 공공 API key와
운영 로그 정책을 직접 통제할 수 있는 VM self-hosting을 기준으로 둔다.

참고:

- Oracle Cloud Free Tier: https://docs.oracle.com/iaas/Content/FreeTier/freetier.htm
- Caddy reverse proxy: https://caddyserver.com/docs/quick-starts/reverse-proxy
- Docker Compose: https://docs.docker.com/compose/

## 운영 구조

```text
사용자 LLM client
  -> https://mcp.example.com/mcp
  -> Caddy HTTPS reverse proxy
  -> barrier-free-mobility-mcp:8000
  -> memory cache (필요한 경우 Redis로 교체)
  -> 공공 API
```

사용자는 MCP URL과, 제한된 외부 테스트인 경우 MCP Bearer token만 알면 된다. OIDC 운영에서는
사용자가 인증 제공자에서 로그인하고 MCP client가 access token을 전달한다.
공공 API key와 endpoint URL은 운영 서버 `.env`에만 둔다. Redis를 선택한 경우 Redis URL도
같은 방식으로 관리한다.

## Local Mode와 Hosted Mode 차이

| 구분 | Local install mode | Hosted mode |
| --- | --- | --- |
| 실행 위치 | 사용자 PC | 운영자 서버 |
| 공공 API key | 사용자가 직접 발급/설정 | 운영자 서버 `.env`에서 관리 |
| MCP URL | `http://127.0.0.1:8000/mcp` | `https://mcp.example.com/mcp` |
| 인증 | 기본 `none`, 필요 시 `static` | 외부 테스트는 `static`, 운영은 `oidc` |
| cache | memory 기본 | memory 기본, 다중 instance에서 Redis 선택 |
| 대상 | 개발, 개인 테스트 | 제한된 외부 테스트, 공개 체험 전 단계 |

## Oracle Cloud VM 준비

1. Oracle Cloud에서 Always Free 가능한 VM을 만든다.
2. Ubuntu LTS 이미지를 권장한다.
3. VM 보안 목록 또는 NSG에서 다음 포트를 연다.
   - `22/tcp`: SSH
   - `80/tcp`: Caddy HTTP challenge 및 redirect
   - `443/tcp`: HTTPS MCP endpoint
4. 도메인 DNS의 `A` record를 VM public IP로 연결한다.
5. 서버에 Docker Engine과 Docker Compose plugin을 설치한다.

운영 서버 내부에서 MCP app port `8000`은 외부에 직접 열지 않는다. Redis를 사용하는 경우
Redis port `6379`도 외부에 열지 않는다.
외부 공개는 Caddy의 `80`, `443`만 사용한다.

## 배포 파일 준비

서버에서 repository를 받은 뒤 hosted env 파일을 만든다.

```bash
cp deploy/hosted/hosted.env.example deploy/hosted/.env.hosted
```

`deploy/hosted/.env.hosted`에 실제 값을 채운다.

필수 운영 값:

- `MCP_DOMAIN`: MCP에 사용할 도메인
- `MCP_PUBLIC_BASE_URL`: `https://도메인`
- `APP_MODE=live`
- `CACHE_BACKEND=memory`
- `MCP_AUTH_MODE=static`
- `MCP_API_KEY`: 32자 이상의 긴 랜덤 문자열. 예시 placeholder를 그대로 사용하면 서버가 시작되지 않는다.
- 공공 API key 5종
- 공공 API endpoint URL 5종

`MCP_API_KEY`는 공공 API key가 아니라 MCP 접속용 token이다.
외부 LLM client가 Bearer token을 보낼 수 없는 공개 체험형 endpoint를 만들려면
`MCP_AUTH_MODE=none`으로 둘 수 있지만, rate limit과 WAF 없이 공개하는 것은 권장하지 않는다.

여러 app instance가 cache를 공유해야 할 때만 아래처럼 Redis profile을 사용한다.

```env
CACHE_BACKEND=redis
REDIS_URL=redis://redis:6379/0
```

```bash
docker compose -f deploy/hosted/docker-compose.hosted.yml \
  --env-file deploy/hosted/.env.hosted --profile redis up -d --build
```

## OIDC 운영 모드

static token 테스트가 끝나고 인증 제공자가 준비되면 다음 값으로 전환한다.

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

서버는 access token의 서명, 만료, issuer, audience, scope와 `exp`, `sub`, `nbf` claim을
검증한다. JWT 발급과 로그인, 사용자 계정, consent는 OIDC 제공자가 담당한다.
`MCP_API_KEY`는 OIDC 모드에서 사용하지 않는다.

MCP 보호 리소스 metadata 확인:

```bash
curl https://mcp.example.com/.well-known/oauth-protected-resource/mcp
```

응답의 `authorization_servers`, `scopes_supported`, `resource`가 실제 운영 설정과 일치해야 한다.
OIDC 제공자가 MCP client가 요구하는 authorization flow 또는 client registration을 지원하는지는
provider별로 별도 검증해야 한다.

## 실행

설정이 Docker Compose에서 해석되는지 먼저 확인한다.

```bash
docker compose \
  -f deploy/hosted/docker-compose.hosted.yml \
  --env-file deploy/hosted/.env.hosted \
  config
```

문제가 없으면 서버를 시작한다.

```bash
docker compose \
  -f deploy/hosted/docker-compose.hosted.yml \
  --env-file deploy/hosted/.env.hosted \
  up -d --build
```

로그는 다음처럼 확인한다.

```bash
docker compose \
  -f deploy/hosted/docker-compose.hosted.yml \
  --env-file deploy/hosted/.env.hosted \
  logs -f barrier-free-mobility-mcp
```

## 확인

헬스 체크:

```bash
curl https://mcp.example.com/health
```

인증이 켜진 metrics 확인:

```bash
curl -H "Authorization: Bearer <mcp-api-key>" https://mcp.example.com/metrics
```

로컬 MCP smoke:

```bash
uv run python scripts/test_mcp_client.py \
  --url https://mcp.example.com/mcp \
  --api-key "<mcp-api-key>" \
  --tool answer_accessibility_question \
  --summary-only
```

live 답변 품질 점검:

```bash
uv run python scripts/evaluate_live_quality.py --case-set basic --limit 5 --compare-cache
```

출력의 `performance` 표에서 cold/warm 지연, 공공 API 호출 수, cache hit/miss를 비교한다.
warm 실행에서도 공공 API 호출이 반복되면 cache key 또는 TTL 설정을 먼저 확인한다.

`/health`가 `degraded`로 나오면 공공 API endpoint/key 또는 live 설정 누락을 먼저 확인한다.
Redis backend를 선택한 경우에만 Redis 연결 상태도 확인한다. Redis 장애는 MCP 전체 장애로
올리지 않고 cache miss처럼 처리하지만, 운영 상태는 degraded로 표시한다.

## 운영 보안 기준

- 공공 API key, MCP token, Redis credential은 `.env` 계열 파일에만 둔다.
- `.env`, `.env.*`, `deploy/hosted/.env.hosted`는 commit하지 않는다.
- MCP 응답, health, metrics, log에 secret 값을 출력하지 않는다.
- 제한된 외부 테스트는 `MCP_AUTH_MODE=static`과 긴 `MCP_API_KEY`를 사용한다.
- hosted 운영은 `MCP_AUTH_MODE=oidc`로 전환하고 issuer, audience, scope를 고정한다.
- 공개 체험 endpoint는 최소한 reverse proxy/WAF/rate limit을 둔다.
- OIDC 제공자의 client 등록과 로그인 흐름은 실제 MCP client로 end-to-end 검증한다.

## PaaS 대안

PaaS를 쓰면 VM 관리 부담은 줄지만, 다음 제약을 먼저 확인해야 한다.

- Streamable HTTP MCP endpoint가 장시간 연결과 request body를 안정적으로 처리하는지
- Redis를 같은 private network에서 붙일 수 있는지
- 공공 API key와 MCP token을 secret env로 안전하게 저장할 수 있는지
- 무료/저가 플랜에서 sleep, cold start, outbound timeout 문제가 없는지
- custom domain과 HTTPS가 MCP client 요구사항과 맞는지

따라서 초기 제한 테스트는 Oracle VM 기준으로 문서화하고, PaaS는 운영 편의가 더 중요할 때 별도 검증한다.

## 배포 전 체크

배포 전 다음 명령을 통과시킨다.

```bash
uv run pytest
uv run ruff check .
uv run python scripts/check_release_safety.py
```

Docker 설정만 빠르게 확인할 때는 다음 명령을 사용한다.

```bash
docker compose \
  -f deploy/hosted/docker-compose.hosted.yml \
  --env-file deploy/hosted/hosted.env.example \
  config
```
