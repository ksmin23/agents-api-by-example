"""Saved Agent reuse through actual notebook cells and fake API resources."""
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

import httpx2
import nbformat
from openai import NotFoundError
from tutorial_helpers.common import (
    cleanup_on_error, cleanup_resources, check_event, new_session_metadata,
    safe_error, save_agent_reference,
)
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
        calls, owned, deleted = [], {}, set()
        clock = SimpleNamespace(now=0)
        base_instructions = 'Use Python and return JSON.'
        override = base_instructions + ' Use compact commentary.'
        saved = SimpleNamespace(id='agent-fixture', model='fixture', instructions=base_instructions)
        turns = [SimpleNamespace(id=f'turn-{i}', status='completed', subagent_id=None, usage=None) for i in [1, 2]]
        results = [SimpleNamespace(session_id=f'session-{i}', turn_id=t.id, turn=t,
                                   output_text=json.dumps(expected)) for i, t in enumerate(turns, 1)]
        streams = []
        for result in results:
            events = [SimpleNamespace(type='agent.session.created', session=SimpleNamespace(
                id=result.session_id, environment=SimpleNamespace(id='environment-' + result.session_id))),
                SimpleNamespace(type='agent.session.turn.output_text.delta', delta=result.output_text),
                SimpleNamespace(type='agent.session.turn.completed', turn=result.turn)]
            stream = Mock()
            stream.with_result_collection.return_value = stream
            stream.__enter__ = Mock(return_value=stream)
            stream.__exit__ = Mock(return_value=False)
            stream.__iter__ = Mock(side_effect=lambda events=events: iter(events))
            stream.get_final_result.return_value = result
            streams.append(stream)
        client = Mock()
        client.beta.agents.create.side_effect = lambda **kw: calls.append('agent.create') or saved
        def create(**kw):
            index = 0 if kw['metadata']['label'] == 'base' else 1
            result = results[index]
            owned[result.session_id] = SimpleNamespace(
                id=result.session_id, status='idle', metadata=kw['metadata'],
                agent=SimpleNamespace(model=saved.model, instructions=kw.get('agent', {}).get('instructions', saved.instructions)))
            calls.append('session.create:' + result.session_id)
            return streams[index]
        client.beta.agents.sessions.create.side_effect = create
        def missing():
            return NotFoundError('fixture', response=httpx2.Response(
                404, request=httpx2.Request('GET', 'https://api.openai.com/fixture')), body=None)
        def retrieve_session(sid, **kw):
            if sid in deleted:
                raise missing()
            return owned[sid]
        client.beta.agents.sessions.retrieve.side_effect = retrieve_session
        client.beta.agents.sessions.list.side_effect = lambda metadata, **kw: [
            obj for obj in owned.values() if obj.id not in deleted and all(obj.metadata.get(k) == v for k, v in metadata.items())]
        client.beta.agents.sessions.turns.retrieve.side_effect = lambda tid, **kw: next(t for t in turns if t.id == tid)
        client.beta.agents.sessions.items.list.side_effect = lambda sid, **kw: [SimpleNamespace(
            type='command_execution', command='python analyze.py', exit_code=0, status='completed',
            turn_id=next(r.turn_id for r in results if r.session_id == sid))]
        def delete_session(sid, **kw):
            calls.append('session.delete:' + sid)
            deleted.add(sid)
            return SimpleNamespace(deleted=True)
        client.beta.agents.sessions.delete.side_effect = delete_session
        def retrieve_agent(aid, **kw):
            if aid in deleted:
                raise missing()
            return saved
        client.beta.agents.retrieve.side_effect = retrieve_agent
        def delete_agent(aid, **kw):
            calls.append('agent.delete')
            deleted.add(aid)
            return SimpleNamespace(deleted=True)
        client.beta.agents.delete.side_effect = delete_agent
        def cleanup(*args):
            calls.append('cleanup')
            return cleanup_resources(*args)
        clean = Mock(side_effect=cleanup)
        env = dict(settings=SimpleNamespace(root=root, model='fixture', api_key=None),
                   CHAPTER='04_agent_configuration', client=client, uuid4=uuid4, json=json, sys=sys,
                   csv_text=csv_text, task='CSV fixture', BASE_INSTRUCTIONS=base_instructions,
                   override_instructions=override, environment={'type': 'openai_hosted'},
                   time=SimpleNamespace(monotonic=lambda: clock.now), cleanup_on_error=cleanup_on_error,
                   cleanup_resources=clean, new_session_metadata=new_session_metadata,
                   save_agent_reference=save_agent_reference, check_event=check_event, safe_error=safe_error)
        nb = nbformat.read(ROOT / 'notebooks/chapters/04_agent_configuration.ipynb', as_version=4)
        if instrumented:
            instrument_notebook(nb, '04_agent_configuration', live=True)
        steps = {i: next(c.source for c in nb.cells if f'configuration_step_{i}' in c.metadata.get('tags', [])) for i in range(1, 6)}
        # Let the real error-cleanup context call the same recorder, without recursion.
        with patch('tutorial_helpers.common.cleanup_resources', clean), contextlib.redirect_stdout(io.StringIO()) as output:
            if instrumented:
                exec(nb.cells[0].source, env)
                def validate(*args):
                    calls.append('validate')
                    return validate_lesson(*args)
                env.update(_validate_lesson=validate, _save_validation=save_validation)
            exec(next(c.source for c in nb.cells if c.id == '0e906bf4e4d7'), env)
            try:
                yield env, steps, clean, calls, clock, output, streams, owned
            finally:
                env.pop('_validation_error', None)
                env.clear()


