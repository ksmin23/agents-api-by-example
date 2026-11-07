"""Chapter 8 cells with fake Agents API data, plus real stdio on supplied server bytes."""
import base64
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
        for source in ['data/sales.csv', 'data/sales_targets.json', 'examples/mcp/sales_targets_server.py']:
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
                                  exit_code=0, command='python analyze.py')
        items = [command, older, call]
        files = {'summary.json': json.dumps(expected).encode(),
                 'report.md': (render_markdown(expected) + '\nTarget: 150000; attainment: 85%\n').encode()}
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
        env = dict(settings=SimpleNamespace(root=root, model='fixture', api_key=None), CHAPTER='08_mcp',
                   client=client, uuid4=uuid4, json=json, sys=sys,
                   time=SimpleNamespace(monotonic=lambda: clock.now), cleanup_on_error=cleanup_on_error,
                   cleanup_resources=clean, new_session_metadata=new_session_metadata,
                   check_event=check_event, safe_error=safe_error)
        nb = nbformat.read(ROOT / 'notebooks/chapters/08_mcp.ipynb', as_version=4)
        if instrumented:
            instrument_notebook(nb, '08_mcp', live=True)
        steps = {i: next(c.source for c in nb.cells if f'mcp_step_{i}' in c.metadata.get('tags', [])) for i in range(1, 6)}
        with patch('tutorial_helpers.common.cleanup_resources', clean), contextlib.redirect_stdout(io.StringIO()) as output, \
                patch('IPython.display.display', side_effect=lambda value: calls.append('display')):
            if instrumented:
                exec(nb.cells[0].source, env)
                def validate(*args):
                    calls.append('validate')
                    return validate_lesson(*args)
                env.update(_validate_lesson=validate, _save_validation=save_validation)
            for identifier in ['08-input-preview', 'extension-08-06', '08-mcp-registration', 'c9689373', '5fe293cbf41b']:
                exec(next(c.source for c in nb.cells if c.id == identifier), env)
            try:
                yield env, steps, clean, calls, clock, output, stream, call, items, files, errors, events
            finally:
                env.pop('_validation_error', None)
                env.clear()


