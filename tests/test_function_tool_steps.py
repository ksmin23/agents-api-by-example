"""Actual notebook cells with the SDK function dispatcher and fake API/file transport."""
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
from openai.lib.beta.agents._artifacts import AgentResultArtifacts
from openai.lib.streaming.agents._dispatch import ToolDispatcher
from openai.types.beta.agent_function_call_item import AgentFunctionCallItem
from tutorial_helpers.common import cleanup_on_error, check_event, new_session_metadata, safe_error
from tutorial_helpers.validation import analyze_csv, render_markdown, validate_lesson, save_validation

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
        (root / 'data/sales_targets.json').write_bytes((ROOT / 'data/sales_targets.json').read_bytes())
        expected = analyze_csv(csv_text)
        calls, files, errors, control = [], {}, {}, {}
        clock = SimpleNamespace(now=0)
        turn = SimpleNamespace(id='turn-fixture', status='completed', subagent_id=None, usage=None)
        result = SimpleNamespace(session_id='session-fixture', turn_id=turn.id, turn=turn, output_text='not-set')
        call = AgentFunctionCallItem(id='item-fixture', call_id='call-fixture', turn_id=turn.id,
                                    name='get_sales_target', arguments={'period': '2026-01'},
                                    type='function_call', status='in_progress')
        older = AgentFunctionCallItem(id='old-item', call_id='old-call', turn_id='older-turn',
                                     name='get_sales_target', arguments={'period': '2026-01'},
                                     type='function_call', status='completed')
        command = SimpleNamespace(type='command_execution', turn_id=turn.id, status='completed',
                                  exit_code=0, command='python analyze.py')
        items = [command, older, call]
        client = Mock()
        notifications = []
        def submit(sid, *, events, **kwargs):
            payload = events[0]
            calls.append('tool.result')
            call.status = 'completed' if payload['success'] else 'failed'
            if payload['success']:
                target = json.loads(payload['output'])
                enriched = dict(metrics=expected, target_revenue=target['target_revenue'],
                                attainment_rate=expected['total_revenue'] / target['target_revenue'])
                result.output_text = json.dumps(enriched)
                files['summary.json'] = json.dumps(expected).encode()
                files['report.md'] = (render_markdown(expected) + '\nTarget: 150000; attainment: 85%\n').encode()
        client.beta.agents.sessions.events.create.side_effect = submit
        stream = Mock()
        stream.with_result_collection.return_value = stream
        stream.__enter__ = Mock(return_value=stream)
        stream.__exit__ = Mock(return_value=False)
        def create(**kwargs):
            calls.append('session.create')
            dispatcher = ToolDispatcher(client.beta.agents.sessions, kwargs.get('tool_handlers'),
                                        on_tool_error=notifications.append)
            def events():
                yield SimpleNamespace(type='agent.session.created', session=SimpleNamespace(
                    id=result.session_id, environment=SimpleNamespace(id='environment-fixture')))
                event = SimpleNamespace(type='agent.session.turn.item.added', session_id=result.session_id, item=call)
                pending = dispatcher.prepare(event)
                yield event
                if pending:
                    dispatcher.dispatch(pending)  # Real SDK argument validation, callback, serialization and submission.
                if control.get('duplicate_event'):
                    self_same = dispatcher.prepare(event)
                    if self_same:
                        dispatcher.dispatch(self_same)
                if control.get('interrupt_after_tool'):
                    raise SimulatedInterruption('fixture')
                yield SimpleNamespace(type='agent.session.turn.output_text.delta', delta=result.output_text)
                yield SimpleNamespace(type='agent.session.turn.completed', turn=turn)
            stream.__iter__ = Mock(side_effect=events)
            return stream
        client.beta.agents.sessions.create.side_effect = create
        stream.get_final_result.return_value = result
        client.beta.agents.sessions.turns.retrieve.return_value = turn
        class Pages:
            def __init__(self, values, label):
                self.values, self.label = values, label
            def __iter__(self):
                for index, page in enumerate([self.values[:1], self.values[1:]]):
                    calls.append(f'{self.label}.page.{index+1}')
                    yield from page
        client.beta.agents.sessions.items.list.side_effect = lambda *a, **kw: Pages(items, 'items')
        resource = client.beta.agents.sessions.artifacts
        def artifacts(*args, **kwargs):
            values = [SimpleNamespace(id=name, session_id=result.session_id, turn_id=turn.id,
                      path='/workspace/outputs/' + name, size_bytes=len(data)) for name, data in files.items()]
            return Pages(values, 'artifacts')
        resource.list.side_effect = artifacts
        resource.for_result.side_effect = lambda result: AgentResultArtifacts(resource, result)
        @contextlib.contextmanager
        def content(artifact_id, **kwargs):
            calls.append('download:' + artifact_id)
            def write(to):
                Path(to).write_bytes(files[artifact_id][:5] if artifact_id in errors else files[artifact_id])
                if artifact_id in errors:
                    raise errors[artifact_id]
            yield SimpleNamespace(stream_to_file=write)
        resource.with_streaming_response.content.side_effect = content
        def cleanup(client, sessions, agents, attempts):
            calls.append('cleanup')
            for owned in sessions.values():
                owned.update(deleted=True, verified_absent=True)
            client.close()
            return []
        clean = Mock(side_effect=cleanup)
        env = dict(settings=SimpleNamespace(root=root, model='fixture', api_key=None), CHAPTER='07_function_tools',
                   client=client, uuid4=uuid4, json=json, sys=sys,
                   time=SimpleNamespace(monotonic=lambda: clock.now), cleanup_on_error=cleanup_on_error,
                   cleanup_resources=clean, check_event=check_event, new_session_metadata=new_session_metadata,
                   safe_error=safe_error)
        nb = nbformat.read(ROOT / 'notebooks/chapters/07_function_tools.ipynb', as_version=4)
        if instrumented:
            instrument_notebook(nb, '07_function_tools', live=True)
        steps = {i: next(c.source for c in nb.cells if f'function_tool_step_{i}' in c.metadata.get('tags', [])) for i in range(1, 6)}
        with patch('tutorial_helpers.common.cleanup_resources', clean), contextlib.redirect_stdout(io.StringIO()) as output, \
                patch('IPython.display.display', side_effect=lambda value: calls.append('display')):
            if instrumented:
                exec(nb.cells[0].source, env)
                def validate(*args):
                    calls.append('validate')
                    return validate_lesson(*args)
                env.update(_validate_lesson=validate, _save_validation=save_validation)
            for identifier in ['07-input-preview', 'extension-07-06', '07-tool-preflight', '07-tool-definition',
                               '07-tool-registration', 'a1db7d38', 'ea51530b9849']:
                exec(next(c.source for c in nb.cells if c.id == identifier), env)
            try:
                yield env, steps, clean, calls, clock, output, stream, call, items, files, errors, control, notifications
            finally:
                env.pop('_validation_error', None)
                env.clear()


