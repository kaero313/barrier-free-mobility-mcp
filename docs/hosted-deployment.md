# Hosted Deployment Guide

이 문서는 일반 사용자가 공공 API key 없이 MCP URL만 등록해 테스트할 수 있도록
Barrier-Free Mobility MCP를 hosted 서버로 운영하는 절차를 정리한다.

기본 기준은 Oracle Cloud VM + Docker Compose + Redis + Caddy HTTPS reverse proxy다.
Render, Fly.io, Railway 같은 PaaS도 가능하지만, 이 프로젝트는 공공 API key와 Redis,
rate limit, 운영 로그 정책을 직접 통제해야 하므로 1차 운영 문서는 VM self-hosting을 기준으로 둔다.

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
  -> Redis cache
  -> 공공 API
```

사용자는 MCP URL과, 제한된 외부 테스트인 경우 MCP Bearer token만 알면 된다.
공공 API key, Redis URL, endpoint URL은 운영 서버 `.env`에만 둔다.

## Local Mode와 Hosted Mode 차이

| 구분 | Local install mode | Hosted mode |
| --- | --- | --- |
| 실행 위치 | 사용자 PC | 운영자 서버 |
| 공공 API key | 사용자가 직접 발급/설정 | 운영자 서버 `.env`에서 관리 |
| MCP URL | `http://127.0.0.1:8000/mcp` | `https://mcp.example.com/mcp` |
| 인증 | 기본 off, 필요 시 Bearer | 외부 테스트는 Bearer 권장 |
| cache | memory 기본 | Redis 권장 |
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

운영 서버 내부에서 MCP app port `8000`과 Redis port `6379`는 외부에 직접 열지 않는다.
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
- `CACHE_BACKEND=redis`
- `MCP_AUTH_ENABLED=true`
- `MCP_API_KEY`: 긴 랜덤 문자열
- 공공 API key 5종
- 공공 API endpoint URL 5종

`MCP_API_KEY`는 공공 API key가 아니라 MCP 접속용 token이다.
외부 LLM client가 Bearer token을 보낼 수 없는 공개 체험형 endpoint를 만들려면
`MCP_AUTH_ENABLED=false`로 둘 수 있지만, rate limit과 WAF 없이 공개하는 것은 권장하지 않는다.

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
uv run python scripts/evaluate_live_quality.py --case-set basic --limit 5
```

`/health`가 `degraded`로 나오면 공공 API endpoint/key 누락, Redis 연결 실패, live 설정 누락을 먼저 확인한다.
Redis 장애는 MCP 전체 장애로 올리지 않고 cache miss처럼 처리하지만, 운영 상태는 degraded로 표시한다.

## 운영 보안 기준

- 공공 API key, MCP token, Redis credential은 `.env` 계열 파일에만 둔다.
- `.env`, `.env.*`, `deploy/hosted/.env.hosted`는 commit하지 않는다.
- MCP 응답, health, metrics, log에 secret 값을 출력하지 않는다.
- 제한된 외부 테스트는 `MCP_AUTH_ENABLED=true`와 긴 `MCP_API_KEY`를 사용한다.
- 공개 체험 endpoint는 최소한 reverse proxy/WAF/rate limit을 둔다.
- 상용 공개 운영은 static Bearer만으로 끝내지 않고 OAuth/OIDC gateway 전환을 별도 작업으로 진행한다.

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
