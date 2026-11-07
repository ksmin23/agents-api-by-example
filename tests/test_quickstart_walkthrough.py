"""Run the actual combined Quickstart cell with fake SDK responses and real validation."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as Obj
import unittest
from unittest.mock import Mock
from uuid import uuid4

import nbformat
from tutorial_helpers.common import check_event, new_session_metadata, safe_error
from tutorial_helpers.validation import save_validation, validate_lesson

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from notebook_validation import instrument_notebook


class Item(Obj):
    def to_dict(self):
        return vars(self).copy()


class Pages:
    data = []

    def __init__(self, entries):
        self.entries = entries

    def __iter__(self):
        yield from self.entries


class Stream:
    def __init__(self, result):
        self.result = result
        self.events = [Obj(type='agent.session.created', session=Obj(id='session')),
                       Obj(type='agent.session.turn.output_text.delta', delta='Progress')]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def __iter__(self):
        yield from self.events

    def get_final_result(self):
        return self.result


@contextlib.contextmanager
def lesson(*, instrumented=True, with_creation_event=True):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)  # No data/sales.csv: this is a numeric exercise.
        turn = Obj(id='turn', status='completed', subagent_id=None, usage=None)
        result = Obj(session_id='session', turn_id=turn.id, turn=turn, output_text='{"count":3,"total":60}')
        stream = Stream(result)
        if not with_creation_event:
            stream.events = stream.events[1:]
        command = Item(id='python-item', type='command_execution', turn_id=turn.id,
                       command='python /workspace/quickstart_sum.py', status='completed',
                       exit_code=0, output='{"count":3,"total":60}\n')
        other = Item(id='other-turn', type='command_execution', turn_id='foreign',
                     command='python other.py', status='completed', exit_code=0, output='not this run')
        client = Mock()
        api = client.beta.agents.sessions
        api.create.return_value.with_result_collection.return_value = stream
        api.turns.retrieve.return_value = turn
        api.items.list.return_value = Pages([other, command])
        calls = []
        def cleanup(client, sessions, agents, attempts):
            calls.append('cleanup')
            for value in sessions.values():
                value.update(deleted=True, verified_absent=True)
            client.close()
            return []
        clean = Mock(side_effect=cleanup)
        env = dict(settings=Obj(root=root, model='fixture', api_key=None), client=client, request={},
                   uuid4=uuid4, json=json, sys=sys, cleanup_resources=clean,
                   check_event=check_event, new_session_metadata=new_session_metadata, safe_error=safe_error)
        notebook = nbformat.read(ROOT/'notebooks/quickstart.ipynb', as_version=4)
        if instrumented:
            instrument_notebook(notebook, 'preface', live=True)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            if instrumented:
                exec(notebook.cells[0].source, env)
                def validate(*args):
                    calls.append('validate')
                    return validate_lesson(*args)
                def save(*args, **kwargs):
                    calls.append('save')
                    return save_validation(*args, **kwargs)
                env.update(_validate_lesson=validate, _save_validation=save)
            exec(next(c.source for c in notebook.cells if c.id == 'quickstart-run-state'), env)
            workflow = next(c.source for c in notebook.cells if c.id == 'ecc18541c062')
            summary = next(c.source for c in notebook.cells if c.id == 'quickstart-preface-13')
            yield env, workflow, summary, api, clean, calls, output, stream, command


class QuickstartWalkthroughTests(unittest.TestCase):
    def test_result_and_original_command_history_are_inspected_before_automatic_cleanup(self):
        with lesson() as (env, cell, summary, api, clean, calls, output, stream, command):
            exec(cell, env)
            self.assertEqual(env['_validation_summary']['status'], 'passed')
            self.assertEqual([item.id for item in env['commands']], ['python-item'])
            text = output.getvalue()
            self.assertLess(text.index('Final JSON:'), text.index('Automatic session cleanup:'))
            self.assertLess(text.index('Command stdout/result:'), text.index('Automatic session cleanup:'))
            self.assertEqual(calls, ['validate', 'cleanup', 'save'])
            api.create.assert_called_once()
            client = env['client']
            client.close.assert_called_once()
            before = list(api.mock_calls)
            exec(summary, env)
            self.assertEqual(api.mock_calls, before)
            api.traces.list.assert_not_called()
            self.assertTrue(env['sessions']['session']['verified_absent'])

    def test_missing_creation_event_still_tracks_the_collected_session(self):
        with lesson(with_creation_event=False) as (env, cell, summary, api, clean, calls, output, stream, command):
            exec(cell, env)
            self.assertIn('session', env['sessions'])
            self.assertEqual(env['_validation_summary']['status'], 'passed')

    def test_duplicate_execution_stops_before_any_second_api_call_or_cleanup(self):
        with lesson() as (env, cell, summary, api, clean, calls, output, stream, command):
            exec(cell, env)
            with self.assertRaisesRegex(RuntimeError, 'already attempted'):
                exec(cell, env)
            api.create.assert_called_once()
            clean.assert_called_once()

    def test_foreign_child_and_failed_root_responses_are_not_success(self):
        for attribute, value in [('id', 'foreign'), ('subagent_id', 'child'), ('status', 'failed')]:
            with self.subTest(attribute=attribute), lesson() as fixture:
                env, cell, summary, api, clean, calls, output, stream, command = fixture
                original = stream.result.turn
                api.turns.retrieve.return_value = Obj(**{**vars(original), attribute:value})
                with self.assertRaisesRegex(RuntimeError, 'original completed root turn'):
                    exec(cell, env)
                clean.assert_called_once()
                self.assertFalse(env['results_checked'])
                self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_invalid_final_json_and_unexpected_actions_still_clean_up(self):
        for scenario in ['json', 'action']:
            with self.subTest(scenario=scenario), lesson() as fixture:
                env, cell, summary, api, clean, calls, output, stream, command = fixture
                if scenario == 'json':
                    stream.result.output_text = '{"count":true,"total":60}'
                else:
                    stream.events.append(Obj(type='agent.session.requires_action'))
                with self.assertRaises(RuntimeError):
                    exec(cell, env)
                clean.assert_called_once()
                self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_api_error_or_keyboard_interrupt_does_not_mask_cleanup(self):
        for error in [TimeoutError('request timeout'), KeyboardInterrupt()]:
            with self.subTest(error=type(error).__name__), lesson() as fixture:
                env, cell, summary, api, clean, calls, output, stream, command = fixture
                api.create.side_effect = error
                with self.assertRaises(type(error)):
                    exec(cell, env)
                clean.assert_called_once()
                self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_cleanup_error_cannot_replace_the_original_validation_error(self):
        with lesson() as (env, cell, summary, api, clean, calls, output, stream, command):
            env['_validate_lesson'] = Mock(side_effect=ValueError('original validation error'))
            clean.side_effect = OSError('cleanup error')
            with self.assertRaisesRegex(ValueError, 'original validation error') as raised:
                exec(cell, env)
            self.assertIn('cleanup incomplete', raised.exception.__notes__[0])
            self.assertEqual(env['_validation_summary']['status'], 'failed')
            self.assertEqual(env['_validation_summary']['cleanup_errors'][0]['exception'], 'OSError')

    def test_failed_final_cleanup_never_prints_verified(self):
        with lesson() as (env, cell, summary, api, clean, calls, output, stream, command):
            clean.side_effect = OSError('cleanup error')
            with self.assertRaisesRegex(RuntimeError, 'cleanup incomplete'):
                exec(cell, env)
            self.assertNotIn('Automatic session cleanup: verified', output.getvalue())
            self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_correct_stdout_from_foreign_or_mentioned_script_cannot_pass_validation(self):
        for scenario in ['foreign', 'echo', 'path', 'stdout']:
            with self.subTest(scenario=scenario), lesson() as fixture:
                env, cell, summary, api, clean, calls, output, stream, command = fixture
                if scenario == 'foreign':
                    command.turn_id = 'foreign'
                elif scenario == 'echo':
                    command.command = "echo 'python /workspace/quickstart_sum.py'"
                elif scenario == 'path':
                    command.command = 'python /workspace/quickstart_sum.py.bak'
                else:
                    command.output = '{"count":3,"total":61}'
                with self.assertRaises((RuntimeError, ValueError)):
                    exec(cell, env)
                clean.assert_called_once()
                self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_manual_execution_keeps_receipts_in_the_runner_only(self):
        with lesson(instrumented=False) as (env, cell, summary, api, clean, calls, output, stream, command):
            exec(cell, env)
            self.assertFalse((env['output_dir']/'summary.json').exists())
            self.assertTrue((env['output_dir']/'creation.json').exists())
            self.assertIn('Final JSON:', output.getvalue())
            clean.assert_called_once()


if __name__ == '__main__':
    unittest.main()