class McpStepTests(unittest.TestCase):
    def test_environment_registration_history_downloads_and_cleanup(self):
        for instrumented in [False, True]:
            with self.subTest(instrumented=instrumented), lesson(instrumented) as (env, steps, clean, calls, clock, output, stream, call, items, files, errors, events):
                env['client'].beta.agents.sessions.create.assert_not_called()
                self.assertEqual(env['environment']['packages']['python'], [f"mcp=={env['MCP_VERSION']}"])
                self.assertEqual(env['environment']['network'], {'access': 'enabled'})
                self.assertNotIn('connection_origin', env['mcp_tool'])
                self.assertTrue(env['mcp_tool']['required'])
                self.assertEqual(env['mcp_tool']['allowed_tools'], ['get_sales_target'])
                clock.now = 2000
                exec(steps[1], env)
                self.assertEqual(env['started'], 2000)
                request = env['client'].beta.agents.sessions.create.call_args.kwargs
                self.assertEqual(request['agent']['tools'], [env['mcp_tool']])
                self.assertNotIn('tool_handlers', request)
                env['client'].beta.agents.sessions.events.create.assert_not_called()
                clock.now += 2000
                for step in [2, 3, 4]:
                    exec(steps[step], env)
                self.assertEqual([c.id for c in env['mcp_calls']], ['mcp-item'])
                self.assertIn('items.page.2', calls)
                self.assertIn('server_label', output.getvalue())
                self.assertEqual(env['actual']['attainment_rate'], 0.85)
                self.assertNotIn('target_revenue', env['downloaded_summary'])
                self.assertEqual(env['downloads'], env['output_dir'] / 'downloads' / 'turn-fixture')
                clean.assert_not_called()
                exec(steps[5], env)
                clean.assert_called_once()
                if instrumented:
                    self.assertLess(calls.index('validate'), calls.index('cleanup'))
                    self.assertEqual(env['_validation_summary']['status'], 'passed')
                    self.assertTrue(env['_validation_summary']['checks']['mcp_call']['error_absent'])

    def test_validator_checks_exact_root_server_tool_period_count_and_success(self):
        for mode in ['missing', 'duplicate', 'server', 'name', 'status', 'error', 'period']:
            with self.subTest(mode=mode), lesson(True) as (env, steps, clean, calls, clock, output, stream, call, items, files, errors, events):
                for step in [1, 2, 3, 4]:
                    exec(steps[step], env)
                if mode == 'missing':
                    items.remove(call)
                elif mode == 'duplicate':
                    items.append(call.model_copy(update={'id': 'second-call'}))
                elif mode == 'server':
                    call.server_label = 'other-server'
                elif mode == 'name':
                    call.name = 'get_sales_target_extra'
                elif mode == 'status':
                    call.status = 'failed'
                elif mode == 'error':
                    call.error = {'code': 'unknown_period'}
                else:
                    call.arguments = {'period': '2026-02'}
                with self.assertRaises(ValueError):
                    exec(steps[5], env)
                clean.assert_called_once()
                self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_string_arguments_are_supported(self):
        with lesson(True) as (env, steps, clean, calls, clock, output, stream, call, *rest):
            call.arguments = json.dumps({'period': '2026-01'})
            for step in range(1, 6):
                exec(steps[step], env)
            self.assertEqual(env['_validation_summary']['status'], 'passed')

    def test_required_initialization_failure_stops_before_result_and_artifacts(self):
        with lesson(True) as (env, steps, clean, calls, clock, output, stream, call, items, files, errors, events):
            turn = stream.get_final_result.return_value.turn
            turn.status = 'failed'
            events[:] = events[:1] + [SimpleNamespace(type='agent.session.turn.failed', turn=turn)]
            with self.assertRaisesRegex(RuntimeError, 'Root turn ended'):
                exec(steps[1], env)
            stream.get_final_result.assert_not_called()
            env['client'].beta.agents.sessions.items.list.assert_not_called()
            env['client'].beta.agents.sessions.artifacts.for_result.assert_not_called()
            clean.assert_called_once()
            self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_failed_call_is_not_success_even_if_turn_and_calculation_complete(self):
        with lesson(True) as (env, steps, clean, calls, clock, output, stream, call, *rest):
            call.status, call.error = 'failed', {'code': 'unknown_period'}
            for step in [1, 2, 3, 4]:
                exec(steps[step], env)
            self.assertIn('unknown_period', output.getvalue())
            with self.assertRaises(ValueError):
                exec(steps[5], env)
            self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_repeated_submission_does_not_start_another_session(self):
        with lesson(True) as (env, steps, clean, *rest):
            exec(steps[1], env)
            with self.assertRaisesRegex(RuntimeError, 'Do not resubmit'):
                exec(steps[1], env)
            env['client'].beta.agents.sessions.create.assert_called_once()
            clean.assert_called_once()

    def test_partial_download_and_missing_artifact_do_not_rerun_analysis(self):
        for mode in ['partial', 'missing']:
            with self.subTest(mode=mode), lesson(True) as (env, steps, clean, calls, clock, output, stream, call, items, files, errors, events):
                exec(steps[1], env)
                if mode == 'partial':
                    errors['report.md'] = OSError('transfer fixture')
                else:
                    files.pop('report.md')
                with self.assertRaises(OSError if mode == 'partial' else ValueError):
                    exec(steps[3], env)
                self.assertFalse(env['downloads_complete'])
                env['client'].beta.agents.sessions.create.assert_called_once()
                clean.assert_called_once()
                self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_interrupt_and_local_parse_error_preserve_cleanup(self):
        with lesson(True) as (env, steps, clean, calls, clock, output, stream, call, items, files, errors, events):
            def interrupted():
                yield events[0]
                raise SimulatedInterruption('fixture')
            stream.__iter__.side_effect = interrupted
            with self.assertRaises(SimulatedInterruption):
                exec(steps[1], env)
            clean.assert_called_once()
        with lesson(True) as (env, steps, clean, *rest):
            exec(steps[1], env)
            exec(steps[3], env)
            env['result'].output_text = 'not json'
            clean.side_effect = RuntimeError('cleanup fixture')
            with self.assertRaises(json.JSONDecodeError) as raised:
                exec(steps[4], env)
            self.assertTrue(raised.exception.__notes__)
            self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_partial_cleanup_and_retained_local_files(self):
        with lesson() as (env, steps, clean, *rest):
            exec(steps[5], env)
            env['client'].beta.agents.sessions.create.assert_not_called()
        with lesson() as (env, steps, clean, calls, *rest):
            exec(steps[1], env)
            exec(steps[3], env)
            exec(steps[5], env)
            before = len(env['client'].mock_calls)
            exec(steps[4], env)
            self.assertEqual(len(env['client'].mock_calls), before)


class SuppliedMcpProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_stdio_discovery_and_calls_using_notebook_supplied_bytes(self):
        # Local protocol validation only: no hosted sandbox or package installation is exercised.
        with lesson() as (env, steps, clean, *rest):
            workspace = env['settings'].root / 'materialized'
            workspace.mkdir()
            for file in env['environment']['files']:
                (workspace / Path(file['path']).name).write_bytes(base64.b64decode(file['data']))
            transport = env['mcp_tool']['transport']
            args = [str(workspace / Path(arg).name) if arg.startswith('/workspace/') else arg
                    for arg in transport['args']]
            params = StdioServerParameters(command=sys.executable, args=args, cwd=str(workspace))
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    initialized = await session.initialize()
                    self.assertEqual(initialized.serverInfo.name, 'sales-targets')
                    tools = await session.list_tools()
                    self.assertIn('get_sales_target', [tool.name for tool in tools.tools])
                    result = await session.call_tool('get_sales_target', {'period': '2026-01'})
                    self.assertFalse(result.isError)
                    payload = result.structuredContent or json.loads(next(item.text for item in result.content if item.type == 'text'))
                    self.assertEqual(payload['target_revenue'], 150000)
                    for period in ['2026-02', '2026-13']:
                        denied = await session.call_tool('get_sales_target', {'period': period})
                        self.assertTrue(denied.isError)
            env['client'].beta.agents.sessions.create.assert_not_called()


if __name__ == '__main__':
    unittest.main()
