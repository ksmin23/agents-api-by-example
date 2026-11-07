"""Actual chapter 6 cells with fake transport and a simulated pandas setup runtime."""
import contextlib
import csv
import io
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import nbformat
from openai.lib.beta.agents._artifacts import AgentResultArtifacts
from tutorial_helpers.common import cleanup_on_error, check_event, new_session_metadata, safe_error
from tutorial_helpers.validation import analyze_csv, render_markdown, validate_lesson, save_validation

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from notebook_validation import instrument_notebook


class SimulatedInterruption(BaseException):
    pass


def run_setup(source, workspace, version):
    """Execute the supplied script with local paths and a fake installed pandas module."""
    pandas = ModuleType('pandas')
    pandas.__version__ = version
    class Frame:
        def __init__(self, columns, rows):
            self.columns, self.rows = columns, rows
        def __len__(self):
            return len(self.rows)
    def read_csv(path):
        with Path(path).open(encoding='utf-8') as file:
            reader = csv.DictReader(file)
            return Frame(reader.fieldnames, list(reader))
    pandas.read_csv = read_csv
    with patch.dict(sys.modules, {'pandas': pandas}):
        exec(compile(source.replace('/workspace', str(workspace)), 'check_setup.py', 'exec'), {})


@contextlib.contextmanager
def lesson(instrumented=False):
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        (root / 'data').mkdir()
        csv_text = (ROOT / 'data/sales.csv').read_text()
        (root / 'data/sales.csv').write_text(csv_text)
        expected = analyze_csv(csv_text)
        info = dict(pandas_version='2.3.3', python_version='3.12-fixture', input_rows=6)
        calls, transfer_errors = [], {}
        clock = SimpleNamespace(now=0)
        turn = SimpleNamespace(id='turn-fixture', status='completed', subagent_id=None, usage=None)
        result = SimpleNamespace(session_id='session-fixture', turn_id=turn.id, turn=turn,
                                 output_text=json.dumps(expected))
        files = {'summary.json': json.dumps(expected).encode(), 'report.md': render_markdown(expected).encode(),
                 'environment.json': json.dumps(info).encode()}
        artifacts = [SimpleNamespace(id=name, session_id=result.session_id, turn_id=turn.id,
                     path='/workspace/outputs/' + name, size_bytes=len(data)) for name, data in files.items()]
        old = SimpleNamespace(id='older-environment', session_id=result.session_id, turn_id='older-turn',
                              path='/workspace/outputs/environment.json', size_bytes=1)
        artifacts.insert(0, old)
        events = [SimpleNamespace(type='agent.session.created', session=SimpleNamespace(
            id=result.session_id, environment=SimpleNamespace(id='environment-fixture'))),
            SimpleNamespace(type='agent.session.environment.pending', environment=SimpleNamespace(id='environment-fixture')),
            SimpleNamespace(type='agent.session.environment.ready', environment=SimpleNamespace(id='environment-fixture')),
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
                            command='python analyze.py')]
        class Pages:
            def __iter__(self):
                for index, page in enumerate([artifacts[:1], artifacts[1:]]):
                    calls.append(f'artifacts.page.{index+1}')
                    yield from page
        resource = client.beta.agents.sessions.artifacts
        resource.list.side_effect = lambda *a, **kw: Pages()
        resource.for_result.side_effect = lambda result: AgentResultArtifacts(resource, result)
        @contextlib.contextmanager
        def content(artifact_id, **kwargs):
            calls.append('download:' + artifact_id)
            def write(to):
                data = files[artifact_id]
                Path(to).write_bytes(data[:5] if artifact_id in transfer_errors else data)
                if artifact_id in transfer_errors:
                    raise transfer_errors[artifact_id]
            yield SimpleNamespace(stream_to_file=write)
        resource.with_streaming_response.content.side_effect = content
        def cleanup(client, sessions, agents, attempts):
            calls.append('cleanup')
            for value in sessions.values():
                value.update(deleted=True, verified_absent=True)
            client.close()
            return []
        clean = Mock(side_effect=cleanup)
        env = dict(settings=SimpleNamespace(root=root, model='fixture', api_key=None), CHAPTER='06_environment',
                   client=client, uuid4=uuid4, json=json, sys=sys,
                   time=SimpleNamespace(monotonic=lambda: clock.now),
                   cleanup_on_error=cleanup_on_error, cleanup_resources=clean,
                   new_session_metadata=new_session_metadata, check_event=check_event, safe_error=safe_error)
        nb = nbformat.read(ROOT / 'notebooks/chapters/06_environment.ipynb', as_version=4)
        if instrumented:
            instrument_notebook(nb, '06_environment', live=True)
        steps = {i: next(c.source for c in nb.cells if f'environment_step_{i}' in c.metadata.get('tags', [])) for i in range(1, 6)}
        with patch('tutorial_helpers.common.cleanup_resources', clean), contextlib.redirect_stdout(io.StringIO()) as output, \
                patch('IPython.display.display', side_effect=lambda value: calls.append('display')):
            if instrumented:
                exec(nb.cells[0].source, env)
                def validate(*args):
                    calls.append('validate')
                    return validate_lesson(*args)
                env.update(_validate_lesson=validate, _save_validation=save_validation)
            for identifier in ['06-input-preview', '06-setup-source', 'intro-06-06', 'ce76291f', 'f1c50d428007']:
                exec(next(c.source for c in nb.cells if c.id == identifier), env)
            try:
                yield env, steps, clean, calls, clock, output, stream, artifacts, files, transfer_errors, events
            finally:
                env.pop('_validation_error', None)
                env.clear()


