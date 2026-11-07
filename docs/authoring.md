# 장 작성 규칙

## 설명과 실행 코드

각 장의 학습 목표·개념·진행 순서·실행 코드·결과·실패 처리·공식 자료는 하나의 `.ipynb`에 작성합니다.
독립 보충 자료·작성/운영 문서만 별도 Markdown으로 관리합니다. 장별 Markdown 설명 페이지를 노트북의 부모 메뉴로 만들지 않습니다. `notebooks/_template.ipynb`를 복사하고
`myst.yml`의 목차를 갱신합니다. chapters/ 아래 노트북도 링크·검증 도구가 재귀적으로 처리합니다.

각 장에는 학습 목표, 사전 조건, 입력, 실행, 실제 기대 결과, 실패 처리,
자원 정리, 공식 출처, 검증 날짜를 넣습니다. 아직 구현하지 않은 부분은 명시합니다.

## 노트북 규칙

- 새 커널에서 위에서 아래로 실행합니다. 이전 노트북의 변수·세션에 의존하지 않습니다.
- API 키를 출력하거나 샘플 출력에 넣지 않습니다. 결과물은 `outputs/`에 저장합니다.
- 유료 API, sandbox 생성, 외부 쓰기 작업은 명시적인 라이브 경로로 분리합니다.
- 기본 `RUN_LIVE=False`를 유지합니다. 모의 데이터는 실제 응답으로 표시하지 않습니다.
- 커밋하는 노트북은 코드 셀의 출력과 execution count를 비웁니다.
- 복사한 노트북은 셀 ID도 새로 생성합니다. Book 전체에서 중복되지 않게 유지합니다.
- API 기능과 SDK 기능, 설치·활성화·사용, 상태 스냅샷·감사 이력을 구분합니다.

## 검사

```bash
uv run --group dev python -m unittest discover -s tests -v
uv run --group dev python scripts/check_notebooks.py
uv run --group dev python scripts/check_notebooks.py --execute
uv run --group docs jupyter book build --html
```

튜토리얼 전체의 공통 코드는 `src/tutorial_helpers/common.py`에 있습니다. uv가 로컬 패키지로 설치하며
Colab 배포본은 build_colab.py로 `_build/colab/`에 생성하며 Git에서 제외합니다. 생성기는 원본을 수정하지 않습니다. 준비 셀은 lockfile에서 선택한 패키지를 이름·버전으로 직접 설치하고 helper·데이터·예제 파일을 텍스트로 포함합니다. GitHub 다운로드와 requirements 파일에 의존하지 않습니다. 원본 실행 셀은 변경하지 않습니다.
Preface도 같은 준비·설정 함수를 사용하며 다른 장의 커널 상태에 의존하지 않습니다.

## 참고

