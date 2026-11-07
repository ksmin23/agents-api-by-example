# 예제로 배우는 Agents API

이 프로젝트는 OpenAI가 공식 제작하거나 승인한 문서가 아닌 독립적인 학습 자료입니다.

CSV 분석·보고서 예제로 시작해 도구 연결, Skills·Plugins, 승인, Multi-agent와 사내 배포까지 실습합니다.

Agents API의 기능별 사용법을 Python·Jupyter Notebook·Docker 예제로 학습하는 독립적인 한국어 가이드입니다. CSV 분석·보고서 작성을 시작으로 Function Tool, MCP, Skills, Plugins, 승인과 사내 배포·운영까지 확장합니다. 15장에서는 두 하위 에이전트의 분석을 통합하는 Multi-agent 종합 실습을 제공합니다.

**Jupyter Book + Jupyter Notebook + Colab + uv**로 설명과 실행 코드를 Git에서 함께 관리합니다. Python OpenAI SDK의 `client.beta.agents`를 사용하며, API 설정·실행·결과 확인은 노트북에서 직접 읽을 수 있습니다.

[처음 시작하기](#처음-시작하기) · [기능별로 찾기](#무엇을-배우고-싶으신가요) · [전체 실습 목차](#순서대로-학습하기) · [실습 안내와 검증 방법](docs/validation.md)

## 처음 시작하기

Python·기본 함수 사용에 익숙한 개발자를 대상으로 합니다. 로컬에서는 **uv와 Python 3.12**를 사용하며, Python 버전은 `.python-version`, 패키지 버전은 `uv.lock`으로 맞춥니다. [uv 설치 안내](https://docs.astral.sh/uv/getting-started/installation/)를 참고하세요. 교재 웹 미리보기·빌드에는 Node.js 22 LTS도 필요합니다.

### 1. 프로젝트 설치

저장소 접근 권한이 있는 환경에서 소스를 준비합니다. 이미 작업 폴더가 있다면 그 폴더에서 `uv sync --locked`부터 실행하세요.

```bash
git clone https://github.com/ksmin23/agents-api-by-example.git
cd agents-api-by-example
uv sync --locked
```

### 2. 키 설정 후 Jupyter 실행

오프라인 환경 점검에는 키가 필요하지 않습니다. 실제 API 실습에는 [API 키 생성과 설정](#openai-키-생성과-설정)에 따라 `.env.local`의 `OPENAI_API_KEY`·`OPENAI_MODEL`을 준비합니다. 기존 파일과 키는 유지하세요.

```bash
uv run jupyter lab
```

[환경 준비와 실행 점검](notebooks/setup.ipynb)을 실행한 뒤, [빠른 시작](notebooks/quickstart.ipynb)에서 **세션 생성 → 스트리밍 → 결과 확인 → 자원 정리**를 실습합니다. VS Code에서는 프로젝트의 `.venv` Python을 노트북 커널로 선택하세요.

노트북은 기본 `RUN_LIVE=False`·`RUN_DOCKER=False`입니다. 실제 API는 노트북의 `RUN_LIVE=True` 또는 실행 도구의 `--live`로 선택하며, 모델·sandbox 사용에는 비용이 발생합니다. Docker 실습은 별도로 활성화합니다.

일반 Jupyter에서 기본값으로 **모두 실행**하면 API 준비 셀에서 안내 오류와 함께 멈춥니다. 설정 셀의 `RUN_LIVE=True`를 적용한 뒤 준비 셀부터 순서대로 실행하세요. 준비 셀에서만 실행 허용을 확인하고, 이후 셀은 API 호출·결과 처리·`finally` 정리를 직접 보여줍니다. `requires_api` 태그는 검증기에서 API 준비·실행·결과 의존 셀을 건너뛰는 기준이며, Jupyter 자체에서 셀 실행을 막지 않습니다.

```bash
# 키 없이 로컬 준비·정의·계산 셀만 새 커널에서 실행
uv run --group dev python scripts/check_notebooks.py --execute
```

## 필요한 패키지 선택하기

`uv sync --locked`는 SDK와 Jupyter 실습 패키지만 설치합니다. 다음 선택 그룹은 필요한 경우에만 추가하세요.

| 목적 | 실행 명령 |
| --- | --- |
| 기본 노트북 실습 | `uv run jupyter lab` |
| 13장 메모리 Telemetry | `uv run --group telemetry jupyter lab` |
| 13장 선택 Collector 전송 | `uv run --group telemetry-otlp jupyter lab` |
| 전체 테스트·자동 검증 | `uv run --group dev python -m unittest discover -s tests -v` |
| 교재 빌드·미리보기 | `uv run --group docs python scripts/preview_book.py --build` |
| SOCKS 프록시 사용 | `uv run --group proxy jupyter lab` |

여러 그룹은 함께 지정할 수 있습니다. dev는 MCP 테스트와 Collector 검사까지 포함합니다. 선택 기능을 사용할 때에는 `uv run`에도 그룹을 명시해야 하며, 그룹 없이 실행하면 선택 패키지가 제거될 수 있습니다. VS Code에서 직접 `.venv` 커널을 고르면 먼저 `uv sync --locked --group telemetry`처럼 필요한 그룹을 설치하세요. CI는 dev·docs를 설치한 뒤 `uv run --no-sync`로 같은 환경을 유지합니다.

환경의 `UV_DEFAULT_INDEX`가 프로젝트의 공개 PyPI 설정을 덮어쓸 수 있습니다. 잠금 파일 오류 시 `uv sync --locked --default-index https://pypi.org/simple`로 비교하고, 후속 `uv run`에도 같은 `--default-index`를 사용하세요. 회사 정책상 사설 인덱스가 필수라면 정책에 맞는 별도 잠금 구성을 사용합니다. SOCKS 사용 시에만 proxy 그룹을 추가하고, 프록시·인덱스 URL의 자격 증명을 출력하지 마세요.

## 무엇을 배우고 싶으신가요?

| 하고 싶은 일 | 시작할 실습 | 확인할 결과 | 참고 문서 |
| --- | --- | --- | --- |
| 첫 세션을 만들고 응답 받기 | [빠른 시작](notebooks/quickstart.ipynb) · [2장](notebooks/chapters/02_first_agent.ipynb) | 스트리밍 응답·완료 Turn·계산 결과 | [Quickstart](https://developers.openai.com/api/docs/guides/agents-api/quickstart) · [Events and items](https://developers.openai.com/api/docs/guides/agents-api/sessions/events) |
| 대화를 이어가고 Agent 설정 재사용하기 | [3장](notebooks/chapters/03_sessions.ipynb) · [4장](notebooks/chapters/04_agent_configuration.ipynb) | 후속 Turn·저장 이력·세션별 설정 | [Sessions](https://developers.openai.com/api/docs/guides/agents-api/sessions) · [Configuring Agents](https://developers.openai.com/api/docs/guides/agents-api/configuration) |
| 파일을 분석하고 보고서 내려받기 | [5장](notebooks/chapters/05_files_artifacts.ipynb) · [6장](notebooks/chapters/06_environment.ipynb) | JSON·Markdown·설치 환경 증거 | [Files and artifacts](https://developers.openai.com/api/docs/guides/agents-api/environments/files) · [OpenAI-hosted sandboxes](https://developers.openai.com/api/docs/guides/agents-api/environments/openai-hosted) |
| Python 함수나 MCP로 업무 데이터 연결하기 | [7장](notebooks/chapters/07_function_tools.ipynb) · [8장](notebooks/chapters/08_mcp.ipynb) | 업무 목표 조회·달성률 보고서 | [Functions](https://developers.openai.com/api/docs/guides/agents-api/tools/functions) · [MCP connections](https://developers.openai.com/api/docs/guides/agents-api/tools/mcp) |
| Skills·Plugins로 분석 기능 재사용하기 | [9장](notebooks/chapters/09_skills.ipynb) · [10장](notebooks/chapters/10_plugins.ipynb) | 등록 목록·번들 코드 실행·MCP 연동 | [Hosted skills 설정](https://developers.openai.com/api/docs/guides/agents-api/environments/openai-hosted#add-skills-and-plugins) · [Plugins](https://developers.openai.com/api/docs/guides/agents-api/tools/plugins) · [Skills — Agents API 절 · 공통 보조](https://developers.openai.com/api/docs/guides/tools-skills#agents-api) |
| 검증과 승인 절차 추가하기 | [11장](notebooks/chapters/11_guardrails_approvals.ipynb) | 정책 거절·승인된 보고서의 로컬 등록 | [Functions](https://developers.openai.com/api/docs/guides/agents-api/tools/functions) · [Automatic review](https://developers.openai.com/api/docs/guides/agents-api/sessions/approvals) · [Sandbox security](https://developers.openai.com/api/docs/guides/agents-api/environments/security) |
| 사내 패키지·네트워크에서 실행하기 | [12장](notebooks/chapters/12_self_hosted.ipynb) | Self-hosted 연결·사내 패키지·Skill 실행 | [Self-hosted sandboxes](https://developers.openai.com/api/docs/guides/agents-api/environments/self-hosted) · [Sandbox lifecycle](https://developers.openai.com/api/docs/guides/agents-api/environments/lifecycle) |
| 실행을 조사하고 중단된 관찰에서 복구하기 | [13장](notebooks/chapters/13_hooks_telemetry.ipynb) · [14장](notebooks/chapters/14_operations.ipynb) | Trace 확인 경로·OTel span·원래 Turn 복구 | [Observability](https://developers.openai.com/api/docs/guides/agents-api/observability) · [Tracing](https://developers.openai.com/api/docs/guides/agents-api/tracing) · [Events and items](https://developers.openai.com/api/docs/guides/agents-api/sessions/events) |
| 분석을 여러 담당에게 분담하기 | [15장](notebooks/chapters/15_multi_agent.ipynb) | 두 하위 에이전트의 매출·목표 분석, 메인의 보고서 통합 | [Multi-agent](https://developers.openai.com/api/docs/guides/agents-api/multi-agent) |

참고 문서는 별도 표시가 없으면 Agents API 전용 문서입니다. 공통 Skills 문서는 Agents API 절을 직접 연결했으며, Codex 문서는 각 노트북의 보조 자료에서 별도로 안내합니다.

## 공통 실습 예제

합성 [sales.csv](data/sales.csv)를 분석해 **6행·판매 수량 11·총매출 127,500**을 계산하고, `summary.json`과 한국어 `report.md`를 만듭니다.

```text
CSV 입력 → Python 분석 → JSON·Markdown 보고서
                      → 업무 목표 조회 → Skill·Plugin 재사용
                      → 검증·승인 → 사내 실행·관측·복구
                      → 매출 구조·목표 분석 분담 → 통합 보고서
```

2–4장은 메시지 CSV의 JSON 응답을 확인하고, 5장부터 분석 요약 파일·보고서를 다운로드합니다. 각 장은 같은 입력으로 기능을 비교하는 독립 실습이며, 도구·패키지·승인 구성이 자동으로 누적되지는 않습니다. [공통 학습·실습 안내](docs/validation.md)에서 장별 응답·파일 변화와 실행 환경을 비교할 수 있습니다.

목표 조회 예제에서는 가상의 목표 매출 **150,000**을 연결합니다. JSON 달성률은 **0.85**, 보고서의 백분율은 **85%** 입니다. Preface는 이 예제에 앞서 숫자 3개의 합계 60으로 API 구동을 확인합니다.

## 순서대로 학습하기

**준비·Preface → 입문 1–6장 → 기능 확장 7–11장 → 사내 배포·운영 12–14장 → Multi-agent 종합 실습 15장** 순서입니다. 15장은 3·5장 이후 바로 실습할 수도 있으며, 12–14장 사내 환경 구성은 선행 조건이 아닙니다. 각 장은 새 커널에서 독립적으로 실행할 수 있으며, 장 제목을 누르면 실행 노트북을 확인할 수 있습니다. 설명 문서의 학습 목표·진행 순서·운영 주의사항을 노트북에 통합했으며, Book 메뉴에는 장마다 하나의 페이지만 표시합니다.

| 학습 목적 | 권장 연결 |
| --- | --- |
| API 기능부터 역할 분담까지 | 1–11장 → 15장 |
| 사내 배포·운영까지 | 1–11장 → 12–14장 → 15장 |
| Multi-agent 먼저 | 3·5장 → 15장 |

### 준비와 첫 실행

| 단계 | 장 제목·실행 노트북 | 소개할 내용 | 실습 결과·확인 항목 |
| --- | --- | --- | --- |
| 준비 | [환경 준비와 실행 점검](notebooks/setup.ipynb) | 로컬 Jupyter·Colab, Python·SDK 버전과 데이터 경로 확인 | API 호출 없이 환경 정보와 노트북 실행 확인 |
| Preface | [빠른 시작: 첫 세션 실행](notebooks/quickstart.ipynb) | 세션 생성 → 이벤트 스트리밍 → root Turn·명령 결과 확인 → 삭제 | 숫자 3개의 합계 60, 명령 종료 코드 0, 세션 삭제 후 404 |

### 입문 과정: 1–6장

Agent·Session·Turn·Environment를 이해하고 CSV 분석부터 파일·설치 환경 관리까지 실습합니다. 1장은 입력 CSV 구조와 산출물 규약을 확인하며 API를 호출하지 않습니다.

| 단계 | 장 제목·실행 노트북 | 소개할 내용 | 실습 결과·확인 항목 |
| --- | --- | --- | --- |
| 1장 | [Agents API 핵심 개념](notebooks/chapters/01_concepts.ipynb) | Agent·Session·Turn·Environment의 역할, 입력·출력·실행 환경의 구분 | CSV 입력·반환 필드·미전송 요청 구성 확인; API 호출 없음 |
| 2장 | [CSV 분석 에이전트 실행](notebooks/chapters/02_first_agent.ipynb) | CSV를 메시지로 전달, `sessions.create`, 스트리밍 이벤트·최종 결과 수집 | 실제 Python 명령과 최종 집계 JSON 일치, 소유 세션 정리 |
| 3장 | [대화 이어가기와 실행 상태 관리](notebooks/chapters/03_sessions.ipynb) | 같은 세션의 후속 입력, `sessions.stream`, Turn·items 이력 조회 | 동일 Session의 서로 다른 2개 Turn, 전체·일별 매출 JSON과 저장 이력 |
| 4장 | [에이전트 설정과 재사용](notebooks/chapters/04_agent_configuration.ipynb) | 저장 Agent 생성·`agent_id` 재사용·세션별 지침 override | 독립된 두 세션의 결과 비교, 저장 지침 유지, 세션·Agent 삭제 |
| 5장 | [파일 입력과 결과물 다운로드](notebooks/chapters/05_files_artifacts.ipynb) | `environment.files`, artifacts 조회·다운로드·파일 내용 검증 | 내려받은 `summary.json`·`report.md`와 CSV 기준값 일치 |
| 6장 | [실행 환경과 의존성 준비](notebooks/chapters/06_environment.ipynb) | `packages`·네트워크·`setup_commands`, pandas 설치와 준비 순서 | 분석 보고서와 `environment.json`, 설치 버전·입력 행 수 확인 |

### 기능 확장: 7–11장

Function Tool → MCP → Skills → Plugins → 애플리케이션 Guardrails·승인 순서로 같은 보고서 예제를 확장합니다.

| 단계 | 장 제목·실행 노트북 | 소개할 내용 | 실습 결과·확인 항목 |
| --- | --- | --- | --- |
| 7장 | [Function Tool로 업무 데이터 연결하기](notebooks/chapters/07_function_tools.ipynb) | 직접 호출하는 `get_sales_target` 함수, 공식 `function_tool`·`.definition`·`tool_handlers`로 등록·실행 | 목표 150,000 조회, 달성률 0.85와 보고서, 저장된 실제 함수 호출 확인 |
| 8장 | [MCP로 같은 업무 도구 제공하기](notebooks/chapters/08_mcp.ipynb) | 환경 내부 stdio MCP, 도구 허용 목록·초기화·호출 확인 | 같은 목표 조회를 MCP로 수행, MCP 호출 기록과 달성률 보고서 |
| 9장 | [Skills로 분석 절차와 코드 재사용하기](notebooks/chapters/09_skills.ipynb) | `SKILL.md`·번들 스크립트·inline ZIP·`environment.skills`, 등록된 스킬 목록 조회 | Skill 코드가 만든 보고서와 `skill_evidence.json`, 등록 이름·유형·revision·입력 해시 확인 |
| 10장 | [Plugins로 Skill과 MCP 묶어 배포하기](notebooks/chapters/10_plugins.ipynb) | Plugin manifest·MCP 설정·ZIP·`environment.plugins`, 의존성 분리 | Plugin에 포함된 Skill 실행과 MCP 호출을 각각 검증한 목표 비교 보고서 |
| 11장 | [Guardrails와 사람의 승인 구현하기](notebooks/chapters/11_guardrails_approvals.ipynb) | 애플리케이션 입력·출력 검증·권한·승인, API `review` 설정의 역할 | 허용하지 않은 채널 거절, 승인된 보고서만 로컬 등록, SHA-256·저장 바이트 대조 |

7장 기본 예제는 공식 SDK가 함수 인자를 검증하고 실행 결과를 제출합니다. `required_actions`·원래 Turn/Call ID로 `tool_result`를 직접 처리하는 방법은 [Function Tool 심화 자료](docs/extensions/function-tool-actions.md)와 11장에서 설명합니다. 별도로 등록하지 않은 Spreadsheets가 등장하는 이유와 목록 확인은 [기본 스킬 보충 자료](docs/extensions/builtin-skills.md)를 참고하세요.

### 사내 배포·운영: 12–14장

Self-hosted 환경과 사내 패키지, 실행 관측, 재구독·복구를 다룹니다. 13·14장의 hosted API 실습과 선택 Docker 확장을 구분합니다.

| 단계 | 장 제목·실행 노트북 | 소개할 내용 | 실습 결과·확인 항목 |
| --- | --- | --- | --- |
| 12장 | [Self-hosted 환경과 사내 패키지 설치](notebooks/chapters/12_self_hosted.ipynb) | Docker `exec-server`·Environment key·내부 패키지 설치·Skill·자원 관리 | `acme-sales`로 만든 보고서와 `package_evidence.json`, 실제 API 연결·세션/Docker 정리 |
| 13장 | [Hooks와 Telemetry로 실행 관측하기](notebooks/chapters/13_hooks_telemetry.ipynb) | 기본 Trace 확인과 선택 export, 실제 API 이벤트 → 애플리케이션 callback/span, 선택 OTLP·native Hook과의 구분 | `application-hooks.json`, Session/Turn에 연결된 span과 선택 Collector 수집 결과, Trace export 상태 확인 |
| 14장 | [장애·복구와 운영 관리](notebooks/chapters/14_operations.ipynb) | 관찰 스트림 재연결·저장 Turn/items·usage·중복 입력 방지, 선택 Docker 복원 | 입력 재전송 없이 원래 root Turn 1개와 보고서 복구, usage 미보고/0 구분 |

### 종합 실습: 15장 Multi-agent

| 단계 | 장 제목·실행 노트북 | 소개할 내용 | 실습 결과·확인 항목 |
| --- | --- | --- | --- |
| 15장 | [Multi-agent로 매출 분석을 분담하고 보고서 통합하기](notebooks/chapters/15_multi_agent.ipynb) | `agent.multi_agent`, 두 담당의 생성 이벤트·저장 명령·Turn 조회, 공유 환경과 메인의 보고서 통합 | 매출 구조·목표 달성 JSON 2개, `summary.json`·`report.md`, 서로 다른 하위 에이전트의 Python 실행과 세션 정리 |

5장 파일 실습 이후 따라갈 수 있는 OpenAI-hosted 종합 실습입니다. Docker·executor 키가 필요하지 않습니다. 목표 매출은 같은 JSON 파일에서 읽고 각 담당은 독립적으로 계산합니다. [공식 Multi-agent 문서](https://developers.openai.com/api/docs/guides/agents-api/multi-agent)를 참고하세요.

## 실행 환경 선택하기

| 환경 | 사용할 실습 | 준비와 범위 |
| --- | --- | --- |
| 로컬 Jupyter·VS Code | 준비·Preface·1–15장 | uv로 설치하고 `.venv` 커널 사용; 실제 API는 `.env.local` 설정 |
| Colab | 준비·Preface·1–11장·15장의 Python 실습 경로 | 독립 실행본 업로드; 실제 API 실습은 Colab Secrets 사용, 준비·1장은 키 불필요; GitHub 접근 불필요 |
| Docker가 실행되는 로컬 환경 | 12장 Self-hosted, 13·14장 Docker 확장 | `RUN_DOCKER=True`; 12장 실연결에는 전용 Environment key도 필요 |

13·14장의 실제 OpenAI-hosted API 실습은 **Docker와 executor 키 없이** 로컬에서 실행할 수 있습니다. 이 장들의 Colab 배포본은 읽기용이며, Docker 실습은 로컬에서 수행합니다.

**GitHub 없이 실행하기:** [다운로드 안내](docs/colab.md)와 [Sites의 독립 실행본 ZIP](https://agents-api-by-example.openai.chatgpt.site/downloads/colab-notebooks.zip)에서 필요한 `.ipynb` 파일 하나를 내려받고, Colab의 **파일 → 노트북 업로드**로 엽니다. Google Drive로 공유해도 됩니다. 준비 셀은 현재 Python에 필요한 패키지와 버전을 직접 전달해 공개 PyPI에서 설치한 뒤, 포함된 helper·CSV·MCP·Skill·Plugin 파일을 임시 실습 폴더에 만듭니다. Git clone, 원격 Python 코드 실행, requirements 파일 다운로드는 없습니다. Python 패키지 설치에는 PyPI 인터넷 연결이 필요하며, 실제 API에는 API 접근 권한·키가 별도로 필요합니다.

`notebooks/`만 노트북 원본으로 관리합니다. 독립 실행본은 `_build/colab/`에 생성하며 Git에 포함하지 않습니다. 생성기는 원본을 수정하지 않고 helper·데이터·예제 파일을 포함한 배포 파일만 만듭니다. 학습자는 제공자가 전달한 파일을 업로드하면 됩니다. CI에서는 `colab-notebooks` 산출물을 제공하도록 구성했습니다. 비공개 저장소의 CI 산출물은 접근 권한이 있는 제공자가 받아 전달합니다.

생성과 점검:

```bash
uv run python scripts/configure_repository.py --check
uv run python scripts/build_colab.py
uv run python scripts/build_colab.py --check
uv run --group dev python scripts/check_colab.py --execute
```

검증기는 새 커널과 저장소 밖 작업 폴더에서 `requires_api` 셀·설치 셀을 제외한 오프라인 실행을 확인합니다. 실제 패키지 설치와 Colab 웹·유료 API 실행 검증은 구분해 기록합니다. 로컬 개발은 기존 `uv sync --locked`를 사용합니다. Colab에서 수정한 내용은 원본 Git 저장소에 자동 반영되지 않습니다.

<details>
<summary>다운로드 파일 목록 보기</summary>

<!-- colab-links:start -->
- 환경 준비와 실행 점검 · `setup.ipynb` · Colab 업로드용
- 빠른 시작: 첫 세션 실행 · `quickstart.ipynb` · Colab 업로드용
- 1장. Agents API 핵심 개념 · `chapters/01_concepts.ipynb` · Colab 업로드용
- 2장. CSV 분석 에이전트 실행 · `chapters/02_first_agent.ipynb` · Colab 업로드용
- 3장. 대화 이어가기와 실행 상태 관리 · `chapters/03_sessions.ipynb` · Colab 업로드용
- 4장. 에이전트 설정과 재사용 · `chapters/04_agent_configuration.ipynb` · Colab 업로드용
- 5장. 파일 입력과 결과물 다운로드 · `chapters/05_files_artifacts.ipynb` · Colab 업로드용
- 6장. 실행 환경과 의존성 준비 · `chapters/06_environment.ipynb` · Colab 업로드용
- 7장. Function Tool로 업무 데이터 연결하기 · `chapters/07_function_tools.ipynb` · Colab 업로드용
- 8장. MCP로 같은 업무 도구 제공하기 · `chapters/08_mcp.ipynb` · Colab 업로드용
- 9장. Skills로 분석 절차와 코드 재사용하기 · `chapters/09_skills.ipynb` · Colab 업로드용
- 10장. Plugins로 Skill과 MCP 묶어 배포하기 · `chapters/10_plugins.ipynb` · Colab 업로드용
- 11장. Guardrails와 사람의 승인 구현하기 · `chapters/11_guardrails_approvals.ipynb` · Colab 업로드용
- 12장. Self-hosted 환경과 사내 패키지 설치 · `chapters/12_self_hosted.ipynb` · 읽기용 · 실습은 로컬 Docker
- 13장. Hooks와 Telemetry로 실행 관측하기 · `chapters/13_hooks_telemetry.ipynb` · 읽기용 · 실습은 로컬 Python·선택 Docker
- 14장. 장애·복구와 운영 관리 · `chapters/14_operations.ipynb` · 읽기용 · 실습은 로컬 Python·선택 Docker
- 15장. Multi-agent로 매출 분석을 분담하고 보고서 통합하기 · `chapters/15_multi_agent.ipynb` · Colab 업로드용
<!-- colab-links:end -->

</details>

## OpenAI 키 생성과 설정

실제 API 실습 전에 아래 키를 준비합니다. 오프라인 노트북 점검과 교재 빌드에는 키가 필요하지 않습니다.

| 변수 | 필요한 실습 | 발급 위치·용도 |
| --- | --- | --- |
| `OPENAI_API_KEY` | Preface와 API를 호출하는 장 | 프로젝트 API key. 세션 생성·조회·모델 실행에 사용 |
| `OPENAI_EXECUTOR_API_KEY` | 12장 Self-hosted 실제 API 연결 | Environment key. executor의 환경 연결에만 사용 |

13·14장의 OpenAI-hosted API 실습에는 `OPENAI_API_KEY`만 필요합니다. 12장의 로컬 Docker 전용 검증도 executor 키 없이 실행할 수 있습니다.

### 1. 애플리케이션 API 키 만들기

1. [OpenAI Platform](https://platform.openai.com/)에 로그인하고 실습에 사용할 Organization과 Project를 선택합니다.
2. [API keys](https://platform.openai.com/api-keys)에서 해당 프로젝트의 새 API 키를 생성합니다. 이미 사용할 수 있는 프로젝트 키가 있다면 재사용할 수 있습니다.
3. 권한을 제한하는 경우 세션 작업에 `api.agents.read`·`api.agents.write`, 모델 추론에 `api.responses.write`가 허용되어 있는지 확인합니다.
4. 생성한 값을 아래 안내대로 로컬 `.env.local`의 `OPENAI_API_KEY`에 저장합니다. 선택한 프로젝트가 Agents API와 사용할 모델에 접근 가능한지도 확인합니다.

공식 안내: [API 키 생성](https://developers.openai.com/api/docs/quickstart#create-and-export-an-api-key) · [Agents API 인증과 권한](https://developers.openai.com/api/docs/guides/agents-api/environments/self-hosted#authentication).

### 2. Self-hosted용 Environment key 만들기 — 12장

1. 앱 키와 같은 Organization·Project에서 [Agents → Environments → Keys](https://platform.openai.com/agents?tab=environments&environment_view=keys)를 열고 **Create**를 선택합니다.
2. 세션을 소유하는 앱 키와 **동일한 사용자 또는 서비스 계정** 소유로 키를 생성합니다. 같은 Organization·Project만 맞추고 소유자를 다르게 설정하지 않도록 확인합니다.
3. 환경 연결 권한인 `api.agents.environments.connect`를 확인하고 다른 권한은 **None**으로 설정합니다.
4. 생성한 값을 `.env.local`의 `OPENAI_EXECUTOR_API_KEY`에 저장합니다. IP 제한을 사용한다면 executor가 OpenAI에 접속할 때 사용하는 외부 통신 IP도 허용합니다.

기존 앱 키를 `OPENAI_EXECUTOR_API_KEY`에 복사해 넣지 않습니다. 공식 Self-hosted 구성은 두 키를 분리하며, 이 튜토리얼도 같은 값이면 실행을 중단합니다. 앱 키는 컨테이너 밖에 두고, executor 키만 임시 읽기 전용 파일로 전달한 뒤 컨테이너 안에서 `CODEX_API_KEY`로 설정합니다. `CODEX_API_KEY`를 별도로 발급하거나 로컬 `.env.local`에 추가할 필요는 없습니다.

공식 안내: [Self-hosted 인증](https://developers.openai.com/api/docs/guides/agents-api/environments/self-hosted#authentication) · [Environment key 생성·IP 제한](https://developers.openai.com/cookbook/examples/agents_api/apps/sev_bot/readme#configure-the-slack-bot).

### 3. 로컬 파일과 Colab Secrets에 설정하기

프로젝트 루트에서 `.env.local`이 없을 때만 [.env.example](.env.example)을 복사합니다. 기존 파일의 키를 덮어쓰지 않습니다.

```bash
if [ ! -f .env.local ]; then
    cp .env.example .env.local
fi
```

`.env.local`을 편집해 아래 자리표시자를 실제 값으로 바꿉니다. 기존 키·모델을 사용하는 경우 해당 값을 유지합니다.

```dotenv
OPENAI_API_KEY=YOUR_APPLICATION_API_KEY
OPENAI_MODEL=gpt-6.1-sol
RUN_LIVE=false

# 12장 Self-hosted 실제 연결에만 필요합니다. 다른 실습에서는 비워 둡니다.
OPENAI_EXECUTOR_API_KEY=
```

`gpt-6.1-sol`은 이 교재의 실행 검증에 사용한 모델 예시입니다. 자신의 프로젝트에서 접근 가능한 모델로 설정하세요. `.env.local`에 `RUN_LIVE`를 적어도 API가 자동 실행되지는 않습니다. 노트북의 `RUN_LIVE=True` 또는 검증 도구의 `--live`로 실행을 명시하며, 모델·실행 환경 사용에는 비용이 발생합니다.

Colab에서 Preface·2–11장·15장의 실제 API 실습을 실행하려면 Secrets에 `OPENAI_API_KEY`와 `OPENAI_MODEL`을 등록하고 해당 노트북의 접근을 허용합니다. 12–14장 배포본은 읽기용이며 Self-hosted·Docker 검증은 로컬 Jupyter에서 수행합니다.

실제 키는 Git·노트북 셀·출력·이미지·로그에 넣지 않습니다. `.env.local`은 Git에서 제외되며 공개하는 `.env.example`에는 빈 값만 유지합니다.

## 실행 과정과 결과 확인하기

각 실행은 최종 응답·Turn 완료 상태·다운로드한 파일을 확인하고 생성한 세션을 정리합니다. 계산값과 실제 파일을 검증하며, 모델의 “완료했다”는 문구만으로 성공을 판단하지 않습니다. 반복되는 설정·metadata·자원 정리는 [공통 코드](src/tutorial_helpers/README.md)에서 처리합니다.

상세 실행 과정은 [Platform → Logs → Agents](https://platform.openai.com/logs?api=agents)에서 Session ID로 찾을 수 있습니다. 일반 장에는 별도 Trace 조회·저장 루프를 넣지 않습니다. [13장](notebooks/chapters/13_hooks_telemetry.ipynb)에서 필요한 경우에만 다음을 선택합니다.

| 선택 | 동작 |
| --- | --- |
| `INSPECT_TRACE=True` | 결과 검증 후 세션 삭제 전에 대기; Dashboard 확인 후 Enter로 정리 |
| `EXPORT_TRACES=True` | 세션 삭제 전에 API로 Trace 조회·OTLP JSON 저장 시도 |
| 기본값 | Trace 확인 대기·export 없이 분석 결과 확인과 정리 |

Trace export에는 조직 활성화와 `api.traces.read` 또는 `api.agents.read` 권한이 필요합니다. Trace 수집 상태는 분석 결과의 정확성·자원 정리 여부와 구분합니다.

실행 사본·다운로드·검증 결과는 Git에서 제외한 `outputs/` 아래에 보관합니다. Preface 결과는 `outputs/quickstart/<run_id>/summary.json`, 각 장 결과는 `outputs/intro`·`outputs/extensions`·`outputs/deployment-api`, Docker 기록은 `outputs/deployment`에 있습니다. 커널 강제 종료로 정리가 중단됐다면 `creation.json`의 고유 metadata와 저장된 ID로 복구합니다. [문제 해결 안내](docs/troubleshooting.md)를 참고하세요.

## 실습 실행과 검증 안내

실행 방법과 검증 명령은 아래 [교재 실행·빌드·기여](#교재-실행빌드기여)를 참고하세요. 실행 모드와 결과 해석은 [실습 안내와 검증 범위](docs/validation.md)를 참고하세요. 작업 진행 기록은 Git에서 제외한 `.work/PROGRESS.md`, 상세 실행 결과는 `outputs/`에서 로컬로 관리합니다. 기록 파일 없이도 실습·검증·빌드를 실행할 수 있습니다.

## 프로젝트 구성

```text
notebooks/             준비·Preface·1–15장과 새 장 템플릿 (노트북 원본)
_build/colab/          자동 생성 독립 실행본·전달용 README (Git 제외)
_build/bundles/        Skill·Plugin ZIP
_build/book/           sites·pages 대상별 완성 Book
_build/packages/       독립 Colab ZIP·공식 helper의 Sites 패키지
_build/manifest.json   입력·출력 해시·대상별 경로
docs/                  독립 보충 자료·실습 도움말·운영/검증 안내
scripts/               Colab 준비·링크 설정·노트북/번들 검증
data/                  합성 CSV와 가상의 매출 목표
src/tutorial_helpers/  설정·자원 정리·Docker/OTLP 기반 처리와 검증 전용 모듈
skills/csv-report/     CSV 분석 Skill과 번들 스크립트
plugins/sales-reporting/ Skill·MCP 서버를 포함한 Plugin
deploy/                Docker 이미지·사내 패키지·Skill·Hook/OTLP 설정
examples/self_hosted/  Self-hosted 예제 안내
.github/workflows/     검증·문서 게시 workflow 정의
```

## 교재 실행·빌드·기여

### 교재 미리보기와 빌드

```bash
uv run --group docs jupyter book start
uv run --group docs python scripts/build_artifacts.py --target sites
uv run --group docs python scripts/check_artifacts.py --target sites
```

Sites 완성본은 `_build/book/sites/`, Pages 완성본은 `_build/book/pages/`입니다. `--target pages` 또는 `--target all`로 선택합니다. 격리된 작업 폴더에서 Book을 빌드하고 리다이렉트·다운로드 조립과 manifest 검증까지 같은 명령으로 처리합니다. 빌드 중 노트북 API·Docker 셀은 실행하지 않습니다. 자세한 경로·개별 명령·Sites 준비 절차는 [배포 산출물 관리](docs/artifact-pipeline.md)를 참고하세요.

### 검증과 실제 실행 명령

<details>
<summary>작성자용 검사·장별 실행 명령 보기</summary>

키 없이 수행하는 검사(산출물 검사는 위 통합 빌드를 먼저 실행):

```bash
python3 scripts/check_tutorial.py --require-public --require-repository
uv lock --check
uv run --group dev python -m unittest discover -s tests -v
uv run --group dev python scripts/check_installation.py
uv run --group dev python scripts/check_notebooks.py --execute
uv run python scripts/configure_repository.py --check
uv run python scripts/build_bundles.py --check
uv run --group docs python scripts/check_artifacts.py --target sites
```

실제 모델·sandbox 사용과 생성 자원 정리를 포함하는 명시적 실행:

```bash
uv run --group dev python scripts/run_quickstart.py --live
uv run --group dev python scripts/run_intro.py --all --live
uv run --group dev python scripts/run_extensions.py --all --live --approval-fixture
uv run --group dev python scripts/run_multi_agent.py --live
uv run --group dev python scripts/run_deployment.py --chapter 12 --live --docker --build
uv run --group dev python scripts/run_deployment.py --chapter 13 --live
uv run --group dev python scripts/run_deployment.py --chapter 14 --live
```

`--approval-fixture`는 실제 사람 승인을 대신하는 테스트 입력입니다. 12장에는 Docker와 전용 executor 키가 필요합니다. 13·14장의 Docker 확장은 `--docker`로 별도 선택합니다. 선택 Trace export 재현 명령은 13장 노트북을, 각 실행의 범위는 [실습 안내와 검증 범위](docs/validation.md)를 참고하세요.

오프라인 과정별 점검은 `scripts/run_intro.py --all`, `scripts/run_extensions.py --all`, `scripts/run_deployment.py --all`을 `uv run python`으로 실행합니다. 실행 사본은 원본과 별도로 `outputs/*-validation/`에 저장합니다.

</details>

### 의존성 관리

```bash
uv add PACKAGE_NAME
uv run python scripts/build_colab.py
uv run python scripts/build_colab.py --check
```

`pyproject.toml`과 `uv.lock`을 검토한 뒤 Colab 노트북을 재생성합니다. 생성기는 직접 의존성의 고정 버전을 lockfile에서 읽어 설치 셀에 기록합니다. 13장은 메모리 관측용 OpenTelemetry SDK만 추가하며 HTTP exporter는 포함하지 않습니다. 전이 의존성 전체와 OS까지 동일하게 고정하는 것은 아닙니다. 기존 `requirements-colab.txt`와 GitHub 다운로드 bootstrap은 제거했습니다. 생성 파일은 직접 편집하지 않으며 CI에서 생성 후 최신 원본과 대조하고 오프라인 실행 뒤 다운로드 산출물로 업로드합니다.

### GitHub·Colab·Pages 설정

저장소 설정은 `ksmin23/agents-api-by-example`, 기준 ref는 `main`입니다. Pages 배포 대상 경로는 `https://ksmin23.github.io/agents-api-by-example/`이며, 현재 라이브 사이트가 게시됐다는 의미는 아닙니다. Publish workflow의 중단 상태는 유지합니다.

```bash
uv run python scripts/configure_repository.py --repository ksmin23/agents-api-by-example --ref main
```

이 명령은 로컬 메타데이터와 링크를 동기화합니다. 실제 저장소 생성·commit·push·게시를 수행하지 않습니다. workflow 구성과 Pages 경로 설정은 [게시 안내](docs/publishing.md)를 참고하세요. 라이선스는 공개 배포 전에 별도로 정합니다.

## 참고 자료

- [공식 Multi-agent](https://developers.openai.com/api/docs/guides/agents-api/multi-agent) — 하위 에이전트 위임·공유 환경·실행 이력

- [공식 Agents API 개요](https://developers.openai.com/api/docs/guides/agents-api/overview) · [Quickstart](https://developers.openai.com/api/docs/guides/agents-api/quickstart)
- [공식 Function Tools](https://developers.openai.com/api/docs/guides/agents-api/tools/functions) · [Skills](https://developers.openai.com/api/docs/guides/tools-skills) · [Plugins](https://developers.openai.com/api/docs/guides/agents-api/tools/plugins)
- [공식 Self-hosted 환경](https://developers.openai.com/api/docs/guides/agents-api/environments/self-hosted) · [Tracing](https://developers.openai.com/api/docs/guides/agents-api/tracing)
- [OpenAI Python SDK](https://github.com/openai/openai-python) · [OpenAI Cookbook](https://github.com/openai/openai-cookbook)

교재에는 학습·보충 자료·실습 도움말만 게시합니다. 작업 진행·계획·개편·출판 관리 기록은 저장소에서만 관리하며, `scripts/check_tutorial.py`와 `scripts/check_book_output.py`로 교재 재포함을 검사합니다.

장별 설명은 `notebooks/`에 통합했습니다. 이전 Markdown 안내 28개는 제거하고 노트북으로 직접 연결합니다. 기존 웹 URL 16개의 이동 안내는 `book-redirects.json`으로 유지합니다.

15장은 `uv run --group dev python scripts/run_multi_agent.py`로 오프라인 점검하고 `--live`로 실제 API를 실행합니다. 7–11장 실행 명령의 범위는 유지합니다.

## 한국어·영어 배포

한국어 교재는 기존 주소를 유지하고 영어 교재는 `/en/`에 생성합니다. 화면의 한국어/English 전환은 같은 장으로 이동하며, 언어별 검색과 다운로드를 사용합니다. 원본 `notebooks/`는 수정하지 않고 `translations/en/`의 셀 ID·원문 해시에 연결한 번역을 빌드 사본에 적용합니다. Python 코드와 한국어 보고서 생성 지침은 두 언어에서 동일합니다.

```bash
# API 호출 없이 번역의 누락·원문 변경 확인
uv run python scripts/localization.py
# 두 언어 교재·Colab·ZIP 생성 및 검사
uv run --group docs python scripts/build_artifacts.py --target all
uv run --group docs python scripts/check_artifacts.py --target all
uv run --group dev python scripts/check_colab.py --execute --language all
# 번역 갱신을 명시적으로 선택할 때만 유료 API 호출
uv run python scripts/update_translations.py --refresh
```

영어 번역은 별도 카탈로그로 Git에서 관리하며 원문 변경 시 갱신해야 합니다. 빌드는 번역 API를 호출하지 않으며 오래되거나 누락된 번역을 거절합니다. 초기 번역은 기계 번역과 구조 검사에 기반하므로 편집 검토가 권장됩니다. 상세 유지보수 방법은 [다국어 교재 관리](docs/localization.md)를 참고하세요. 진행·검증 결과는 로컬 `.work/PROGRESS.md`와 `outputs/`에 기록하며 Git과 배포 산출물에서 제외합니다.


## 로컬 교재 미리보기

```bash
# 변경된 원본으로 Sites용 한국어·영어 교재를 빌드하고 실행
uv run --group docs python scripts/preview_book.py --build
# 이미 빌드한 교재를 검사한 뒤 실행
uv run --group docs python scripts/preview_book.py
# Pages의 프로젝트 하위 경로까지 재현
uv run --group docs python scripts/preview_book.py --build --target pages --port 8001
```

기본 주소는 한국어 http://127.0.0.1:8000/ , 영어 http://127.0.0.1:8000/en/ 입니다. Pages는 `/agents-api-by-example/` 아래에서 확인합니다. 서버는 로컬 주소에만 바인딩하며 Ctrl+C로 종료합니다. 원본이나 산출물이 바뀌면 재빌드가 필요합니다.

다운로드는 호스트 이름이 없는 배포 루트 상대 경로를 사용합니다. Sites의 `/downloads/`, 영어 `/en/downloads/`, Pages의 `/agents-api-by-example/downloads/` 및 영어 하위 경로를 빌드별로 적용하므로 로컬과 실제 호스팅이 같은 파일을 제공합니다. 미리보기는 교재 열람용이며 Python 실행은 Jupyter/Colab을 사용합니다.
