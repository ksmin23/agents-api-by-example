"""Self-hosted source invariants using simulated API/Docker; no live resources."""
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import nbformat
from test_self_hosted_steps import execution, Stream
from tutorial_helpers.validation import validate_lesson

ROOT = Path(__file__).resolve().parents[1]


class SelfHostedContractTests(unittest.TestCase):
    def test_repeated_creation_keeps_original_ownership_and_blocks_another_session(self):
        with execution() as (env, steps, clean, calls, clock, output, provider, secret):
            exec(steps[1], env)
            session, run_id, attempts = env['session'], env['run_id'], list(env['attempts'])
            with self.assertRaisesRegex(RuntimeError, 'Do not resubmit'):
                exec(steps[1], env)
            self.assertIs(env['session'], session)
            self.assertEqual(env['run_id'], run_id)
            self.assertEqual(env['attempts'], attempts)
            env['client'].beta.agents.sessions.create.assert_called_once()
            self.assertTrue(env['sessions'][session.id]['verified_absent'])

    def test_image_input_mismatch_blocks_session_creation(self):
        with execution() as (env, steps, clean, calls, clock, output, provider, secret):
            env['image_input_sha256'] = 'different'
            with self.assertRaisesRegex(RuntimeError, 'fixed CSV bytes'):
                exec(steps[1], env)
            env['client'].beta.agents.sessions.create.assert_not_called()
            env['prepare_executor'].assert_not_called()

    def test_preparation_and_start_cannot_allocate_or_start_twice(self):
        for repeat in [2, 3]:
            with self.subTest(repeat=repeat), execution() as (env, steps, clean, calls, clock, output, provider, secret):
                for step in range(1, repeat+1): exec(steps[step], env)
                with self.assertRaisesRegex(RuntimeError, 'only once'):
                    exec(steps[repeat], env)
                env['prepare_executor'].assert_called_once()
                self.assertEqual(provider.start.call_count, repeat-2)
                clean.assert_called_once()
                self.assertFalse(secret.exists())

    def test_ready_alone_is_not_connection_but_connected_after_ready_is_accepted(self):
        for include_connected in [False, True]:
            with self.subTest(include_connected=include_connected), execution() as (env, steps, clean, calls, clock, output, provider, secret):
                for step in [1, 2]: exec(steps[step], env)
                types = ['ready'] + (['connected'] if include_connected else [])
                events = [SimpleNamespace(type='agent.session.environment.'+kind, environment=env['session'].environment)
                          for kind in types]
                env['client'].beta.agents.sessions.events.stream.side_effect = lambda *a, **kw: Stream(events, calls, 'connection')
                if include_connected:
                    exec(steps[3], env)
                    self.assertTrue(env['connected'])
                    clean.assert_not_called()
                else:
                    with self.assertRaisesRegex(RuntimeError, 'did not connect'):
                        exec(steps[3], env)
                    self.assertFalse(env['connected'])
                    clean.assert_called_once()
                env['client'].beta.agents.sessions.stream.assert_not_called()

    def test_wrong_session_or_child_result_is_not_treated_as_root_work(self):
        for mode in ['session', 'child']:
            with self.subTest(mode=mode), execution() as (env, steps, clean, calls, clock, output, provider, secret):
                for step in [1, 2, 3]: exec(steps[step], env)
                def stream(*args, **kwargs):
                    turn = SimpleNamespace(id='turn-fixture', status='completed', subagent_id='child' if mode=='child' else None)
                    result = SimpleNamespace(session_id='wrong-session' if mode=='session' else env['session'].id,
                                             turn_id=turn.id, turn=turn)
                    return SimpleNamespace(with_result_collection=lambda: Stream([], calls, 'task', result))
                env['client'].beta.agents.sessions.stream.side_effect = stream
                with self.assertRaisesRegex(RuntimeError, 'Result differs'):
                    exec(steps[4], env)
                self.assertNotIn('wrong-session', env['sessions'])
                provider.copy_out.assert_not_called()

    def test_partial_collection_resets_prior_success_and_missing_result_does_not_copy(self):
        with execution() as (env, steps, clean, calls, clock, output, provider, secret):
            for step in range(1, 6): exec(steps[step], env)
            self.assertTrue(env['report_downloaded'])
            provider.copy_out.side_effect = OSError('partial copy fixture')
            with self.assertRaises(OSError): exec(steps[5], env)
            self.assertFalse(env['report_downloaded'])
        with execution() as (env, steps, clean, calls, clock, output, provider, secret):
            exec(steps[1], env)
            with self.assertRaisesRegex(RuntimeError, 'Complete input submission'):
                exec(steps[5], env)
            provider.copy_out.assert_not_called()

    def test_validator_binds_command_bytes_root_and_container(self):
        for mode in ['old_command', 'wrong_interpreter', 'read_only', 'wrong_input', 'wrong_output',
                     'none_exit', 'status', 'hash', 'image', 'container', 'container_environment', 'model']:
            with self.subTest(mode=mode), execution() as (env, steps, clean, calls, clock, output, provider, secret):
                for step in range(1, 6): exec(steps[step], env)
                item = env['items'][0]
                if mode == 'old_command':
                    env['items'] = [SimpleNamespace(**(vars(item) | {'turn_id': 'old'})),
                                    SimpleNamespace(**(vars(item) | {'command': '/opt/venv/bin/python other.py'}))]
                elif mode == 'wrong_interpreter': item.command = item.command.replace('/opt/venv/bin/python', 'python')
                elif mode == 'read_only': item.command = 'cat /opt/capabilities/skills/corporate-csv/scripts/run_report.py'
                elif mode == 'wrong_input': item.command = item.command.replace('/workspace/sales.csv', '/workspace/other.csv')
                elif mode == 'wrong_output': item.command = item.command.replace('/workspace/outputs', '/tmp/outputs')
                elif mode == 'none_exit': item.exit_code = None
                elif mode == 'status': item.status = 'in_progress'
                elif mode == 'hash':
                    path = env['downloads'] / 'package_evidence.json';evidence=json.loads(path.read_text())
                    evidence['input_sha256']='different';path.write_text(json.dumps(evidence))
                elif mode == 'image': env['image_input_sha256'] = 'different'
                elif mode == 'container': env['execution_context']['container_id'] = 'different'
                elif mode == 'container_environment': env['execution_context']['container_environment_id'] = 'different'
                else: env['result'].output_text = '{}'
                with self.assertRaises((ValueError, RuntimeError)):
                    validate_lesson('12_self_hosted', env, env['items'])

    def test_preparation_keeps_crlf_bytes_and_build_hash_without_invoking_api(self):
        notebook=nbformat.read(ROOT/'notebooks/chapters/12_self_hosted.ipynb',4)
        source=next(c.source for c in notebook.cells if c.id=='094fac4b2c32')
        prepare=next(c.source for c in notebook.cells if c.id=='12-image-preparation')
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()):
            root=Path(folder);(root/'data').mkdir()
            data=b'date,product,quantity,unit_price\r\n2026-01-01,A,1,42\r\n'
            (root/'data/sales.csv').write_bytes(data)
            env=dict(load_settings=lambda *a: SimpleNamespace(root=root,enabled=False,model='fixture'), os=__import__('os'), hashlib=hashlib)
            exec(source,env)
            self.assertEqual(env['csv_bytes'],data)
            self.assertIsNone(env['image_input_sha256'])
            generated=root/'deploy/.generated/data';generated.mkdir(parents=True);(generated/'sales.csv').write_bytes(data)
            env.update(docker_enabled=True, build_images=Mock(return_value={'executor':'fixture'}))
            exec(prepare,env)
            self.assertEqual(env['image_input_sha256'],hashlib.sha256(data).hexdigest())
            (generated/'sales.csv').write_bytes(b'different')
            with self.assertRaisesRegex(RuntimeError,'CSV changed'):
                exec(prepare,env)


if __name__=='__main__': unittest.main()
