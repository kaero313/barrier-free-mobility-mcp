# Barrier-Free Mobility MCP Roadmap

이 문서는 아직 완료되지 않은 작업만 관리한다.

현재 MCP는 자연어 경로·시설 질문, deterministic 접근성 판단, 공공 API mock/live mode,
부분 실패 응답, 역별 근거, 사용자용 `user_message`, 테스트 및 사용성 리뷰 도구까지 갖췄다.
지금은 기능을 넓히는 단계가 아니라 **현재 기능의 정확성, 사용성, 유지보수성,
재현성을 높이는 안정화 단계**다.

제품과 답변 판단 기준은 [제품 및 사용자 답변 원칙](docs/product-principles.md)을 따른다.

## 작업 원칙

- 신규 tool, API, 인프라는 사용자 문제나 실제 운영 요구가 확인된 경우에만 추가한다.
- 일반 길찾기 정보보다 엘리베이터, 환승·출구 동선, 장애인화장실 근거를 우선한다.
- 확인된 사실, 미확인 정보, 지원 범위 밖, API 실패를 구분한다.
- 서버 내부에서 LLM을 호출하거나 LLM이 위험도를 결정하게 하지 않는다.
- public schema와 MCP tool은 가능한 한 하위 호환성을 유지한다.
- 동작 변경과 구조 refactoring을 같은 작업으로 섞지 않는다.
- mock fixture와 회귀 테스트를 먼저 만들고 live API는 별도 smoke로 검증한다.
- memory cache를 기본으로 유지하고 Redis·OIDC는 배포 요구가 있을 때만 선택한다.

## 우선순위

1. Repository 기준선 정리와 재현 가능한 빌드
2. 실제 MCP client 상호운용성 검증
3. 사용자 리뷰 기반 개선 반복

새로운 시설 종류, 이미지, 연락처, hosted 인프라는 위 안정화 작업을 마친 뒤 필요성을
다시 판단한다.

## 1. Repository 기준선 정리와 재현 가능한 빌드

목표: 검증한 코드와 공개 repository, clean clone, Docker image가 같은 동작을 재현하게 한다.

작업:

- 남아 있는 수정·미추적 파일을 기능 단위로 검토해 commit 또는 제외한다.
- `.gitattributes`를 추가해 Windows/Linux 줄바꿈 차이를 정리한다.
- Docker image가 `uv.lock`을 복사하고 `uv sync --frozen --no-dev`를 사용하게 한다.
- GitHub Actions에서 pytest, ruff, release safety, Docker build를 실행한다.
- mock mode에서 secret 없이 전체 검증이 가능해야 한다.

완료 기준:

- 작업트리가 의도한 상태로 정리돼 있다.
- clean clone에서 `uv run pytest`와 `uv run ruff check .`가 통과한다.
- lockfile을 변경하지 않고 Docker image를 만들 수 있다.
- CI와 로컬 검증 결과가 일치한다.

상태: 진행 중. `.gitattributes`, frozen lockfile 기반 Docker build, GitHub Actions 검증은
구현했다. 현재 Git 공개 후보 파일만 복사한 격리 스냅샷에서 secret 없이 frozen dependency
설치, 전체 테스트, Ruff, release safety, hosted Compose 설정, Docker image build와 `/health`
smoke까지 통과했다. 남은 수정·미추적 파일을 기능 단위로 커밋한 뒤 실제 clean clone에서
같은 검증을 한 번 더 수행하면 완료된다.

## 2. 실제 MCP client 상호운용성 검증

목표: MCP server가 특정 개발 환경에 의존하지 않고 외부 client에서 같은 tool 계약을
제공하는지 확인한다.

작업:

- 가능한 MCP client에서 tool discovery와 `answer_accessibility_question` 호출을 검증한다.
- 자연어 질문, 구조화 경로 질문, clarification 흐름을 각각 확인한다.
- client LLM이 `user_message`를 재작성할 수 있다는 한계와 권장 system instruction을 기록한다.
- MCP JSON 결과와 사용자에게 표시된 답변을 secret 없이 예제로 남긴다.

완료 기준:

- 최소 두 종류의 MCP client 또는 공식 inspector 성격의 client에서 호출이 재현된다.
- tool description, prompt, resource, schema의 답변 정책이 서로 충돌하지 않는다.
- 로컬 mock mode 검증은 별도 hosted 인프라 없이 실행할 수 있다.

상태: repository 기준선 정리 후 진행.

## 3. 사용자 리뷰 기반 개선 반복

목표: 기능 추가가 아니라 실제 답변의 이해도와 행동 가능성을 검증한다.

작업:

- 휠체어, 유모차, 보행약자 관점의 대표 답변을 검토한다.
- 실제 사용자와 준실제 리뷰를 구분해 기록한다.
- 이해도, 행동 가능성, 불확실성 구분, 접근성 관련성, 간결성을 평가한다.
- 반복되는 낮은 점수와 flag만 회귀 테스트와 문장 builder에 반영한다.
- live smoke 결과와 저장 fixture의 차이가 생기면 정규화·판단 회귀 여부를 기록한다.
- 개인 이동 기록이나 장애 진단 정보는 수집하지 않는다.

완료 기준:

- 대표 시나리오별로 수정 전후 결과를 비교할 수 있다.
- 반복된 문제는 fixture와 테스트로 재현된다.
- 개선 후 행동 가능성과 이해도가 악화되지 않았는지 다시 검토한다.

상태: 리뷰 도구 준비 완료, 추가 검증 필요.

## 선택 Backlog

다음 항목은 현재 필수 작업이 아니다.

- **역별 연락처 API**: 출발 전 문의 수요가 반복적으로 확인될 때 연동한다.
- **실제 OIDC provider**: 공개 hosted endpoint와 사용자 계정 요구가 생길 때 검증한다.
- **Redis 및 분산 rate limit**: 다중 instance 또는 gateway 요구가 생길 때 적용한다.
- **이미지·지도·출구 보행 동선**: 신뢰할 수 있는 공식 데이터와 명확한 사용자 가치가
  확보될 때 별도 설계한다.

선택 항목을 시작할 때는 사용자 문제, 데이터 출처, 실패 동작, cache 정책, 회귀 테스트를
먼저 문서화한다.
