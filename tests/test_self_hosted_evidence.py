"""Inspect actual notebook cells with synthetic API/Docker data; never use live services."""
from contextlib import ExitStack, redirect_stdout
import ast
import hashlib
import io
import json
import re
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch
from tutorial_helpers.deployment import prepare_executor, inspect_executor
from tutorial_helpers.common import cleanup_on_error, check_event
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def source(identifier):
    notebook = json.loads((ROOT/'notebooks/chapters/12_self_hosted.ipynb').read_text())
    return ''.join(next(c['source'] for c in notebook['cells'] if c['id'] == identifier))


class SelfHostedEvidenceTests(unittest.TestCase):
    def test_overview_is_markdown_and_uses_the_runnable_environment_configuration(self):
        notebook = json.loads((ROOT/'notebooks/chapters/12_self_hosted.ipynb').read_text())
        overview = next(c for c in notebook['cells'] if c['id']=='12-self-hosted-overview')
        self.assertEqual(overview['cell_type'], 'markdown')
        snippet = re.search(r'```python\n(.*?)\n```', ''.join(overview['source']), re.S).group(1)
        def environment(text):
            tree = ast.parse(text)
            call = next(n for n in ast.walk(tree) if isinstance(n,ast.Call)
                        and ast.unparse(n.func)=='client.beta.agents.sessions.create')
            return ast.literal_eval(next(k.value for k in call.keywords if k.arg=='environment'))
        self.assertEqual(environment(snippet), environment(source('8c61da61')))
        self.assertEqual(sum('api_workflow' in c['metadata'].get('tags',[]) for c in notebook['cells']),1)

    def inspect(self, directory, items, *, matching_hash=True):
        csv_text = 'date,product,quantity,unit_price\n2026-01-01,A,1,42\n'
        for name in ['summary.json', 'report.md', 'package_evidence.json']:
            (directory/name).write_text('# fixture report' if name.endswith('.md') else '{}')
        evidence = {
            'distribution': 'acme-sales', 'version': '0.1.0',
            'module_file': '/opt/venv/lib/python3.12/site-packages/acme_sales/__init__.py',
            'input_sha256': hashlib.sha256(csv_text.encode()).hexdigest() if matching_hash else 'different',
        }
        client, docker = Mock(), Mock()
        namespace = dict(items=items, result=SimpleNamespace(turn_id='current-turn', session_id='session-fixture', output_text='{}'),
                         report_downloaded=True,
                         execution_context={'container_id':'container-fixture','environment_id':'environment-fixture'},
                         evidence=evidence, csv_text=csv_text, csv_bytes=csv_text.encode(), downloads=directory,
                         hashlib=hashlib, json=json, client=client, docker=docker)
        (directory/'package_evidence.json').write_text(json.dumps(evidence))
        output = io.StringIO()
        with redirect_stdout(output):
            exec(source('12-execution-evidence-display'), namespace)
        self.assertEqual(client.mock_calls, [])
        docker.assert_not_called()
        return output.getvalue()

    def test_inspection_after_cleanup_is_read_only_and_filters_other_turns(self):
        command = SimpleNamespace(type='command_execution', turn_id='current-turn',
                                  id='command-current', command='/opt/venv/bin/python run_report.py',
                                  cwd='/workspace', status='completed', exit_code=0, output='report-created')
        other = SimpleNamespace(type='command_execution', turn_id='older-turn', command='older-command')
        message = SimpleNamespace(type='message')
        with tempfile.TemporaryDirectory() as temporary:
            output = self.inspect(Path(temporary), [command, other, message])
        for expected in ['Captured command executions: 1', 'command-current', 'report-created',
                         'Session: session-fixture', 'container-fixture',
                         'Working directory: /workspace', 'Exit code: 0',
                         'Input SHA-256 matches: True', 'Installed under /opt/venv: True', 'Saved file:']:
            self.assertIn(expected, output)
        self.assertNotIn('older-command', output)

    def test_missing_commands_missing_exit_code_and_hash_mismatch_are_visible(self):
        command = SimpleNamespace(type='command_execution', turn_id='current-turn',
                                  id='pending-command', command='python run_report.py',
                                  cwd=None, status='in_progress', exit_code=None, output=None)
        with tempfile.TemporaryDirectory() as temporary:
            output = self.inspect(Path(temporary), [], matching_hash=False)
            self.assertIn('execution was not confirmed', output)
            self.assertIn('Input SHA-256 matches: False', output)
            output = self.inspect(Path(temporary), [command])
            self.assertIn('Exit code: None', output)
            self.assertIn('(No captured output)', output)
            self.assertNotIn('Exit code: 0', output)

    def test_wrong_container_environment_blocks_input_and_still_cleans_up(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            client = Mock()
            session = SimpleNamespace(id='session-fixture', environment=SimpleNamespace(
                id='environment-fixture', remote_url='https://example.invalid/executor'))
            client.beta.agents.sessions.create.return_value = session
            connection = MagicMock()
            connection.__enter__.return_value = iter([SimpleNamespace(
                type='agent.session.environment.connected', environment=session.environment)])
            client.beta.agents.sessions.events.stream.return_value = connection
            provider = MagicMock()
            provider.package_environment.return_value = ('network-fixture', 'worker-fixture')
            provider.create.return_value = 'container-fixture'
            provider.assert_owned = Mock()
            provider.assert_owned.return_value = {'Config': {'Env': ['ENVIRONMENT_ID=wrong-environment']}}
            manager, secret = MagicMock(), MagicMock()
            manager.__enter__.return_value = provider
            secret.__enter__.return_value = root/'unused-fixture-secret'
            cleanup = Mock(return_value=[])
            namespace = dict(ExitStack=ExitStack, uuid4=uuid4, time=time, json=json,
                             settings=SimpleNamespace(root=root, model='fixture-model'), root=root,
                             CHAPTER='12_self_hosted', client=client, BASE_INSTRUCTIONS='fixture',
                             csv_bytes=b'fixture', image_input_sha256=hashlib.sha256(b'fixture').hexdigest(), hashlib=hashlib, check_event=check_event,
                             task='fixture task', new_session_metadata=Mock(return_value={}),
                             prepare_executor=prepare_executor, inspect_executor=inspect_executor,
                             EXECUTOR_IMAGE='fixture-image', key='fixture-key', docker=Mock(),
                             cleanup_resources=cleanup, cleanup_on_error=cleanup_on_error)
            with (
                redirect_stdout(io.StringIO()),
                patch('tutorial_helpers.deployment.DockerLab', return_value=manager),
                patch('tutorial_helpers.deployment.executor_secret', return_value=secret),
                patch('tutorial_helpers.deployment.docker'),
                patch('tutorial_helpers.common.cleanup_resources', cleanup),
                self.assertRaisesRegex(RuntimeError, 'different environment'),
            ):
                for identifier in ['12-run-state', '8c61da61', '12-step-2-code', '12-step-3-code']:
                    exec(source(identifier), namespace)
            client.beta.agents.sessions.stream.assert_not_called()
            cleanup.assert_called_once()
            manager.__exit__.assert_called_once()
            secret.__exit__.assert_called_once()


class DockerExecutorHelperTests(unittest.TestCase):
    def fixture(self):
        provider, manager, secret = MagicMock(), MagicMock(), MagicMock()
        provider.package_environment.return_value = ('network-fixture', 'worker-fixture')
        provider.create.return_value = 'container-fixture'
        manager.__enter__.return_value = provider
        secret.__enter__.return_value = Path('/fixture/key-file')
        return provider, manager, secret

    def test_preparation_forwards_connection_values_without_starting_executor(self):
        provider, manager, secret = self.fixture()
        remote = 'https://example.invalid/connect?opaque=1'
        with (
            patch('tutorial_helpers.deployment.DockerLab', return_value=manager),
            patch('tutorial_helpers.deployment.executor_secret', return_value=secret),
            patch('tutorial_helpers.deployment.docker') as docker,
        ):
            with prepare_executor(environment_id='environment-fixture', remote_url=remote,
                                  key='fixture-key', root=ROOT) as (actual, identifier):
                self.assertIs(actual, provider)
                self.assertEqual(identifier, 'container-fixture')
                provider.start.assert_not_called()
                arguments = provider.create.call_args.kwargs['arguments']
                self.assertIn('ENVIRONMENT_ID=environment-fixture', arguments)
                self.assertIn('REMOTE_URL='+remote, arguments)
                self.assertNotIn('fixture-key', str(arguments))
            docker.assert_called_once_with(['network','connect','network-fixture','container-fixture'])
        manager.__exit__.assert_called_once()
        secret.__exit__.assert_called_once()

    def test_partial_preparation_failure_releases_resources(self):
        provider, manager, secret = self.fixture()
        with (
            patch('tutorial_helpers.deployment.DockerLab', return_value=manager),
            patch('tutorial_helpers.deployment.executor_secret', return_value=secret),
            patch('tutorial_helpers.deployment.docker', side_effect=RuntimeError('network-failed')),
            self.assertRaisesRegex(RuntimeError, 'network-failed'),
        ):
            with prepare_executor(environment_id='environment-fixture', remote_url='https://example.invalid',
                                  key='fixture-key', root=ROOT):
                self.fail('Preparation must fail before yielding')
        provider.start.assert_not_called()
        manager.__exit__.assert_called_once()
        secret.__exit__.assert_called_once()

    def test_snapshot_contains_only_selected_fields_and_no_key_or_remote_url(self):
        provider = Mock()
        provider.output_dir = Path('/fixture/docker-state')
        provider.assert_owned = Mock(return_value={
            'Id':'container-fixture','Name':'/executor-fixture',
            'Config':{'Image':'fixture-image','Hostname':'fixture-host',
                      'Env':['ENVIRONMENT_ID=environment-fixture','CODEX_API_KEY=private-fixture',
                             'REMOTE_URL=https://secret-endpoint.invalid']},
        })
        result = inspect_executor(provider, 'container-fixture', expected_environment_id='environment-fixture')
        self.assertEqual(result['container_environment_id'], 'environment-fixture')
        self.assertEqual(result['container_name'], 'executor-fixture')
        self.assertEqual(result['docker_state_file'], '/fixture/docker-state/state.json')
        self.assertNotIn('private-fixture', json.dumps(result))
        self.assertNotIn('secret-endpoint.invalid', json.dumps(result))
        provider.assert_owned.assert_called_once_with('container-fixture')


if __name__ == '__main__':
    unittest.main()
