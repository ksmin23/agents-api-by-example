"""Run extension notebooks in fresh kernels. Paid API work requires explicit --live."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

from dotenv import dotenv_values
import nbformat
from nbclient import NotebookClient

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from update_intro_progress import update

CHAPTERS={7:'07_function_tools',8:'08_mcp',9:'09_skills',10:'10_plugins',11:'11_guardrails_approvals'}


def run(number, live, approval_fixture=False, *, chapter_slug=None):
    slug=chapter_slug or CHAPTERS[number]
    source=ROOT/f'notebooks/chapters/{slug}.ipynb'
    notebook=nbformat.read(source,as_version=4)
    nbformat.validate(notebook)
    from check_notebooks import validate_api_tags
    api_cells = validate_api_tags(notebook)
    switches=0
    for cell in notebook.cells:
        if 'live_configuration' in cell.metadata.get('tags',[]):
            if cell.source.count('RUN_LIVE = False')!=1:
                raise RuntimeError('Source must contain one default-off live switch')
            if live:
                cell.source=cell.source.replace('RUN_LIVE = False','RUN_LIVE = True')
            if number == 11 and approval_fixture:
                if cell.source.count('APPROVAL_MODE = "interactive"') != 1:
                    raise RuntimeError("Source must default to interactive approval")
                cell.source = cell.source.replace(
                    'APPROVAL_MODE = "interactive"', 'APPROVAL_MODE = "fixture"'
                )
            switches+=1
    if switches!=1:
        raise RuntimeError('Missing live configuration cell')
    from notebook_validation import instrument_notebook
    instrument_notebook(notebook, slug, live=live and number != 1)
    destination=ROOT/f'outputs/extensions-validation/{slug}.executed.ipynb'
    destination.parent.mkdir(parents=True,exist_ok=True)
    update(number,note=('실제 API 검증 시작.' if live and number!=1 else '오프라인 실행 검증 시작.'))
    failed=None
    print(f'Chapter {number}: {slug} | mode={"live" if live and number!=1 else "offline"}',flush=True)
    with tempfile.TemporaryDirectory(prefix='extensions-notebook-') as temp:
        directory=Path(temp)/'kernels/tutorial-intro'
        directory.mkdir(parents=True)
        (directory/'kernel.json').write_text(json.dumps({
            'argv':[sys.executable,'-m','ipykernel_launcher','-f','{connection_file}'],
            'display_name':'Tutorial intro validation','language':'python',
        }))
        old=os.environ.get('JUPYTER_PATH')
        os.environ['JUPYTER_PATH']=temp
        env=dict(os.environ)
        env.pop('OPENAI_LOG',None)
        env.pop("TUTORIAL_APPROVAL_FIXTURE", None)
        if live:
            env.pop('TUTORIAL_OFFLINE_CHECK',None)
        else:
            env['TUTORIAL_OFFLINE_CHECK']='1'
            for key_name in ['OPENAI_API_KEY', 'OPENAI_EXECUTOR_API_KEY', 'CODEX_API_KEY']:
                env.pop(key_name, None)
            # Same Python socket guard as the repository-wide offline checker.
            from check_notebooks import GUARD
            notebook.cells.insert(0,nbformat.v4.new_code_cell(GUARD))
        try:
            NotebookClient(notebook,timeout=1200 if number == 15 else 720,kernel_name='tutorial-intro',coalesce_streams=True,
                           resources={'metadata':{'path':str(ROOT)}},allow_errors=False,
                           skip_cells_with_tag='skip-execution' if live else 'requires_api').execute(env=env)
        except Exception as error:
            failed=type(error).__name__
        finally:
            if old is None:
                os.environ.pop('JUPYTER_PATH',None)
            else:
                os.environ['JUPYTER_PATH']=old
    serialized=nbformat.writes(notebook)
    values=dotenv_values(ROOT/'.env.local')
    if any(key and key in serialized for key in [values.get('OPENAI_API_KEY'),os.environ.get('OPENAI_API_KEY')]):
        raise RuntimeError('Secret detected; refusing to persist executed notebook')
    destination.write_text(serialized)
    stage='live' if live and number!=1 else 'offline'
    if failed:
        update(number,**{stage:'실패'},note=f'{stage} 검증 실패({failed}). outputs/extensions-validation 실행 사본과 state.json 확인 필요.')
        print(f'FAIL chapter {number}: {failed}; inspect {destination.relative_to(ROOT)}',flush=True)
        return False
    if stage=='live':
        latest=ROOT/f'outputs/extensions/{slug}/latest.json'
        summary=json.loads(latest.read_text())
        if (summary['status']!='passed' or not summary['sessions']
            or not all(v.get('verified_absent') for v in summary['sessions'].values())
            or not all(v.get('verified_absent') for v in summary['agents'].values())):
            update(number,live='실패',note='노트북은 종료됐지만 실제 실행 또는 자원 삭제 확인이 불완전합니다.')
            return False
        update(number,live='통과',note=f'실제 API 검증 통과. 세션 {len(summary["sessions"])}개·저장 Agent {len(summary["agents"])}개 삭제 확인. 결과: outputs/extensions/{slug}/latest.json')
    else:
        update(number,offline='통과',note=f'새 커널 로컬 셀 검증 통과. requires_api {api_cells}개 셀 건너뜀; API·모델·sandbox 미실행. 원본 출력 없음.')
    print(f'PASS chapter {number}: {destination.relative_to(ROOT)}',flush=True)
    return True


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    choice=parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--chapter',type=int,choices=range(7,12))
    choice.add_argument('--all',action='store_true')
    parser.add_argument('--live',action='store_true',help='Authorize paid model and sandbox execution')
    parser.add_argument('--approval-fixture',action='store_true',help='Use explicit test approval, not a real human decision; local training storage only')
    args=parser.parse_args()
    numbers=range(7,12) if args.all else [args.chapter]
    if args.live and 11 in numbers and not args.approval_fixture:
        parser.error('--approval-fixture is required for noninteractive chapter 11 validation; use Jupyter for human input')
    for number in numbers:
        if not run(number,args.live,args.approval_fixture):
            return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
