"""Paths, deterministic archives and input fingerprints for publication builds."""
from __future__ import annotations
import hashlib
import io
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = ('notebooks', 'translations', 'src', 'data', 'skills', 'plugins', 'deploy', 'examples', 'docs', 'scripts', 'tests', '.github')
SOURCE_FILES = ('index.md', 'README.md', 'myst.yml', 'tutorial.json', 'pyproject.toml', 'uv.lock',
                'book-redirects.json', '.python-version', '.env.example', '.gitignore')
LOCAL_RECORDS = frozenset({'docs/tutorial-improvement-validation.md', 'PROGRESS.md', 'docs/tutorial-improvement-plan.md', 'todo.md', 'docs/final-review.md', 'docs/api-direct-refactor.md'})


def source_files(root=ROOT):
    root = Path(root)
    files = [root / name for name in SOURCE_FILES if (root / name).is_file()]
    for folder in SOURCE_DIRS:
        files += [p for p in (root / folder).rglob('*') if p.is_file()]
    result = []
    for path in files:
        relative = path.relative_to(root)
        if any(x in relative.parts for x in ('__pycache__', '.ipynb_checkpoints', '.generated')) or path.suffix == '.pyc':
            continue
        if relative.as_posix() in LOCAL_RECORDS or ".work" in relative.parts:
            continue
        if path.is_symlink():
            raise ValueError('Source symlink is not supported: ' + str(relative))
        result.append(path)
    return sorted(set(result))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fingerprint(files, root):
    return {p.relative_to(root).as_posix(): digest(p.read_bytes()) for p in sorted(files)}


def tree(directory):
    directory = Path(directory)
    files = list(p for p in directory.rglob('*') if p.is_file())
    if any(p.is_symlink() for p in files):
        raise ValueError('Artifact tree contains a symlink')
    return fingerprint(files, directory)


def source_state(root=ROOT):
    root = Path(root)
    files = fingerprint(source_files(root), root)
    commit = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], capture_output=True, text=True)
    return {'commit': commit.stdout.strip() if commit.returncode == 0 else None,
            'inputs_sha256': digest(json.dumps(files, sort_keys=True).encode()), 'files': files}


def archive_bytes(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    return stream.getvalue()


def write_or_check(files, *, check=False):
    stale = [str(p) for p, data in files.items() if not p.is_file() or p.read_bytes() != data]
    if check and stale:
        raise ValueError('Missing or stale artifact: ' + ', '.join(stale))
    if not check:
        for path, data in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
