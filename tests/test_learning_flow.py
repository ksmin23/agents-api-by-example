"""Check cross-chapter navigation, environment boundaries, and reader guidance."""
import ast
import json
from pathlib import Path
import re
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from localization import notebook as translated_notebook


def lesson(number, language='ko'):
    path=next((ROOT/'notebooks/chapters').glob(f'{number:02}_*.ipynb'))
    return translated_notebook(ROOT,path.relative_to(ROOT).as_posix(),language)


def markdown(notebook):
    return '\n'.join(''.join(c['source']) for c in notebook['cells'] if c['cell_type']=='markdown')


class LearningFlowTests(unittest.TestCase):
    def test_all_adjacent_chapters_have_a_direct_next_link_in_both_languages(self):
        for language in ['ko','en']:
            for number in range(1,15):
                with self.subTest(language=language,chapter=number):
                    links=re.findall(r'\]\(([^)]+)\)',markdown(lesson(number,language)))
                    expected=next((ROOT/'notebooks/chapters').glob(f'{number+1:02}_*.ipynb')).name
                    self.assertIn(expected,links)

    def test_capability_section_offers_both_operations_and_delegation_routes(self):
        for language in ['ko','en']:
            text=markdown(lesson(11,language))
            self.assertIn('12_self_hosted.ipynb',text)
            self.assertIn('15_multi_agent.ipynb',text)
            self.assertIn('14_operations.ipynb',markdown(lesson(12,language)))

    def test_hosted_operation_introductions_agree_with_actual_environment_code(self):
        for number in [13,14]:
            for language in ['ko','en']:
                notebook=lesson(number,language)
                self.assertIn('OpenAI-hosted',''.join(notebook['cells'][0]['source']))
                environment=[]
                for cell in notebook['cells']:
                    if cell['cell_type']=='code':
                        for node in ast.walk(ast.parse(''.join(cell['source']))):
                            if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='environment' for t in node.targets):
                                environment.append(node.value)
                self.assertEqual(len(environment),1)
                value=environment[0]
                fields={k.value:v for k,v in zip(value.keys,value.values) if isinstance(k,ast.Constant)}
                self.assertEqual(ast.literal_eval(fields['type']),'openai_hosted')

    def test_chapter_scope_links_share_one_published_guide(self):
        for number in range(2,16):
            notebook=lesson(number)
            scope=[c for c in notebook['cells'] if 'validation_scope' in c['metadata'].get('tags',[])]
            self.assertEqual(len(scope),1)
            self.assertIn('../../docs/validation.md',''.join(scope[0]['source']))
            self.assertIn('이번 실습 조합',''.join(notebook['cells'][0]['source']))

    def test_homepage_and_shared_guide_keep_setup_keyless_and_distinguish_records(self):
        homepage=(ROOT/'index.md').read_text()
        self.assertNotIn('설치·API 키·커널',homepage)
        self.assertIn('키 없이 설치·커널·데이터 경로',homepage)
        guide=(ROOT/'docs/validation.md').read_text()
        for text in ['downloads/summary.json','&lt;run_id&gt;/summary.json','&lt;run_id&gt;/creation.json',
                     '.approval.json','12–14장은 15장의 선행 조건이 아닙니다']:
            self.assertIn(text,guide)
        self.assertNotRegex((ROOT/'README.md').read_text(),re.compile(r'^## (?:실행 )?검증 (?:범위|결과)', re.M))

    def test_template_points_run_history_to_local_work_records(self):
        notebook=json.loads((ROOT/'notebooks/_template.ipynb').read_text())
        text=markdown(notebook)
        self.assertIn('.work/PROGRESS.md',text)
        self.assertIn('## 검증 방법과 범위',text)
        self.assertNotIn('## 검증 기록',text)


if __name__=='__main__':
    unittest.main()
