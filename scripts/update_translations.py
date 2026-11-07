"""Explicit, resumable English translation refresh. Builds never invoke this command."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
import re
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from localization import ROOT, catalog_path, pages, protect, restore, sha, units, validate_translation


def refresh(root, env_file, workers):
    from dotenv import dotenv_values
    from openai import OpenAI, DefaultHttpxClient
    settings = dotenv_values(env_file)
    if not settings.get('OPENAI_API_KEY') or not settings.get('OPENAI_MODEL'):
        raise ValueError('Configure an existing API key and model in the ignored env file')
    glossary_text = (root / 'translations/glossary.json').read_text()
    instruction = (
        'Translate this Korean developer tutorial into fluent, accurate English. Return only a JSON object '
        'mapping the SAME unit IDs to translated Markdown strings. Do not add backticks or new code blocks. Preserve ALL ⟦Pn⟧ tokens exactly once '
        'and in their original order, Markdown headings/depths, tables, list structure, numbers and technical '
        'claims. Translate link labels but never invent features, results or citations. Preserve HTML comments '
        'and MyST syntax. Use Chapter N for Korean chapter headings. No Korean prose outside protected tokens. '
        'Keep policy distinctions between API, SDK, mocked/local/live verification and approvals. Glossary: '
        + glossary_text
    )
    def one(source):
        values = units(root, source)
        path = catalog_path(root, source)
        old = json.loads(path.read_text()) if path.exists() else {}
        saved = old.get('units', {}) if old.get('glossary_sha256') == sha(glossary_text) else {}
        pending = {k:v for k,v in values.items() if saved.get(k,{}).get('source_sha256') != sha(v)}
        if pending:
            protected = {k:protect(v) for k,v in pending.items()}
            request_sha = sha(json.dumps(pending, sort_keys=True, ensure_ascii=False) + glossary_text)
            draft_path = root/'outputs/translation-drafts'/(source+'.json')
            draft = json.loads(draft_path.read_text()) if draft_path.exists() else {}
            # Use the configured HTTPS proxy explicitly when ALL_PROXY requires optional SOCKS extras.
            proxy = os.environ.get('HTTPS_PROXY')
            transport = DefaultHttpxClient(proxy=proxy, trust_env=not bool(proxy))
            if draft.get('request_sha256') == request_sha:
                translated = draft['translation']
                transport.close()
            else:
                with OpenAI(api_key=settings['OPENAI_API_KEY'], timeout=240, max_retries=1,
                            http_client=transport) as client:
                    response = client.responses.create(
                        model=settings['OPENAI_MODEL'], store=False, max_output_tokens=16000,
                        reasoning={'effort':'low'},
                        input=[{'role':'developer','content':instruction},
                               {'role':'user','content':json.dumps(
                                   {k:v[0] for k,v in protected.items()},ensure_ascii=False)}],
                        text={'format':{'type':'json_object'}},
                    )
                translated = json.loads(response.output_text)
                draft_path.parent.mkdir(parents=True,exist_ok=True)
                draft_path.write_text(json.dumps(
                    {'request_sha256':request_sha,'translation':translated},
                    ensure_ascii=False,indent=2)+'\n')
            if set(translated) != set(pending):
                raise ValueError('Translation returned the wrong unit IDs: ' + source)
            for key, value in pending.items():
                # Extra single-backtick emphasis is not a new protected source literal.
                proposal = re.sub(r'(?<!`)`([^`\n]+)`(?!`)',r'\1',translated[key])
                text = restore(proposal, protected[key][1])
                try: validate_translation(value, text)
                except ValueError as e: raise ValueError(f'{source}:{key}: {e}') from e
                saved[key] = {'source_sha256':sha(value),'text':text}
        data = {'schema_version':1,'source':source,'language':'en','glossary_sha256':sha(glossary_text),
                'review_status':'machine-translated; structure checked; editorial review recommended',
                'units':{k:saved[k] for k in values}}
        path.parent.mkdir(parents=True,exist_ok=True)
        temp=path.with_suffix(path.suffix+'.tmp')
        temp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');temp.replace(path)
        print(f'Translated {source}: {len(pending)} refreshed / {len(values)} units',flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one,[*pages(root),'myst.yml']))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--env-file',type=Path,default=ROOT/'.env.local')
    parser.add_argument('--workers',type=int,choices=[1,2],default=2)
    parser.add_argument('--refresh',action='store_true',help='Authorize translation API calls')
    args=parser.parse_args()
    if not args.refresh:parser.error('--refresh is required; this command makes paid translation requests')
    refresh(args.root,args.env_file,args.workers)