class EnvironmentStepTests(unittest.TestCase):
    def test_setup_version_and_request_use_one_value_and_fail_unmet_conditions(self):
        with lesson() as (env, steps, clean, calls, *rest):
            nb = nbformat.read(ROOT / 'notebooks/chapters/06_environment.ipynb', as_version=4)
            env['PANDAS_VERSION'] = 'version-fixture'
            exec(next(c.source for c in nb.cells if c.id == '06-setup-source'), env)
            exec(next(c.source for c in nb.cells if c.id == 'intro-06-06'), env)
            self.assertEqual(env['environment']['packages']['python'], ['pandas==version-fixture'])
            source = env['base64'].b64decode(env['environment']['files'][1]['data']).decode()
            self.assertEqual(source, env['setup_source'])
            self.assertEqual(env['base64'].b64decode(env['environment']['files'][0]['data']), env['csv_bytes'])
            workspace = env['settings'].root / 'sandbox'
            workspace.mkdir()
            with self.assertRaises(FileNotFoundError):
                run_setup(source, workspace, 'version-fixture')
            (workspace / 'sales.csv').write_bytes(env['csv_bytes'])
            with self.assertRaisesRegex(RuntimeError, 'pandas version'):
                run_setup(source, workspace, 'wrong-version')
            (workspace / 'sales.csv').write_text('wrong,columns\n1,2\n')
            with self.assertRaisesRegex(ValueError, 'CSV columns'):
                run_setup(source, workspace, 'version-fixture')
            (workspace / 'sales.csv').write_bytes(env['csv_bytes'])
            run_setup(source, workspace, 'version-fixture')
            record = json.loads((workspace / 'setup_info.json').read_text())
            self.assertEqual(record['pandas_version'], 'version-fixture')
            self.assertEqual(record['input_rows'], 6)
            self.assertEqual(set(record), {'pandas_version', 'python_version', 'input_rows'})
            commands = env['environment']['setup_commands']
            self.assertEqual([c['command'] for c in commands],
                             ['mkdir -p /workspace/outputs', 'python /workspace/check_setup.py'])
            env['client'].beta.agents.sessions.create.assert_not_called()

    def test_full_flow_displays_preparation_versions_and_results_before_cleanup(self):
        for instrumented in [False, True]:
            with self.subTest(instrumented=instrumented), lesson(instrumented) as (env, steps, clean, calls, clock, output, stream, artifacts, files, errors, events):
                clock.now = 2000
                exec(steps[1], env)
                self.assertEqual(env['started'], 2000)
                request = env['client'].beta.agents.sessions.create.call_args.kwargs
                self.assertEqual(request['environment'], env['environment'])
                self.assertNotIn(env['csv_text'], request['input'])
                clock.now += 3000
                for step in [2, 3, 4]:
                    exec(steps[step], env)
                self.assertEqual(len(env['current_artifacts']), 3)
                self.assertTrue(env['downloads_complete'])
                self.assertTrue(env['pandas_version_matches'])
                self.assertEqual([c for c in calls if c.startswith('download:')],
                                 ['download:summary.json', 'download:report.md', 'download:environment.json'])
                self.assertIn('artifacts.page.2', calls)
                self.assertIn('agent.session.environment.pending', output.getvalue())
                self.assertIn('agent.session.environment.ready', output.getvalue())
                self.assertIn('requested_pandas_version', output.getvalue())
                clean.assert_not_called()
                exec(steps[5], env)
                clean.assert_called_once()
                self.assertTrue(env['sessions']['session-fixture']['verified_absent'])
                if instrumented:
                    self.assertLess(calls.index('validate'), calls.index('cleanup'))
                    self.assertEqual(env['_validation_summary']['status'], 'passed')

    def test_environment_failure_stops_before_result_and_download_without_error_body(self):
        with lesson(True) as (env, steps, clean, calls, clock, output, stream, artifacts, files, errors, events):
            events[:] = events[:1] + [SimpleNamespace(type='agent.session.environment.failed',
                environment=SimpleNamespace(id='environment-fixture', error='private diagnostic body'))]
            with self.assertRaisesRegex(RuntimeError, 'environment.failed'):
                exec(steps[1], env)
            stream.get_final_result.assert_not_called()
            env['client'].beta.agents.sessions.artifacts.list.assert_not_called()
            self.assertNotIn('private diagnostic body', output.getvalue())
            clean.assert_called_once()
            self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_optional_preparation_events_are_not_required_for_completion(self):
        with lesson() as (env, steps, clean, calls, clock, output, stream, artifacts, files, errors, events):
            events[:] = [e for e in events if not e.type.startswith('agent.session.environment.')]
            for step in range(1, 6):
                exec(steps[step], env)
            self.assertTrue(env['pandas_version_matches'])
            clean.assert_called_once()

    def test_reported_wrong_version_is_rejected_with_cleanup(self):
        with lesson(True) as (env, steps, clean, calls, clock, output, stream, artifacts, files, errors, events):
            files['environment.json'] = json.dumps(dict(pandas_version='wrong', python_version='fixture', input_rows=6)).encode()
            exec(steps[1], env)
            exec(steps[3], env)
            with self.assertRaisesRegex(RuntimeError, 'Reported pandas version'):
                exec(steps[4], env)
            clean.assert_called_once()
            self.assertNotIn('display', calls)
            self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_last_file_transfer_failure_and_retry_do_not_leave_stale_success(self):
        with lesson(True) as (env, steps, clean, calls, clock, output, stream, artifacts, files, errors, events):
            exec(steps[1], env)
            exec(steps[3], env)
            errors['environment.json'] = OSError('last file fixture')
            with self.assertRaises(OSError):
                exec(steps[3], env)
            self.assertFalse(env['downloads_complete'])
            self.assertEqual((env['downloads'] / 'environment.json').stat().st_size, 5)
            env['client'].beta.agents.sessions.create.assert_called_once()
            self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_missing_environment_artifact_cannot_be_replaced_by_an_older_turn(self):
        with lesson(True) as (env, steps, clean, calls, clock, output, stream, artifacts, files, errors, events):
            artifacts[:] = [a for a in artifacts if a.id != 'environment.json']
            exec(steps[1], env)
            with self.assertRaises(ValueError):
                exec(steps[3], env)
            self.assertFalse(env['downloads_complete'])
            self.assertNotIn('download:older-environment', calls)
            clean.assert_called_once()

    def test_row_count_reference_check_stays_in_validator(self):
        with lesson(True) as (env, steps, clean, calls, clock, output, stream, artifacts, files, errors, events):
            files['environment.json'] = json.dumps(dict(pandas_version='2.3.3', python_version='fixture', input_rows=999)).encode()
            for step in [1, 2, 3, 4]:
                exec(steps[step], env)
            with self.assertRaisesRegex(ValueError, 'Setup package evidence'):
                exec(steps[5], env)
            clean.assert_called_once()
            self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_interruption_and_original_parsing_error_attempt_cleanup(self):
        with lesson(True) as (env, steps, clean, calls, clock, output, stream, *rest):
            stream.__iter__.side_effect = SimulatedInterruption('fixture')
            with self.assertRaises(SimulatedInterruption):
                exec(steps[1], env)
            clean.assert_called_once()
        with lesson(True) as (env, steps, clean, calls, *rest):
            exec(steps[1], env)
            exec(steps[3], env)
            (env['downloads'] / 'environment.json').write_text('not json')
            clean.side_effect = RuntimeError('cleanup fixture')
            with self.assertRaises(json.JSONDecodeError) as raised:
                exec(steps[4], env)
            self.assertTrue(raised.exception.__notes__)
            self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_partial_cleanup_and_local_files_remain_readable(self):
        with lesson() as (env, steps, clean, *rest):
            exec(steps[5], env)
            env['client'].beta.agents.sessions.create.assert_not_called()
        with lesson() as (env, steps, clean, calls, *rest):
            exec(steps[1], env)
            exec(steps[3], env)
            exec(steps[5], env)
            before = len(env['client'].mock_calls)
            exec(steps[4], env)
            self.assertEqual(len(env['client'].mock_calls), before)
            self.assertIn('display', calls)


if __name__ == '__main__':
    unittest.main()