class FunctionToolStepTests(unittest.TestCase):
    def test_sdk_dispatch_registration_result_serialization_and_cleanup(self):
        for instrumented in [False, True]:
            with self.subTest(instrumented=instrumented), lesson(instrumented) as (env, steps, clean, calls, clock, output, stream, call, items, files, errors, control, notices):
                env['client'].beta.agents.sessions.events.create.assert_not_called()  # Local preflight is not an API call.
                clock.now = 2000
                exec(steps[1], env)
                self.assertEqual(env['started'], 2000)
                request = env['client'].beta.agents.sessions.create.call_args.kwargs
                self.assertEqual(request['agent']['tools'], [env['sales_target_tool'].definition])
                self.assertIs(request['tool_handlers']['get_sales_target'], env['sales_target_tool'])
                payload = env['client'].beta.agents.sessions.events.create.call_args.kwargs['events'][0]
                self.assertTrue(payload['success'])
                self.assertEqual(payload['turn_id'], 'turn-fixture')
                self.assertEqual(payload['call_id'], 'call-fixture')
                self.assertEqual(json.loads(payload['output'])['target_revenue'], 150000)
                self.assertEqual(notices, [])
                clock.now += 2000
                for step in [2, 3, 4]:
                    exec(steps[step], env)
                self.assertEqual([c.call_id for c in env['function_calls']], ['call-fixture'])
                self.assertIn('items.page.2', calls)
                self.assertEqual(env['actual']['attainment_rate'], 0.85)
                self.assertNotIn('target_revenue', env['downloaded_summary'])
                self.assertEqual(env['downloads'], env['output_dir'] / 'downloads' / 'turn-fixture')
                self.assertTrue(env['downloads_complete'])
                clean.assert_not_called()
                exec(steps[5], env)
                clean.assert_called_once()
                if instrumented:
                    self.assertEqual(env['_validation_summary']['status'], 'passed')
                    self.assertLess(calls.index('validate'), calls.index('cleanup'))
                    self.assertEqual(env['_validation_summary']['checks']['function_call']['arguments'], {'period': '2026-01'})

    def test_sdk_error_results_are_generic_and_original_error_is_only_local(self):
        for mode in ['arguments', 'period', 'role']:
            with self.subTest(mode=mode), lesson() as (env, steps, clean, calls, clock, output, stream, call, items, files, errors, control, notices):
                if mode == 'arguments':
                    call.arguments = {}
                elif mode == 'period':
                    call.arguments = {'period': '2026-02'}
                else:
                    env['ACTOR_ROLE'] = 'viewer'
                exec(steps[1], env)
                payload = env['client'].beta.agents.sessions.events.create.call_args.kwargs['events'][0]
                self.assertFalse(payload['success'])
                self.assertEqual(payload['error'], 'Tool handler failed.')
                self.assertNotIn('unknown_period', str(payload))
                self.assertNotIn('role_not_allowed', str(payload))
                self.assertEqual(len(notices), 1)
                self.assertEqual(notices[0].stage, 'arguments' if mode == 'arguments' else 'execution')
                self.assertEqual(notices[0].call_id, 'call-fixture')
                # This fixture inspects local dispatch, not how a real model reacts to tool errors.
                exec(steps[5], env)

    def test_validator_rejects_wrong_call_count_name_status_and_period(self):
        for mode in ['missing', 'duplicate', 'name', 'status', 'period']:
            with self.subTest(mode=mode), lesson(True) as (env, steps, clean, calls, clock, output, stream, call, items, files, errors, control, notices):
                for step in [1, 2, 3, 4]:
                    exec(steps[step], env)
                if mode == 'missing':
                    items.remove(call)
                elif mode == 'duplicate':
                    items.append(call.model_copy(update={'call_id': 'second-call'}))
                elif mode == 'name':
                    call.name = 'get_sales_target_extra'
                elif mode == 'status':
                    call.status = 'failed'
                else:
                    call.arguments = {'period': '2026-02'}
                with self.assertRaises(ValueError):
                    exec(steps[5], env)
                clean.assert_called_once()
                self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_string_arguments_and_duplicate_stream_item_are_supported(self):
        with lesson(True) as (env, steps, clean, calls, clock, output, stream, call, items, files, errors, control, notices):
            call.arguments = json.dumps({'period': '2026-01'})
            control['duplicate_event'] = True
            for step in range(1, 6):
                exec(steps[step], env)
            env['client'].beta.agents.sessions.events.create.assert_called_once()
            self.assertEqual(env['_validation_summary']['status'], 'passed')

    def test_repeated_submission_never_reexecutes_function(self):
        with lesson(True) as (env, steps, clean, *rest):
            exec(steps[1], env)
            with self.assertRaisesRegex(RuntimeError, 'Do not resubmit'):
                exec(steps[1], env)
            env['client'].beta.agents.sessions.create.assert_called_once()
            env['client'].beta.agents.sessions.events.create.assert_called_once()
            clean.assert_called_once()

    def test_interrupt_after_tool_result_does_not_replay_the_call(self):
        with lesson(True) as (env, steps, clean, calls, clock, output, stream, call, items, files, errors, control, notices):
            control['interrupt_after_tool'] = True
            with self.assertRaises(SimulatedInterruption):
                exec(steps[1], env)
            env['client'].beta.agents.sessions.events.create.assert_called_once()
            clean.assert_called_once()
            self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_partial_download_and_missing_artifact_are_not_success(self):
        for mode in ['partial', 'missing']:
            with self.subTest(mode=mode), lesson(True) as (env, steps, clean, calls, clock, output, stream, call, items, files, errors, control, notices):
                exec(steps[1], env)
                if mode == 'partial':
                    errors['report.md'] = OSError('transfer fixture')
                else:
                    files.pop('report.md')
                with self.assertRaises(OSError if mode == 'partial' else ValueError):
                    exec(steps[3], env)
                self.assertFalse(env['downloads_complete'])
                env['client'].beta.agents.sessions.events.create.assert_called_once()
                clean.assert_called_once()
                self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_local_error_preserves_original_when_cleanup_also_fails(self):
        with lesson(True) as (env, steps, clean, calls, *rest):
            exec(steps[1], env)
            exec(steps[3], env)
            env['result'].output_text = 'not json'
            clean.side_effect = RuntimeError('cleanup fixture')
            with self.assertRaises(json.JSONDecodeError) as raised:
                exec(steps[4], env)
            self.assertTrue(raised.exception.__notes__)
            self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_partial_cleanup_and_retained_files_do_not_call_api_again(self):
        with lesson() as (env, steps, clean, *rest):
            exec(steps[5], env)
            env['client'].beta.agents.sessions.create.assert_not_called()
        with lesson() as (env, steps, clean, *rest):
            exec(steps[1], env)
            exec(steps[3], env)
            exec(steps[5], env)
            before = len(env['client'].mock_calls)
            exec(steps[4], env)
            self.assertEqual(len(env['client'].mock_calls), before)

    def test_analysis_failure_blocks_history_and_downloads(self):
        with lesson(True) as (env, steps, clean, calls, clock, output, stream, call, items, files, errors, control, notices):
            stream.get_final_result.return_value.turn.status = 'failed'
            with self.assertRaisesRegex(RuntimeError, 'completion'):
                exec(steps[1], env)
            env['client'].beta.agents.sessions.items.list.assert_not_called()
            env['client'].beta.agents.sessions.artifacts.for_result.assert_not_called()
            self.assertEqual(env['_validation_summary']['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
