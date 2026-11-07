"""Split telemetry cells with fake API/Collector; OTel uses only an in-memory exporter."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import nbformat
from tutorial_helpers.common import cleanup_on_error, new_session_metadata, safe_error
from tutorial_helpers.deployment import ApplicationHooks, decode_otlp_spans
from tutorial_helpers.validation import analyze_csv, render_markdown, validate_lesson, save_validation

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from notebook_validation import instrument_notebook


@contextlib.contextmanager
def telemetry(docker=False, instrumented=False, export=False):
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
        events = [SimpleNamespace(type='agent.session.created', session=SimpleNamespace(
            id=result.session_id, environment=SimpleNamespace(id='environment-fixture'))),
            SimpleNamespace(type='agent.session.turn.completed', session_id=result.session_id, turn=turn)]
        stream = Mock()
        stream.with_result_collection.return_value = stream
        stream.__enter__ = Mock(return_value=stream)
        stream.__exit__ = Mock(return_value=False)
        stream.__iter__ = Mock(side_effect=lambda: iter(events))
        stream.get_final_result.return_value = result
        client = Mock()
        client.beta.agents.sessions.create.return_value = stream
        client.beta.agents.sessions.turns.retrieve.return_value = turn
        client.beta.agents.sessions.traces.list.return_value = []
        client.beta.agents.sessions.items.list.side_effect = lambda *a, **kw: calls.append('history') or [
            SimpleNamespace(type='command_execution', turn_id=turn.id, status='completed', exit_code=0)]
        def download(source, *, to, **kwargs):
            Path(to).write_text(render_markdown(expected) if source.endswith('.md') else json.dumps(expected))
            return SimpleNamespace(id=Path(source).name, turn_id=turn.id, path=source)
        client.beta.agents.sessions.artifacts.for_result.return_value = SimpleNamespace(download=download)
        lab = Mock()
        lab.network.return_value = 'network-fixture'
        lab.__enter__ = Mock(side_effect=lambda *args: calls.append('docker.open') or lab)
        lab.__exit__ = Mock(side_effect=lambda *a: calls.append('docker.close') or False)
        lab.record.side_effect = lambda **kw: calls.append('docker.record')
        hooks_created = []
        def hooks_factory(endpoint, run_id):
            hooks = ApplicationHooks(None, run_id)  # Never send HTTP from a test.
            close = hooks.close
            def traced_close():
                if not hooks.closed:
                    calls.append('otel.close')
                close()
            hooks.close = traced_close
            hooks_created.append(hooks)
            return hooks
        def cleanup(client, sessions, agents, attempts):
            calls.append('cleanup')
            for value in sessions.values():
                value.update(deleted=True, verified_absent=True)
            return []
        clean = Mock(side_effect=cleanup)
        env = dict(settings=SimpleNamespace(root=root, model='fixture', api_key=None), root=root,
                   CHAPTER='13_hooks_telemetry', Path=Path, uuid4=uuid4, json=json,
                   ExitStack=contextlib.ExitStack, client=client, csv_text=csv_text, csv_bytes=csv_text.encode(), sys=sys,
                   decode_otlp_spans=decode_otlp_spans,
                   time=SimpleNamespace(monotonic=lambda: clock.now, sleep=Mock()),
                   environment={}, BASE_INSTRUCTIONS='fixture', task='fixture',
                   docker_enabled=docker, DockerLab=Mock(return_value=lab),
                   ApplicationHooks=Mock(side_effect=hooks_factory),
                   start_collector=Mock(return_value=('collector-fixture', 'http://fixture')),
                   cleanup_on_error=cleanup_on_error, cleanup_resources=clean,
                   new_session_metadata=new_session_metadata, check_event=lambda event: None,
                   safe_error=safe_error, EXPORT_TRACES=export,
                   TRACE_EXPORT_ATTEMPTS=3, TRACE_EXPORT_INTERVAL_SECONDS=2)
        def collector_file(*args, **kwargs):
            calls.append('collector.read')
            spans = env['hooks'].exporter.get_finished_spans()
            def attribute(key, value):
                return {'key': key, 'value': {'intValue': str(value)} if isinstance(value, int) else {'stringValue': value}}
            return json.dumps({'resourceSpans':[{
                'resource':{'attributes':[attribute('service.name','tutorial.application-hooks')]},
                'scopeSpans':[{'spans':[dict(name=span.name, traceId=f'{span.context.trace_id:032x}',
                    spanId=f'{span.context.span_id:016x}', attributes=[attribute(k,v) for k,v in span.attributes.items()]) for span in spans]}]
            }]})
        env['read_collector_file'] = Mock(side_effect=collector_file)
        nb = nbformat.read(ROOT / 'notebooks/chapters/13_hooks_telemetry.ipynb', as_version=4)
        if instrumented:
            instrument_notebook(nb, '13_hooks_telemetry', live=True, docker=docker)
        stages = {}
        for cell in nb.cells:
            for step in range(1, 7):
                if f'telemetry_step_{step}' in cell.metadata.get('tags', []):
                    stages[step] = cell.source
        with patch('tutorial_helpers.common.cleanup_resources', clean), \
                patch('builtins.input', side_effect=AssertionError('No input wait is allowed')), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            if instrumented:
                exec(nb.cells[0].source, env)
                def validate(*args):
                    calls.append('validate')
                    return validate_lesson(*args)
                def save(*args, **kwargs):
                    calls.append('save')
                    return save_validation(*args, **kwargs)
                env.update(_validate_lesson=validate, _save_validation=save)
            exec(next(c.source for c in nb.cells if c.id=='13-run-state'), env)
            try:
                yield env, stages, clean, calls, clock, output, lab
            finally:
                # Drop retained tracebacks before temporary fixture teardown.
                env.pop("_validation_error", None)
                for hooks in hooks_created:
                    hooks.provider.shutdown()
                env.clear()


class SimulatedInterruption(BaseException):
    """Exercise interruption cleanup without changing the test runner signal state."""


class TelemetryStepTests(unittest.TestCase):
    def test_default_path_and_docker_fixture_validate_before_resource_shutdown(self):
        for docker in [False, True]:
            with self.subTest(docker=docker), telemetry(docker, True) as (env, stages, clean, calls, clock, output, lab):
                for step in range(1, 6):
                    clock.now += 2000
                    exec(stages[step], env)
                    clean.assert_not_called()
                self.assertEqual(env['api_duration_ms'], 0)  # No between-cell review time included.
                self.assertTrue(env['report_downloaded'])
                self.assertTrue(env['application_hooks_checked'])
                env['client'].beta.agents.sessions.traces.list.assert_not_called()
                exec(stages[6], env)
                clean.assert_called_once()
                self.assertEqual(env['_validation_summary']['status'], 'passed')
                self.assertLess(calls.index('validate'), calls.index('cleanup'))
                self.assertEqual([r['event'] for r in env['hooks'].records],
                                 ['report.started', 'session.created', 'turn.completed', 'report.completed'])
                if docker:
                    self.assertLess(calls.index('collector.read'), calls.index('docker.close'))
                    self.assertLess(calls.index('docker.record'), calls.index('docker.close'))
                    self.assertLess(calls.index('otel.close'), calls.index('docker.close'))

    def test_export_statuses_do_not_change_analysis_success(self):
        trace = SimpleNamespace(to_dict=lambda: {'otlp': {'resourceSpans': [{'scopeSpans': [{'spans': [{'name': 'fixture'}]}]}]}})
        for outcome in ['exported', 'not_ready', 'unavailable']:
            with self.subTest(outcome=outcome), telemetry(instrumented=True, export=True) as (env, stages, clean, calls, clock, output, lab):
                query = env['client'].beta.agents.sessions.traces.list
                if outcome == 'exported':
                    query.side_effect = [[], [trace]]
                elif outcome == 'unavailable':
                    query.side_effect = PermissionError('private fixture text')
                for step in range(1, 7):
                    exec(stages[step], env)
                self.assertEqual(env['trace_export'], outcome)
                self.assertEqual(env['_validation_summary']['status'], 'passed')
                self.assertEqual((env['output_dir'] / 'traces.otlp.json').exists(), outcome == 'exported')
                self.assertNotIn('private fixture text', output.getvalue())
                if outcome == 'not_ready':
                    self.assertEqual(query.call_count, 3)
                    self.assertEqual(env['time'].sleep.call_count, 2)

    def test_partial_manual_run_can_close_collector_without_running_agent(self):
        with telemetry(docker=True) as (env, stages, clean, calls, clock, output, lab):
            exec(stages[1], env)
            exec(stages[6], env)
            env['client'].beta.agents.sessions.create.assert_not_called()
            self.assertTrue(env['hooks'].closed)
            self.assertIn('docker.close', calls)

    def test_stage_errors_and_interrupt_close_session_otel_and_docker_before_receipt(self):
        for failed in range(1, 6):
            with self.subTest(step=failed), telemetry(True, True, True) as (env, stages, clean, calls, clock, output, lab):
                for step in range(1, failed):
                    exec(stages[step], env)
                if failed == 1:
                    env['ApplicationHooks'].side_effect = RuntimeError('fixture')
                elif failed == 2:
                    env['client'].beta.agents.sessions.create.side_effect = RuntimeError('fixture')
                elif failed == 3:
                    env['client'].beta.agents.sessions.artifacts.for_result.side_effect = RuntimeError('fixture')
                elif failed == 4:
                    env['read_collector_file'].side_effect = RuntimeError('fixture')
                else:
                    env['client'].beta.agents.sessions.traces.list.side_effect = SimulatedInterruption
                with self.assertRaises(SimulatedInterruption if failed == 5 else RuntimeError):
                    exec(stages[failed], env)
                clean.assert_called_once()
                self.assertIn('docker.close', calls)
                self.assertLess(calls.index('docker.close'), calls.index('save'))
                self.assertEqual(env['_validation_summary']['status'], 'failed')
                if env['hooks'] is not None:
                    self.assertTrue(env['hooks'].closed)

    def test_failed_final_validation_still_closes_every_resource(self):
        with telemetry(True, True) as (env, stages, clean, calls, clock, output, lab):
            for step in range(1, 6):
                exec(stages[step], env)
            env['_validate_lesson'] = Mock(side_effect=ValueError('fixture check'))
            with self.assertRaisesRegex(ValueError, 'fixture check'):
                exec(stages[6], env)
            clean.assert_called_once()
            self.assertIn('docker.close', calls)
            self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_extra_finalizers_run_even_when_session_cleanup_fails(self):
        calls, errors = [], []
        def broken():
            calls.append('first')
            raise RuntimeError('finalizer fixture')
        with patch('tutorial_helpers.common.cleanup_resources', side_effect=ValueError('cleanup fixture')):
            with self.assertRaisesRegex(KeyError, 'original'):
                with cleanup_on_error(None, {}, {}, [], errors=errors,
                                      finalizers=(broken, lambda: calls.append('second'))):
                    raise KeyError('original')
        self.assertEqual(calls, ['first', 'second'])
        self.assertEqual(len(errors), 2)


if __name__ == '__main__':
    unittest.main()
