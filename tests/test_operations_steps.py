"""Execute the chapter's real cells with paginated fake API responses, never a paid API."""
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
from tutorial_helpers.common import cleanup_on_error, new_session_metadata, safe_error, check_event
from tutorial_helpers.validation import analyze_csv, render_markdown, validate_lesson, save_validation

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from notebook_validation import instrument_notebook


class Pages:
    """Mimic an SDK iterable: .data contains only the first page."""
    def __init__(self, pages, calls, name):
        self.pages, self.calls, self.name = pages, calls, name
        self.data = pages[0]

    def __iter__(self):
        for index, page in enumerate(self.pages):
            self.calls.append(f'{self.name}.page.{index + 1}')
            yield from page


class Stream:
    def __init__(self, events, calls, name):
        self.events, self.calls, self.name = events, calls, name

    def __enter__(self):
        self.calls.append(self.name + '.open')
        return self

    def __exit__(self, *args):
        self.calls.append(self.name + '.close')

    def __iter__(self):
        self.calls.append(self.name + '.iterate')
        yield from self.events


class SimulatedInterruption(BaseException):
    pass


@contextlib.contextmanager
def operations(*, instrumented=True, early=True, initial='in_progress', usage=None):
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        (root / 'data').mkdir()
        csv_text = (ROOT / 'data/sales.csv').read_text()
        (root / 'data/sales.csv').write_text(csv_text)
        expected = analyze_csv(csv_text)
        calls, clock = [], SimpleNamespace(now=0)
        session = SimpleNamespace(id='session-fixture', environment=SimpleNamespace(id='env-fixture'))
        done = SimpleNamespace(id='turn-fixture', status='completed', subagent_id=None, usage=usage)
        active = SimpleNamespace(id=done.id, status='in_progress', subagent_id=None, usage=None)
        first = [] if initial == 'missing' else [SimpleNamespace(
            type='agent.session.turn.' + initial, turn=done if initial == 'completed' else active)]
        resumed = [] if early else [SimpleNamespace(type='agent.session.turn.output_text.delta', delta='{}'),
                                   SimpleNamespace(type='agent.session.turn.completed', turn=done)]
        client = Mock()
        api = client.beta.agents.sessions
        api.create.side_effect = lambda **kw: calls.append('create') or session
        api.events.stream.side_effect = [Stream(first, calls, 'initial'), Stream(resumed, calls, 'reconnected')]
        api.events.create.side_effect = lambda *a, **kw: calls.append('submit')
        api.retrieve.side_effect = lambda *a, **kw: calls.append('snapshot') or SimpleNamespace(status='active', required_actions=[])
        api.turns.retrieve.side_effect = [done if early else active, done, done]
        api.turns.list.side_effect = lambda *a, **kw: Pages([[], [done]], calls, 'turns')
        command = SimpleNamespace(type='command_execution', turn_id=done.id, status='completed', exit_code=0)
        answer = SimpleNamespace(id='answer-fixture', type='message', turn_id=done.id, role='assistant',
                                 phase='final_answer', output_text=json.dumps(expected))
        api.items.list.side_effect = lambda *a, **kw: Pages([[command], [answer]], calls, 'items')
        artifacts = [SimpleNamespace(id=name, turn_id=done.id, path='/workspace/outputs/' + name)
                     for name in ['summary.json', 'report.md']]
        api.artifacts.list.side_effect = lambda *a, **kw: Pages([[], artifacts], calls, 'artifacts')
        def content(artifact_id, **kwargs):
            data = render_markdown(expected) if artifact_id.endswith('.md') else json.dumps(expected)
            return contextlib.nullcontext(SimpleNamespace(stream_to_file=lambda path: Path(path).write_text(data)))
        api.artifacts.with_streaming_response.content.side_effect = content
        def cleanup(client, sessions, agents, attempts):
            calls.append('cleanup')
            for value in sessions.values():
                value.update(deleted=True, verified_absent=True)
            return []
        clean = Mock(side_effect=cleanup)
        env = dict(settings=SimpleNamespace(root=root, model='fixture', api_key=None), root=root,
                   CHAPTER='14_operations', client=client, uuid4=uuid4, sys=sys, json=json,
                   time=SimpleNamespace(monotonic=lambda: clock.now), environment={}, task='fixture',
                   display=Mock(), Markdown=lambda text: text, BASE_INSTRUCTIONS='fixture', cleanup_on_error=cleanup_on_error, cleanup_resources=clean,
                   new_session_metadata=new_session_metadata, safe_error=safe_error, check_event=check_event)
        notebook = nbformat.read(ROOT / 'notebooks/chapters/14_operations.ipynb', as_version=4)
        if instrumented:
            instrument_notebook(notebook, '14_operations', live=True)
        stages = {}
        for cell in notebook.cells:
            for step in range(1, 7):
                if f'operations_step_{step}' in cell.metadata.get('tags', []):
                    stages[step] = cell.source
        with patch('tutorial_helpers.common.cleanup_resources', clean), \
                patch('builtins.input', side_effect=AssertionError('No input prompt expected')), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            if instrumented:
                exec(notebook.cells[0].source, env)
                def validate(*args):
                    calls.append('validate')
                    return validate_lesson(*args)
                def save(*args, **kwargs):
                    calls.append('save')
                    return save_validation(*args, **kwargs)
                env.update(_validate_lesson=validate, _save_validation=save)
            state_cell = next(c for c in notebook.cells if c.id == '14-run-state')
            exec(state_cell.source, env)
            yield env, stages, clean, calls, clock, output, done
            env.pop('_validation_error', None)


