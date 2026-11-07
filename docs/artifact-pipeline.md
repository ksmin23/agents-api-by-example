# 배포 산출물과 처리 과정

노트북 원본은 notebooks/ 한 곳에서 관리합니다. 배포 파일은 _build/, 실행·검증·배포 증거는 outputs/에 보관합니다. 모두 Git에서 제외하며, 기존 장별 outputs 경로와 Docker 구성·deploy/.generated는 유지합니다.

```text
_build/
  colab/                     한국어 독립 실행 노트북 17개·README
  colab/en/                  영어 독립 실행 노트북 17개·README
  bundles/                   Skill·Plugin ZIP
  book/sites/                루트 BASE_URL의 완성 Book
  book/pages/                프로젝트 BASE_URL의 완성 Book
  packages/colab-notebooks.zip
  packages/colab-notebooks-en.zip
  packages/sites.tar.gz      공식 Sites helper가 패키징할 때 생성
  manifest.json              입력·출력 해시와 대상별 경로
  templates/                 MyST 테마 캐시
  work/                      격리된 임시 MyST 작업 폴더

outputs/
  intro/·extensions/·…       기존 실습 결과 경로 유지
  validation/build-<id>/     빌드 로그·완료 결과
  deployments/<id>/          Sites 준비·배포 기록
```

## 통합 빌드와 읽기 전용 검증

```bash
uv run --group docs python scripts/build_artifacts.py --target sites
uv run --group docs python scripts/check_artifacts.py --target sites

uv run --group docs python scripts/build_artifacts.py --target pages
uv run --group docs python scripts/check_artifacts.py --target pages

# 두 대상의 경로·출력을 함께 확인할 때
uv run --group docs python scripts/build_artifacts.py --target all
uv run --group docs python scripts/check_artifacts.py --target all
```

흐름은 Colab·번들 생성 → 독립 ZIP 생성 → 격리 작업 폴더에서 대상별 Book 빌드 → 리다이렉트·다운로드 복사 → 출판 제외 검사 → manifest 기록·재검증입니다. 문서 빌드에서 노트북 API·Docker 셀을 실행하지 않습니다.

Jupyter Book의 기본 _build/html·site 경로는 임시 작업 폴더 안에서 사용합니다. 완성 결과만 _build/book/<target>/에 복사하므로 각 대상은 한국어 루트와 /en 영어 교재를 포함합니다. 두 대상과 과거 다운로드가 섞이지 않습니다. 로컬 미리보기의 기존 _build/html은 배포 기준으로 사용하지 않습니다.

manifest는 입력 파일 목록·SHA-256, 입력 집계 해시, 생성 시 Git commit, 대상별 BASE_URL, Colab·번들·Book·ZIP 해시를 담습니다. 생성 후 원본이나 산출물이 달라지면 검증이 실패합니다. `.work/`와 `outputs/`, 이전 작업 기록 경로는 빌드 입력·격리 작업 폴더·Sites 소스 스냅샷에서 제외합니다. 로컬 작업 기록을 만들거나 수정해도 manifest는 바뀌지 않습니다. 이 파일들은 Book 본문·다운로드에도 포함하지 않습니다. Git commit은 빌드 시점의 정보이며 실제 내용 대조는 파일 해시를 기준으로 합니다.

## 개별 생성·검증

```bash
uv run python scripts/build_colab.py
uv run python scripts/build_bundles.py
uv run python scripts/build_colab_zip.py

uv run python scripts/build_colab.py --check
uv run python scripts/build_bundles.py --check
uv run python scripts/build_colab_zip.py --check
```

ZIP 생성에는 HTML이 필요하지 않습니다. book_colab_downloads.py는 검증된 노트북·ZIP을 Book의 downloads/로 복사하는 작업만 합니다. check_artifacts.py와 --check 명령은 누락·불일치를 보고하며 파일이나 검증 기록을 쓰지 않습니다.

Plugin 예제의 원본 복사본을 동기화할 때만 sync_plugin_sources.py를 명시적으로 실행하고 diff를 검토합니다. 배포 빌드가 예제 원본을 자동 수정하지 않습니다. 기존 outputs/bundles의 과거 ZIP은 자동 이동·삭제하지 않으며 새 배포에서 사용하지 않습니다.

## Sites 준비

