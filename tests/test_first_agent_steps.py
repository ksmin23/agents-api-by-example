"""Exercise the actual chapter 2 cells with fake API responses, never paid calls."""
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
from tutorial_helpers.common import cleanup_on_error, check_event, new_session_metadata, safe_error
from tutorial_helpers.validation import analyze_csv, validate_lesson, save_validation

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
            SimpleNamespace(type='command_execution', turn_id=turn.id, status='completed', exit_code=0)]
        def cleanup(client, sessions, agents, attempts):
            calls.append('cleanup')
            for value in sessions.values():
                value.update(deleted=True, verified_absent=True)
            client.close()
            return []
        clean = Mock(side_effect=cleanup)
        env = dict(settings=SimpleNamespace(root=root, model='fixture', api_key=None),
                   CHAPTER='02_first_agent', uuid4=uuid4, json=json, sys=sys, client=client,
                   time=SimpleNamespace(monotonic=lambda: clock.now),
                   environment={'type':'openai_hosted', 'network':{'access':'disabled'}},
                   BASE_INSTRUCTIONS='fixture', task='CSV fixture', cleanup_on_error=cleanup_on_error,
                   cleanup_resources=clean, new_session_metadata=new_session_metadata,
                   check_event=check_event, safe_error=safe_error)
        nb = nbformat.read(ROOT / 'notebooks/chapters/02_first_agent.ipynb', as_version=4)
        if instrumented:
            instrument_notebook(nb, '02_first_agent', live=True)
        steps = {step: next(c.source for c in nb.cells if f'first_agent_step_{step}' in c.metadata.get('tags', []))
                 for step in range(1,4)}
        with patch('tutorial_helpers.common.cleanup_resources', clean), contextlib.redirect_stdout(io.StringIO()) as output:
            if instrumented:
                exec(nb.cells[0].source, env)
                def validate(*a):
                    calls.append('validate')
                    return validate_lesson(*a)
                env.update(_validate_lesson=validate, _save_validation=save_validation)
            exec(next(c.source for c in nb.cells if c.id=='24e56ec25b78'), env)
            try:
                yield env, steps, clean, calls, clock, output, stream
            finally:
                env.pop('_validation_error', None)
                env.clear()


class FirstAgentStepTests(unittest.TestCase):
    def test_execute_inspect_cleanup_and_validation_order(self):
        for instrumented in [False, True]:
            with self.subTest(instrumented=instrumented), lesson(instrumented) as (env, steps, clean, calls, clock, output, stream):
                clock.now = 2000  # Study time since state preparation must not consume the deadline.
                exec(steps[1], env)
                clean.assert_not_called()
                self.assertEqual(env['started'], 2000)
                env['client'].beta.agents.sessions.turns.retrieve.assert_not_called()
                clock.now += 2000
                exec(steps[2], env)
                clean.assert_not_called()
                self.assertEqual(env['actual']['total_revenue'], 127500)
                env['client'].beta.agents.sessions.create.assert_called_once()
                exec(steps[3], env)
                clean.assert_called_once()
                self.assertTrue(env['sessions']['session-fixture']['verified_absent'])
                env['client'].close.assert_called_once()
                self.assertIn('Turn status: completed', output.getvalue())
                self.assertIn('verified_absent', output.getvalue())
                if instrumented:
                    self.assertLess(calls.index('history'), calls.index('cleanup'))
                    self.assertLess(calls.index('validate'), calls.index('cleanup'))
                    self.assertEqual(env['_validation_summary']['status'], 'passed')

    def test_partial_run_can_cleanup_without_creating_work(self):
        with lesson() as (env, steps, clean, *rest):
            exec(steps[3], env)
            env['client'].beta.agents.sessions.create.assert_not_called()
            clean.assert_called_once()

    def test_failed_stream_or_interrupt_cleans_up_and_records_failure(self):
        for error in [RuntimeError('stream failed'), SimulatedInterruption('interrupted')]:
            with self.subTest(error=type(error).__name__), lesson(True) as (env, steps, clean, calls, clock, output, stream):
                def events():
                    yield SimpleNamespace(type='agent.session.created', session=SimpleNamespace(
                        id='session-fixture', environment=SimpleNamespace(id='environment-fixture')))
                    raise error
                stream.__iter__.side_effect = events
                with self.assertRaises(type(error)):
                    exec(steps[1], env)
                clean.assert_called_once()
                self.assertTrue(env['sessions']['session-fixture']['verified_absent'])
                self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_json_failure_preserves_original_even_when_cleanup_fails(self):
        with lesson(True) as (env, steps, clean, *rest):
            exec(steps[1], env)
            env['result'].output_text='not json'
            clean.side_effect=RuntimeError('cleanup failed')
            with self.assertRaises(json.JSONDecodeError) as raised:
                exec(steps[2], env)
            self.assertTrue(raised.exception.__notes__)
            self.assertEqual(env['_validation_summary']['status'], 'failed')
            self.assertTrue(env['_validation_summary']['cleanup_errors'])

    def test_failed_turn_and_unexpected_action_do_not_pass(self):
        for mode in ['turn', 'action']:
            with self.subTest(mode=mode), lesson(True) as (env, steps, clean, calls, clock, output, stream):
                if mode=='action':
                    stream.__iter__.side_effect=lambda: iter([SimpleNamespace(type='agent.session.requires_action')])
                    step=1
                else:
                    exec(steps[1], env)
                    env['result'].turn.status='failed'
                    step=2
                with self.assertRaises(RuntimeError):
                    exec(steps[step], env)
                clean.assert_called_once()
                self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_repeated_submission_is_blocked(self):
        with lesson() as (env, steps, clean, *rest):
            exec(steps[1], env)
            with self.assertRaisesRegex(RuntimeError,'Do not resubmit'):
                exec(steps[1], env)
            env['client'].beta.agents.sessions.create.assert_called_once()
            clean.assert_called_once()

    def test_validation_error_and_cleanup_error_preserve_validation_error(self):
        with lesson(True) as (env, steps, clean, *rest):
            exec(steps[1], env)
            exec(steps[2], env)
            env['_validate_lesson']=Mock(side_effect=ValueError('validation failed'))
            clean.side_effect=RuntimeError('cleanup failed')
            with self.assertRaisesRegex(ValueError,'validation failed') as raised:
                exec(steps[3], env)
            self.assertTrue(raised.exception.__notes__)
            self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_cleanup_failure_is_not_reported_as_success(self):
        with lesson(True) as (env, steps, clean, *rest):
            exec(steps[1], env)
            exec(steps[2], env)
            clean.side_effect=lambda *a: [{'stage':'fixture'}]
            with self.assertRaisesRegex(RuntimeError,'Resource cleanup incomplete'):
                exec(steps[3], env)
            self.assertEqual(env['_validation_summary']['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