class OperationsStepTests(unittest.TestCase):
    def test_already_completed_or_still_active_recovery_uses_one_original_turn(self):
        for early in [True, False]:
            with self.subTest(early=early), operations(early=early) as (env, stages, clean, calls, clock, output, done):
                for step in range(1, 6):
                    clock.now += 2000  # Study time between cells must not consume the next budget.
                    exec(stages[step], env)
                    clean.assert_not_called()
                api = env['client'].beta.agents.sessions
                api.create.assert_called_once()
                api.events.create.assert_called_once()
                self.assertEqual(api.events.stream.call_count, 2)
                self.assertLess(calls.index('reconnected.open'), calls.index('snapshot'))
                self.assertEqual('reconnected.iterate' in calls, not early)
                self.assertTrue(env['observer_reconnected'])
                self.assertTrue(env['report_downloaded'])
                self.assertEqual(env['root_turn_count'], 1)
                self.assertEqual(env['turn_id'], done.id)
                self.assertIn('artifacts.page.2', calls)
                self.assertIn('items.page.2', calls)
                self.assertIn('turns.page.2', calls)
                self.assertIn('Summary:', output.getvalue())
                self.assertIn('Downloaded report:', output.getvalue())
                request = json.loads(env['state_path'].read_text())
                self.assertEqual(request['turn_id'], done.id)
                self.assertEqual(request['submission_state'], 'accepted')
                self.assertEqual(request['idempotency_key'], api.events.create.call_args.kwargs['idempotency_key'])
                self.assertNotIn('task', request)
                exec(stages[6], env)
                self.assertEqual(env['_validation_summary']['status'], 'passed')
                self.assertLess(calls.index('validate'), calls.index('cleanup'))
                self.assertLess(calls.index('cleanup'), calls.index('save'))
                self.assertEqual(env['_validation_summary']['checks']['input_submission_attempts'], 1)
                self.assertEqual(json.loads(env['state_path'].read_text())['cleanup'], 'verified')
                api.traces.list.assert_not_called()

    def test_completed_initial_event_or_missing_event_falls_back_to_persisted_turns(self):
        for initial in ['completed', 'missing']:
            with self.subTest(initial=initial), operations(initial=initial) as (env, stages, clean, calls, clock, output, done):
                for step in range(1, 7):
                    exec(stages[step], env)
                self.assertEqual(env['_validation_summary']['status'], 'passed')
                self.assertEqual(env['turn_id'], done.id)
                env['client'].beta.agents.sessions.events.create.assert_called_once()

    def test_unknown_acceptance_is_not_resubmitted(self):
        with operations() as (env, stages, clean, calls, clock, output, done):
            exec(stages[1], env)
            api = env['client'].beta.agents.sessions
            api.events.create.side_effect = TimeoutError('acceptance unknown')
            with self.assertRaisesRegex(TimeoutError, 'acceptance unknown'):
                exec(stages[2], env)
            self.assertEqual(env['input_submission_attempts'], 1)
            self.assertFalse(env['input_accepted'])
            self.assertEqual(json.loads(env['state_path'].read_text())['submission_state'], 'attempting')
            api.events.create.assert_called_once()
            clean.assert_called_once()
            self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_repeating_submission_cell_stops_without_a_second_input(self):
        with operations() as (env, stages, clean, calls, clock, output, done):
            exec(stages[1], env)
            exec(stages[2], env)
            with self.assertRaisesRegex(RuntimeError, 'already attempted'):
                exec(stages[2], env)
            env['client'].beta.agents.sessions.events.create.assert_called_once()
            clean.assert_called_once()

    def test_observation_error_or_interruption_cleans_up_without_retrying_input(self):
        for failure in [TimeoutError('observation timeout'), SimulatedInterruption()]:
            with self.subTest(failure=type(failure).__name__), operations() as (env, stages, clean, calls, clock, output, done):
                exec(stages[1], env)
                exec(stages[2], env)
                env['client'].beta.agents.sessions.retrieve.side_effect = failure
                with self.assertRaises(type(failure)):
                    exec(stages[3], env)
                env['client'].beta.agents.sessions.events.create.assert_called_once()
                clean.assert_called_once()
                self.assertLess(calls.index('cleanup'), calls.index('save'))
                self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_failed_or_cancelled_persisted_turn_is_not_downloaded_as_success(self):
        for status in ['failed', 'cancelled']:
            with self.subTest(status=status), operations() as (env, stages, clean, calls, clock, output, done):
                done.status = status
                for step in [1, 2]:
                    exec(stages[step], env)
                with self.assertRaisesRegex(RuntimeError, status):
                    exec(stages[3], env)
                env['client'].beta.agents.sessions.artifacts.with_streaming_response.content.assert_not_called()
                self.assertFalse(env['report_downloaded'])
                clean.assert_called_once()

    def test_unexpected_tool_action_requires_reconciliation(self):
        with operations() as (env, stages, clean, calls, clock, output, done):
            for step in [1, 2]:
                exec(stages[step], env)
            api = env['client'].beta.agents.sessions
            api.retrieve.side_effect = None
            api.retrieve.return_value = SimpleNamespace(status='active', required_actions=[SimpleNamespace(type='function_call')])
            with self.assertRaisesRegex(RuntimeError, 'Unexpected external action'):
                exec(stages[3], env)
            api.events.create.assert_called_once()  # No tool result or extra input was fabricated.
            clean.assert_called_once()

    def test_usage_none_and_reported_zero_remain_distinct(self):
        for usage in [None, SimpleNamespace(to_dict=lambda: {'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0})]:
            with self.subTest(reported=usage is not None), operations(usage=usage) as (env, stages, clean, calls, clock, output, done):
                for step in range(1, 7):
                    exec(stages[step], env)
                if usage is None:
                    self.assertIsNone(env['usage'])
                else:
                    self.assertEqual(env['usage']['total_tokens'], 0)
                self.assertEqual(env['_validation_summary']['status'], 'passed')

    def test_partial_manual_run_can_clean_up_without_a_turn(self):
        with operations(instrumented=False) as (env, stages, clean, calls, clock, output, done):
            exec(stages[1], env)
            exec(stages[6], env)
            env['client'].beta.agents.sessions.events.create.assert_not_called()
            clean.assert_called_once()
            self.assertIn('not_completed', output.getvalue())

    def test_validation_error_survives_a_second_cleanup_error(self):
        with operations() as (env, stages, clean, calls, clock, output, done):
            for step in range(1, 6):
                exec(stages[step], env)
            env['_validate_lesson'] = Mock(side_effect=ValueError('original validation error'))
            clean.side_effect = None
            clean.return_value = [{'exception': 'cleanup fixture'}]
            with self.assertRaisesRegex(ValueError, 'original validation error') as raised:
                exec(stages[6], env)
            self.assertIn('Resource cleanup incomplete', raised.exception.__notes__[0])
            self.assertEqual(env['_validation_summary']['status'], 'failed')
            self.assertEqual(env['_validation_summary']['failure']['exception'], 'ValueError')
            self.assertEqual(len(env['_validation_summary']['cleanup_errors']), 1)

    def test_duplicate_creation_keeps_original_ownership_and_does_not_create_again(self):
        with operations(instrumented=False) as (env, stages, clean, calls, clock, output, done):
            exec(stages[1], env)
            original_key = env['input_idempotency_key']
            with self.assertRaisesRegex(RuntimeError, 'already attempted'):
                exec(stages[1], env)
            env['client'].beta.agents.sessions.create.assert_called_once()
            self.assertEqual(env['input_idempotency_key'], original_key)
            self.assertIn('session-fixture', env['sessions'])
            clean.assert_called_once()

    def test_failed_session_stops_before_retrieving_a_turn(self):
        with operations() as (env, stages, clean, calls, clock, output, done):
            for step in [1, 2]:
                exec(stages[step], env)
            api = env['client'].beta.agents.sessions
            api.retrieve.side_effect = None
            api.retrieve.return_value = SimpleNamespace(status='failed', required_actions=[])
            with self.assertRaisesRegex(RuntimeError, 'Session failed'):
                exec(stages[3], env)
            api.turns.retrieve.assert_not_called()
            api.events.create.assert_called_once()
            clean.assert_called_once()

    def test_stream_eof_while_original_turn_active_does_not_report_completion(self):
        with operations(early=False) as (env, stages, clean, calls, clock, output, done):
            for step in [1, 2]:
                exec(stages[step], env)
            api = env['client'].beta.agents.sessions
            active = SimpleNamespace(id=done.id, status='in_progress', subagent_id=None)
            api.events.stream.side_effect = [Stream([], calls, 'eof')]
            api.turns.retrieve.side_effect = [active, active]
            with self.assertRaisesRegex(RuntimeError, 'in_progress; do not resubmit'):
                exec(stages[3], env)
            self.assertTrue(env['observer_reconnected'])
            self.assertFalse(env['report_downloaded'])
            api.events.create.assert_called_once()
            clean.assert_called_once()

    def test_foreign_or_child_turn_cannot_be_used_for_recovery(self):
        for identity, child in [('another-turn', None), ('turn-fixture', 'child')]:
            with self.subTest(identity=identity, child=child), operations() as fixture:
                env, stages, clean, calls, clock, output, done = fixture
                for step in [1, 2]:
                    exec(stages[step], env)
                api = env['client'].beta.agents.sessions
                api.turns.retrieve.side_effect = None
                api.turns.retrieve.return_value = SimpleNamespace(id=identity, subagent_id=child)
                with self.assertRaisesRegex(RuntimeError, 'not the original root turn'):
                    exec(stages[3], env)
                self.assertFalse(env['report_downloaded'])
                clean.assert_called_once()

    def test_final_answer_selection_excludes_other_turns_and_interim_messages(self):
        with operations(instrumented=False) as (env, stages, clean, calls, clock, output, done):
            api = env['client'].beta.agents.sessions
            original = list(api.items.list())
            original.extend([
                SimpleNamespace(type='message', turn_id='other', role='assistant', phase='final_answer', output_text='INVALID'),
                SimpleNamespace(type='message', turn_id=done.id, role='assistant', phase='commentary', output_text='INVALID'),
            ])
            api.items.list.side_effect = lambda *a, **kw: Pages([original], calls, 'filtered-items')
            for step in range(1, 5):
                exec(stages[step], env)
            self.assertTrue(env['report_downloaded'])
            env['display'].assert_called_once()
            self.assertEqual(len(env['downloaded_artifacts']), 2)
            self.assertEqual({a['turn_id'] for a in env['downloaded_artifacts']}, {done.id})
            clean.assert_not_called()

    def test_malformed_final_answer_has_an_actionable_error(self):
        with operations() as (env, stages, clean, calls, clock, output, done):
            for step in [1, 2, 3]:
                exec(stages[step], env)
            api = env['client'].beta.agents.sessions
            api.items.list.side_effect = None
            api.items.list.return_value = [SimpleNamespace(id='bad', type='message', turn_id=done.id,
                role='assistant', phase='final_answer', output_text='not JSON')]
            with self.assertRaisesRegex(RuntimeError, 'not the requested JSON'):
                exec(stages[4], env)
            self.assertFalse(env['report_downloaded'])
            clean.assert_called_once()

    def test_partial_streaming_download_resets_success_flag(self):
        with operations() as (env, stages, clean, calls, clock, output, done):
            for step in [1, 2, 3]:
                exec(stages[step], env)
            api = env['client'].beta.agents.sessions
            api.artifacts.with_streaming_response.content.side_effect = [
                contextlib.nullcontext(SimpleNamespace(stream_to_file=lambda path: Path(path).write_text('{}'))),
                OSError('download interrupted'),
            ]
            env['report_downloaded'] = True
            with self.assertRaisesRegex(OSError, 'download interrupted'):
                exec(stages[4], env)
            self.assertFalse(env['report_downloaded'])
            self.assertEqual(len(env['downloaded_artifacts']), 1)
            self.assertEqual(api.artifacts.with_streaming_response.content.call_args.kwargs['timeout'], 30)
            clean.assert_called_once()

    def test_validation_rejects_tampered_recovery_evidence(self):
        mutations = [
            lambda env: env['request_state'].update(session_id='foreign'),
            lambda env: env['request_state'].update(turn_id='foreign'),
            lambda env: env['request_state'].update(idempotency_key='foreign'),
            lambda env: env['request_state'].update(submission_state='attempting'),
            lambda env: env['downloaded_artifacts'][0].update(turn_id='foreign'),
            lambda env: setattr(env['messages'][0], 'phase', 'commentary'),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index), operations() as (env, stages, clean, calls, clock, output, done):
                for step in range(1, 6):
                    exec(stages[step], env)
                mutate(env)
                with self.assertRaises(ValueError):
                    exec(stages[6], env)
                self.assertEqual(env['_validation_summary']['status'], 'failed')
                clean.assert_called_once()

    def test_final_cleanup_failure_cannot_produce_a_passed_receipt(self):
        with operations() as (env, stages, clean, calls, clock, output, done):
            for step in range(1, 6):
                exec(stages[step], env)
            clean.side_effect = OSError('cleanup fixture')
            with self.assertRaisesRegex(RuntimeError, 'cleanup incomplete'):
                exec(stages[6], env)
            self.assertEqual(env['_validation_summary']['status'], 'failed')
            self.assertEqual(env['_validation_summary']['cleanup_errors'][0]['exception'], 'OSError')


if __name__ == '__main__':
    unittest.main()
