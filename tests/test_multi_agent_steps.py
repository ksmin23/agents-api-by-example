"""Execute real chapter-15 stages with paginated SDK fixtures, never paid API calls."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import shlex
from types import SimpleNamespace as Obj
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import nbformat
from tutorial_helpers.common import cleanup_on_error, new_session_metadata, check_event, safe_error
from tutorial_helpers.validation import validate_lesson, save_validation
import test_multi_agent as fixtures

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from notebook_validation import instrument_notebook


class Pages:
    def __init__(self, entries):
        self.data = []  # The real entries are on a later SDK page.
        self.entries = entries

    def __iter__(self):
        yield from self.entries


class Stream:
    def __init__(self, events, result):
        self.events, self.result = events, result

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def __iter__(self):
        yield from self.events

    def get_final_result(self):
        return self.result


@contextlib.contextmanager
def lesson(*, instrumented=True):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / 'data').mkdir()
        for name in ['sales.csv', 'sales_targets.json']:
            (root / 'data' / name).write_bytes((ROOT / 'data' / name).read_bytes())
        samples = root / 'samples'
        samples.mkdir()
        evidence, root_items = fixtures.MultiAgentTests().fixture(samples)
        payloads = {p.name: p.read_bytes() for p in samples.iterdir()}
        workers = evidence['subagents']
        child_turns, child_items = evidence['child_turns'], evidence['child_items']
        artifacts = evidence['published']
        result, root_turn = evidence['result'], evidence['turn']
        session = Obj(id='session', environment=Obj(id='env'))
        stream = Stream([Obj(type='agent.session.created', session=session)] +
                        [Obj(type='agent.session.subagent.created', subagent=w) for w in workers], result)
        client = Mock()
        api = client.beta.agents.sessions
        api.create.return_value.with_result_collection.return_value = stream
        api.turns.retrieve.return_value = root_turn
        api.subagents.list.return_value = Pages(workers)
        api.subagents.items.list.side_effect = lambda sid, **kw: Pages(child_items[sid])
        api.subagents.turns.list.side_effect = lambda sid, **kw: Pages(child_turns[sid])
        api.subagents.turns.retrieve.side_effect = lambda tid, subagent_id, **kw: next(
            t for t in child_turns[subagent_id] if t.id == tid)
        api.items.list.return_value = Pages(root_items)
        api.artifacts.list.return_value = Pages(artifacts)
        api.artifacts.with_streaming_response.content.side_effect = lambda aid, **kw: contextlib.nullcontext(
            Obj(stream_to_file=lambda path: path.write_bytes(payloads[aid])))
        calls = []
        def cleanup(client, sessions, agents, attempts):
            calls.append('cleanup')
            for value in sessions.values():
                value.update(deleted=True, verified_absent=True)
            return []
        clean = Mock(side_effect=cleanup)
        env = dict(settings=Obj(root=root, model='fixture', api_key=None), client=client,
                   CHAPTER='15_multi_agent', PERIOD='2026-01', uuid4=uuid4, time=time, shlex=shlex, Path=Path,
                   sys=sys, json=json, cleanup_on_error=cleanup_on_error, cleanup_resources=clean,
                   new_session_metadata=new_session_metadata, check_event=check_event, safe_error=safe_error,
                   COORDINATOR_INSTRUCTIONS='fixture', TASK='fixture', environment={},
                   csv_bytes=(root/'data/sales.csv').read_bytes(),
                   targets_bytes=(root/'data/sales_targets.json').read_bytes(),
                   display=Mock(), Markdown=lambda text: text)
        notebook = nbformat.read(ROOT/'notebooks/chapters/15_multi_agent.ipynb', as_version=4)
        if instrumented:
            instrument_notebook(notebook, '15_multi_agent', live=True)
        stages = {step: next(c.source for c in notebook.cells if f'multi_agent_step_{step}' in c.metadata.get('tags', []))
                  for step in range(1, 7)}
        with patch('tutorial_helpers.common.cleanup_resources', clean), contextlib.redirect_stdout(io.StringIO()) as output:
            if instrumented:
                exec(notebook.cells[0].source, env)
                def validate(*args):
                    calls.append('validate')
                    return validate_lesson(*args)
                def save(*args, **kwargs):
                    calls.append('save')
                    return save_validation(*args, **kwargs)
                env.update(_validate_lesson=validate, _save_validation=save)
            exec(next(c.source for c in notebook.cells if c.id == 'multi-agent-15-12'), env)
            yield env, stages, api, clean, calls, output, artifacts


class MultiAgentStepTests(unittest.TestCase):
    def test_all_stages_keep_one_session_and_inspect_worker_published_files(self):
        with lesson() as (env, stages, api, clean, calls, output, artifacts):
            env['time'] = Obj(monotonic=lambda: 1000000)  # No timer starts in the preparation cell.
            for step in range(1, 6):
                exec(stages[step], env)
                clean.assert_not_called()
            api.create.assert_called_once()
            api.events.create.assert_not_called()
            api.traces.list.assert_not_called()
            self.assertEqual(set(env['role_executions']), {'structure.py', 'target.py'})
            self.assertEqual(api.subagents.turns.retrieve.call_count, 2)
            self.assertTrue(env['report_downloaded'])
            self.assertEqual({a['turn_id'] for a in env['downloaded_artifacts']}, {'root', 'structure-turn', 'target-turn'})
            env['display'].assert_called_once()
            self.assertIn('Coordinator command:', output.getvalue())
            exec(stages[6], env)
            self.assertEqual(env['_validation_summary']['status'], 'passed')
            self.assertLess(calls.index('validate'), calls.index('cleanup'))
            self.assertLess(calls.index('cleanup'), calls.index('save'))

    def test_duplicate_creation_does_not_resubmit_or_reset_ownership(self):
        with lesson() as (env, stages, api, clean, calls, output, artifacts):
            exec(stages[1], env)
            with self.assertRaisesRegex(RuntimeError, 'already attempted'):
                exec(stages[1], env)
            api.create.assert_called_once()
            self.assertIn('session', env['sessions'])
            clean.assert_called_once()

    def test_failed_child_or_foreign_root_stops_before_downloads(self):
        for scenario in ['child', 'root']:
            with self.subTest(scenario=scenario), lesson() as (env, stages, api, clean, calls, output, artifacts):
                exec(stages[1], env)
                if scenario == 'child':
                    api.subagents.turns.list.side_effect = lambda sid, **kw: Pages([Obj(id='bad', subagent_id=sid, status='failed')])
                else:
                    api.turns.retrieve.return_value = Obj(id='foreign', status='completed', subagent_id=None)
                with self.assertRaises(RuntimeError):
                    exec(stages[2], env)
                api.artifacts.list.assert_not_called()
                clean.assert_called_once()

    def test_script_mentions_and_failed_commands_are_not_execution(self):
        with lesson() as (env, stages, api, clean, calls, output, artifacts):
            for step in [1, 2]:
                exec(stages[step], env)
            env['child_items']['structure'] = [Obj(type='command_execution', status='completed', exit_code=0,
                command="echo 'python /workspace/workers/structure.py'", turn_id='structure-turn')]
            with self.assertRaisesRegex(RuntimeError, 'Missing or ambiguous'):
                exec(stages[3], env)
            clean.assert_called_once()

    def test_retrieved_command_owner_must_match_the_selected_worker(self):
        with lesson() as (env, stages, api, clean, calls, output, artifacts):
            for step in [1, 2]:
                exec(stages[step], env)
            api.subagents.turns.retrieve.side_effect = None
            api.subagents.turns.retrieve.return_value = Obj(id='structure-turn', subagent_id='foreign', status='completed')
            with self.assertRaisesRegex(RuntimeError, 'identity, owner, or completion'):
                exec(stages[3], env)
            self.assertFalse(env['commands_checked'])
            clean.assert_called_once()

    def test_missing_duplicate_and_foreign_artifacts_have_actionable_errors(self):
        for scenario in ['missing', 'duplicate', 'foreign']:
            with self.subTest(scenario=scenario), lesson() as (env, stages, api, clean, calls, output, artifacts):
                for step in [1, 2, 3]:
                    exec(stages[step], env)
                if scenario == 'missing':
                    artifacts.pop(0)
                elif scenario == 'duplicate':
                    artifacts.append(artifacts[0])
                else:
                    artifacts[0].turn_id = 'unrelated-turn'
                with self.assertRaisesRegex(RuntimeError, 'sales_breakdown.json; found'):
                    exec(stages[4], env)
                self.assertFalse(env['report_downloaded'])
                clean.assert_called_once()

    def test_partial_streaming_download_cannot_leave_success_flag(self):
        with lesson() as (env, stages, api, clean, calls, output, artifacts):
            for step in [1, 2, 3]:
                exec(stages[step], env)
            first = contextlib.nullcontext(Obj(stream_to_file=lambda p: p.write_text('{}')))
            api.artifacts.with_streaming_response.content.side_effect = [first, OSError('partial download')]
            env['report_downloaded'] = True
            with self.assertRaisesRegex(OSError, 'partial download'):
                exec(stages[4], env)
            self.assertFalse(env['report_downloaded'])
            self.assertEqual(len(env['downloaded_artifacts']), 1)
            clean.assert_called_once()

    def test_revenue_disagreement_stops_before_rendering_report(self):
        with lesson() as (env, stages, api, clean, calls, output, artifacts):
            for step in [1, 2, 3, 4]:
                exec(stages[step], env)
            path = env['downloads']/'target_assessment.json'
            data = json.loads(path.read_text()); data['total_revenue'] = 0
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(RuntimeError, 'revenues disagree'):
                exec(stages[5], env)
            env['display'].assert_not_called()
            clean.assert_called_once()

    def test_validation_error_survives_cleanup_error_and_receipt_is_failed(self):
        with lesson() as (env, stages, api, clean, calls, output, artifacts):
            for step in range(1, 6):
                exec(stages[step], env)
            env['_validate_lesson'] = Mock(side_effect=ValueError('original validation error'))
            clean.side_effect = OSError('cleanup error')
            with self.assertRaisesRegex(ValueError, 'original validation error') as raised:
                exec(stages[6], env)
            self.assertIn('cleanup incomplete', raised.exception.__notes__[0])
            self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_partial_manual_run_can_clean_up_before_result_retrieval(self):
        with lesson(instrumented=False) as (env, stages, api, clean, calls, output, artifacts):
            exec(stages[1], env)
            exec(stages[6], env)
            clean.assert_called_once()
            self.assertIn('not_completed', output.getvalue())


if __name__ == '__main__':
    unittest.main()