- [Jupyter Book](https://jupyterbook.org/stable/)
- [uv와 Jupyter](https://docs.astral.sh/uv/guides/integration/jupyter/)

## API를 직접 가르치는 코드 경계

각 장은 `OpenAI()` 생성, agent/environment/tools 설정, 주요 API 호출, 결과 수신·상태 확인, 필요한 파일 다운로드와 검증을 직접 보여줍니다. 공식 SDK의 result collection, artifact 다운로드, `function_tool`·`tool_handlers`를 우선 사용합니다. 직접 pending action 응답은 11장과 7장 심화 자료에서 설명합니다.

설정·metadata·세션 취소·삭제·404 확인은 `common.py`에 모으고 노트북에서 `finally`로 호출합니다. helper가 주요 실행 loop를 감싸지 않게 합니다. 실행 과정 추적을 위해 `RunRecord` 같은 별도 recorder를 만들지 않습니다. 일반 장은 Session·Turn ID와 Platform Trace 안내만 제공하고, API Trace export는 13장의 명시적 선택입니다.

결과 검증과 자원 정리는 Trace와 별개로 유지합니다. 검증 실행 사본에서 최종 receipt는 한 번 저장하며 상세 이벤트 로그를 반복 저장하지 않습니다. 정책·승인·복구의 핵심 코드는 학습할 수 있도록 본문에 둡니다. fixture·Docker 프로토콜 재생·실제 API·native Codex 검증은 구분합니다.

## API 실행 준비와 오프라인 태그

API를 사용하는 노트북은 다음 순서로 구성합니다. 개념 설명·로컬 계산만 있는 1장에는 API 준비 셀이 필요하지 않습니다.

1. 일반 설정 셀: `RUN_LIVE=False`, `client=None`, `load_settings(...)`, 입력 파일·상수 준비. API 키 값은 출력하지 않습니다.
2. 함수·정책·도구 정의: 호출하지 않는 함수 정의는 오프라인에서도 실행할 수 있습니다.
3. 단 하나의 API 준비 셀: `requires_api`와 `api_preparation` 태그. `client=None`으로 이전 참조를 지우고 `if not settings.enabled: raise RuntimeError(...)`로 안내합니다. 12장은 Docker 실행 허용·전용 executor 키 검사도 여기서 수행합니다. 검사를 통과하면 `OpenAI(...)`를 생성합니다.
4. API 실행·결과 의존 셀: 모두 `requires_api` 태그. `if settings.enabled:`를 반복하지 않습니다. 스트리밍·응답 확인·다운로드·`try/finally` 정리는 노트북에 직접 작성합니다. 결과 표시와 자원 삭제 확인도 API 실행에 의존하므로 같은 태그가 필요합니다.

일반 Jupyter에서 False로 모두 실행하면 준비 셀에서 멈춥니다. 설정을 True로 바꾼 뒤 설정 셀과 준비 셀부터 순서대로 실행합니다. 태그는 Jupyter 자체의 실행 제한이 아니므로 중간 API 셀만 임의로 실행하는 방식을 지원하지 않습니다.

검증 스크립트는 nbclient의 기본 `skip_cells_with_tag="requires_api"`로 해당 셀을 건너뜁니다. 원본 셀의 코드를 빈 코드나 가짜 응답으로 바꾸지 않습니다. 오프라인 통과는 로컬 셀·정의·입력 검증의 통과를 의미하며, API 결과 검증 통과가 아닙니다. `--live`에서는 이 태그의 셀도 실행합니다. `run_deployment.py --docker` 단독은 Docker 로컬 실습만 실행하며 API 셀은 제외합니다.

`scripts/check_notebooks.py`는 API 호출·클라이언트 생성 위치와 단일 준비 셀 규칙을 검사합니다. 전체 오프라인 실행은 태그가 빠진 결과 의존 셀의 미정의 변수도 검출합니다. 새 준비 셀을 복사할 때에는 고유 cell ID를 지정하세요.

## import 정리

각 셀만 보지 않고 노트북 전체의 사용을 기준으로 미사용·중복 import를 확인합니다. bootstrap에서 이미 가져온 표준 모듈도 다시 import하지 않습니다. `OpenAI`는 API 준비 셀에서 한 번만 가져옵니다. 공통 모듈의 함수를 테스트하려고 노트북에 미사용 import를 남기지 말고 테스트가 공통 모듈을 직접 참조하도록 작성합니다.

## 긴 코드 셀의 구간 표시

편집 전 소스 기준 70줄 이상인 Python 코드 셀은 처리 목적이 바뀌는 지점에 번호 있는 짧은 주석과 빈 줄을 넣습니다. 세션 생성·응답 스트리밍, 완료 확인, 파일 다운로드, 결과 검증을 구분하고, 여러 Turn은 요청 목적을 표시합니다. 큰 단계 내부의 완료 확인은 `1-1`처럼 표시할 수 있습니다. 실패 처리·자원 정리·검증 기록은 역할을 나타내는 주석을 사용합니다.

일반적인 긴 셀 서식 정리는 셀을 분할·병합·이동하지 않으며 `try/except/finally`와 `with`의 범위를 유지합니다. `# %%`나 API 흐름을 감싸는 실행 helper는 추가하지 않습니다. 편집 후 셀 ID·태그·메타데이터, AST, 주석과 줄바꿈을 제외한 Python 토큰이 같은지 확인합니다.

## 공식 참고 자료

각 노트북 끝의 `official_references` 태그가 있는 Markdown 셀에 해당 장의 문서를 모읍니다. `Agents API 전용 문서`를 먼저 배치하고, 공통 문서·Codex 문서는 각각 `보조 자료 — 공통 문서`, `보조 자료 — Codex 문서`로 분리합니다. 공통 문서에 Agents API 절이 있으면 해당 앵커로 직접 연결하며 페이지 전체를 Agents API 전용 문서로 표시하지 않습니다.

9장의 Skills는 공통 문서의 `#agents-api` 절과 전용 OpenAI-hosted 문서를 연결합니다. 13장의 Codex Hooks는 별도 Codex 환경 참고용이며 API callback·native Hook dispatch와 구분합니다. 링크를 바꿀 때에는 본문 조회, HTTP 상태, HTML 앵커와 로컬 링크를 확인하고 날짜·실습 재실행 여부를 별도로 기록합니다.

## 학습 코드와 검증 코드의 분리

원본 노트북에는 `verify_metrics`, `verify_report`, `verify_enriched`, `verify_tool_execution`, `verify_execution`, `save_validation`과 정답 oracle을 넣지 않습니다. API 요청·스트림·결과 객체·파일 다운로드·정리는 직접 보여줍니다. 필요한 결과는 출력하며 검증용 `checks`·Turn receipt 목록을 만들지 않습니다.

테스트용 계산·검증·receipt는 `src/tutorial_helpers/validation.py`에 있습니다. `scripts/notebook_validation.py`는 실행기가 읽은 사본에만 검증을 추가하며 원본 파일은 쓰지 않습니다. 원격 이력은 세션 삭제 전에 조회하고, 검증 실패가 원래 finally를 건너뛰지 않게 합니다. 검증 receipt는 정리 결과와 실패를 함께 기록합니다. API 실행 loop를 helper로 옮기지 않습니다.

11장의 입력·출력 검증, 역할·채널·승인 digest와 pending action 처리는 해당 장의 학습 기능으로 유지합니다. 14장의 재구독·저장 상태·중복 입력 방지·캐시는 복구 학습 기능으로 유지합니다. usage의 None/0 fixture는 단위 테스트에 두고, 실제 응답은 미보고를 0으로 표시하지 않습니다.

## 빈 셀과 설명 일치 점검

배포용 원본에 출력·실행 의도가 없는 빈 코드 셀을 남기지 않습니다. 기능을 검증 도구로 옮기면 설명의 정답 계산·fixture·결과 표시·복구 파일 안내도 실제 원본과 맞춥니다. 최종 응답과 usage 등 학습에 필요한 SDK 결과 표시는 유지하며, 수동 실행의 `creation.json`과 검증 도구가 만드는 `summary.json`을 구분합니다.

## 단일 장 페이지와 주소 호환

시작하기는 `notebooks/setup.ipynb`와 `notebooks/quickstart.ipynb`이며 제목에 장 번호를 붙이지 않습니다. 1–15장은 `notebooks/chapters` 아래 노트북을 목차의 말단 페이지로 등록합니다. 고유한 설명은 `chapter_overview` Markdown 셀에 두고, 운영 검증 이력은 실행 코드 뒤에 배치합니다.

예전 설명 문서 파일은 통합 안내 링크만 유지합니다. Book은 `myst.yml`의 노트북 페이지를 표시하며, 정적 빌드 후 `scripts/book_redirects.py`가 `book-redirects.json`에 명시된 예전 URL을 새 페이지로 안내합니다. 실제 본문을 덮어쓰는 리다이렉트는 허용하지 않습니다.

## 독자용 교재 범위

문서는 한글 또는 영문으로 작성합니다. 작업 진행·계획·개편·출판 관리 기록은 저장소에서 유지하고 교재 목차·본문 링크·검색·다운로드에서 제외합니다. 노트북의 공통 안내는 독자용 `docs/validation.md`를 연결합니다. 정적 빌드 후 `scripts/check_book_output.py`로 이전 작업 기록 파일이 남지 않았는지 확인합니다.

배포 빌드·검증은 build_artifacts.py와 check_artifacts.py를 공통 진입점으로 사용합니다. 경로와 Sites 준비 절차는 [배포 산출물 관리](artifact-pipeline.md)에 있습니다.

이전 장별 Markdown 안내 파일은 제거했습니다. 본문 링크는 notebooks/setup.ipynb·quickstart.ipynb·chapters/*.ipynb로 직접 연결합니다. 노트북의 integrated_documents 메타데이터는 설명을 통합한 과거 출처 기록이며 파일 존재를 요구하는 링크가 아닙니다. 기존 웹 URL 호환은 book-redirects.json과 book_redirects.py에서만 관리합니다.

## 검증 결과의 기록 위치

README에는 목적·목차·설치·실행·검증 방법만 둡니다. 날짜별 테스트 수, 실행 성공·실패·재시도, 자원 정리 결과와 미검증 범위는 README에 기록하지 않습니다. 장별 상태와 작업 이력은 Git에서 제외한 `.work/PROGRESS.md`, 작업 요청은 `.work/todo.md`, 과거 계획·검토는 `.work/archive/`에 로컬로 보존합니다. 상세 실행 결과는 기존 `outputs/` 경로를 유지합니다. 공유 문서에서는 로컬 기록에 대한 Markdown 링크를 만들지 않습니다. 기록이 없는 새 clone에서도 모든 명령이 동작해야 하며 장별 검증기는 필요할 때 진행 표를 자동 생성합니다. CI 검증 근거는 Actions 로그·아티팩트로 확인합니다.

## 코드 셀의 언어

Python 코드 셀의 주석과 실행 안내·상태·오류·사용자 입력 메시지는 자연스러운 영문으로 작성합니다. 설명 Markdown은 한국어로 유지합니다. 한국어 보고서 제목·내용, 모델에 전달하는 업무 지침과 보고서 제목 검사처럼 실습 계약에 속한 문자열은 출력 안내와 구분해 유지합니다. Colab 생성기가 추가하는 준비 코드의 주석·메시지도 같은 규칙을 적용합니다.


## 시나리오별 실행 셀 — 11장

11장 승인 실습은 사용자 행동에 맞춰 생성·다운로드/검토·정책 거절·사용자 판단·로컬 결과 읽기·최종 정리의 여섯 셀로 나눕니다. 각 API·결과 의존 셀에는 requires_api와 approval_step_1..6 태그를 붙입니다. 1–5단계는 cleanup_on_error로 오류·KeyboardInterrupt 시 정리를 시도하고 정상 완료 시에는 세션을 유지합니다. 6단계는 명시적 try/finally로 정리합니다. 셀 사이에서 중단하면 정리 셀을 직접 실행해야 하며 강제 커널 종료는 자동 정리를 보장하지 않습니다. 오류 뒤에는 새 실행을 준비합니다. 단계별 시계를 재설정하고 사용자 승인 대기·로컬 도구 처리 시간은 승인 단계의 시간 예산에서 제외합니다.

검증 실행 사본은 각 단계의 실패를 정리 후 기록하며 최종 정리 셀에서는 원격 이력을 조회·검증한 뒤 삭제합니다. 학습 셀의 API 호출·이벤트 분기는 helper로 옮기지 않습니다.

11장 실제 CSV는 준비와 제출 시 모두 검사하고 검토한 바이트를 승인 전후 대조합니다. interactive callback은 원본에 직접 정의하며 REVIEW_MODE 기본 none은 업무 승인 모드와 별도입니다. 승인 영수증(.approval.json)·Call 캐시·자동 검증 summary.json을 구분합니다. 승인/거절의 같은 세션·서로 다른 Turn 및 실제 함수 이력/캐시 응답은 삭제 전 검증 사본에서 대조하며 Trace는 선택 조사 수단입니다. 오류 정리·최종 정리 후 닫힌 client의 재사용을 가정하지 않습니다.


## 관측 시나리오별 실행 셀 — 13장

13장은 관측 준비·Agent 실행·결과/다운로드·애플리케이션 OTel 확인·선택 Trace export·정리의 여섯 API 의존 셀로 나누고 telemetry_step_1..6 태그를 사용합니다. 기본 Trace와 별도 애플리케이션 span, 선택 export, native Hook 프로토콜 재생을 구분합니다. 1–5단계의 cleanup_on_error는 오류 시 세션 정리와 ExitStack 종료를 모두 시도합니다. ExitStack에는 OTel 종료를 Docker 종료보다 나중에 등록해 Collector가 살아 있을 때 flush합니다. 정상 경로에서는 4단계에서 flush/실제 memory exporter 또는 Collector span을 확인하고 6단계에서 provider를 종료합니다. 상태 초기화는 별도 셀이며 관측 준비/세션 중복 생성을 차단합니다. RUN_LOCAL_CHECKS로 별도 Hook 재생을 API Collector와 분리합니다. callback records와 실제 OTel 속성/ID를 구분하고 같은 run/session/root Turn·duration·보고된 usage를 대조합니다. 기본 Trace/export에는 app 허용 필드 필터가 적용되지 않습니다. API 실패 이벤트와 로컬 오류를 구분하며 최종 정리 오류가 원래 오류를 덮지 않습니다.

실행 사본 검증은 6단계에서 세션 삭제·Collector 종료 전에 수행하며, 각 단계의 실패는 오류 정리 후 기록합니다. INSPECT_TRACE 입력 대기는 사용하지 않고 사용자가 5단계 뒤 직접 Dashboard를 확인한 다음 6단계로 진행합니다. Trace export는 기본 False이며 CLI의 TUTORIAL_EXPORT_TRACES=1은 실행 사본만 변경합니다. duration_ms는 세션 생성·스트리밍 시간으로 한정해 셀 사이 검토 시간과 구분합니다.


## 복구 시나리오별 실행 셀 — 14장

14장은 세션 생성·입력 한 번 제출/관찰 종료·같은 Turn 재연결·저장 결과/파일·usage/운영 정보·정리의 여섯 셀로 나누고 operations_step_1..6 및 requires_api 태그를 붙입니다. API 요청·이벤트 처리·페이지 반복·최종 응답 선택은 노트북에 직접 둡니다. 검증 실행 사본은 6단계에서 삭제 전에 검사하고 각 단계 오류 정리 후 실패를 기록합니다. 오류가 있는 최종 정리에서는 추가 정리 오류로 원래 오류를 덮지 않습니다.

관찰 종료·작업 취소·세션 삭제와 OpenAI-hosted 관찰자 복구·Self-hosted executor 연결·별도 Docker 프로세스 복원을 구분합니다. 재연결 때 이미 완료된 Turn은 이벤트 replay를 기다리지 않습니다. 단계별 관찰 시계를 새로 시작하고 timeout을 원격 실패로 단정하지 않습니다. 입력 전송 시도 상태를 기록하되 키/ID 저장만으로 자동 재시작 복구를 보장한다고 설명하지 않습니다.

JobStore·pending Function Tool 결과 복구는 보충 경로이며 기본 실습에서 미등록 도구를 자동 실행하지 않습니다. 별도 Docker 실습은 docker_store를 사용하고 API 정리 후 실행합니다. 원본의 요약 출력과 검증 실행 사본의 정답/파일 검사는 분리하며 usage=None과 보고된 0을 구분합니다.


## Self-hosted 단계별 실행 셀 — 12장

12장은 필수 이미지 준비와 키 확인 후 세션 생성·Docker 준비·구독/시작/연결·입력 한 번 제출·이력/파일 확보·정리의 여섯 self_hosted_step_1..6 셀로 구성합니다. API 호출·환경 설정·이벤트 분기는 원본에 남기고 추가 Docker 종료는 cleanup_on_error finalizer로 처리합니다. API 정리가 Docker 종료보다 먼저 실행되어야 합니다. 상태 초기화는 별도 준비 셀에 두고 생성·Docker 준비·시작·입력은 각각 중복을 차단합니다. connected와 ready를 구분하며 Self-hosted 입력은 같은 환경의 connected 뒤에만 제출합니다. 입력은 read_bytes 기준으로 이미지 빌드 입력과 고정하며, 모델 응답/API 이력/Docker 복사 파일의 출처를 구분합니다. 상세 Docker snapshot과 결과 읽기는 정리 후 별도 구간에 유지합니다. 연결/작업 단계 시계를 분리하고 중간 중단 시 최종 정리 셀 실행을 안내합니다.

파일 수집은 collect_report의 output_dir을 지정해 한 경로로 보관하며 상세 표시는 정리 후 API/Docker 호출 없이 수행합니다. RUN_PACKAGE_CHECKS는 기본 False이고 로컬 전용 CLI 검증 사본에서만 켭니다. 기본 API 검증 receipt는 6단계에서 삭제 전에 검사한 결과이며, 별도 worker의 로컬 Skill 실행을 API 실행 증거로 사용하지 않습니다. 과거 날짜별 검증 기록은 .work/에 보관하고 본문에는 재사용할 문제 해결 안내만 유지합니다.

## 첫 실행의 단계별 셀 — 2장

2장은 세션 생성/스트리밍·완료 상태/JSON 표시·명시적 정리의 세 셀에 requires_api와 first_agent_step_1..3 태그를 사용합니다. 스트림 컨텍스트는 첫 셀에서 열고 닫으며, 앞의 두 셀은 cleanup_on_error로 오류 시 정리합니다. 정상 경로에서는 마지막 셀의 try/finally가 정리하고 검증 사본의 검사 오류를 보존합니다. 타이머는 작업 제출 직전에 시작하여 셀 사이 학습 시간을 제외합니다. 검증 주입기는 세션 삭제 전에 이력/계산값을 검사하고 오류 정리 후 receipt를 기록합니다. 원본은 입력 CSV·최종 JSON·세션별 삭제 확인을 표시하며 정답 검사는 포함하지 않습니다. 중간 중단 시 정리 셀 실행과 강제 커널 종료의 한계를 설명합니다.

## 세션 이어가기 단계별 셀 — 3장

3장은 첫 분석/완료 확인·후속 입력/완료 확인·동일 Session/서로 다른 Turn/저장 이력 확인·정리의 네 session_step_1..4 셀을 사용합니다. 각 스트림 컨텍스트는 해당 셀 안에서 닫고, 1–3단계는 오류 시 정리하며 최종 단계는 try/finally로 정리합니다. 후속 입력의 message_key는 상태 준비에서 한 번 만들고 제출 시도 전에 follow_up_attempted를 기록합니다. 이 장은 자동 재시도·재연결을 구현하지 않습니다. 두 Turn의 시계를 개별 설정하여 학습 시간을 제외합니다. 원본의 Session/Turn 관계와 이력 존재 확인은 학습 기능으로 유지하고 계산값·명령 실행의 정답 검사는 삭제 직전 검증 사본에만 주입합니다.

## 저장 Agent 재사용 단계별 셀 — 4장

4장은 저장 Agent 생성·기본 Session·override Session·조회 설정 비교·정리의 configuration_step_1..5 셀을 사용합니다. 저장 Agent와 Session은 별도 소유 자원으로 추적하고 Agent ID 응답 직후 save_agent_reference로 run ID/Agent ID만 agent.json에 저장합니다. 생성 응답 유실 시 자동 Agent 검색은 제공하지 않는다는 한계를 설명합니다. 1–4단계 오류 정리와 최종 try/finally 정리를 유지하고, 두 Session과 Agent 모두 삭제 확인을 표시합니다. Session별 타이머·생성 시도 플래그를 사용합니다. 원본에는 최초 모델/기본 지침/override와 재조회 설정 비교를 남기고 정답 계산/명령 증거 검사는 검증 사본에만 주입합니다. 두 Session의 입력을 각각 전달하며 Agent 재사용이 대화·파일 공유를 뜻하지 않음을 설명합니다.

## 파일 게시·다운로드 단계별 셀 — 5장

5장은 실행/완료 확인·이번 Turn artifact 표시·공식 SDK 다운로드·로컬 파일 읽기·정리의 artifact_step_1..5 셀을 사용합니다. 원본에 경로 구분과 Session/Turn/path 선택을 직접 표시하며 custom 선택 helper를 추가하지 않습니다. 입력은 원본 바이트의 일반 base64로 구성하고 변환 정답 검사는 테스트에서만 합니다. 1–4단계 오류 정리와 최종 try/finally를 유지하고 다운로드 오류의 부분 파일을 성공으로 표시하지 않습니다. downloads_complete는 두 다운로드 성공 후 설정하고 재시도 전 초기화합니다. 기본 예제는 오류 시 정리를 시도하므로 다운로드 재시도 가능성을 보장하지 않습니다. 원본의 결과 표시와 검증 사본의 계산/보고서/명령 정답 검사를 구분합니다. 파일 다운로드는 세션 삭제 전에 완료하고 로컬 결과 보존을 설명합니다.

## 원격 환경 준비 단계별 셀 — 6장

6장은 입력/버전·읽기 쉬운 setup_source·완성된 environment 요청을 로컬 준비 셀로 구분하고, 실제 실행은 environment_step_1..5(준비/분석 관찰·게시 확인·세 파일 다운로드·환경/결과 읽기·정리)로 나눕니다. pandas 버전은 PANDAS_VERSION 한 곳에서 패키지 요청과 setup 검사에 조합합니다. pending/ready/failed는 수신 시 이벤트 종류와 환경 ID만 표시하고 순서/개수/관찰 여부를 성공 조건으로 삼지 않습니다. ready는 버전/계산 검증이 아닙니다. 원본은 요청/기록 버전 비교를 학습 기능으로 유지하고 CSV/보고서/입력 행 수 기준값 대조는 삭제 전 검증 사본에만 추가합니다. 환경 JSON은 에이전트가 setup 기록을 복사한 파일이며 독립 실행 증명으로 취급하지 않습니다. 오류 정리·단계별 상태·세 파일 완료 플래그·최종 try/finally와 로컬 결과 보존은 5장과 일관되게 유지합니다.

## Function Tool 단계별 실행 셀 — 7장

7장은 업무 함수 정의·사전 직접 호출·공식 SDK 도구 생성·모델 스키마/로컬 핸들러 등록을 구분하고 function_tool_step_1..5(실행·호출 이력·다운로드·확장 응답/파일 읽기·정리)를 사용합니다. 함수는 현재 애플리케이션, CSV 명령은 sandbox에서 실행합니다. 직접 사전 호출은 API 실행 증거가 아니며 SDK 자동 결과 제출과 직접 pending 응답을 중복 적용하지 않습니다. 기본 metrics와 최종 확장 JSON 계약을 분리합니다. 원본은 root Turn의 호출명/인자/Call ID/상태/개수를 표시하고 정확한 함수명·기간·완료·1회 조건은 삭제 전 검증 사본에서 검사합니다. SDK 오류는 모델에 일반 실패로 제출되며 로컬 진단은 필요 시 공식 on_tool_error를 참고하되 현재 고정 SDK에서는 sessions.stream의 선택 인자이며 본문 sessions.create에는 없다는 범위를 명시합니다. 예제는 자동 복구/내구성 캐시/장애를 넘는 exactly-once를 보장하지 않습니다. 기존 outputs/extensions 경로와 다운로드의 Turn별 폴더를 유지합니다.

## MCP 단계별 실행 셀 — 8장

8장은 서버 코드를 표시만 하고 파일/환경과 MCP 프로세스 설정을 나누며 mcp_step_1..5(실행·MCP 이력·다운로드·확장 응답/파일 읽기·정리)를 사용합니다. MCP_VERSION 한 곳에서 설치 요청을 구성하고 기존 서버 파일 및 실습 경로는 유지합니다. executor가 stdio 프로세스를 시작하며 노트북에서 별도 서버나 tool_handlers를 실행하지 않습니다. allowed_tools는 도구 접근, required는 초기화 요구이며 실제 호출 1회 보장과 구분합니다. 원본은 root Turn의 서버/도구/인자/Item ID/상태/오류/출력을 표시하고 정확한 서버label·이름·기간·완료·오류 없음·1회 조건은 삭제 전 검증 사본에 추가합니다. 목표 데이터와 에이전트 코드가 같은 환경에 있다는 경계 및 stderr 미수집 범위를 명시합니다. HTTP/15장 확장은 보조 자료로 두고 환경 실패·초기화 실패·도구 오류를 구분합니다.

## Skill 등록·실행 단계별 셀 — 9장

9장은 파일/계약/코드 확인·ZIP 포장·inline 요청을 구분하고 skill_step_1..6(실행·등록·명령 이력·세 파일 다운로드·결과/증거 읽기·정리)를 사용합니다. read_skill_metadata는 이 예제의 인용 부호 없는 단일 행 name/description만 지원하는 boilerplate이며 일반 YAML로 주장하지 않습니다. 등록은 Session의 Environment ID와 요청 Skill 이름/inline 유형으로 확인하고, 실제 사용은 같은 root Turn의 완료/종료 코드/명시적 Python CLI와 입력/출력 인자를 검사합니다. 입력 해시는 실제 전송한 csv_bytes 기준입니다. ZIP 해시·입력 해시·revision을 구분하고 자동 선택 품질·서명·완전한 감사 증명으로 주장하지 않습니다. 원본은 metadata/명령/결과를 표시하고 정답 검사는 삭제 전 검증 사본에만 추가합니다. 기존 실습 경로와 Skill/Plugin 소스는 유지합니다.

## Plugin 단계별 실행 셀 — 10장

10장은 manifest/MCP/Skill/서버 파일 확인·ZIP 포장·inline Plugin 요청을 분리하고 plugin_step_1..6(실행·등록·MCP/명령 이력·다운로드·결과 읽기·정리)을 사용합니다. 같은 Skill/MCP를 별도 등록하지 않습니다. 원본은 등록 metadata·관측 server_label·명령과 결과를 보여주고, 정답·도구/기간/횟수/오류·명시적 CLI·입력 바이트 해시·보고서 목표/백분율은 삭제 전 검증 사본에서 검사합니다. 런타임 label 네임스페이스나 Plugin 내부 Skill의 별도 skills 노출을 가정하지 않습니다. 패키지와 network 설정은 ZIP과 분리하며 원본 동기화는 전용 스크립트로 명시적으로 수행합니다. manifest version은 로컬 선언이며 등록 응답의 버전/코드 해시 증명으로 주장하지 않습니다. template/self-hosted는 선택 확장으로 두고 기존 경로·원본 Skill/Plugin·Docker 구성은 유지합니다.


## Multi-agent 역할별 실행 셀 — 15장

15장은 multi_agent_step_1..6 및 requires_api 태그로 위임 실행·메인/담당 상태·역할별 명령·네 Artifact 다운로드·담당 결과/통합 보고서 읽기·정리를 구분합니다. 상태 준비는 별도 셀에 두고 Session 생성 시도 중복을 차단하며 타이머는 실행 직전에 시작합니다. 앞의 다섯 단계는 cleanup_on_error로 정리하고 최종 finally는 원래 오류를 보존합니다. API 생성·구독·subagents/items/turns 조회·다운로드는 원본에 직접 남깁니다.

동시 실행 상한·프롬프트의 역할 요청·실제 생성/명령 증거를 구분합니다. 전용 파일 경로는 권한 격리가 아니며 담당 역할은 생성 순서가 아닌 정확한 Python 스크립트 경로로 연결합니다. 이 장은 별도 두 토큰 CLI만 확인하며 shell 래퍼 일반 감사기가 아닙니다. 명령 Turn의 ID·소유자·완료 상태와 두 담당의 구분을 확인합니다. 공유 환경 Artifact는 root에 한정하지 않고 현재 실행의 완료 Turn·정확한 경로로 선택하되 게시 Turn만으로 작성자를 단정하지 않습니다. 파일별 메타데이터를 출력하고 전체 다운로드 후 완료 플래그를 켭니다.

담당 JSON·통합 JSON·보고서를 정리 전에 읽고 담당 간 매출 일관성을 확인합니다. 입력 목표 금액과 계산 정답은 구분하며 실제 CSV/목표 정답·달성률·파일·명령 이력의 상세 검사는 실행 사본에만 주입합니다. 달성률 검증은 입력 목표로 계산하며 고정 85%에 의존하지 않습니다. 검증 receipt는 runner 전용이고 수동 실행에는 생성하지 않습니다. 기존 outputs/extensions 경로와 Colab 실행 지원을 유지하며 별도 Trace를 필수로 추가하지 않습니다.


## API 호출 없는 개념 학습 — 1장

1장은 입력 CSV·반환 JSON 필드·Agent/Session/Turn/Environment/Harness·요청 미리보기·환경 선택·API/SDK 비교·자기 점검 순서로 구성합니다. 원본과 Colab 실행본에 API 키·모델·RUN_LIVE·API 준비 조건을 요구하지 않습니다. 로컬 project_root와 CSV 읽기만 사용하고 요청 딕셔너리는 자리표시자 모델을 갖는 미전송 예시로 명시합니다. 환경 유형도 전체 연결 코드가 아닌 설정 조각임을 설명합니다. 실제 클라이언트 생성이나 Session API 호출을 추가하지 않습니다.

2장은 메시지 CSV→텍스트 JSON, 5장은 파일 입력/Artifact 다운로드로 연결합니다. 결과 계약은 필드/자료형/의미로 설명하며 계산 정답을 먼저 제시하거나 전체 집계를 추가하지 않습니다. Mermaid 코드의 라벨은 영어로 유지해 한영 번역에서 같은 구조를 사용합니다. runtime 비교와 환경/권한 책임은 구분하고, standalone Colab의 자동 안내도 로컬 전용으로 생성합니다. run_intro의 1장 경로는 --live 요청을 받아도 소켓 차단 오프라인 실행으로 유지하며 requires_api/live_configuration 태그가 추가되면 검사에서 거절합니다.


## 빠른 시작의 최소 실행과 자동 정리

quickstart.ipynb는 작은 숫자 계산으로 생성·스트리밍·원래 root Turn/JSON/명령 이력 확인·finally 정리를 한 셀에서 경험합니다. 라이브 설정은 settings를 직접 사용하며 API client 준비는 한 번만 수행합니다. 고유 run 상태는 별도 requires_api 셀에서 준비하고 생성 시도를 초기화하지 않은 실행 셀의 중복 제출은 차단합니다. 결과와 명령 stdout은 삭제 전에 출력하고 종료 요약은 닫힌 client를 재사용하지 않고 로컬 값만 읽습니다. 정리 실패가 원래 오류를 가리지 않도록 처리합니다.

학습 원본의 JSON 형식 확인·명령 상태/종료 코드/stdout 표시는 유지하되 계산 정답과 정확한 Python CLI의 원래 Turn 소속·stdout 대조는 검증 사본에만 둡니다. 숫자 실습의 validator가 CSV 파일에 의존하지 않게 합니다. Colab은 GitHub 없이 실행 가능한 독립 실행본으로 안내하고 원본/배포본 bootstrap 차이를 설명합니다. Trace는 선택 Dashboard 링크만 제공하며 호출/export를 추가하지 않습니다. 과거 모델/SDK/날짜별 검증 이력은 .work/로 옮기고 reader에는 완료 기준·문제 해결·실행 명령만 유지합니다. 자동 검증 기록과 수동 creation.json을 구분합니다.


## 키 없는 환경 준비


setup.ipynb는 커널/Python 경로·SDK 버전/모듈 위치·project_root/helper·tutorial.json/CSV 읽기·로컬 계산·완료 요약으로 구성합니다. 키/모델 조회·client 생성·RUN_LIVE·API 준비 셀은 추가하지 않습니다. 설치 단계의 패키지 인터넷 접근과 OpenAI API 호출은 구분합니다. 로컬 Python 3.12 재현 기준과 최소 3.11 지원·Colab 제공 커널의 차이를 설명하되 경로 모양으로 환경을 강제 판정하지 않습니다.

패키지/공통 helper/프로젝트 마커/CSV 누락은 해결 행동을 포함한 오류로 안내합니다. 원본은 로컬 패키지를 자동 설치하지 않고 Colab 생성본만 설치/포함 파일 준비를 수행합니다. 생성기의 local_only는 setup 파일명 또는 1장으로 판정하며 번호 0인 Quickstart의 실제 API 준비 안내를 유지합니다. 설정 키 불필요·API 미검증을 일관되게 표시하고 선택 웹 미리보기는 Python 준비와 분리합니다. 완료 후 1장 또는 Quickstart로 직접 연결합니다.


## 장 사이 학습 흐름

각 장 도입부에 공통 예제·새 기능·현재 실습 조합을 짧게 표시합니다. 이전 장의 도구/설정/산출물이 자동 누적된다고 읽히지 않도록 독립 실행과 학습상 연결을 구분합니다. 최종 응답/분석 요약/보고서/검증 기록의 차이는 docs/validation.md 공통 비교표에 모으고 장별로 달라지는 행동은 해당 셀 가까이에 둡니다. API 호출·상태/정리 코드 반복은 학습을 위해 유지하며 문구 정리만으로 helper에 루프를 숨기지 않습니다.

2→3, 11→12 또는 15, 14→15의 다음 학습 링크를 유지합니다. 13·14장 기본 환경은 OpenAI-hosted이고 12장 executor를 재사용하지 않습니다. setup은 키/모델을 확인하지 않으며 홈페이지의 역할 설명도 동일하게 유지합니다. 검증 이력은 .work/에 기록하고 교재·작성 템플릿에는 검증 방법과 범위만 둡니다. API 원본 코드와 태그를 보존하는 편집은 전후 코드 셀 전체 비교로 확인합니다.

## 의존성 선택과 설치 검증

기본 notebook 그룹은 학습용입니다. 전체 테스트는 dev, 교재 빌드는 docs, 메모리 span은 telemetry, Collector는 telemetry-otlp, SOCKS는 proxy 그룹을 명시합니다. 검증용 dev는 telemetry-otlp를 포함하며 일반 Colab에 테스트·빌드 의존성을 넣지 않습니다. 선택 패키지를 설치한 뒤 그룹 없는 uv run으로 제거하지 않도록 실행 명령에도 같은 그룹을 사용합니다. CI는 필요한 그룹을 먼저 설치하고 --no-sync로 유지합니다.

`scripts/check_installation.py`는 실제 공개 PyPI 설치를 수행합니다. 임시 새 환경의 기본/Telemetry Colab 프로필과 pip check, SDK의 로컬 구성 및 실제 메모리 span을 확인하고 불필요한 MCP·pandas·Jupyter Book·HTTP exporter·SOCKS 패키지의 부재를 검사합니다. 유료 API·sandbox 요청은 없지만 네트워크가 필요합니다. 오프라인 노트북 검사와 실제 Colab 웹·Linux 환경 검증을 구분하며 결과는 outputs/installation-validation/에 저장합니다.
