"""Package local source notebooks and their exercise files without repository access."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from artifact_common import ROOT, archive_bytes, source_files, write_or_check

README_KO = """# 전체 실습 파일

이 프로젝트는 OpenAI가 공식 제작하거나 승인한 문서가 아닌 독립적인 학습 자료입니다.

압축을 풀면 Python 소스, 데이터, 예제와 로컬용 원본 노트북이 함께 있습니다.
Colab에서는 별도 Colab용 노트북을 사용하세요. 이 ZIP은 로컬 Jupyter용입니다.

1. Python 3.11 이상과 uv를 준비하세요.
2. 이 README가 있는 폴더에서 `uv sync --locked`를 실행하세요.
3. `uv run jupyter lab`을 실행하고 `notebooks/setup.ipynb`부터 여세요.
4. Jupyter에서 프로젝트 .venv 커널을 선택하세요. helper 수정은 src/tutorial_helpers/에 반영합니다.

패키지 설치에는 인터넷이 필요합니다. 실제 API 실습에는 키·모델과 접근 권한이 필요합니다.
키는 포함된 .env.example을 참고하여 .env.local에 설정하세요.
Docker·사내 네트워크 실습에는 별도 환경이 필요합니다.
선택 의존성: MCP는 `uv sync --locked --group dev`, telemetry는 `uv sync --locked --group telemetry-otlp`.
API 호출 없는 확인: `uv run python scripts/check_notebooks.py --execute`.
"""
README_EN = """# Complete exercise files

Independent learning material, not produced or endorsed by OpenAI.

This archive contains Python sources, data, examples and original local notebooks.
Use the separate Colab notebooks for Colab; this archive is for local Jupyter.

1. Install Python 3.11+ and uv.
2. Run `uv sync --locked` in the folder containing this README.
3. Run `uv run jupyter lab` and open `notebooks/setup.ipynb`.
4. Select the project .venv kernel. Edit helpers in src/tutorial_helpers/.

Package installation requires internet access. Live exercises require an API key, model and access.
Use .env.example to configure .env.local. Docker/private-network exercises need additional setup.
Optional dependencies: `uv sync --locked --group dev` for MCP; `uv sync --locked --group telemetry-otlp` for telemetry.
Check without API calls: `uv run python scripts/check_notebooks.py --execute`.
Example code is unchanged and may generate Korean reports.
"""


def build(root=ROOT, *, check=False, language='ko'):
    root = Path(root)
    if language not in {'ko', 'en'}:
        raise ValueError('Unsupported language')
    folders = {'notebooks', 'src', 'data', 'examples', 'skills', 'plugins', 'deploy', 'scripts', 'docs', 'translations'}
    names = {'pyproject.toml', 'uv.lock', 'tutorial.json', '.python-version', '.env.example', 'myst.yml', 'index.md', 'book-redirects.json'}
    files = {}
    for path in source_files(root):
        relative = path.relative_to(root)
        if relative.parts[0] in folders or relative.as_posix() in names:
            # Only maintained, distributable source types; never package local credentials/output.
            if path.name.startswith('.env') and relative.as_posix() != '.env.example':
                continue
            if path.suffix not in {'.py', '.ipynb', '.md', '.json', '.csv', '.toml', '.lock', '.yml', '.yaml', '.txt', '.sh', '.example', '.dockerignore', ''}:
                continue
            data = path.read_bytes()
            if language == 'en' and relative.parts[0] == 'notebooks' and path.suffix == '.ipynb' and not path.name.startswith('_'):
                from localization import notebook
                data = (json.dumps(notebook(root, relative.as_posix(), 'en'), ensure_ascii=False, indent=1) + '\n').encode()
            files['agents-api-examples/' + relative.as_posix()] = data
    files['agents-api-examples/README.md'] = (README_EN if language == 'en' else README_KO).encode()
    archive = root / '_build/packages' / ('exercise-files-en.zip' if language == 'en' else 'exercise-files.zip')
    write_or_check({archive: archive_bytes(files)}, check=check)
    return {'files': len(files), 'language': language, 'archive': str(archive.relative_to(root))}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--language', choices=['ko', 'en', 'all'], default='all')
    args = parser.parse_args()
    print(json.dumps([build(check=args.check, language=lang) for lang in (['ko', 'en'] if args.language == 'all' else [args.language])]))
