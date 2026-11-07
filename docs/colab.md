# Colab 독립 실행본 받기

학습자는 준비된 `.ipynb` 파일 하나를 받아 Colab에 업로드합니다. 실행 중 GitHub 주소·인증이나 저장소 복사는 필요하지 않습니다. 패키지 설치에는 공개 PyPI 연결이, 실제 Agents API 실습에는 API 키·모델과 접근 권한이 필요합니다.

## 학습자: 노트북 다운로드·실행

[독립 실행본 17개 ZIP 다운로드](https://agents-api-by-example.openai.chatgpt.site/downloads/colab-notebooks.zip) · [빠른 시작 노트북 다운로드](https://agents-api-by-example.openai.chatgpt.site/downloads/colab/quickstart.ipynb)

ZIP에는 노트북과 전달용 README만 포함합니다. 파일은 현재 교재 Sites의 접근 권한으로 다운로드합니다.

1. 교재 제공자가 전달한 노트북 또는 `colab-notebooks` ZIP을 받습니다. ZIP이면 먼저 압축을 풉니다.
2. Colab에서 **파일 → 노트북 업로드**를 선택하고 필요한 `.ipynb` 하나를 엽니다.
3. 준비 셀을 실행합니다. 필요한 패키지를 현재 Python에 직접 설치하고, 포함된 helper·데이터·예제 파일을 임시 실습 폴더에 만듭니다.
4. 실제 API 실습에는 Colab Secrets에 `OPENAI_API_KEY`와 `OPENAI_MODEL`을 설정하고 `RUN_LIVE=True`를 선택합니다. 기본값은 False이며 준비 셀의 안내에 따라 실행을 선택합니다.

환경 준비·빠른 시작·1–11장·15장은 Python 실습용입니다. 12–14장의 배포용 파일은 읽기용이며 Docker·사내 네트워크 실습은 로컬 Jupyter에서 수행합니다. `.ipynb`에 API 키를 기록하지 않습니다.

## 전체 실습 파일: 소스와 함께 로컬 실행

[전체 실습 파일 ZIP 다운로드](https://agents-api-by-example.openai.chatgpt.site/downloads/exercise-files.zip)

Colab용 ZIP은 노트북에 helper 코드를 내장합니다. 압축 해제 직후에는 Python 소스 파일이 보이지 않으며, 준비 셀을 처음부터 순서대로 실행하면 임시 폴더에 파일이 생성됩니다. 마지막 준비 셀에서 helper import 성공과 파일 위치를 확인하세요.

전체 실습 ZIP에는 로컬용 원본 노트북, `src/tutorial_helpers/`, 데이터·예제·스킬·플러그인·배포 파일, 의존성 설정이 함께 있습니다. helper를 읽거나 수정하며 실행하려면 이 ZIP을 선택하세요. 압축을 푼 뒤 `agents-api-examples/` 폴더에서 실행합니다.

```bash
uv sync --locked
uv run jupyter lab
```

프로젝트 .venv 커널을 선택하고 `notebooks/setup.ipynb`부터 여세요. 이 노트북은 로컬 프로젝트의 helper를 사용합니다. 패키지 설치에는 인터넷이, 실제 API 실습에는 키·모델·접근 권한이 필요합니다. 자세한 실행 방법과 선택 의존성은 ZIP의 README에 있습니다.

제공자는 Book 빌드 없이도 다음 명령으로 한·영 전체 실습 ZIP을 생성·검증할 수 있습니다. 통합 Book 빌드는 두 다운로드를 함께 배치합니다. CI의 `exercise-files` 산출물에서도 받을 수 있습니다.

```bash
uv run python scripts/build_exercise_zip.py
uv run python scripts/build_exercise_zip.py --check
```

## 제공자: 로컬에서 생성·전달

```bash
uv sync --locked
uv run python scripts/build_colab.py
uv run python scripts/build_colab.py --check
uv run python scripts/build_colab_zip.py
uv run --group dev python scripts/check_colab.py --execute
```

생성 위치는 `_build/colab/`입니다. `uv run python scripts/build_colab_zip.py`로 Book 없이 `_build/packages/colab-notebooks.zip`을 만듭니다. 통합 Book 빌드는 검증된 노트북·ZIP을 downloads/로 복사합니다. `setup.ipynb`, `quickstart.ipynb`, `chapters/01_concepts.ipynb`부터 `15_multi_agent.ipynb`까지 17개와 안내 README가 만들어집니다. 필요한 파일을 개별 전달하거나 이 폴더를 압축해 전달합니다. Google Drive로 공유해도 됩니다.

`notebooks/`가 노트북 원본입니다. helper·데이터·예제 파일은 기존 원본 경로에서 관리합니다. 생성기는 원본을 읽기만 하고 `_build/colab/`에만 씁니다. 생성물은 Git에서 제외하며 직접 편집하지 않습니다. 원본이나 의존성을 변경하면 다시 생성합니다.

## 제공자: CI 산출물 받기

변경 사항을 GitHub에 반영한 뒤 **Actions → Validate tutorial → 성공한 실행 → Artifacts → colab-notebooks**에서 받습니다. 산출물에는 생성된 노트북과 README만 포함합니다. CI는 생성·API 실행 셀 보존 검사·오프라인 실행 후 업로드하도록 구성되어 있습니다. 보관 기간은 30일입니다.

GitHub Actions 산출물을 받으려면 GitHub 로그인과 저장소 읽기 권한이 필요합니다. 비공개 저장소에서는 권한이 있는 제공자가 받아 학습자에게 파일로 전달합니다. 학습자의 노트북 실행에는 GitHub 접근이 필요하지 않습니다. [GitHub 공식 다운로드 안내](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts)

자동 Jupyter Book 게시 workflow의 중단 상태는 유지합니다. CI 설정이 있다는 사실과 원격 실행·업로드 성공은 구분합니다. 실제 Colab 웹·Linux 런타임·유료 API 검증도 오프라인 실행과 별도로 확인합니다.

프로젝트 원본 저장소는 [ksmin23/agents-api-by-example](https://github.com/ksmin23/agents-api-by-example)입니다. 독립 실행본에는 저장소 주소를 내려받는 코드가 없으므로 저장소 이름 변경의 영향을 받지 않습니다. 위 ChatGPT Sites 다운로드 주소는 GitHub와 별도로 유지합니다.
