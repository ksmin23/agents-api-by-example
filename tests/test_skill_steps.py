"""Exercise chapter 9 cells and real SDK turn/path selection against fake file transport."""
import contextlib
import io
import json
import base64
import hashlib
import subprocess
import zipfile
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import nbformat
from openai.lib.beta.agents._artifacts import AgentResultArtifacts
from tutorial_helpers.common import cleanup_on_error, check_event, new_session_metadata, safe_error
from tutorial_helpers.validation import analyze_csv, render_markdown, validate_lesson, save_validation, skill_script_commands
from tutorial_helpers.extensions import read_skill_metadata

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from notebook_validation import instrument_notebook


class SimulatedInterruption(BaseException):
    pass


@contextlib.contextmanager
def lesson(instrumented=False):
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        (root / 'data').mkdir()
        csv_text = (ROOT / 'data/sales.csv').read_text()
        (root / 'data/sales.csv').write_text(csv_text)
        expected = analyze_csv(csv_text)
        calls = []
        clock = SimpleNamespace(now=0)
        turn = SimpleNamespace(id='turn-fixture', status='completed', subagent_id=None, usage=None)
        result = SimpleNamespace(session_id='session-fixture', turn_id=turn.id, turn=turn,
                                 output_text=json.dumps(expected))
        files = {'summary': json.dumps(expected).encode(), 'report': render_markdown(expected).encode(),
                 'evidence': json.dumps(dict(skill_name='csv-report', script_revision='csv-report-v1',
                     input_sha256=hashlib.sha256(csv_text.encode()).hexdigest())).encode()}
        artifacts = [SimpleNamespace(id=name, session_id=result.session_id, turn_id=turn.id,
                     path='/workspace/outputs/' + filename, size_bytes=len(files[name]))
                     for name, filename in [('summary', 'summary.json'), ('report', 'report.md'), ('evidence', 'skill_evidence.json')]]
        old = SimpleNamespace(id='old-summary', session_id=result.session_id, turn_id='older-turn',
                              path='/workspace/outputs/summary.json', size_bytes=1)
        artifacts.insert(0, old)
        events = [SimpleNamespace(type='agent.session.created', session=SimpleNamespace(
            id=result.session_id, environment=SimpleNamespace(id='environment-fixture'))),
            SimpleNamespace(type='agent.session.turn.output_text.delta', delta=result.output_text),
            SimpleNamespace(type='agent.session.turn.completed', turn=turn)]
        stream = Mock()
        stream.with_result_collection.return_value = stream
        stream.__enter__ = Mock(return_value=stream)
        stream.__exit__ = Mock(return_value=False)
        stream.__iter__ = Mock(side_effect=lambda: iter(events))
        stream.get_final_result.return_value = result
        client = Mock()
        client.beta.agents.sessions.create.return_value = stream
        client.beta.agents.sessions.turns.retrieve.return_value = turn
        client.beta.agents.sessions.items.list.side_effect = lambda *a, **kw: calls.append('history') or [
            SimpleNamespace(type='command_execution', turn_id=turn.id, status='completed', exit_code=0,
                            id='command-fixture', cwd='/workspace', output='done',
                            command='python /runtime/csv-report/scripts/analyze_sales.py --input /workspace/sales.csv --output-dir /workspace/outputs')]
        installed = SimpleNamespace(id='environment-fixture', skills=[SimpleNamespace(
            name='csv-report', description='fixture', type='inline')])
        client.beta.agents.environments.retrieve.return_value = installed
        client.beta.agents.sessions.retrieve.return_value = SimpleNamespace(environment=SimpleNamespace(id=installed.id))
        class Pages:
            def __iter__(self):
                for index, page in enumerate([artifacts[:1], artifacts[1:]]):
                    calls.append(f'artifacts.page.{index+1}')
                    yield from page
        resource = client.beta.agents.sessions.artifacts
        resource.list.side_effect = lambda *a, **kw: Pages()
        # Real SDK selection rejects missing/duplicate paths and ignores the older Turn.
        resource.for_result.side_effect = lambda result: AgentResultArtifacts(resource, result)
        transfer_error = {}
        @contextlib.contextmanager
        def content(artifact_id, **kwargs):
            calls.append('download:' + artifact_id)
            def write(to):
                data = files[artifact_id]
                Path(to).write_bytes(data[:5] if artifact_id in transfer_error else data)
                if artifact_id in transfer_error:
                    raise transfer_error[artifact_id]
            yield SimpleNamespace(stream_to_file=write)
        resource.with_streaming_response.content.side_effect = content
        def cleanup(client, sessions, agents, attempts):
            calls.append('cleanup')
            for value in sessions.values():
                value.update(deleted=True, verified_absent=True)
            client.close()
            return []
        clean = Mock(side_effect=cleanup)
        env = dict(settings=SimpleNamespace(root=root, model='fixture', api_key=None), CHAPTER='09_skills',
                   uuid4=uuid4, json=json, sys=sys, client=client, task='fixture', BASE_INSTRUCTIONS='fixture',
                   environment={}, skill={'name': 'csv-report'}, csv_bytes=csv_text.encode(), csv_text=csv_text, time=SimpleNamespace(monotonic=lambda: clock.now),
                   cleanup_on_error=cleanup_on_error, cleanup_resources=clean,
                   new_session_metadata=new_session_metadata, check_event=check_event, safe_error=safe_error)
        nb = nbformat.read(ROOT / 'notebooks/chapters/09_skills.ipynb', as_version=4)
        if instrumented:
            instrument_notebook(nb, '09_skills', live=True)
        steps = {i: next(c.source for c in nb.cells if f'skill_step_{i}' in c.metadata.get('tags', [])) for i in range(1, 7)}
        with patch('tutorial_helpers.common.cleanup_resources', clean), contextlib.redirect_stdout(io.StringIO()) as output, \
                patch('IPython.display.display', side_effect=lambda value: calls.append('display')):
            if instrumented:
                exec(nb.cells[0].source, env)
                def validate(*a):
                    calls.append('validate')
                    return validate_lesson(*a)
                env.update(_validate_lesson=validate, _save_validation=save_validation)
            exec(next(c.source for c in nb.cells if c.id == 'f1e04bb949ab'), env)
            try:
                yield env, steps, clean, calls, clock, output, stream, artifacts, files, transfer_error
            finally:
                env.pop('_validation_error', None)
                env.clear()


