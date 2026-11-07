"""Run the real six notebook steps against fake API/Docker, not a live executor."""
from contextlib import ExitStack, contextmanager, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import nbformat
from tutorial_helpers.common import cleanup_on_error, new_session_metadata, check_event, safe_error
from tutorial_helpers.deployment import DockerLab, inspect_executor
from tutorial_helpers.validation import analyze_csv, render_markdown, validate_lesson, save_validation

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from notebook_validation import instrument_notebook


class Stream:
    def __init__(self, events, calls, label, result=None):
        self.events, self.calls, self.label, self.result = events, calls, label, result

    def __enter__(self):
        self.calls.append(self.label + '.subscribe')
        return self

    def __exit__(self, *args):
        return False

    def __iter__(self):
        yield from self.events

    def get_final_result(self):
        return self.result


class Interruption(BaseException):
    pass


@contextmanager
def execution(*, instrumented=True, connection='connected', close_error=None):
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        (root / 'data').mkdir()
        csv_text = (ROOT / 'data/sales.csv').read_text()
        (root / 'data/sales.csv').write_text(csv_text)
        data = analyze_csv(csv_text)
        evidence = dict(distribution='acme-sales', version='0.1.0',
                        module_file='/opt/venv/lib/python3.12/site-packages/acme_sales/__init__.py',
                        input_sha256=hashlib.sha256(csv_text.encode()).hexdigest())
        session = SimpleNamespace(id='session-fixture', environment=SimpleNamespace(
            id='environment-fixture', remote_url='https://fixture.invalid/private-connection'))
        turn = SimpleNamespace(id='turn-fixture', status='completed', subagent_id=None, usage=None)
        result = SimpleNamespace(session_id=session.id, turn_id=turn.id, turn=turn, output_text=json.dumps(data))
        calls, clock = [], SimpleNamespace(now=0)
        client, provider = Mock(), Mock()
        api = client.beta.agents.sessions
        api.create.side_effect = lambda **kw: calls.append('session.create') or session
        events = [] if connection == 'missing' else [SimpleNamespace(
            type='agent.session.environment.connected', environment=SimpleNamespace(
                id='wrong-environment' if connection == 'wrong' else session.environment.id))]
        api.events.stream.side_effect = lambda *a, **kw: Stream(events, calls, 'connection')
        task_events = [SimpleNamespace(type='agent.session.turn.in_progress',
                                      turn=SimpleNamespace(id=turn.id, status='in_progress', subagent_id=None)),
                       SimpleNamespace(type='agent.session.turn.completed', turn=turn)]
        api.stream.side_effect = lambda *a, **kw: calls.append('input.submit') or SimpleNamespace(
            with_result_collection=lambda: Stream(task_events, calls, 'task', result))
        api.turns.retrieve.return_value = turn
        command = SimpleNamespace(type='command_execution', turn_id=turn.id, status='completed', exit_code=0,
                                  id='corporate-command', command='/opt/venv/bin/python /opt/capabilities/skills/corporate-csv/scripts/run_report.py --input /workspace/sales.csv --output-dir /workspace/outputs')
        api.items.list.side_effect = lambda *a, **kw: iter([command])
        provider.output_dir = root / 'docker-state'
        provider.start.side_effect = lambda *a: calls.append('executor.start')
        provider.record.side_effect = lambda **kw: calls.append('provider.record')
        provider.assert_owned = Mock(return_value={
            'Id':'container-fixture','Name':'/fixture','Config':{
                'Env':['ENVIRONMENT_ID=environment-fixture','CODEX_API_KEY=executor-fixture-key'],
                'Image':'fixture-image','Hostname':'fixture-host'}})
        def copy_out(worker, source, to):
            calls.append('copy:' + Path(source).name)
            value = render_markdown(data) if source.endswith('.md') else json.dumps(
                evidence if source.endswith('package_evidence.json') else data)
            Path(to).write_text(value)
        provider.copy_out.side_effect = copy_out
        provider.collect_report.side_effect = lambda worker, **kw: DockerLab.collect_report(provider, worker, **kw)
        secret = root / 'temporary-key'
        @contextmanager
        def prepare(**kwargs):
            calls.append('docker.prepare')
            secret.write_text(kwargs['key'])
            try:
                yield provider, 'container-fixture'
            finally:
                calls.append('docker.close')
                secret.unlink(missing_ok=True)
                if close_error:
                    raise close_error
        def cleanup(client, sessions, agents, attempts):
            calls.append('api.cleanup')
            for owned in sessions.values():
                owned.update(deleted=True, verified_absent=True)
            return []
        clean = Mock(side_effect=cleanup)
        env = dict(settings=SimpleNamespace(root=root, model='fixture', api_key='application-fixture-key'),
                   root=root, CHAPTER='12_self_hosted', csv_text=csv_text, csv_bytes=csv_text.encode(),
                   image_input_sha256=hashlib.sha256(csv_text.encode()).hexdigest(), hashlib=hashlib, client=client,
                   uuid4=uuid4, json=json, sys=sys, ExitStack=ExitStack,
                   time=SimpleNamespace(monotonic=lambda: clock.now),
                   BASE_INSTRUCTIONS='fixture', task='Run the corporate-csv Skill', key='executor-fixture-key',
                   cleanup_resources=clean, cleanup_on_error=cleanup_on_error,
                   new_session_metadata=new_session_metadata, check_event=check_event, safe_error=safe_error,
                   prepare_executor=Mock(side_effect=prepare), inspect_executor=inspect_executor)
        nb = nbformat.read(ROOT / 'notebooks/chapters/12_self_hosted.ipynb', as_version=4)
        if instrumented:
            instrument_notebook(nb, '12_self_hosted', live=True, docker=True)
        stages = {i: next(c.source for c in nb.cells if f'self_hosted_step_{i}' in c.metadata.get('tags', []))
                  for i in range(1, 7)}
        with patch('tutorial_helpers.common.cleanup_resources', clean), redirect_stdout(io.StringIO()) as output:
            if instrumented:
                exec(nb.cells[0].source, env)
                def validate(*args):
                    calls.append('validate')
                    return validate_lesson(*args)
                def save(*args, **kwargs):
                    calls.append('receipt')
                    return save_validation(*args, **kwargs)
                env.update(_validate_lesson=validate, _save_validation=save)
            exec(next(c.source for c in nb.cells if c.id=='12-run-state'), env)
            try:
                yield env, stages, clean, calls, clock, output, provider, secret
            finally:
                env['resources'].close() if 'resources' in env else None
                env.pop('_validation_error', None)


