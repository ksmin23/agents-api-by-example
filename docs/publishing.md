# GitHub Pages·Colab 배포

Git은 소스·이력을, Pages는 정적 HTML을 관리합니다. 현재 상태는 [검증 범위](validation.md)를 확인합니다.

## 배포 순서

저장소 이름은 ksmin23/agents-api-by-example, 기준 ref는 main으로 확정했습니다. 현재 GitHub 저장소와 별도의 ChatGPT Sites 게시를 사용합니다. 로컬 작업 폴더는 기존 agents-api-by-example을 사용합니다.

1. 공개 GitHub 저장소·라이선스를 정하고 Git remote를 연결합니다. 도구는 저장소 생성·commit·push를 자동 수행하지 않습니다.
2. 실제 저장소 주소와 ref를 입력합니다.

```bash
uv run python scripts/configure_repository.py --repository ksmin23/agents-api-by-example --ref main
uv run python scripts/configure_repository.py --check --require-repository
python3 scripts/check_tutorial.py --require-public --require-repository
```

설정 도구는 tutorial.json·README·Book·모든 노트북의 선택적인 Colab 열기 링크를 동기화합니다.
다른 저장소로 배포할 때만 주소를 바꾸세요. ref는 main 또는 공개된 태그/SHA로 정합니다.
독립 실행본은 `scripts/build_colab.py`로 `_build/colab/`에 생성하며 Git에는 포함하지 않습니다. CI의 `colab-notebooks` 산출물 또는 로컬 생성 파일을 학습자에게 전달합니다. [다운로드 안내](colab.md)를 참고하세요.

3. Settings → Pages → Build and deployment → Source를 **GitHub Actions**로 선택합니다.
4. 변경 사항을 검토하고 commit·push합니다. 게시 workflow는 main을 대상으로 정의되어 있으나 현재 중단 상태를 유지합니다. 이 문서 수정으로 다시 활성화하지 않습니다.

## Workflow와 경로

validate.yml은 공개 설치 조건·목차·링크·lock·Colab export·테스트·오프라인 노트북·HTML을 검사합니다.
publish.yml도 같은 통합 빌드·검증 명령을 실행한 뒤 _build/book/pages를 upload-pages-artifact로 전달하고 deploy-pages로 게시합니다.
유료 API와 Docker 장애 실습은 CI에서 실행하지 않습니다. 게시 job에만 pages:write·id-token:write를 부여합니다.
repository가 미설정이면 게시 검사는 의도적으로 실패합니다. 설정 후에는 실제 GITHUB_REPOSITORY와도 대조합니다.

| 저장소 | BASE_URL |
| --- | --- |
| owner/owner.github.io | 빈 문자열 |
| ksmin23/agents-api-by-example | /agents-api-by-example |
| owner/other.github.io | /other.github.io |

scripts/pages_base_url.py는 단순 .github.io 접미사 대신 owner와 일치하는 루트 사이트인지 확인합니다.
사용자 정의 도메인은 이 계산에 포함하지 않으며 도메인·BASE_URL을 별도로 설정합니다.

## Colab

생성 노트북은 포함 파일과 직접 패키지 설치 셀로 실행하며 GitHub clone·requirements 다운로드가 필요하지 않습니다. 독립 ZIP은 _build/packages/colab-notebooks.zip에서 관리합니다. 실제 Colab 웹 실행과 오프라인 검증은 구분합니다. [사용자 다운로드 안내](colab.md)를 참고하세요.

공식 문서: [Jupyter Book 출판](https://jupyterbook.org/stable/get-started/publish/) ·
[GitHub Pages workflow](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)

## 노트북 중심 Book과 Sites

Book의 시작하기는 `notebooks/setup.ipynb`와 `notebooks/quickstart.ipynb`입니다. 각 장은 노트북 한 페이지로 표시하고 설명 문서의 고유 내용을 Markdown 셀에 통합합니다. 보충 자료는 장 번호 없이 별도 묶음으로 제공합니다.

```bash
uv run --group docs python scripts/build_artifacts.py --target sites
uv run --group docs python scripts/check_artifacts.py --target sites
```

Sites는 루트 `BASE_URL`을, GitHub 프로젝트 Pages는 `/agents-api-by-example`를 사용합니다. 통합 빌드가 리다이렉트에도 대상별 BASE_URL을 전달합니다. 구 문서·중복 자식 URL 16개는 새 학습 페이지로 이동하며, 실제 본문을 덮어쓰지 않습니다.

Sites 배포는 기존 project_id와 접근 범위를 유지해 별도의 Sites 소스 저장소로 게시합니다. `.env.local`·로컬 실행 결과·인증 토큰은 복사하지 않습니다. Colab 실행본은 파일 업로드로 배포하며 실행 중 GitHub ref를 읽지 않습니다. CI에서 생성·검증한 산출물과 실제 Colab 웹 실행을 구분해 기록합니다.

정적 출판에는 독자용 목차만 사용합니다. 통합 빌드가 격리 작업 폴더에서 리다이렉트·다운로드 조립과 출판 제외 검사를 수행해, 이전 작업 기록이 검색·다운로드 파일에 남지 않도록 확인합니다. 작업 기록 파일은 Git에서 제외한 로컬 `.work/`에 보관하며 출판물과 Sites 소스 스냅샷에 포함하지 않습니다.

통합 경로와 공식 Sites helper 연계는 [배포 산출물 관리](artifact-pipeline.md)를 참고하세요. 기존 실습 outputs 경로와 Docker 구성은 유지합니다.
