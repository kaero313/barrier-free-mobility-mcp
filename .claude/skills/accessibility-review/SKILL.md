---
name: accessibility-review
description: 접근성 판단, 사용자 답변, 근거 상태, 공개 schema를 바꾼 diff를 이 프로젝트 규칙으로 검토한다. app/engine, app/services/user_message*, 근거 상태 처리, MCP tool이나 Pydantic schema 변경을 마치기 전, 또는 그런 diff의 검토를 요청받았을 때 사용한다.
---

# 접근성 변경 검토

diff와 관련 테스트를 읽고 아래 항목을 확인한다. 검토하는 동안에는 고치지 않고 발견부터 보고한다.

## 확인 항목

1. **단정 금지**: 엘리베이터 위치와 상태, 환승 동선, 출구 동선 근거가 끝까지 확인되지 않았는데 "안전", "이용 가능", "문제 없음"으로 읽히는 문구나 판정이 없는가. `tests/fixtures/user_question_cases.yaml`의 `banned_phrases`를 비켜 가는 비슷한 표현도 본다.
2. **상태 구분**: 확인됨, 미확인, 찾을 수 없음, 지원 범위 밖, 외부 API 실패가 한 상태로 합쳐지지 않았는가(`AccessibilityEvidenceStatus`, `FacilityAnswerState`, `LookupOutcome`, `SourceCoverageStatus`). 부분 실패에 `failed_sources`와 `limitations`가 채워지는가.
3. **결정론**: 위험도와 판정은 `app/engine`에서만 정해지는가. LLM 호출, 난수, 테스트에서 고정할 수 없는 현재 시각 의존이 없는가.
4. **`user_message` 순서**: 첫 몇 줄에 현재 결론과 다음 행동이 있는가. 소요 시간보다 엘리베이터, 환승, 출구, 장애인화장실 근거가 앞서는가. 출처와 기준 시각은 끝에 두되 빠진 근거를 숨기지 않는가. 역이나 호선이 모호하면 질문을 하나만 하는가.
5. **키 노출**: 로그, 응답, fixture, 오류 메시지, 검증 증거에 서비스 키나 키가 붙은 URL이 없는가.
6. **공개 계약**: 8개 MCP tool의 이름과 인자, Pydantic 출력 schema가 하위 호환되는가. 바뀌었다면 이유가 있는가.
7. **테스트**: 새 동작마다 대표 질문 fixture와 회귀 테스트가 있는가. 확인과 미확인의 분리를 단언하는가. 통과 여부는 `scripts/verify.py`의 run id로 확인한다.

## 출력

- 발견: 심각도순. 파일과 줄, 재현 질문이나 입력, 사용자에게 생기는 영향, 필요한 수정.
- 판정: 통과 또는 보류.
- 검토 방식: `자체 점검`(변경한 세션이 직접 확인) 또는 `독립 검토`(변경하지 않은 서브에이전트나 다른 도구). 자체 점검을 독립 검토로 적지 않는다.
