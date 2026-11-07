"""Chapter 10 cells with fake Agents API and real execution from the inline Plugin ZIP."""
import base64
import hashlib
import shutil
import subprocess
import zipfile
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

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import nbformat
from openai.lib.beta.agents._artifacts import AgentResultArtifacts
from openai.types.beta.agent_mcp_call_item import AgentMcpCallItem
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
        shutil.copytree(ROOT / 'plugins', root / 'plugins')
        for source in ['data/sales.csv', 'data/sales_targets.json']:
            destination = root / source
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((ROOT / source).read_bytes())
        csv_text = (root / 'data/sales.csv').read_text()
        expected = analyze_csv(csv_text)
        target = json.loads((root / 'data/sales_targets.json').read_text())['2026-01']
        enriched = dict(metrics=expected, target_revenue=target['target_revenue'],
                        attainment_rate=expected['total_revenue'] / target['target_revenue'])
        calls, errors = [], {}
        clock = SimpleNamespace(now=0)
        turn = SimpleNamespace(id='turn-fixture', status='completed', subagent_id=None, usage=None)
        result = SimpleNamespace(session_id='session-fixture', turn_id=turn.id, turn=turn,
                                 output_text=json.dumps(enriched))
        call = AgentMcpCallItem(id='mcp-item', turn_id=turn.id, name='get_sales_target',
            arguments={'period': '2026-01'}, server_label='sales_targets', status='completed',
            type='mcp_call', error=None, output={'period': '2026-01', **target})
        older = call.model_copy(update={'id': 'older-item', 'turn_id': 'older-turn'})
        command = SimpleNamespace(type='command_execution', turn_id=turn.id, status='completed',
                                  exit_code=0, id='skill-command', cwd='/workspace', output='done',
                                  command='python /runtime/plugins/sales-reporting/skills/csv-report/scripts/analyze_sales.py --input /workspace/sales.csv --output-dir /workspace/outputs')
        items = [command, older, call]
        files = {'summary.json': json.dumps(expected).encode(),
                 'report.md': (render_markdown(expected) + '\nTarget revenue: 150000\nAttainment: 85.00%\n').encode(),
                 'skill_evidence.json': json.dumps(dict(skill_name='csv-report', script_revision='csv-report-v1', input_sha256=hashlib.sha256(csv_text.encode()).hexdigest())).encode()}
        events = [SimpleNamespace(type='agent.session.created', session=SimpleNamespace(
            id=result.session_id, environment=SimpleNamespace(id='environment-fixture'))),
            SimpleNamespace(type='agent.session.turn.item.added', item=call),
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
        installed = SimpleNamespace(id='environment-fixture', plugins=[SimpleNamespace(name='sales-reporting', type='inline', description='fixture')])
        client.beta.agents.environments.retrieve.return_value = installed
        client.beta.agents.sessions.retrieve.return_value = SimpleNamespace(environment=SimpleNamespace(id=installed.id))
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
            return Pages([SimpleNamespace(id=name, session_id=result.session_id, turn_id=turn.id,
                path='/workspace/outputs/' + name, size_bytes=len(data)) for name, data in files.items()], 'artifacts')
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
        env = dict(settings=SimpleNamespace(root=root, model='fixture', api_key=None), CHAPTER='10_plugins',
                   client=client, uuid4=uuid4, json=json, sys=sys,
                   time=SimpleNamespace(monotonic=lambda: clock.now), cleanup_on_error=cleanup_on_error,
                   cleanup_resources=clean, new_session_metadata=new_session_metadata,
                   check_event=check_event, safe_error=safe_error)
        nb = nbformat.read(ROOT / 'notebooks/chapters/10_plugins.ipynb', as_version=4)
        if instrumented:
            instrument_notebook(nb, '10_plugins', live=True)
        steps = {i: next(c.source for c in nb.cells if f'plugin_step_{i}' in c.metadata.get('tags', [])) for i in range(1, 7)}
        with patch('tutorial_helpers.common.cleanup_resources', clean), contextlib.redirect_stdout(io.StringIO()) as output, \
                patch('IPython.display.display', side_effect=lambda value: calls.append('display')):
            if instrumented:
                exec(nb.cells[0].source, env)
                def validate(*args):
                    calls.append('validate')
                    return validate_lesson(*args)
                env.update(_validate_lesson=validate, _save_validation=save_validation)
            for identifier in ['10-input-preview', 'extension-10-06', '10-plugin-environment', '88b31c2d', 'f8105f0eadce']:
                exec(next(c.source for c in nb.cells if c.id == identifier), env)
            try:
                yield env, steps, clean, calls, clock, output, stream, call, items, files, errors, events
            finally:
                env.pop('_validation_error', None)
                env.clear()


class PluginStepTests(unittest.TestCase):
    def test_single_plugin_request_registration_history_results_and_cleanup(self):
        for instrumented in [False, True]:
            with self.subTest(instrumented=instrumented), lesson(instrumented) as (env, steps, clean, calls, clock, output, stream, call, items, files, errors, events):
                clock.now = 2000
                exec(steps[1], env)
                self.assertEqual(env['started'], 2000)
                request = env['client'].beta.agents.sessions.create.call_args.kwargs
                self.assertEqual(request['environment']['plugins'], [env['plugin']])
                self.assertNotIn('tools', request['agent'])
                self.assertNotIn('skills', request['environment'])
                self.assertNotIn('tool_handlers', request)
                self.assertIn(env['METRICS_CONTRACT'], request['input'])
                self.assertIn(env['ENRICHED_CONTRACT'], request['input'])
                clock.now += 2000
                for step in range(2, 6):
                    exec(steps[step], env)
                self.assertIn('items.page.2', calls)
                self.assertEqual([i.id for i in env['mcp_calls']], ['mcp-item'])
                self.assertEqual(env['actual']['attainment_rate'], .85)
                self.assertNotIn('target_revenue', env['downloaded_summary'])
                self.assertEqual(env['skill_evidence']['skill_name'], 'csv-report')
                self.assertTrue(env['downloads_complete'])
                self.assertIn('skill-command', output.getvalue())
                self.assertIn('server_label', output.getvalue())
                clean.assert_not_called()
                exec(steps[6], env)
                clean.assert_called_once()
                self.assertTrue(env['sessions']['session-fixture']['verified_absent'])
                if instrumented:
                    self.assertLess(calls.index('validate'), calls.index('cleanup'))
                    checks = env['_validation_summary']['checks']
                    self.assertEqual(checks['report_target_comparison']['attainment_percent'], '85.00')
                    self.assertEqual(checks['skill_command_ids'], ['skill-command'])
                    self.assertEqual(checks['installed_plugins'][0]['name'], 'sales-reporting')

    def test_registration_id_recovery_and_wrong_environment_or_plugin(self):
        for mode in ['recover', 'environment', 'plugin', 'type']:
            with self.subTest(mode=mode), lesson() as (env, steps, clean, calls, clock, output, stream, *rest):
                exec(steps[1], env)
                env['sessions']['session-fixture']['environment_id'] = None
                installed = env['client'].beta.agents.environments.retrieve.return_value
                if mode == 'environment': installed.id = 'different'
                elif mode == 'plugin': installed.plugins[0].name = 'different'
                elif mode == 'type': installed.plugins[0].type = 'different'
                if mode == 'recover':
                    exec(steps[2], env)
                    env['client'].beta.agents.sessions.retrieve.assert_called_once()
                    clean.assert_not_called()
                else:
                    with self.assertRaises(RuntimeError): exec(steps[2], env)
                    clean.assert_called_once()

    def test_validator_checks_mcp_root_name_period_count_status_and_error(self):
        for mode in ['older', 'missing', 'duplicate', 'name', 'period', 'status', 'error']:
            with self.subTest(mode=mode), lesson(True) as (env, steps, clean, calls, clock, output, stream, call, items, files, errors, events):
                for step in range(1, 6): exec(steps[step], env)
                if mode == 'older': call.turn_id = 'different'
                elif mode == 'missing': items.remove(call)
                elif mode == 'duplicate': items.append(call.model_copy(update={'id': 'duplicate'}))
                elif mode == 'name': call.name = 'get_sales_target_extra'
                elif mode == 'period': call.arguments = {'period': '2026-02'}
                elif mode == 'status': call.status = 'failed'
                else: call.error = {'code': 'unknown_period'}
                with self.assertRaises(ValueError): exec(steps[6], env)
                clean.assert_called_once()
                self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_string_arguments_and_observed_label_do_not_invent_namespace_contract(self):
        with lesson(True) as (env, steps, clean, calls, clock, output, stream, call, *rest):
            call.arguments = json.dumps({'period': '2026-01'})
            call.server_label = 'runtime-fixture-namespace/sales_targets'
            for step in range(1, 7): exec(steps[step], env)
            self.assertEqual(env['_validation_summary']['checks']['plugin_mcp_call']['server_label'], call.server_label)
            self.assertEqual(env['_validation_summary']['checks']['plugin_mcp_call']['configured_servers'], ['sales_targets'])

    def test_validator_rejects_wrong_skill_command_hash_name_and_registration(self):
        for mode in ['command', 'older', 'hash', 'name', 'registration']:
            with self.subTest(mode=mode), lesson(True) as (env, steps, clean, calls, clock, output, stream, call, items, files, errors, events):
                for step in range(1, 6): exec(steps[step], env)
                if mode == 'command': items[0].command = 'echo analyze_sales.py'
                elif mode == 'older':
                    items[0].turn_id = 'old-turn'
                    items.append(SimpleNamespace(type='command_execution', turn_id='turn-fixture', status='completed', exit_code=0, command='python other.py'))
                elif mode == 'registration': env['installed_environment'].plugins.clear()
                else:
                    path = env['downloads'] / 'skill_evidence.json'
                    evidence = json.loads(path.read_text())
                    evidence['input_sha256' if mode == 'hash' else 'skill_name'] = 'different'
                    path.write_text(json.dumps(evidence))
                with self.assertRaises(ValueError): exec(steps[6], env)
                clean.assert_called_once()

    def test_report_requires_target_and_percentage_not_fraction(self):
        for addition in ['', 'Target revenue: 149999\nAttainment: 85.00%\n',
                         'Target revenue: 150000\nAttainment: 0.85%\n',
                         'Target revenue: 150000\nAttainment: 85.00%\nAttainment: 85.00%\n']:
            with self.subTest(addition=addition), lesson(True) as (env, steps, clean, *rest):
                for step in range(1, 6): exec(steps[step], env)
                path = env['downloads'] / 'report.md'
                path.write_text(render_markdown(env['downloaded_summary']) + addition)
                with self.assertRaisesRegex(ValueError, 'Report target'): exec(steps[6], env)
                clean.assert_called_once()

    def test_failed_turn_interrupt_and_repeated_submission_cleanup(self):
        for mode in ['failed', 'interrupt', 'repeat']:
            with self.subTest(mode=mode), lesson(True) as (env, steps, clean, calls, clock, output, stream, call, items, files, errors, events):
                if mode == 'failed':
                    turn = stream.get_final_result.return_value.turn
                    turn.status = 'failed'
                    events[:] = events[:1] + [SimpleNamespace(type='agent.session.turn.failed', turn=turn)]
                    with self.assertRaises(RuntimeError): exec(steps[1], env)
                elif mode == 'interrupt':
                    def interrupted():
                        yield events[0]
                        raise SimulatedInterruption()
                    stream.__iter__.side_effect = interrupted
                    with self.assertRaises(SimulatedInterruption): exec(steps[1], env)
                else:
                    exec(steps[1], env)
                    with self.assertRaisesRegex(RuntimeError, 'Do not resubmit'): exec(steps[1], env)
                clean.assert_called_once()
                env['client'].beta.agents.sessions.create.assert_called_once()
                self.assertFalse(any(c.startswith('download:') for c in calls))

    def test_partial_or_missing_evidence_and_parse_error_never_skip_cleanup(self):
        for mode in ['partial', 'missing', 'parse']:
            with self.subTest(mode=mode), lesson(True) as (env, steps, clean, calls, clock, output, stream, call, items, files, errors, events):
                exec(steps[1], env)
                if mode == 'partial': errors['skill_evidence.json'] = OSError('transfer fixture')
                elif mode == 'missing': files.pop('skill_evidence.json')
                if mode != 'parse':
                    with self.assertRaises(OSError if mode == 'partial' else ValueError): exec(steps[4], env)
                    self.assertFalse(env['downloads_complete'])
                else:
                    exec(steps[4], env)
                    (env['downloads'] / 'skill_evidence.json').write_text('not json')
                    clean.side_effect = RuntimeError('cleanup fixture')
                    with self.assertRaises(json.JSONDecodeError) as raised: exec(steps[5], env)
                    self.assertTrue(raised.exception.__notes__)
                clean.assert_called_once()
                env['client'].beta.agents.sessions.create.assert_called_once()

    def test_preparation_preserves_crlf_bytes_and_manifest_matching_without_api(self):
        nb = nbformat.read(ROOT / 'notebooks/chapters/10_plugins.ipynb', 4)
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            root = Path(folder)
            shutil.copytree(ROOT / 'plugins', root / 'plugins')
            (root / 'data').mkdir()
            raw_csv = (ROOT / 'data/sales.csv').read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
            (root / 'data/sales.csv').write_bytes(raw_csv)
            before = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            env = dict(settings=SimpleNamespace(root=root), json=json)
            for identifier in ['10-input-preview', 'extension-10-06', '10-plugin-environment', '88b31c2d']:
                exec(next(c.source for c in nb.cells if c.id == identifier), env)
            self.assertEqual(base64.b64decode(env['environment']['files'][0]['data']), raw_csv)
            self.assertEqual(env['plugin']['name'], env['manifest']['name'])
            self.assertEqual(env['plugin']['description'], env['manifest']['description'])
            self.assertEqual(env['environment']['packages']['python'], [f"mcp=={env['MCP_VERSION']}"])
            self.assertEqual(before, {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()})


class PluginZipTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_inline_plugin_zip_skill_script_and_stdio_mcp(self):
        with lesson() as (env, *rest), tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            raw = base64.b64decode(env['plugin']['source']['data'])
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                self.assertEqual({Path(p).parts[0] for p in archive.namelist()}, {'sales-reporting'})
                archive.extractall(target)
            plugin_root = target / 'sales-reporting'
            manifest = json.loads((plugin_root / '.codex-plugin/plugin.json').read_text())
            self.assertTrue((plugin_root / manifest['skills'] / 'csv-report/SKILL.md').is_file())
            config = json.loads((plugin_root / manifest['mcpServers']).read_text())['mcpServers']['sales_targets']
            input_path = target / 'sales.csv'
            input_path.write_bytes(env['csv_bytes'])
            out = target / 'outputs'
            subprocess.run([sys.executable, str(plugin_root / 'skills/csv-report/scripts/analyze_sales.py'),
                            '--input', str(input_path), '--output-dir', str(out)], check=True, capture_output=True)
            self.assertEqual(json.loads((out / 'summary.json').read_text()), analyze_csv(env['csv_text']))
            self.assertEqual(json.loads((out / 'skill_evidence.json').read_text())['input_sha256'], hashlib.sha256(env['csv_bytes']).hexdigest())
            self.assertTrue((out / 'report.md').read_text().startswith('# 매출 분석 보고서'))
            params = StdioServerParameters(command=sys.executable, args=config['args'], cwd=str(plugin_root / config['cwd']))
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    self.assertIn('get_sales_target', [t.name for t in tools.tools])
                    response = await session.call_tool('get_sales_target', {'period': '2026-01'})
                    self.assertFalse(response.isError)
                    actual = json.loads(response.content[0].text)
                    self.assertEqual(actual, {'period': '2026-01', **json.loads((ROOT / 'data/sales_targets.json').read_text())['2026-01']})
                    rejected = await session.call_tool('get_sales_target', {'period': '2026-99'})
                    self.assertTrue(rejected.isError)


if __name__ == '__main__': unittest.main()
