# Barrier-Free Mobility MCP Roadmap

이 문서는 아직 완료되지 않은 상용 배포 전 backlog만 기록한다.

현재 상태는 **MCP MVP 완료**에 가깝다. mock/live mode, 공공 API 연동,
deterministic risk engine, canonical `user_message`, MCP prompt/resource, static
Bearer 인증, health/metrics, 운영 cache까지 동작한다. 따라서 제한된 외부 테스트는 가능하다.

다만 이것은 **상용 준비 완료**와 다르다. 실제 장애인/교통약자 사용자를 대상으로
공개 배포하기 전에는 아래 항목을 보강해야 한다.

## 1. OAuth/OIDC gateway 전환

- static Bearer 인증, request size 제한, text input 제한, process-local rate limit은
  외부 테스트용으로 유지한다.
- 상용 공개 전 OAuth/OIDC gateway, 사용자별 access control, WAF, abuse 방어를 설계한다.
- 운영 로그에는 이동 조건과 경로 정보를 최소화하고, API key, service key, bearer token,
  원본 인증 header는 계속 기록하지 않는다.
- 상태: 후속 상용화 작업.
