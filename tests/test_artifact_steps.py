"""Exercise chapter 5 cells and real SDK turn/path selection against fake file transport."""
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
from openai.lib.beta.agents._artifacts import AgentResultArtifacts
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
        (root / 'data').mkdir()
        csv_text = (ROOT / 'data/sales.csv').read_text()
        (root / 'data/sales.csv').write_text(csv_text)
        expected = analyze_csv(csv_text)
        calls = []
        clock = SimpleNamespace(now=0)
        turn = SimpleNamespace(id='turn-fixture', status='completed', subagent_id=None, usage=None)
        result = SimpleNamespace(session_id='session-fixture', turn_id=turn.id, turn=turn,
                                 output_text=json.dumps(expected))
        files = {'summary': json.dumps(expected).encode(), 'report': render_markdown(expected).encode()}
        artifacts = [SimpleNamespace(id=name, session_id=result.session_id, turn_id=turn.id,
                     path='/workspace/outputs/' + filename, size_bytes=len(files[name]))
                     for name, filename in [('summary', 'summary.json'), ('report', 'report.md')]]
        old = SimpleNamespace(id='old-summary', session_id=result.session_id, turn_id='older-turn',
                              path='/workspace/outputs/summary.json', size_bytes=1)
        artifacts.insert(0, old)
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
            SimpleNamespace(type='command_execution', turn_id=turn.id, status='completed', exit_code=0,
                            command='python analyze.py')]
        class Pages:
            def __iter__(self):
                for index, page in enumerate([artifacts[:1], artifacts[1:]]):
                    calls.append(f'artifacts.page.{index+1}')
                    yield from page
        resource = client.beta.agents.sessions.artifacts
        resource.list.side_effect = lambda *a, **kw: Pages()
        # Real SDK selection rejects missing/duplicate paths and ignores the older Turn.
        resource.for_result.side_effect = lambda result: AgentResultArtifacts(resource, result)
        transfer_error = {}
        @contextlib.contextmanager
        def content(artifact_id, **kwargs):
            calls.append('download:' + artifact_id)
            def write(to):
                data = files[artifact_id]
                Path(to).write_bytes(data[:5] if artifact_id in transfer_error else data)
                if artifact_id in transfer_error:
                    raise transfer_error[artifact_id]
            yield SimpleNamespace(stream_to_file=write)
        resource.with_streaming_response.content.side_effect = content
        def cleanup(client, sessions, agents, attempts):
            calls.append('cleanup')
            for value in sessions.values():
                value.update(deleted=True, verified_absent=True)
            client.close()
            return []
        clean = Mock(side_effect=cleanup)
        env = dict(settings=SimpleNamespace(root=root, model='fixture', api_key=None), CHAPTER='05_files_artifacts',
                   uuid4=uuid4, json=json, sys=sys, client=client, task='fixture', BASE_INSTRUCTIONS='fixture',
                   environment={}, time=SimpleNamespace(monotonic=lambda: clock.now),
                   cleanup_on_error=cleanup_on_error, cleanup_resources=clean,
                   new_session_metadata=new_session_metadata, check_event=check_event, safe_error=safe_error)
        nb = nbformat.read(ROOT / 'notebooks/chapters/05_files_artifacts.ipynb', as_version=4)
        if instrumented:
            instrument_notebook(nb, '05_files_artifacts', live=True)
        steps = {i: next(c.source for c in nb.cells if f'artifact_step_{i}' in c.metadata.get('tags', [])) for i in range(1, 6)}
        with patch('tutorial_helpers.common.cleanup_resources', clean), contextlib.redirect_stdout(io.StringIO()) as output, \
                patch('IPython.display.display', side_effect=lambda value: calls.append('display')):
            if instrumented:
                exec(nb.cells[0].source, env)
                def validate(*a):
                    calls.append('validate')
                    return validate_lesson(*a)
                env.update(_validate_lesson=validate, _save_validation=save_validation)
            exec(next(c.source for c in nb.cells if c.id == 'f7d6d2ed4048'), env)
            try:
                yield env, steps, clean, calls, clock, output, stream, artifacts, files, transfer_error
            finally:
                env.pop('_validation_error', None)
                env.clear()