class SkillStepTests(unittest.TestCase):
    def test_six_stages_and_injected_validation_before_cleanup(self):
        for instrumented in [False, True]:
            with self.subTest(instrumented=instrumented), lesson(instrumented) as (env, steps, clean, calls, clock, output, stream, artifacts, files, errors):
                for step in range(1, 6):
                    exec(steps[step], env)
                clean.assert_not_called()
                self.assertEqual(env['skill_evidence']['skill_name'], 'csv-report')
                self.assertEqual(env['installed_environment'].id, 'environment-fixture')
                self.assertNotIn('old-summary', output.getvalue())
                self.assertIn('command-fixture', output.getvalue())
                self.assertTrue(env['downloads_complete'])
                self.assertEqual((env['downloads'] / 'skill_evidence.json').read_bytes(), files['evidence'])
                exec(steps[6], env)
                clean.assert_called_once()
                self.assertTrue(env['sessions']['session-fixture']['verified_absent'])
                if instrumented:
                    self.assertLess(calls.index('validate'), calls.index('cleanup'))
                    self.assertEqual(env['_validation_summary']['status'], 'passed')

    def test_registration_recovery_and_wrong_environment_or_skill_cleanup(self):
        for failure in ['none', 'environment', 'skill']:
            with self.subTest(failure=failure), lesson() as (env, steps, clean, calls, clock, output, stream, artifacts, files, errors):
                exec(steps[1], env)
                env['sessions']['session-fixture']['environment_id'] = None
                installed = env['client'].beta.agents.environments.retrieve.return_value
                if failure == 'environment':
                    installed.id = 'different'
                elif failure == 'skill':
                    installed.skills[0].type = 'skill_reference'
                if failure == 'none':
                    exec(steps[2], env)
                    env['client'].beta.agents.sessions.retrieve.assert_called_once()
                    clean.assert_not_called()
                else:
                    with self.assertRaises(RuntimeError):
                        exec(steps[2], env)
                    clean.assert_called_once()

    def test_download_interruption_cleans_up_and_blocks_local_read(self):
        with lesson() as (env, steps, clean, calls, clock, output, stream, artifacts, files, errors):
            exec(steps[1], env)
            errors['evidence'] = SimulatedInterruption()
            with self.assertRaises(SimulatedInterruption):
                exec(steps[4], env)
            clean.assert_called_once()
            self.assertFalse(env['downloads_complete'])
            with self.assertRaisesRegex(RuntimeError, 'Complete all three'):
                exec(steps[5], env)

    def test_incomplete_turn_cleans_up_without_download(self):
        with lesson() as (env, steps, clean, calls, clock, output, stream, artifacts, files, errors):
            stream.get_final_result.return_value.turn.status = 'failed'
            with self.assertRaisesRegex(RuntimeError, 'completion'):
                exec(steps[1], env)
            clean.assert_called_once()
            self.assertFalse(any(c.startswith('download:') for c in calls))

    def test_validator_rejects_wrong_command_hash_name_and_environment(self):
        for mode in ['hash', 'skill_name', 'environment', 'command']:
            with self.subTest(mode=mode), lesson(True) as (env, steps, clean, calls, clock, output, stream, artifacts, files, errors):
                for step in range(1, 6):
                    exec(steps[step], env)
                if mode in {'hash', 'skill_name'}:
                    path = env['downloads'] / 'skill_evidence.json'
                    evidence = json.loads(path.read_text())
                    evidence['input_sha256' if mode == 'hash' else 'skill_name'] = 'wrong'
                    path.write_text(json.dumps(evidence))
                elif mode == 'environment':
                    env['installed_environment'].id = 'different'
                else:
                    env['client'].beta.agents.sessions.items.list.side_effect = lambda *a, **k: [SimpleNamespace(
                        id='mention', type='command_execution', turn_id='turn-fixture', status='completed',
                        exit_code=0, command='echo analyze_sales.py')]
                with self.assertRaises(ValueError):
                    exec(steps[6], env)
                clean.assert_called_once()
                self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_command_matching_requires_root_success_and_explicit_cli(self):
        good = 'python /runtime/skill/scripts/analyze_sales.py --input /workspace/sales.csv --output-dir /workspace/outputs'
        for command in [good, good + ' && cat /workspace/outputs/summary.json', 'cd /runtime/skill && python3 scripts/analyze_sales.py --output-dir /workspace/outputs --input /workspace/sales.csv', good.replace('/runtime/skill', '/runtime/skill with space').replace('/runtime/skill with space/scripts/analyze_sales.py', "'/runtime/skill with space/scripts/analyze_sales.py'")]:
            item = SimpleNamespace(id='ok', type='command_execution', turn_id='root', status='completed', exit_code=0, command=command)
            self.assertEqual(skill_script_commands([item], 'root'), [item])
        for change in [dict(turn_id='old'), dict(status='in_progress'), dict(exit_code=None), dict(exit_code=1),
                       dict(command='echo ' + good), dict(command=good + ' || true'),
                       dict(command=good + '; echo ignored'), dict(command='cat /runtime/skill/scripts/analyze_sales.py'),
                       dict(command=good.replace('/workspace/sales.csv', '/workspace/other.csv')),
                       dict(command=good.replace('/workspace/outputs', '/tmp/outputs')),
                       dict(command=good.replace('scripts/analyze_sales.py', 'notscripts/analyze_sales.py'))]:
            item = SimpleNamespace(**(dict(type='command_execution', turn_id='root', status='completed', exit_code=0, command=good) | change))
            self.assertEqual(skill_script_commands([item], 'root'), [])

    def test_notebook_inline_zip_is_runnable_with_exact_input_bytes(self):
        notebook = nbformat.read(ROOT / 'notebooks/chapters/09_skills.ipynb', as_version=4)
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            root = Path(folder)
            (root / 'data').mkdir()
            # Deliberate CRLF bytes: the evidence must match bytes, not a text-mode rewrite.
            raw_csv = (ROOT / 'data/sales.csv').read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
            (root / 'data/sales.csv').write_bytes(raw_csv)
            import shutil
            shutil.copytree(ROOT / 'skills', root / 'skills')
            env = dict(settings=SimpleNamespace(root=root))
            for identifier in ['09-input-preview', 'extension-09-06', '09-skill-environment', '386e71b7']:
                exec(next(c.source for c in notebook.cells if c.id == identifier), env)
            skill = env['environment']['skills'][0]
            self.assertEqual(base64.b64decode(env['environment']['files'][0]['data']), raw_csv)
            self.assertIn(env['METRICS_CONTRACT'], env['task'])
            archive = base64.b64decode(skill['source']['data'])
            extracted = root / 'extracted'
            with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
                self.assertEqual(set(bundle.namelist()), {'csv-report/SKILL.md', 'csv-report/references/report-schema.md', 'csv-report/scripts/analyze_sales.py'})
                bundle.extractall(extracted)
            out = root / 'script-output'
            subprocess.run([sys.executable, str(extracted / 'csv-report/scripts/analyze_sales.py'),
                            '--input', str(root / 'data/sales.csv'), '--output-dir', str(out)], check=True, capture_output=True)
            self.assertEqual(json.loads((out / 'summary.json').read_text()), analyze_csv(raw_csv.decode()))
            evidence = json.loads((out / 'skill_evidence.json').read_text())
            self.assertEqual(evidence['input_sha256'], hashlib.sha256(raw_csv).hexdigest())
            self.assertTrue((out / 'report.md').read_text().startswith('# 매출 분석 보고서'))

    def test_limited_metadata_reader_rejects_unsupported_or_missing_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'SKILL.md'
            for header in ['', 'name: csv-report', '---\nname: csv-report\n---',
                           '---\nname: csv-report\nname: duplicate\ndescription: one line\n---',
                           '---\nname: csv-report\ndescription: >\n  multiline\n---',
                           '---\nname: csv-report\ndescription: "quoted"\n---']:
                path.write_text(header)
                with self.assertRaises(ValueError):
                    read_skill_metadata(folder)
            path.write_text('---\nname: csv-report\ndescription: Analyze CSV: sales data.\n---\nBody')
            self.assertEqual(read_skill_metadata(folder), dict(name='csv-report', description='Analyze CSV: sales data.'))


if __name__ == '__main__':
    unittest.main()