1. Sites 플러그인에서 기존 Site와 접근 범위를 확인하고 공식 source helper로 체크아웃을 먼저 엽니다. 기존 project_id와 .openai/hosting.json을 유지합니다.
2. sites 대상 빌드·검증 후 아래 명령을 사용합니다.

```bash
uv run --group docs python scripts/prepare_sites.py --checkout /PATH/TO/OPENED-SITES-CHECKOUT
uv run --group docs python scripts/prepare_sites.py --checkout /PATH/TO/OPENED-SITES-CHECKOUT --check
```

준비 스크립트는 검증된 _build/book/sites를 Site의 static.directory에, 원본 스냅샷을 book-source/에 복사하고 UPSTREAM-SNAPSHOT.json에 해시·출처를 기록합니다. 기존 변경이 있는 체크아웃은 덮어쓰지 않습니다. credentials·.env.local·outputs·Docker 생성 파일은 복사하지 않습니다. --check는 복사본을 대조하기만 합니다.

3. 공식 Sites source helper에 열린 체크아웃의 source 결과와 세션 메모리의 credential 객체를 stdin으로 전달합니다. commands는 이미 빌드·검증했다면 빈 배열이고, archivePath는 이 프로젝트의 절대 경로에 _build/packages/sites.tar.gz를 붙인 값입니다. 압축 파일은 Site 체크아웃 밖에 있어야 합니다.
4. 공식 helper가 반환한 정확한 commit_sha·archive로 native save/deploy를 진행합니다. credential을 파일·명령행·로그에 저장하지 않습니다. 준비 스크립트 자체는 commit·push·게시·접근 범위 변경을 하지 않습니다.

Sites 체크아웃의 dist 등은 전송용 복사본이며 직접 편집하지 않습니다. 패키징과 원격 게시 성공은 prepare 성공과 별도로 기록합니다.

## CI와 검증 범위

validate workflow는 sites 대상, Pages publish workflow는 pages 대상으로 같은 통합 명령을 호출합니다. Colab 업로드는 _build/colab, Pages 업로드는 _build/book/pages를 사용합니다. 기존 Pages 자동 게시 중단 상태는 이 설정 변경으로 활성화하지 않습니다.

실제 Colab 웹·유료 API·Docker·Sites/GitHub 원격 배포는 파일·로컬 빌드 검증과 구분해 기록합니다. 배포 준비의 로컬 회귀 검사에는 임시 Git 체크아웃을 사용합니다.

다국어 번역·코드 보존·언어 전환은 [다국어 교재 관리](localization.md)를 참고하세요.


## 로컬 미리보기와 다운로드 경로

`uv run --group docs python scripts/preview_book.py --build`로 Sites 빌드와 서버 실행을 함께 수행합니다. 이미 빌드했다면 --build를 생략합니다. `--target pages --port 8001`은 manifest의 Pages BASE_URL을 그대로 마운트하고 잘못된 접두사는 404로 거절합니다. 실행 전 입력/산출물 manifest를 검사하며 원본이나 산출물이 바뀌면 재빌드를 안내합니다.

외부 호스트로 고정된 교재 다운로드 URL은 원본 문서가 아닌 렌더링된 HTML·client JSON에서 배포 루트 상대 경로로 바꿉니다. 한국어/영어 및 Sites/Pages 접두사를 구분하고, 다운로드 파일을 복사한 뒤 두 형식의 링크 대상 존재를 검사합니다. 독립 Colab 파일 바이트는 변경하지 않습니다.

MyST가 상대 URL을 페이지 내비게이션으로 추론하지 않도록 다운로드 노드의 internal=false·static=false를 client JSON과 HTML 내 초기 상태에 함께 적용합니다. internal=false는 네이티브 파일 링크를 사용하게 하고, static=false는 기존 SSR 외부 링크 아이콘을 유지해 hydration 불일치를 방지합니다. BASE_URL 중복과 JSON 페이지 요청을 방지하며, 초기 상태를 다시 직렬화할 때 HTML script 종료 문자열을 이스케이프합니다. MyST 업그레이드 시 초기 상태 형식과 링크 렌더러도 함께 확인하세요.

미리보기 서버는 Remix의 `_data` 요청에도 대응합니다. 미리 생성한 HTML 초기 상태의 해당 loader 데이터를 JSON으로 제공하며, 없는 경로나 loader는 404로 처리합니다. API나 Python 실습 코드를 실행하는 서버가 아닙니다. 응답은 no-store로 전달합니다.
