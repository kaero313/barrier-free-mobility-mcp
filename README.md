# Barrier-Free Mobility MCP

[![CI](https://github.com/kaero313/barrier-free-mobility-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/kaero313/barrier-free-mobility-mcp/actions/workflows/ci.yml)

서울 지하철의 엘리베이터와 장애인화장실 정보를 AI에서 질문할 수 있게 해 주는 MCP
서버입니다. 휠체어, 유모차, 보행 보조기구를 사용하거나 계단과 에스컬레이터 이용이 어려운
사람이 **확인된 정보와 출발 전에 더 확인할 내용**을 구분해서 볼 수 있도록 돕습니다.

일반 길찾기처럼 소요 시간만 알려주는 서비스가 아닙니다. 출발역, 환승역, 도착역의 접근성
정보를 공공데이터에서 조회하고, 사용자의 이동 조건에 맞춰 같은 규칙으로 판단합니다.

## 프로젝트 자료

- 기술 블로그: [공공데이터로 교통약자 이동 MCP 서버를 만들어보자](https://kaero313.github.io/posts/mcp_3/)
- 상세 설계·운영 기록: [Barrier-Free Mobility MCP Notion 허브](https://torpid-icon-d8a.notion.site/Barrier-Free-Mobility-MCP-39f4054272b58145b90ed07cd4f38ce0)

## 먼저 확인하세요

| 항목 | 현재 상태 |
|---|---|
| 공개 MCP 주소 | 아직 제공하지 않습니다 |
| API key 없는 로컬 체험 | `mock` 모드로 가능합니다 |
| 실제 공공데이터 조회 | `live` 모드와 공공 API key가 필요합니다 |
| 설치 없는 일반 사용자 이용 | 공개 HTTPS 서버가 배포된 뒤 가능합니다 |

현재는 **로컬에서 실행하고 검증할 수 있는 단계**입니다. 개발 지식이 없는 사용자가 GPT나
Claude 같은 웹 화면에 주소만 추가해 바로 쓰는 공개 서비스는 아직 아닙니다.

## 이런 질문을 할 수 있습니다

- `휠체어로 홍대입구역에서 삼성역까지 갈 수 있어?`
- `유모차로 서울역에서 시청역까지 계단 없이 갈 수 있어?`
- `2호선 삼성역 엘리베이터 어디 있어?`
- `강남역 엘리베이터 지금 운행 중이야?`
- `2호선 잠실역에 장애인화장실 있어?`
- `엘리베이터 점검 중인 역을 피할 대안이 있어?`

역이나 호선이 모호하면 임의로 고르지 않고 한 번에 한 가지 정보만 다시 묻습니다. 예를 들어
`고속터미널역`처럼 여러 호선이 지나는 역은 확인할 호선을 요청합니다.

## 답변은 이렇게 보여줍니다

다음은 형식을 설명하기 위한 예시입니다. 실제 위치, 운행 상태, 조회 시각은 `live` 조회 결과에
따라 달라집니다.

> **엘리베이터는 운행 중입니다. 휠체어 이동 동선을 추가로 확인하세요.**
>
> 홍대입구역과 삼성역의 엘리베이터 위치와 운행 상태는 확인됐습니다. 다만 승강장에서
> 대합실까지 엘리베이터로 이어지는지는 현재 공공데이터만으로 확인되지 않았습니다.
>
> **권장 확인:** 두 역의 역무실에 승강장에서 대합실까지 엘리베이터로 이동할 수 있는지
> 문의하세요.

| 역 | 확인된 정보 | 추가 확인 |
|---|---|---|
| 출발역: 2호선 홍대입구역 | 엘리베이터 위치, 현재 운행 중 | 승강장→대합실 연결 |
| 도착역: 2호선 삼성역 | 엘리베이터 위치, 현재 운행 중 | 승강장→대합실 연결 |

답변 아래에는 사용한 데이터의 종류와 조회 시각, 현장에서 달라질 수 있는 사항을 함께
표시합니다.

### 표현의 의미

| 표현 | 의미 |
|---|---|
| 확인됨 | 연결된 데이터에서 근거를 찾았습니다 |
| 미확인 | 데이터만으로 판단할 근거가 부족합니다 |
| 조회 결과 없음 | API 조회는 성공했지만 일치하는 항목이 없었습니다 |
| 지원 범위 밖 | 연결된 데이터가 해당 역이나 운영기관을 제공하지 않습니다 |
| 조회 실패 | 외부 API 오류로 현재 정보를 가져오지 못했습니다 |

`미확인`은 시설이 없다는 뜻이 아닙니다. 반대로 엘리베이터가 있다는 사실만으로 승강장에서
출구까지 모든 구간이 연결됐다고 판단하지도 않습니다.

## 가장 빠르게 체험하기

`mock` 모드는 실제 현장 상태가 아닌 고정 예시 데이터로 동작합니다. 기능 확인과 개발용으로만
사용하고 실제 이동 판단에는 사용하지 마세요.

### 1. 준비

- Python 3.12 이상
- [uv](https://docs.astral.sh/uv/)
- Windows PowerShell

### 2. 내려받기

```powershell
git clone https://github.com/kaero313/barrier-free-mobility-mcp.git
Set-Location barrier-free-mobility-mcp
uv sync --frozen
Copy-Item .env.example .env
```

### 3. 서버 실행

```powershell
.\scripts\start_local_mcp.ps1
```

기본 MCP 주소는 다음과 같습니다.

```text
http://127.0.0.1:8000/mcp
```

서버를 실행한 터미널은 그대로 둡니다.

### 4. 질문해 보기

새 PowerShell 터미널을 열고 프로젝트 폴더에서 실행합니다.

```powershell
uv run python scripts/test_mcp_client.py `
  --tool answer_accessibility_question `
  --question "휠체어로 홍대입구역에서 삼성역까지 갈 수 있어?" `
  --summary-only
```

출력의 `user_message`가 일반 사용자에게 보여줄 기본 답변입니다.

## 내 AI에 연결하기

서버를 실행한 뒤, Streamable HTTP 방식의 MCP 주소를 지원하는 클라이언트에 아래 값을
등록합니다.

| 설정 | 값 |
|---|---|
| 이름 | `Barrier-Free Mobility MCP` |
| MCP URL | `http://127.0.0.1:8000/mcp` |
| 전송 방식 | `Streamable HTTP` |
| 인증 | 없음, 로컬 기본 설정 |

클라이언트마다 MCP 등록 화면과 설정 파일 형식은 다릅니다. 연결 후에는 평소 대화하듯 질문하면
되고, 일반 자연어 질문은 `answer_accessibility_question` 도구가 처리합니다.

### localhost 연결이 안 되는 경우

브라우저에서만 동작하는 AI 서비스는 사용자 PC의 `127.0.0.1`에 직접 접근하지 못할 수
있습니다. 이 경우 코드 문제가 아니라 실행 위치의 차이입니다.

| 사용 환경 | 로컬 MCP 연결 |
|---|---|
| 같은 PC에서 실행되는 MCP 클라이언트 | 연결 가능 |
| 웹에서만 실행되는 AI 서비스 | 일반적으로 직접 연결 불가 |
| HTTPS로 배포된 MCP 서버 | 외부 연결 가능 |

웹 기반 AI에서 사용하려면 운영자가 이 서버를 HTTPS 주소로 배포해야 합니다. 그때 공공 API
key는 운영 서버가 관리하며 일반 사용자가 직접 발급받을 필요는 없습니다.

## 실제 공공데이터로 실행하기

로컬에서 실제 데이터를 조회하려면 `.env`에 발급받은 key와 API endpoint를 입력합니다.

```env
APP_MODE=live
PUBLIC_DATA_SERVICE_KEY=
ELEVATOR_STATUS_API_KEY=
ELEVATOR_INFO_API_KEY=
RESTROOM_API_KEY=
FACILITY_API_URL=
SHORTEST_ROUTE_API_URL=
ELEVATOR_STATUS_API_URL=
ELEVATOR_INFO_API_URL=
RESTROOM_API_URL=
```

전체 설정 항목은 [.env.example](.env.example)을 참고합니다. 실제 key는 `.env`에만 저장하고
이슈, 채팅, 문서, fixture, 로그에 넣지 마세요.

설정 후 다음 명령으로 실행합니다.

```powershell
.\scripts\start_local_mcp.ps1 -AppMode live
```

일부 공공 API가 실패하더라도 확인 가능한 결과는 반환합니다. 답변의 `미확인`, `조회 실패`,
`기준 시각`을 함께 확인해야 합니다.

## 데이터와 지원 범위

다음 서울 지하철 공공데이터를 정규화해 사용합니다.

- 최단경로 이동정보
- 편의시설 위치정보
- 교통약자 이용시설 승강기 가동현황
- 지하철역 엘리베이터 현황
- 지하철역 장애인화장실 현황

현재 `live` 완전 지원 범위는 28개 역·호선 조합입니다. 그 외 등록된 조합은 가능한 정보만
반환하고 부족한 근거를 답변에 표시합니다. 등록되지 않은 역을 비슷한 이름의 다른 역으로
자동 확정하지 않습니다.

<details>
<summary>완전 지원 역 목록 보기</summary>

| 호선 | 완전 지원 역 |
|---|---|
| 1호선 | 서울역, 시청, 신도림 |
| 2호선 | 시청, 홍대입구, 강남, 삼성, 교대, 사당, 동대문역사문화공원, 왕십리, 합정, 신도림, 건대입구, 잠실 |
| 3호선 | 교대, 고속터미널 |
| 4호선 | 서울역, 사당, 동대문역사문화공원 |
| 5호선 | 동대문역사문화공원, 왕십리, 여의도 |
| 6호선 | 합정 |
| 7호선 | 고속터미널, 건대입구 |
| 8호선 | 잠실 |
| 9호선 | 봉은사 |

</details>

9호선 1단계 구간인 `개화`부터 `신논현`까지는 현재 연결된 서울교통공사 시설 데이터의 제공
범위 밖입니다. 이 경우 시설이 없다고 표현하지 않고 `지원 범위 밖`으로 안내합니다.

## 이용 전에 알아둘 점

- 이 MCP는 일반 지하철 길찾기 앱을 대체하지 않습니다.
- 특정 경로가 안전하거나 완전히 무단차라고 보장하지 않습니다.
- 엘리베이터 존재와 필요한 전체 이동 동선 연결은 서로 다른 정보입니다.
- 공공데이터 조회 시점과 실제 현장 상태가 다를 수 있습니다.
- 실제 이동 전에는 답변의 기준 시각과 권장 확인 사항을 확인하세요.

## 문제가 생겼을 때

| 증상 | 확인할 내용 |
|---|---|
| 서버가 시작되지 않음 | Python 3.12 이상과 `uv sync --frozen` 실행 여부를 확인합니다 |
| `localhost`에 연결할 수 없음 | 서버 터미널이 실행 중인지, 클라이언트가 같은 PC에서 동작하는지 확인합니다 |
| 8000 포트를 이미 사용 중 | `.env`의 `MCP_PORT`를 다른 값으로 바꿉니다 |
| 실제 정보가 아닌 예시가 나옴 | `.env`의 `APP_MODE`가 `mock`인지 확인합니다 |
| 답변에 미확인 정보가 많음 | API 실패, 부분 지원 역, 제공되지 않는 동선 정보인지 확인합니다 |

## 개발자 참고

핵심 판단은 서버 내부 LLM이 아니라 규칙 기반 엔진에서 수행됩니다. 공공 API 응답은 adapter와
normalizer를 거쳐 Pydantic v2 구조로 변환되며, 일부 데이터 소스가 실패해도 가능한 범위에서
부분 결과를 반환합니다.

### MCP 도구

| 도구 | 용도 |
|---|---|
| `answer_accessibility_question` | 자연어 경로, 시설, 대안 질문 처리 |
| `generate_accessibility_brief` | 구조화 입력으로 사용자용 답변 생성 |
| `check_accessible_trip` | 경로 판단과 상세 근거 반환 |
| `resolve_station` | 역명, 호선, 별칭 해석 |
| `get_station_facilities` | 역 편의시설 조회 |
| `get_elevator_status` | 엘리베이터 위치와 운행 상태 조회 |
| `get_accessible_restroom` | 장애인화장실 조회 |
| `get_route_candidates` | 공공 API 경로 후보 조회 |

`user_message`는 최종 사용자에게 우선 표시할 답변입니다. `status`, `risk_level`,
`accessibility_checks`, `evidence_sources`, `failed_sources`, `limitations`는 판단 근거와 검증에
사용합니다. LLM 클라이언트가 구조화 필드를 보고 별도의 안전 보장을 만들어서는 안 됩니다.

### 구조

```text
LLM client → MCP tools → services → public API adapters
                              ↓
                    deterministic engine
                              ↓
                 Pydantic result + user_message
```

상세한 계층 경계와 설계 결정은 [아키텍처 문서](docs/architecture.md)를 참고합니다.

### 검증

```powershell
uv run --frozen pytest
uv run --frozen ruff check .
uv run --frozen python scripts/check_release_safety.py
```

실제 API 답변 품질, MCP 상호운용성, 사용자 리뷰 절차는
[검증 가이드](docs/validation.md)에 정리되어 있습니다.

## 문서

| 문서 | 내용 |
|---|---|
| [아키텍처](docs/architecture.md) | 데이터 흐름, 계층 경계, 주요 설계 결정 |
| [검증 가이드](docs/validation.md) | 자동 테스트, live 평가, MCP 상호운용성, 사용성 리뷰 |
| [ROADMAP](ROADMAP.md) | 아직 완료되지 않은 작업 |
| [AGENTS](AGENTS.md) | repository 작업 규칙 |
