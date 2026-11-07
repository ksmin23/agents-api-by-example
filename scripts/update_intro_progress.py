"""Maintain optional, ignored .work/PROGRESS.md; no API requests."""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import argparse

ROOT=Path(__file__).resolve().parents[1]


def update(chapter, *, writing=None, offline=None, live=None, note="", root=None):
    if chapter not in range(1, 16):
        raise ValueError("Expected chapter 1..15")
    root = Path(root) if root is not None else ROOT
    if note == '실제 API 검증 시작.' and live is None:
        live = '진행 중'
    if note == '오프라인 실행 검증 시작.' and offline is None:
        offline = '진행 중'
    path = root / '.work/PROGRESS.md'
    if path.exists():
        lines = path.read_text().splitlines()
    else:
        lines = [
            '# Local tutorial progress', '',
            'Local run history only; a new checkout has no inherited validation results.', '',
            '| Chapter | Topic | Writing | Offline validation | Live API validation |',
            '| --- | --- | --- | --- | --- |',
        ]
        for number in range(1, 16):
            paths = sorted((root / 'notebooks/chapters').glob(f'{number:02d}_*.ipynb'))
            topic = paths[0].stem if paths else f'Chapter {number}'
            lines.append(f'| {number} | {topic} | Not recorded | Not run | Not run |')
    found=False
    for index,line in enumerate(lines):
        if line.startswith(f'| {chapter} |'):
            fields=line.split('|')
            for column,value in ((3,writing),(4,offline),(5,live)):
                if value is not None:
                    fields[column]=' '+value+' '
            lines[index]='|'.join(fields)
            found=True
    if not found:
        raise ValueError('Chapter row not found')
    now=datetime.now(ZoneInfo('Asia/Seoul')).isoformat(timespec='seconds')
    if note:
        lines.append(f'- {now}: {chapter}장 — {note}')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chapter',type=int,choices=range(1,16),required=True)
    parser.add_argument('--writing')
    parser.add_argument('--offline')
    parser.add_argument('--live')
    parser.add_argument('--note',default='')
    args=vars(parser.parse_args())
    update(args.pop('chapter'),**args)