class SelfHostedStepTests(unittest.TestCase):
    def test_subscribe_start_connect_submit_copy_once_validate_cleanup_order(self):
        with execution() as (env, stages, clean, calls, clock, output, provider, secret):
            for step in range(1, 6):
                clock.now += 2000  # Exclude between-cell study time from phase budgets.
                exec(stages[step], env)
                clean.assert_not_called()
                if step <= 3:
                    env['client'].beta.agents.sessions.stream.assert_not_called()
                if step == 2:
                    provider.start.assert_not_called()
                    self.assertTrue(secret.exists())
            api = env['client'].beta.agents.sessions
            api.create.assert_called_once()
            self.assertEqual(api.create.call_args.kwargs['environment']['type'], 'self_hosted')
            forwarded = env['prepare_executor'].call_args.kwargs
            self.assertEqual(forwarded['environment_id'], env['session'].environment.id)
            self.assertEqual(forwarded['remote_url'], env['session'].environment.remote_url)
            api.stream.assert_called_once()
            self.assertLess(calls.index('connection.subscribe'), calls.index('executor.start'))
            self.assertLess(calls.index('executor.start'), calls.index('input.submit'))
            self.assertEqual(provider.copy_out.call_count, 3)
            self.assertEqual(env['downloads'], env['output_dir'] / 'downloads')
            self.assertTrue(env['report_downloaded'])
            self.assertEqual(env['execution_context']['container_environment_id'], env['session'].environment.id)
            exec(stages[6], env)
            self.assertEqual(env['_validation_summary']['status'], 'passed')
            self.assertLess(calls.index('validate'), calls.index('provider.record'))
            self.assertLess(calls.index('provider.record'), calls.index('api.cleanup'))
            self.assertLess(calls.index('api.cleanup'), calls.index('docker.close'))
            self.assertLess(calls.index('docker.close'), calls.index('receipt'))
            self.assertFalse(secret.exists())
            self.assertEqual(env['input_submission_attempts'], 1)
            for private in ['executor-fixture-key', 'application-fixture-key', 'private-connection', 'fixture-host']:
                self.assertNotIn(private, output.getvalue())

    def test_missing_or_wrong_environment_connection_never_submits_input(self):
        for connection in ['missing', 'wrong']:
            with self.subTest(connection=connection), execution(connection=connection) as (env, stages, clean, calls, clock, output, provider, secret):
                for step in [1, 2]:
                    exec(stages[step], env)
                with self.assertRaises(RuntimeError):
                    exec(stages[3], env)
                env['client'].beta.agents.sessions.stream.assert_not_called()
                clean.assert_called_once()
                self.assertFalse(secret.exists())
                self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_stage_errors_and_interruption_always_attempt_ordered_cleanup(self):
        for failed in range(1, 6):
            with self.subTest(step=failed), execution() as (env, stages, clean, calls, clock, output, provider, secret):
                for step in range(1, failed):
                    exec(stages[step], env)
                if failed == 1:
                    env['client'].beta.agents.sessions.create.side_effect = RuntimeError('fixture')
                elif failed == 2:
                    env['prepare_executor'].side_effect = RuntimeError('fixture')
                elif failed == 3:
                    provider.start.side_effect = TimeoutError('fixture')
                elif failed == 4:
                    env['client'].beta.agents.sessions.stream.side_effect = Interruption()
                else:
                    provider.copy_out.side_effect = OSError('fixture')
                with self.assertRaises([RuntimeError, RuntimeError, TimeoutError, Interruption, OSError][failed - 1]):
                    exec(stages[failed], env)
                clean.assert_called_once()
                self.assertFalse(secret.exists())
                self.assertEqual(env['_validation_summary']['status'], 'failed')
                self.assertLess(calls.index('api.cleanup'), calls.index('receipt'))
                if failed >= 3:
                    self.assertLess(calls.index('api.cleanup'), calls.index('docker.close'))

    def test_failed_turn_is_not_copied_as_success(self):
        with execution() as (env, stages, clean, calls, clock, output, provider, secret):
            for step in range(1, 5):
                exec(stages[step], env)
            env['result'].turn.status = 'failed'
            with self.assertRaisesRegex(RuntimeError, 'completion was not confirmed'):
                exec(stages[5], env)
            provider.copy_out.assert_not_called()
            self.assertFalse(env['report_downloaded'])
            self.assertFalse(secret.exists())

    def test_repeated_input_is_blocked_before_second_submission(self):
        with execution() as (env, stages, clean, calls, clock, output, provider, secret):
            for step in range(1, 5):
                exec(stages[step], env)
            with self.assertRaisesRegex(RuntimeError, 'only once'):
                exec(stages[4], env)
            env['client'].beta.agents.sessions.stream.assert_called_once()
            self.assertFalse(secret.exists())

    def test_partial_manual_run_can_cleanup_without_result_or_executor(self):
        for last in [1, 2, 3]:
            with self.subTest(last=last), execution(instrumented=False) as (env, stages, clean, calls, clock, output, provider, secret):
                for step in range(1, last + 1):
                    exec(stages[step], env)
                exec(stages[6], env)
                clean.assert_called_once()
                self.assertFalse(secret.exists())
                self.assertIn('not_completed', output.getvalue())

    def test_validation_error_survives_docker_shutdown_failure(self):
        with execution(close_error=OSError('shutdown fixture')) as (env, stages, clean, calls, clock, output, provider, secret):
            for step in range(1, 6):
                exec(stages[step], env)
            env['_validate_lesson'] = Mock(side_effect=ValueError('original validation error'))
            with self.assertRaisesRegex(ValueError, 'original validation error') as raised:
                exec(stages[6], env)
            self.assertIn('Resource cleanup incomplete', raised.exception.__notes__[0])
            self.assertFalse(secret.exists())
            self.assertEqual(env['_validation_summary']['failure']['exception'], 'ValueError')
            self.assertEqual(env['_validation_summary']['cleanup_errors'][0]['exception'], 'OSError')

    def test_session_cleanup_failure_still_closes_docker_and_secret(self):
        with execution() as (env, stages, clean, calls, clock, output, provider, secret):
            for step in range(1, 6):
                exec(stages[step], env)
            clean.side_effect = OSError('api cleanup fixture')
            with self.assertRaisesRegex(RuntimeError, 'cleanup incomplete'):
                exec(stages[6], env)
            self.assertFalse(secret.exists())
            self.assertIn('docker.close', calls)
            self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_collect_report_default_directory_remains_compatible(self):
        with tempfile.TemporaryDirectory() as folder:
            provider = Mock(output_dir=Path(folder))
            def copy(worker, source, to):
                Path(to).write_text('# report' if source.endswith('.md') else '{}')
            provider.copy_out.side_effect = copy
            self.assertEqual(DockerLab.collect_report(provider, 'fixture-worker'), ({}, {}))
            self.assertEqual(provider.copy_out.call_count, 3)
            self.assertTrue((Path(folder) / 'downloaded/report.md').exists())

    def test_failed_package_installation_prevents_exec_server_start(self):
        with patch('subprocess.run', side_effect=subprocess.CalledProcessError(1, ['pip'])) as install, \
                patch('os.execvpe') as start, self.assertRaises(subprocess.CalledProcessError):
            runpy.run_path(str(ROOT / 'deploy/install_and_exec.py'), run_name='__main__')
        self.assertTrue(install.call_args.kwargs['check'])
        start.assert_not_called()


if __name__ == '__main__':
    unittest.main()
