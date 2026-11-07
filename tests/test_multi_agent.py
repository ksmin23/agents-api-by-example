"""Verify delegation evidence, data oracles, and the standalone lesson contract."""
import json
from pathlib import Path
from types import SimpleNamespace as Obj
import tempfile
import unittest
from tutorial_helpers.validation import analyze_csv, validate_multi_agent

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "scripts"))


class MultiAgentTests(unittest.TestCase):
    def fixture(self, directory):
        csv_text = (ROOT / 'data/sales.csv').read_text()
        metrics = analyze_csv(csv_text)
        target = dict(period='2026-01', total_revenue=127500, target_revenue=150000,
                      attainment_rate=0.85, shortfall=22500, currency='KRW')
        downloads = Path(directory)
        for name, data in [('summary.json', metrics), ('target_assessment.json', target),
                           ('sales_breakdown.json', {'metrics': metrics, 'by_date': {'2026-01-01': 65000, '2026-01-02': 25000, '2026-01-03': 37500}})]:
            (downloads / name).write_text(json.dumps(data))
        (downloads / 'report.md').write_text('# 매출 분석 보고서\n127500 A 30000 B 75000 C 22500\n목표 150000, 달성 85.00%, 부족 22500\n2026-01-01 65000, 2026-01-02 25000, 2026-01-03 37500\nsales_breakdown.json target_assessment.json')
        def command(script, turn):
            return Obj(id=script, type='command_execution', command='python /workspace/workers/' + script,
                       turn_id=turn, status='completed', exit_code=0)
        ns = dict(settings=Obj(root=ROOT), downloads=downloads,
                  PERIOD='2026-01', csv_bytes=(ROOT/'data/sales.csv').read_bytes(),
                  targets_bytes=(ROOT/'data/sales_targets.json').read_bytes(),
                  history_checked=True, commands_checked=True, report_downloaded=True,
                  result=Obj(session_id='session', turn_id='root', output_text=json.dumps(metrics)),
                  turn=Obj(id='root', status='completed', subagent_id=None, usage=None),
                  subagents=[Obj(id='structure'), Obj(id='target')],
                  created_subagent_ids=['structure', 'target'],
                  command_actors={'structure': 'structure', 'target': 'target'},
                  child_turns={sid: [Obj(id=sid+'-turn', status='completed', subagent_id=sid)]
                               for sid in ['structure', 'target']},
                  child_items={'structure': [command('structure.py', 'structure-turn')],
                               'target': [command('target.py', 'target-turn')]})
        ns['role_executions'] = {script: {'subagent_id': sid, 'turn_id': sid+'-turn', 'command_item_id': script}
                                 for script, sid in [('structure.py', 'structure'), ('target.py', 'target')]}
        ns['published'] = [Obj(id=name, path='/workspace/outputs/'+name, turn_id=turn)
                           for name, turn in [('sales_breakdown.json', 'structure-turn'),
                           ('target_assessment.json', 'target-turn'), ('summary.json', 'root'), ('report.md', 'root')]]
        ns['downloaded_artifacts'] = [dict(id=a.id, path=a.path, turn_id=a.turn_id) for a in ns['published']]
        return ns, [command('combine.py', 'root')]

    def test_distinct_workers_and_correct_outputs_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            ns, items = self.fixture(temp)
            checks, turns = validate_multi_agent(ns, items)
            self.assertEqual(checks['subagent_count'], 2)
            self.assertEqual(checks['target']['shortfall'], 22500)
            self.assertEqual(turns[0]['turn_id'], 'root')

    def test_same_worker_cannot_claim_both_roles(self):
        with tempfile.TemporaryDirectory() as temp:
            ns, items = self.fixture(temp)
            command = ns['child_items']['target'][0]
            command.turn_id = 'structure-turn'
            ns['child_items']['structure'].append(command)
            ns['child_items']['target'] = []
            with self.assertRaisesRegex(ValueError, 'different subagents'):
                validate_multi_agent(ns, items)

    def test_correct_files_do_not_replace_execution_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            ns, items = self.fixture(temp)
            ns['child_items']['target'] = []
            with self.assertRaisesRegex(ValueError, 'Missing successful'):
                validate_multi_agent(ns, items)

    def test_failed_worker_turn_cannot_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            ns, items = self.fixture(temp)
            ns['child_turns']['target'][0].status = 'failed'
            with self.assertRaisesRegex(ValueError, 'Missing successful'):
                validate_multi_agent(ns, items)

    def test_wrong_target_result_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            ns, items = self.fixture(temp)
            p = Path(temp) / 'target_assessment.json'
            value = json.loads(p.read_text()); value['shortfall'] = 0
            p.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, 'Target assessment differs'):
                validate_multi_agent(ns, items)

    def test_mentions_of_worker_or_root_python_are_not_execution(self):
        for role in ['worker', 'root']:
            with self.subTest(role=role), tempfile.TemporaryDirectory() as temp:
                ns, items = self.fixture(temp)
                command = ns['child_items']['structure'][0] if role == 'worker' else items[0]
                command.command = "echo '" + command.command + "'"
                with self.assertRaisesRegex(ValueError, 'Missing successful|integration command'):
                    validate_multi_agent(ns, items)

    def test_saved_role_artifact_and_input_evidence_must_match(self):
        mutations = [
            lambda ns: ns['role_executions']['structure.py'].update(subagent_id='target'),
            lambda ns: ns['downloaded_artifacts'][0].update(turn_id='foreign'),
            lambda ns: ns['downloaded_artifacts'][0].update(id='foreign'),
            lambda ns: ns.update(csv_bytes=b'foreign input'),
            lambda ns: ns.update(report_downloaded=False),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as temp:
                ns, items = self.fixture(temp)
                mutate(ns)
                with self.assertRaises(ValueError):
                    validate_multi_agent(ns, items)

    def test_attainment_validation_uses_selected_target_instead_of_fixed_85_percent(self):
        with tempfile.TemporaryDirectory() as temp:
            ns, items = self.fixture(temp)
            root = Path(temp)/'project'
            (root/'data').mkdir(parents=True)
            (root/'data/sales.csv').write_bytes((ROOT/'data/sales.csv').read_bytes())
            targets = {'2026-01': {'target_revenue': 200000, 'currency': 'KRW'}}
            (root/'data/sales_targets.json').write_text(json.dumps(targets))
            ns['settings'] = Obj(root=root)
            ns['targets_bytes'] = (root/'data/sales_targets.json').read_bytes()
            assessment_path = Path(temp)/'target_assessment.json'
            assessment = json.loads(assessment_path.read_text())
            assessment.update(target_revenue=200000, attainment_rate=0.6375, shortfall=72500)
            assessment_path.write_text(json.dumps(assessment))
            report_path = Path(temp)/'report.md'
            report = report_path.read_text().replace('150000', '200000').replace('22500', '72500')
            # Keep product C's original revenue while changing the target shortfall.
            report = report.replace('C 72500', 'C 22500')
            report_path.write_text(report.replace('85.00%', '63.75%'))
            checks, _ = validate_multi_agent(ns, items)
            self.assertEqual(checks['target']['attainment_rate'], 0.6375)
            report_path.write_text(report)
            with self.assertRaisesRegex(ValueError, 'Target results'):
                validate_multi_agent(ns, items)

    def test_colab_contains_targets_and_keeps_chapter_15_runnable(self):
        from build_colab import render
        body = json.loads(render()[ROOT / '_build/colab/chapters/15_multi_agent.ipynb'])
        self.assertIn('data/sales_targets.json', body['metadata']['tutorial']['assets'])
        marker = next(''.join(c['source']) for c in body['cells']
                      if ''.join(c['source']).startswith('<!-- colab-link -->'))
        self.assertNotIn('읽기용', marker)

    def test_task_requests_calculation_without_supplying_expected_answers(self):
        import ast
        from notebook_code import tree
        assignment = next(n for n in ast.walk(tree(15))
                    if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == 'TASK' for t in n.targets))
        namespace = {'PERIOD': '2026-01'}
        exec(compile(ast.Module(body=[assignment], type_ignores=[]), '<task>', 'exec'), namespace)
        task = namespace['TASK']
        for answer in ['85%', '0.85', '127500', '127,500', '22500', '22,500']:
            self.assertNotIn(answer, task)
        self.assertIn('attainment_rate * 100', task)

    def test_lesson_shows_native_delegation_and_history_calls(self):
        from notebook_code import tree
        import ast
        source = ast.unparse(tree(15))
        for text in ['client.beta.agents.sessions.create', "'multi_agent': {'enabled': True",
                     'client.beta.agents.sessions.subagents.items.list',
                     'client.beta.agents.sessions.subagents.turns.list',
                     'client.beta.agents.sessions.artifacts.with_streaming_response.content', 'finally:']:
            self.assertIn(text, source)
        self.assertNotIn('validate_multi_agent', source)
        self.assertNotIn('verify_metrics', source)


if __name__ == '__main__':
    unittest.main()
