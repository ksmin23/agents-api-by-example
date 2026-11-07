"""Generate readable, self-contained Colab notebooks from the maintained sources."""
from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def specs(root, number):
    project = tomllib.loads((root / "pyproject.toml").read_text())
    names = [re.match(r"[\w-]+", item).group() for item in project["project"]["dependencies"]]
    if number == 13:
        names += ["opentelemetry-sdk"]
    packages = tomllib.loads((root / "uv.lock").read_text())["package"]
    return [f"{name}=={next(p['version'] for p in packages if p['name'] == name)}" for name in names]


def installer(packages):
    condition = 'os.environ.get("TUTORIAL_OFFLINE_CHECK") != "1"'
    lines = "\n".join(f"            {p!r}," for p in packages)
    return f'''import os
import subprocess
import sys

if {condition}:
    subprocess.run(
        [
            sys.executable, "-m", "pip", "install", "--quiet",
            "--index-url", "https://pypi.org/simple",
{lines}
        ],
        check=True,
    )
else:
    print("Using the local uv environment or offline validation environment.")
'''


def asset_paths(root, number, notebook):
    paths = ["src/tutorial_helpers/__init__.py", "src/tutorial_helpers/common.py", "data/sales.csv"]
    for c in notebook["cells"]:
        if c["cell_type"] != "code":
            continue
        for node in ast.walk(ast.parse("".join(c["source"]))):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("tutorial_helpers."):
                paths.append("src/" + node.module.replace(".", "/") + ".py")
    if number in {7, 8, 10, 15}:
        paths.append("data/sales_targets.json")
    if number in {8, 10}:
        paths.append("examples/mcp/sales_targets_server.py")
    if number in {9, 10}:
        folders = ["skills/csv-report"] + (["plugins/sales-reporting"] if number == 10 else [])
        for folder in folders:
            paths += [p.relative_to(root).as_posix() for p in (root / folder).rglob("*")
                      if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"]
    if number in {12, 13, 14}:
        paths += [p.relative_to(root).as_posix() for p in (root / "deploy").rglob("*")
                  if p.is_file() and not any(x in p.parts for x in {".generated", "__pycache__"})
                  and p.suffix != ".pyc"]
    return sorted(set(paths))


def cell(kind, source, identifier, tags=()):
    result = {"cell_type": kind, "id": identifier, "metadata": {"tags": list(tags)},
              "source": source.splitlines(keepends=True)}
    if kind == "code":
        result.update(execution_count=None, outputs=[])
    return result


def file_cell(name, body, identifier):
    # Raw triple-quoted text preserves readable Python, Markdown and backslashes.
    delimiter = next((d for d in ["'''", '"""'] if d not in body), None)
    if delimiter is None:
        literal = "(\n" + "\n".join("    " + repr(line) for line in body.splitlines(keepends=True)) + "\n)"
    else:
        literal = "r" + delimiter + body + delimiter
    source = f"# Bundled file: {name}\npath = COLAB_ROOT / {name!r}\npath.parent.mkdir(parents=True, exist_ok=True)\npath.write_text({literal}, encoding='utf-8')\n"
    return cell("code", source, identifier, ["colab_asset", "hide-input"])


def render(root=ROOT, language='ko'):
    root = Path(root)
    updates = {}
    for path in sorted((root / "notebooks").rglob("*.ipynb")):
        if ".ipynb_checkpoints" in path.parts:
            continue
        number = int(path.name[:2]) if path.name[:2].isdigit() else 0
        notebook = json.loads(path.read_text())
        if path.name.startswith("_"):
            continue
        if language == 'en':
            from localization import notebook as translated_notebook
            notebook = translated_notebook(root, path.relative_to(root).as_posix(), language)
        elif language != 'ko':
            raise ValueError('Unsupported language')
        local_only = path.name == "setup.ipynb" or number == 1
        relative = path.relative_to(root / "notebooks")
        exported = copy.deepcopy(notebook)
        prefix = "colab-" + hashlib.sha256(relative.as_posix().encode()).hexdigest()[:12]
        assets = asset_paths(root, number, notebook)
        manifest = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in assets}
        exported["metadata"].setdefault("tutorial", {}).update(
            standalone=True, source=path.relative_to(root).as_posix(), assets=manifest,
            packages=specs(root, number), source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            language=language,
        )
        rewritten = []
        for c in exported["cells"]:
            source = "".join(c["source"])
            if source.startswith("<!-- colab-link -->"):
                if language == 'en':
                    notice = ('<!-- colab-link -->\nStandalone notebook; no GitHub download is required.\n'
                              + ('Helper code is embedded in this notebook and written to disk by the preparation cells. Run these cells in order from the beginning. This local exercise requires no API key or model.\n' if local_only else
                               'Helper code is embedded in this notebook and written to disk by the preparation cells. Run these cells in order from the beginning. Live API execution requires RUN_LIVE=True and a key/model in Colab Secrets.\n')
                              + ('Chapters 12–14 are read-only here. Run Docker/private-network exercises locally.\n' if number in {12,13,14} else '')
                              + 'The example code is identical to the Korean source, including instructions that generate Korean reports.\n')
                    c['source'] = notice.splitlines(keepends=True)
                else:
                    c["source"] = ("<!-- colab-link -->\n독립 실행용 노트북입니다. GitHub 다운로드 없이 실행합니다.\n"
                    + ("helper 코드는 노트북에 포함되어 있으며 준비 셀 실행 시 생성됩니다. 처음부터 준비 셀을 순서대로 실행하세요. 로컬 실습이며 API 키나 모델이 필요하지 않습니다.\n" if local_only else
                       "helper 코드는 노트북에 포함되어 있으며 준비 셀 실행 시 생성됩니다. 처음부터 준비 셀을 순서대로 실행하세요. 실제 API는 RUN_LIVE=True와 Colab Secrets의 키·모델 설정이 필요합니다.\n")
                    + ("12–14장은 읽기용입니다. Docker·사내 네트워크 실습은 로컬에서 실행하세요.\n" if number in {12, 13, 14} else "")
                    ).splitlines(keepends=True)
            if c["cell_type"] == "markdown":
                # A downloaded notebook must not depend on local documentation pages.
                suffix = 'see the source guide' if language == 'en' else '원본 교재 참고'
                c["source"] = re.sub(r"\[([^\]]+)\]\((?![a-z]+:|#)([^)]+)\)", r"\1 (`\2` — " + suffix + ')', "".join(c["source"])).splitlines(keepends=True)
            if "bootstrap" in c["metadata"].get("tags", []):
                c["source"] = installer(specs(root, number)).splitlines(keepends=True)
                rewritten.append(c)
                guide_text = ('## Prepare the bundled exercise files\n\nThe following cells write the included helpers, data and examples to a temporary workspace. Expand them to inspect the files. API calls and event handling remain in the later exercise cells.\n' if language == 'en' else "## 포함된 실습 파일 준비\n\n아래 셀은 이 노트북에 포함한 helper·데이터·예제 파일을 임시 작업 폴더에 만듭니다. 코드는 펼쳐서 확인할 수 있습니다. API 호출·이벤트 처리는 이후 실습 셀에 있습니다.\n")
                if local_only:
                    guide_text = ('## Prepare the bundled exercise files\n\nThe following cells create the included helpers and data in a temporary workspace. All later cells in this local exercise check the environment, inspect local data, or preview request dictionaries; none send API requests.\n' if language == 'en' else
                                  '## 포함된 실습 파일 준비\n\n아래 셀은 포함된 helper와 데이터를 임시 폴더에 만듭니다. 이후 셀은 환경·로컬 데이터 확인과 요청 딕셔너리 미리보기만 수행하며 API 요청을 보내지 않습니다.\n')
                rewritten.append(cell("markdown", guide_text, prefix + "-guide"))
                rewritten.append(cell("code", '''from pathlib import Path
import tempfile

COLAB_ROOT = Path(tempfile.mkdtemp(prefix="agents-colab-")).resolve()
(COLAB_ROOT / "tutorial.json").write_text('{"standalone": true}', encoding="utf-8")
for name in list(sys.modules):
    if name == "tutorial_helpers" or name.startswith("tutorial_helpers."):
        del sys.modules[name]
sys.path.insert(0, str(COLAB_ROOT / "src"))
os.chdir(COLAB_ROOT)
print("Working directory:", COLAB_ROOT)
''', prefix + "-root", ["colab_asset", "hide-input"]))
                for i, name in enumerate(assets):
                    rewritten.append(file_cell(name, (root / name).read_text(), prefix + f"-{i}"))
                rewritten.append(cell("code", """from tutorial_helpers import common as tutorial_common

assert Path(tutorial_common.__file__).resolve() == COLAB_ROOT / "src/tutorial_helpers/common.py"
assert (COLAB_ROOT / "data/sales.csv").is_file()
print("Exercise files ready:", COLAB_ROOT)
print("tutorial_helpers:", tutorial_common.__file__)
""", prefix + "-ready", ["colab_asset"]))
            else:
                rewritten.append(c)
        exported["cells"] = rewritten
        directory = root / '_build/colab' / ('en' if language == 'en' else '')
        updates[directory / relative] = json.dumps(exported, ensure_ascii=False, indent=1) + "\n"
    names = sorted(p.relative_to(directory).as_posix() for p in updates)
    guide = ("# 독립 실행용 Colab 노트북\n\n"
             "이 프로젝트는 OpenAI가 공식 제작하거나 승인한 문서가 아닌 독립적인 학습 자료입니다.\n\n"
             "필요한 .ipynb 하나를 Colab의 파일 → 노트북 업로드로 여세요. "
             "helper·데이터는 노트북에 내장되어 있습니다. 압축 해제 직후에는 .py 파일이 보이지 않으며 준비 셀을 처음부터 순서대로 실행하면 임시 폴더에 생성됩니다. 마지막 준비 셀에서 파일 위치와 import 성공을 확인하세요. GitHub 다운로드 없이 공개 PyPI에서 패키지를 설치합니다.\n\n"
             "실제 API는 Colab Secrets의 키·모델과 RUN_LIVE=True가 필요합니다. "
             "12–14장은 읽기용이며 Docker·사내망 실습은 로컬에서 실행합니다.\n\n"
             "이 폴더는 자동 생성물입니다. 원본 notebooks/와 공통 파일을 수정한 뒤 다시 생성하세요.\n\n")
    guide += "\n".join(f"- [{Path(name).stem}]({name})" for name in names) + "\n"
    if language == 'en':
        guide = ('# Standalone Colab notebooks — English\n\n'
                 'Independent learning material, not produced or endorsed by OpenAI.\n\n'
                 'Upload one .ipynb in Colab. Helpers and data are embedded in the notebook. Run preparation cells in order to create the files in a temporary folder; the final preparation cell confirms the helper import and file location. No GitHub download is required. Dependencies install from public PyPI. '
                 'For live API execution, configure Colab Secrets and RUN_LIVE=True. Chapters 12–14 are read-only here; '
                 'run Docker examples locally. Code is unchanged and may generate Korean reports.\n\n'
                 'Generated files; edit notebooks/ and translations/ instead.\n\n'
                 + '\n'.join(f'- [{Path(name).stem}]({name})' for name in names) + '\n')
    updates[directory / 'README.md'] = guide
    return updates


def build(root=ROOT, *, check=False, language='ko'):
    root = Path(root)
    updates = render(root, language)
    directory = root / "_build/colab" / ('en' if language == 'en' else '')
    expected = {p for p in updates if p.suffix == ".ipynb"}
    actual = {p for p in directory.rglob('*.ipynb') if language == 'en' or 'en' not in p.relative_to(directory).parts}
    unexpected = actual - expected
    if unexpected:
        raise ValueError("Unexpected generated notebooks: " + str(sorted(unexpected)))
    stale = [p for p, text in updates.items() if not p.exists() or p.read_text() != text]
    if check and stale:
        raise ValueError("Run scripts/build_colab.py: " + ", ".join(str(p.relative_to(root)) for p in stale))
    if not check:
        for path, text in updates.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
    return {"standalone_notebooks": len(expected), "language": language, "directory": str(directory.relative_to(root)), "sources_modified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument('--language', choices=['ko','en','all'], default='all')
    args = parser.parse_args()
    try:
        report = [build(check=args.check, language=lang) for lang in (['ko','en'] if args.language=='all' else [args.language])]
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(report))


if __name__ == "__main__":
    main()
