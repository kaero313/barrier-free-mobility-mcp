# Barrier-Free Mobility MCP Roadmap

이 문서는 아직 완료되지 않은 backlog만 기록한다.

현재 상태는 **MCP MVP 완료**에 가깝다. mock/live mode, 공공 API 연동,
deterministic risk engine, canonical `user_message`, MCP prompt/resource, static
Bearer 인증, health/metrics, 운영 cache까지 동작한다. 따라서 제한된 외부 테스트는 가능하다.

다만 이것은 **상용 준비 완료**와 다르다. 실제 장애인/교통약자 사용자를 대상으로 공개
배포하기 전에는 "사용자가 자연스럽게 물어도 목적에 맞는 답을 받는가"를 중심으로 보강해야 한다.

## 작업 관리 원칙

- 완료된 항목은 이 문서에서 제거하거나 완료 기록으로 별도 정리한다.
- MCP tool 이름과 기존 public schema는 가능한 한 유지한다.
- 서버 내부에서 LLM을 호출하지 않는다.
- 최종 사용자 답변은 계속 `user_message`를 canonical answer로 관리한다.
- 실제 사용성 개선은 테스트 fixture와 smoke script로 재현 가능하게 만든다.
- 공공 API key, MCP token, endpoint secret은 문서, fixture, 로그, 응답에 포함하지 않는다.

## 우선순위

1. live 품질 평가 스크립트 추가
2. 역별 접근성 근거 세분화
3. hosted 운영 모드 설계와 배포 가이드
4. OAuth/OIDC gateway 전환
5. 실제 사용자 피드백 기반 문장 개선

## 1. live 품질 평가 스크립트 추가

목표: live 공공 API 결과가 실제 사용자 답변 품질에 어떤 영향을 주는지 정량적으로 확인한다.

신규 스크립트 후보:

```text
scripts/evaluate_live_quality.py
```

구현 범위:

- `user_question_cases.yaml` 또는 별도 live case set을 순회한다.
- 각 케이스별 status, risk_level, 판단 문구, latency, payload size, failed_sources,
  unverified_parts, 기준 시각 포함 여부를 요약 출력한다.
- API key, endpoint URL, raw request parameter는 출력하지 않는다.
- 결과는 CI 기본 테스트가 아니라 수동 smoke로 유지한다.

완료 기준:

- live mode에서 여러 질문의 성공/부분 실패/실패 패턴을 한 번에 볼 수 있다.
- latency와 미확인 정보가 눈에 보인다.
- 공개 전 품질 리포트로 사용할 수 있다.

상태: 예정.

## 2. 역별 접근성 근거 세분화

목표: "역에 엘리베이터가 있음"과 "이 이동 조건에 필요한 동선의 엘리베이터가 확인됨"을 구분한다.

구현 범위:

- `AccessibilityCheck` 또는 내부 check context에 다음 개념을 분리한다.
  - `station_has_elevator`
  - `line_matched_elevator`
  - `platform_to_concourse_verified`
  - `transfer_path_elevator_verified`
  - `exit_elevator_verified`
  - `status_verified`
- user_message는 역별로 "확인됨", "미확인", "요구 대상 아님"을 구분해 표시한다.
- live API가 해당 정보를 제공하지 못하는 경우에는 미확인으로 표시하고 단정하지 않는다.

완료 기준:

- "엘리베이터 있음"만으로 과도하게 이동 가능 판단을 내리지 않는다.
- 출발역, 환승역, 도착역의 필요한 접근성 근거가 더 명확해진다.
- 정보 없음과 API 실패가 계속 분리되어 표현된다.

상태: 예정.

## 3. hosted 운영 모드 설계와 배포 가이드

목표: 일반 사용자가 API key 없이 GPT/Claude 등에서 MCP를 연결해 사용할 수 있는 운영 방식을 정리한다.

권장 구조:

```text
사용자 LLM client -> 공개 HTTPS MCP URL -> hosted MCP 서버 -> 공공 API
```

구현 범위:

- Oracle Cloud, Fly.io, Render, Railway 등 배포 후보별 운영 차이를 문서화한다.
- HTTPS, domain, reverse proxy, process manager, Docker Compose, Redis 연결 방법을 정리한다.
- hosted mode에서는 공공 API key를 서버 `.env`에만 보관하고 사용자에게 요구하지 않는다.
- public endpoint에는 인증, rate limit, abuse 방어를 적용한다.

완료 기준:

- 새 사용자가 API key 없이 MCP URL만 등록해 테스트할 수 있는 배포 절차가 문서화된다.
- 운영자가 관리해야 할 secret과 사용자가 알 필요 없는 secret이 구분된다.
- local install mode와 hosted mode의 차이가 README에 명확히 기록된다.

상태: 예정.

## 4. OAuth/OIDC gateway 전환

목표: static Bearer 인증을 외부 테스트용으로 유지하되, 공개 운영 전 사용자 단위 인증과 abuse 방어를 설계한다.

구현 범위:

- OAuth/OIDC gateway, 사용자별 access control, WAF, rate limit을 설계한다.
- 운영 로그에는 이동 조건과 경로 정보를 최소화한다.
- API key, service key, bearer token, 원본 인증 header는 기록하지 않는다.
- 개인 개발용 local mode에서는 인증 없이도 실행 가능하게 유지한다.

완료 기준:

- 공개 hosted MCP endpoint에 대한 인증 방식이 결정된다.
- 개인 로컬 사용, 제한된 외부 테스트, 공개 운영의 인증 정책이 분리된다.
- ChatGPT/Claude 등 MCP client가 전달할 수 있는 인증 방식과 호환된다.

상태: 후속 상용화 작업.

## 5. 실제 사용자 피드백 기반 문장 개선

목표: 현재 템플릿이 실제 장애인, 유모차 이용자, 계단 이용이 어려운 사용자에게 이해하기 쉬운지 검증한다.

구현 범위:

- 사용자 질문과 실제 답변을 익명화해 검토한다.
- "가능", "주의 필요", "권장하지 않음", "확인 불가" 판단 문구가 충분히 명확한지 확인한다.
- 안전 보장처럼 읽히는 표현을 줄이고, 확인된 정보와 미확인 정보를 더 분명하게 나눈다.
- 답변 길이, 단락 순서, 출처/기준 시각 위치를 조정한다.

완료 기준:

- 최소 10개 이상의 실제 또는 준실제 사용 시나리오로 문장 품질을 검토한다.
- 사용자에게 불필요하게 기술적인 표현이 줄어든다.
- 교통약자 안내 목적에 맞는 단정 수위가 유지된다.

상태: 예정.
