"""Package standalone notebooks without building HTML; --check never writes."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from artifact_common import ROOT, archive_bytes, write_or_check
from build_colab import build as check_colab_build, render


def build(root=ROOT, *, check=False, language='ko'):
    root = Path(root)
    check_colab_build(root, check=True, language=language)
    source = root / '_build/colab' / ('en' if language=='en' else '')
    files = {p.relative_to(source).as_posix(): p.read_bytes() for p in render(root, language)}
    archive = root / '_build/packages' / ('colab-notebooks-en.zip' if language=='en' else 'colab-notebooks.zip')
    write_or_check({archive: archive_bytes(files)}, check=check)
    return {'files': len(files), 'language':language, 'archive': str(archive.relative_to(root))}


if __name__ == '__main__':
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--language', choices=['ko','en','all'], default='all')
    args=parser.parse_args()
    print(json.dumps([build(check=args.check,language=lang) for lang in (['ko','en'] if args.language=='all' else [args.language])]))