class ConfigurationStepTests(unittest.TestCase):
    def test_defaults_override_reference_and_session_before_agent_cleanup(self):
        for instrumented in [False, True]:
            with self.subTest(instrumented=instrumented), lesson(instrumented) as (env, steps, clean, calls, clock, output, streams, owned):
                exec(steps[1], env)
                reference = json.loads((env['output_dir'] / 'agent.json').read_text())
                self.assertEqual(reference, {'run_id': env['run_id'], 'agent_id': 'agent-fixture'})
                self.assertFalse((env['output_dir'] / 'agent.json.tmp').exists())
                clock.now = 2000
                exec(steps[2], env)
                self.assertEqual(env['started'], 2000)
                clock.now = 5000
                exec(steps[3], env)
                self.assertEqual(env['started'], 5000)
                requests = env['client'].beta.agents.sessions.create.call_args_list
                self.assertEqual(len(requests), 2)
                self.assertNotIn('agent', requests[0].kwargs)
                self.assertEqual(requests[1].kwargs['agent'], {'instructions': env['override_instructions']})
                for request in requests:
                    self.assertEqual(request.kwargs['agent_id'], 'agent-fixture')
                    self.assertEqual(request.kwargs['input'], env['task'])
                exec(steps[4], env)
                self.assertTrue(all(env['configuration_checks'].values()))
                clean.assert_not_called()
                exec(steps[5], env)
                clean.assert_called_once()
                self.assertTrue(all(v['verified_absent'] for v in [*env['sessions'].values(), *env['agents'].values()]))
                self.assertLess(calls.index('session.delete:session-1'), calls.index('agent.delete'))
                self.assertLess(calls.index('session.delete:session-2'), calls.index('agent.delete'))
                self.assertIn('Base analysis:', output.getvalue())
                self.assertIn('Override analysis:', output.getvalue())
                self.assertIn('agent_cleanup', output.getvalue())
                if instrumented:
                    self.assertLess(calls.index('validate'), calls.index('cleanup'))
                    self.assertEqual(env['_validation_summary']['status'], 'passed')

    def test_errors_in_each_precleanup_stage_clean_owned_resources(self):
        for failed in range(1, 5):
            with self.subTest(stage=failed), lesson(True) as (env, steps, clean, calls, clock, output, streams, owned):
                for i in range(1, failed):
                    exec(steps[i], env)
                if failed == 1:
                    env['client'].beta.agents.create.side_effect = RuntimeError('create fixture')
                elif failed in [2, 3]:
                    streams[failed - 2].__iter__.side_effect = SimulatedInterruption('stream fixture')
                else:
                    env['client'].beta.agents.sessions.retrieve.side_effect = RuntimeError('retrieve fixture')
                with self.assertRaises(SimulatedInterruption if failed in [2, 3] else RuntimeError):
                    exec(steps[failed], env)
                clean.assert_called_once()
                if failed > 1:
                    self.assertIn('agent.delete', calls)
                self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_reference_write_failure_still_cleans_up_agent(self):
        with lesson(True) as (env, steps, clean, calls, *rest):
            env['save_agent_reference'] = Mock(side_effect=OSError('disk fixture'))
            with self.assertRaises(OSError):
                exec(steps[1], env)
            self.assertIn('agent.delete', calls)
            self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_failed_turn_does_not_reach_configuration_comparison(self):
        with lesson(True) as (env, steps, clean, calls, clock, output, streams, owned):
            exec(steps[1], env)
            streams[0].get_final_result.return_value.turn.status = 'failed'
            with self.assertRaisesRegex(RuntimeError, 'completion'):
                exec(steps[2], env)
            self.assertIn('agent.delete', calls)
            self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_repeated_creation_cells_do_not_create_duplicate_resources(self):
        for step in [1, 2, 3]:
            with self.subTest(stage=step), lesson() as (env, steps, clean, calls, *rest):
                for i in range(1, step + 1):
                    exec(steps[i], env)
                with self.assertRaises(RuntimeError):
                    exec(steps[step], env)
                env['client'].beta.agents.create.assert_called_once()
                self.assertEqual(env['client'].beta.agents.sessions.create.call_count, max(0, step - 1))
                clean.assert_called_once()

    def test_settings_drift_is_rejected_by_notebook_and_validator(self):
        for field in ['base_model', 'override_model', 'saved_model', 'base_instructions', 'saved_instructions', 'override_instructions']:
            with self.subTest(field=field), lesson(True) as (env, steps, clean, calls, clock, output, streams, owned):
                for i in [1, 2, 3, 4]:
                    exec(steps[i], env)
                target = (env['saved_again'] if field.startswith('saved') else
                          env['base_session'].agent if field.startswith('base') else env['custom_session'].agent)
                setattr(target, 'model' if field.endswith('model') else 'instructions', 'changed')
                # Stronger runner check must reject even without the notebook's comparison.
                items = [item for sid in env['sessions'] for item in env['client'].beta.agents.sessions.items.list(sid)]
                with self.assertRaises(ValueError):
                    validate_lesson('04_agent_configuration', env, items)
                with self.assertRaisesRegex(RuntimeError, 'Applied settings'):
                    exec(steps[4], env)
                clean.assert_called_once()

    def test_partial_execution_cleans_only_created_resources(self):
        for count in [0, 1, 2]:
            with self.subTest(count=count), lesson() as (env, steps, clean, calls, *rest):
                for i in range(1, count + 1):
                    exec(steps[i], env)
                exec(steps[5], env)
                self.assertEqual(len(env['agents']), min(count, 1))
                self.assertEqual(len(env['sessions']), max(0, count - 1))
                clean.assert_called_once()

    def test_validation_error_survives_cleanup_failure(self):
        with lesson(True) as (env, steps, clean, calls, *rest):
            for i in [1, 2, 3, 4]:
                exec(steps[i], env)
            env['_validate_lesson'] = Mock(side_effect=ValueError('validation fixture'))
            clean.side_effect = RuntimeError('cleanup fixture')
            with self.assertRaisesRegex(ValueError, 'validation fixture') as raised:
                exec(steps[5], env)
            self.assertTrue(raised.exception.__notes__)
            self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_lost_agent_response_has_no_false_recovery_reference(self):
        with lesson(True) as (env, steps, clean, calls, *rest):
            env['client'].beta.agents.create.side_effect = ConnectionError('response lost')
            with self.assertRaises(ConnectionError):
                exec(steps[1], env)
            self.assertFalse((env['output_dir'] / 'agent.json').exists())
            self.assertTrue(env['agent_creation_attempted'])
            env['client'].beta.agents.list.assert_not_called()
            self.assertEqual(env['_validation_summary']['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
