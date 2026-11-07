"""Execute the split lesson with fake API streams; never submit paid requests."""
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
from tutorial_helpers.common import cleanup_on_error, new_session_metadata
from tutorial_helpers.extensions import ResultCache
from test_approval_walkthrough import Gate
from test_extensions import pending_responder

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from notebook_validation import instrument_notebook


class Stream:
    def __init__(self, scenario, responses):
        self.scenario, self.responses = scenario, responses

    def with_result_collection(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def __iter__(self):
        if self.scenario == 'analysis':
            yield SimpleNamespace(type='agent.session.created', session=SimpleNamespace(
                id='session-fixture', environment=SimpleNamespace(id='environment-fixture')))
        else:
            action = SimpleNamespace(type='function_call', name='publish_report',
                                     arguments={'report_id': 'sales-2026-01', 'channel': self.scenario},
                                     turn_id=self.scenario, call_id=self.scenario)
            yield SimpleNamespace(type='agent.session.requires_action', session=SimpleNamespace(
                id='session-fixture', required_actions=[action]))

    def get_final_result(self):
        if self.scenario == 'analysis':
            output = '{}'
        elif self.responses[-1]['success']:
            output = self.responses[-1]['output']
        else:
            output = json.dumps({'publication_status': 'denied', 'reason': self.responses[-1]['error']})
        return SimpleNamespace(session_id='session-fixture', turn_id=self.scenario,
                               turn=SimpleNamespace(status='completed'), output_text=output)


@contextlib.contextmanager
def lesson(entered='APPROVE', instrumented=False):
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        nb = nbformat.read(ROOT / 'notebooks/chapters/11_guardrails_approvals.ipynb', as_version=4)
        if instrumented:
            instrument_notebook(nb, '11_guardrails_approvals', live=True)
        stages = {}
        for cell in nb.cells:
            for step in range(1, 7):
                if f'approval_step_{step}' in cell.metadata.get('tags', []):
                    stages[step] = cell.source
        responses, calls = [], []
        clock = SimpleNamespace(now=0)
        api = Mock()
        api.beta.agents.sessions.create.return_value = Stream('analysis', responses)
        api.beta.agents.sessions.stream.side_effect = [Stream('external', responses), Stream('training', responses)]
        api.beta.agents.sessions.events.create.side_effect = lambda sid, events, **kw: responses.extend(events)
        api.beta.agents.sessions.turns.retrieve.return_value = SimpleNamespace(status='completed')
        api.beta.agents.sessions.retrieve.return_value = SimpleNamespace(review='none')
        api.beta.agents.sessions.items.list.side_effect = lambda *a, **kw: calls.append('history') or []

        def download(path, *, to, **kwargs):
            Path(to).write_text('# 매출 분석 보고서\nFixture report.\n' if path.endswith('.md') else '{}')
            return SimpleNamespace(id=Path(path).name, turn_id='analysis', path=path)
        api.beta.agents.sessions.artifacts.for_result.return_value = SimpleNamespace(download=download)

        def clean(client, sessions, agents, attempts):
            calls.append('cleanup')
            for value in sessions.values():
                value.update(deleted=True, verified_absent=True)
            return []
        cleanup = Mock(side_effect=clean)
        env = dict(settings=SimpleNamespace(root=root, model='fixture', api_key=None),
                   CHAPTER='11_guardrails_approvals', Path=Path, uuid4=uuid4, ResultCache=ResultCache,
                   time=SimpleNamespace(monotonic=lambda: clock.now), client=api, BASE_INSTRUCTIONS='fixture',
                   csv_text='fixture', csv_bytes=b'fixture', environment={}, REVIEW_MODE='none',
                   validate_input=lambda text: None, task='fixture', using_fixture=False, sys=sys,
                   safe_error=__import__('tutorial_helpers.common', fromlist=['safe_error']).safe_error,
                   PublicationGate=Gate, respond_to_pending=pending_responder, json=json,
                   base64=__import__('base64'), new_session_metadata=new_session_metadata,
                   cleanup_resources=cleanup, cleanup_on_error=cleanup_on_error, check_event=lambda event: None)
        from tutorial_helpers.extensions import interactive_approval
        env['approver'] = interactive_approval
        exec(next(c.source for c in nb.cells if c.id == '11d0dff23a8a'), env)
        state = next(c.source for c in nb.cells if c.id == '93a755da4cc0')

        def answer(prompt):
            clock.now += 1200  # Human input delay must not exhaust the API stage budget.
            return entered
        with patch('tutorial_helpers.common.cleanup_resources', cleanup), \
                patch('builtins.input', side_effect=answer), contextlib.redirect_stdout(io.StringIO()):
            exec(state, env)
            if instrumented:
                exec(nb.cells[0].source, env)
                from tutorial_helpers.validation import save_validation
                def save(*args, **kwargs):
                    calls.append('save')
                    return save_validation(*args, **kwargs)
                env['_save_validation'] = save
                env['_validate_lesson'] = lambda *a: (calls.append('validate') or {'fixture': True}, [])
            yield env, stages, cleanup, calls, clock


class ApprovalStepTests(unittest.TestCase):
    def test_both_choices_retain_session_between_steps_and_exclude_wait_time(self):
        for entered in ['APPROVE', 'REJECT']:
            with self.subTest(entered=entered), lesson(entered) as (env, stages, cleanup, calls, clock):
                for step in range(1, 6):
                    clock.now += 2000  # Time reading a previous cell must not count.
                    exec(stages[step], env)
                    cleanup.assert_not_called()
                self.assertEqual(env['registered'], entered == 'APPROVE')
                exec(stages[6], env)
                cleanup.assert_called_once()
                self.assertTrue(all(v['verified_absent'] for v in env['sessions'].values()))

    def test_cleanup_cell_can_end_a_partially_completed_manual_lesson(self):
        with lesson() as (env, stages, cleanup, calls, clock):
            exec(stages[1], env)
            exec(stages[2], env)
            exec(stages[6], env)
            self.assertEqual(env['decision_label'], 'not_completed')
            self.assertFalse(env['registered'])
            cleanup.assert_called_once()

    def test_each_step_failure_is_saved_after_error_cleanup(self):
        for target in range(1, 5):
            with self.subTest(step=target), lesson(instrumented=True) as (env, stages, cleanup, calls, clock):
                for step in range(1, target):
                    exec(stages[step], env)
                api = env['client'].beta.agents.sessions
                if target == 1:
                    api.create.side_effect = RuntimeError('fixture failure')
                elif target == 2:
                    api.artifacts.for_result.side_effect = RuntimeError('fixture failure')
                else:
                    api.stream.side_effect = RuntimeError('fixture failure')
                with self.assertRaisesRegex(RuntimeError, 'fixture failure'):
                    exec(stages[target], env)
                self.assertEqual(calls[-2:], ['cleanup', 'save'])
                self.assertEqual(env['_validation_summary']['status'], 'failed')
                cleanup.assert_called_once()

    def test_validation_runs_before_final_cleanup_and_failure_still_cleans(self):
        for fail in [False, True]:
            with self.subTest(fail=fail), lesson(instrumented=True) as (env, stages, cleanup, calls, clock):
                for step in range(1, 6):
                    exec(stages[step], env)
                if fail:
                    def invalid(*args):
                        calls.append('validate')
                        raise ValueError('fixture check failed')
                    env['_validate_lesson'] = invalid
                    with self.assertRaisesRegex(ValueError, 'fixture check failed'):
                        exec(stages[6], env)
                else:
                    exec(stages[6], env)
                self.assertEqual(calls[-4:], ['history', 'validate', 'cleanup', 'save'])
                self.assertEqual(env['_validation_summary']['status'], 'failed' if fail else 'passed')
                cleanup.assert_called_once()

    def test_keyboard_interrupt_is_not_converted_to_tool_failure(self):
        with lesson(instrumented=True) as (env, stages, cleanup, calls, clock):
            for step in range(1, 4):
                exec(stages[step], env)
            with patch('builtins.input', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
                exec(stages[4], env)
            cleanup.assert_called_once()
            self.assertEqual(env['_validation_summary']['failure']['exception'], 'KeyboardInterrupt')

    def test_error_cleanup_preserves_original_exception_when_cleanup_fails(self):
        errors = []
        with patch('tutorial_helpers.common.cleanup_resources', return_value=[{'exception': 'fixture'}]):
            with self.assertRaisesRegex(ValueError, 'original') as caught:
                with cleanup_on_error(None, {}, {}, [], errors=errors):
                    raise ValueError('original')
        self.assertTrue(errors)
        self.assertTrue(caught.exception.__notes__)


if __name__ == '__main__':
    unittest.main()