class ArtifactStepTests(unittest.TestCase):
    def test_input_encoding_preserves_bytes_without_sending_csv_in_message(self):
        nb = nbformat.read(ROOT / 'notebooks/chapters/05_files_artifacts.ipynb', as_version=4)
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            root = Path(folder)
            (root / 'data').mkdir()
            data = 'date,product,quantity,unit_price\r\n2026-01-01,상품A,2,10000\r\n'.encode()
            (root / 'data/sales.csv').write_bytes(data)
            env = {'settings': SimpleNamespace(root=root)}
            for identifier in ['05-input-preview', 'intro-05-06', '699babb0']:
                exec(next(c.source for c in nb.cells if c.id == identifier), env)
            file = env['environment']['files'][0]
            self.assertEqual(env['base64'].b64decode(file['data']), data)
            self.assertEqual(file['path'], '/workspace/sales.csv')
            self.assertNotIn(env['csv_text'], env['task'])
            self.assertIn(env['METRICS_CONTRACT'], env['task'])

    def test_publication_exact_turn_downloads_local_reads_and_validation_order(self):
        for instrumented in [False, True]:
            with self.subTest(instrumented=instrumented), lesson(instrumented) as (env, steps, clean, calls, clock, output, stream, artifacts, files, errors):
                clock.now = 2000
                exec(steps[1], env)
                self.assertEqual(env['started'], 2000)
                exec(steps[2], env)
                self.assertEqual([a.id for a in env['current_artifacts']], ['summary', 'report'])
                self.assertNotIn('old-summary', output.getvalue())
                self.assertIn('artifacts.page.2', calls)
                clock.now += 2000
                exec(steps[3], env)
                self.assertTrue(env['downloads_complete'])
                self.assertEqual((env['downloads'] / 'summary.json').read_bytes(), files['summary'])
                self.assertEqual((env['downloads'] / 'report.md').read_bytes(), files['report'])
                self.assertEqual([c for c in calls if c.startswith('download:')], ['download:summary', 'download:report'])
                exec(steps[4], env)
                self.assertEqual(env['downloaded_summary']['total_revenue'], 127500)
                clean.assert_not_called()
                exec(steps[5], env)
                clean.assert_called_once()
                self.assertTrue(env['sessions']['session-fixture']['verified_absent'])
                if instrumented:
                    self.assertLess(calls.index('validate'), calls.index('cleanup'))
                    self.assertEqual(env['_validation_summary']['status'], 'passed')

    def test_missing_or_ambiguous_artifact_is_not_downloaded_as_success(self):
        for mode in ['missing', 'duplicate']:
            with self.subTest(mode=mode), lesson(True) as (env, steps, clean, calls, clock, output, stream, artifacts, files, errors):
                exec(steps[1], env)
                if mode == 'missing':
                    artifacts[:] = [a for a in artifacts if a.id != 'report']
                else:
                    artifacts.append(SimpleNamespace(**vars(artifacts[1])))
                exec(steps[2], env)
                with self.assertRaises(ValueError):
                    exec(steps[3], env)
                self.assertFalse(env['downloads_complete'])
                self.assertNotIn('download:old-summary', calls)
                clean.assert_called_once()
                self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_partial_download_is_not_treated_as_complete(self):
        with lesson(True) as (env, steps, clean, calls, clock, output, stream, artifacts, files, errors):
            exec(steps[1], env)
            errors['report'] = OSError('transfer fixture')
            with self.assertRaises(OSError):
                exec(steps[3], env)
            self.assertTrue((env['downloads'] / 'summary.json').is_file())
            self.assertEqual((env['downloads'] / 'report.md').stat().st_size, 5)
            self.assertFalse(env['downloads_complete'])
            self.assertEqual(env['client'].beta.agents.sessions.create.call_count, 1)
            self.assertNotIn('display', calls)
            self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_download_rerun_is_read_only_and_resets_completion_before_failure(self):
        with lesson() as (env, steps, clean, calls, clock, output, stream, artifacts, files, errors):
            exec(steps[1], env)
            exec(steps[3], env)
            exec(steps[3], env)  # Existing destination directory is supported.
            env['client'].beta.agents.sessions.create.assert_called_once()
            errors['report'] = OSError('retry fixture')
            with self.assertRaises(OSError):
                exec(steps[3], env)
            self.assertFalse(env['downloads_complete'])
            clean.assert_called_once()

    def test_local_result_error_still_cleans_up_and_preserves_original_error(self):
        with lesson(True) as (env, steps, clean, calls, *rest):
            exec(steps[1], env)
            exec(steps[3], env)
            (env['downloads'] / 'summary.json').write_text('not json')
            clean.side_effect = RuntimeError('cleanup fixture')
            with self.assertRaises(json.JSONDecodeError) as raised:
                exec(steps[4], env)
            self.assertTrue(raised.exception.__notes__)
            self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_stream_interrupt_and_publication_failure_attempt_cleanup(self):
        for step in [1, 2]:
            with self.subTest(step=step), lesson(True) as (env, steps, clean, calls, clock, output, stream, artifacts, files, errors):
                if step == 1:
                    stream.__iter__.side_effect = SimulatedInterruption('stream fixture')
                else:
                    exec(steps[1], env)
                    env['client'].beta.agents.sessions.artifacts.list.side_effect = OSError('list fixture')
                with self.assertRaises(SimulatedInterruption if step == 1 else OSError):
                    exec(steps[step], env)
                clean.assert_called_once()
                self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_failed_turn_blocks_artifact_calls(self):
        with lesson(True) as (env, steps, clean, calls, clock, output, stream, artifacts, files, errors):
            stream.get_final_result.return_value.turn.status = 'failed'
            with self.assertRaisesRegex(RuntimeError, 'completion'):
                exec(steps[1], env)
            env['client'].beta.agents.sessions.artifacts.list.assert_not_called()
            self.assertEqual(env['_validation_summary']['status'], 'failed')

    def test_partial_execution_cleanup_and_retained_files(self):
        with lesson() as (env, steps, clean, calls, *rest):
            exec(steps[1], env)
            exec(steps[3], env)
            exec(steps[5], env)
            before = len(env['client'].mock_calls)
            exec(steps[4], env)
            self.assertEqual(len(env['client'].mock_calls), before)
            self.assertIn('display', calls)
        with lesson() as (env, steps, clean, *rest):
            exec(steps[5], env)
            env['client'].beta.agents.sessions.create.assert_not_called()
            clean.assert_called_once()

    def test_validator_rejects_wrong_report_and_still_cleans_up(self):
        with lesson(True) as (env, steps, clean, calls, *rest):
            for step in [1, 2, 3, 4]:
                exec(steps[step], env)
            (env['downloads'] / 'report.md').write_text('# Wrong report')
            with self.assertRaises(ValueError):
                exec(steps[5], env)
            clean.assert_called_once()
            self.assertEqual(env['_validation_summary']['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
