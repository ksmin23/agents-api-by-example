"""Actual memory OTel spans with fake Agents API, and Collector/Trace edge cases."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import nbformat
from test_telemetry_steps import telemetry
from tutorial_helpers.common import check_event
from tutorial_helpers.deployment import ApplicationHooks, decode_otlp_spans
from tutorial_helpers.validation import validate_lesson

ROOT = Path(__file__).resolve().parents[1]


class TelemetryEvidenceTests(unittest.TestCase):
    def test_memory_spans_are_real_flush_keeps_provider_open_and_close_prevents_new_emission(self):
        with telemetry(instrumented=True) as (env, steps, clean, calls, clock, output, lab):
            for step in range(1, 5): exec(steps[step], env)
            self.assertFalse(env['hooks'].closed)
            self.assertEqual(len(env['observed_spans']), len(env['hooks'].records))
            for span in env['observed_spans']:
                self.assertEqual(len(span['trace_id']), 32)
                self.assertEqual(len(span['span_id']), 16)
                self.assertEqual(span['attributes']['run_id'], env['run_id'])
            self.assertTrue((env['output_dir']/'application-spans.json').is_file())
            exec(steps[5], env);exec(steps[6], env)
            self.assertTrue(env['hooks'].closed)
            with self.assertRaisesRegex(RuntimeError, 'closed'):
                env['hooks'].emit('report.started')

    def test_repeated_preparation_and_session_creation_preserve_owned_resources(self):
        for repeat in [1, 2]:
            with self.subTest(repeat=repeat), telemetry(docker=True) as (env, steps, clean, calls, clock, output, lab):
                for step in range(1, repeat+1):exec(steps[step], env)
                run_id=env['run_id'];sessions=env['sessions']
                with self.assertRaisesRegex(RuntimeError, 'twice|once'):
                    exec(steps[repeat], env)
                self.assertEqual(env['run_id'],run_id)
                self.assertIs(env['sessions'],sessions)
                env['ApplicationHooks'].assert_called_once()
                self.assertEqual(env['client'].beta.agents.sessions.create.call_count,repeat-1)
                self.assertTrue(env['hooks'].closed)

    def test_validator_rejects_mismatched_record_span_identity_duration_usage_or_leak(self):
        for mode in ['run','session','turn','status','duration','usage','span','span_id','span_leak']:
            with self.subTest(mode=mode), telemetry() as (env, steps, clean, calls, clock, output, lab):
                for step in range(1,5):exec(steps[step],env)
                record=next(r for r in env['hooks'].records if r['event']=='report.completed')
                field={'run':'run_id','session':'session_id','turn':'turn_id','status':'status','duration':'duration_ms','usage':'input_tokens'}.get(mode)
                if field:record[field]='wrong' if mode not in {'duration','usage'} else 99
                elif mode=='span':env['observed_spans'][0]['attributes']['run_id']='wrong'
                elif mode=='span_id':env['observed_spans'][0]['span_id']=''
                else:env['observed_spans'][0]['attributes']['prompt']='private fixture'
                items=list(env['client'].beta.agents.sessions.items.list(env['result'].session_id))
                with self.assertRaises(ValueError):validate_lesson('13_hooks_telemetry',env,items)

    def test_reported_zero_usage_is_preserved_and_unknown_usage_is_not_filled(self):
        for usage in [None,{'input_tokens':0,'output_tokens':0,'total_tokens':0}]:
            with self.subTest(usage=usage), telemetry(instrumented=True) as (env, steps, clean, calls, clock, output, lab):
                exec(steps[1],env);exec(steps[2],env)
                env['client'].beta.agents.sessions.turns.retrieve.return_value.usage = SimpleNamespace(to_dict=lambda:usage) if usage is not None else None
                for step in range(3,7):exec(steps[step],env)
                record=next(r for r in env['hooks'].records if r['event']=='report.completed')
                self.assertEqual({k:v for k,v in record.items() if k.endswith('_tokens')},usage or {})
                self.assertEqual(env['_validation_summary']['status'],'passed')

    def test_collector_jsonl_decoder_reads_actual_typed_attributes_and_rejects_missing_spans(self):
        payload={'resourceSpans':[{'resource':{'attributes':[{'key':'service.name','value':{'stringValue':'tutorial.application-hooks'}}]},
            'scopeSpans':[{'spans':[{'name':'report.completed','traceId':'trace','spanId':'span',
            'attributes':[{'key':'duration_ms','value':{'intValue':'42'}}]}]}]}]}
        spans=decode_otlp_spans(json.dumps(payload)+'\n'+json.dumps({'resourceSpans':[]}))
        self.assertEqual(spans[0]['attributes']['duration_ms'],42)
        self.assertEqual(spans[0]['service_name'],'tutorial.application-hooks')
        with telemetry(docker=True) as (env,steps,clean,calls,clock,output,lab):
            for step in range(1,4):exec(steps[step],env)
            env['read_collector_file'].side_effect=None
            env['read_collector_file'].return_value=json.dumps({'resourceSpans':[]})
            with self.assertRaisesRegex(RuntimeError,'No application spans'):exec(steps[4],env)
            self.assertFalse(env['application_hooks_checked'])

    def test_api_failure_event_differs_from_local_transport_or_file_failure(self):
        with telemetry() as (env,steps,clean,calls,clock,output,lab):
            exec(steps[1],env)
            failed=SimpleNamespace(type='agent.session.turn.failed',session_id='session-fixture',
                                   turn=SimpleNamespace(id='failed-turn',subagent_id=None,status='failed'))
            stream=env['client'].beta.agents.sessions.create.return_value
            stream.__iter__.side_effect=lambda:iter([failed]);env['check_event']=check_event
            with self.assertRaises(RuntimeError):exec(steps[2],env)
            records=env['hooks'].records
            self.assertTrue(any(r['event']=='turn.failed' and r['turn_id']=='failed-turn' for r in records))
            self.assertTrue(env['hooks'].closed)
        with telemetry() as (env,steps,clean,calls,clock,output,lab):
            exec(steps[1],env)
            env['client'].beta.agents.sessions.create.side_effect=TimeoutError('private fixture')
            with self.assertRaises(TimeoutError):exec(steps[2],env)
            self.assertFalse(any(r['event']=='turn.failed' for r in env['hooks'].records))
            self.assertTrue(any(r['event']=='report.failed' and r['status']=='local_error' for r in env['hooks'].records))
            self.assertNotIn('private fixture',json.dumps(env['hooks'].records))

    def test_trace_object_without_spans_is_not_exported_and_storage_error_is_independent(self):
        for mode in ['empty','storage']:
            with self.subTest(mode=mode),telemetry(export=True,instrumented=True) as (env,steps,clean,calls,clock,output,lab):
                for step in range(1,5):exec(steps[step],env)
                resources=[] if mode=='empty' else [{'scopeSpans':[{'spans':[{'name':'native'}]}]}]
                trace=SimpleNamespace(to_dict=lambda:{'otlp':{'resourceSpans':resources}})
                query=env['client'].beta.agents.sessions.traces.list
                query.return_value=[trace]
                if mode=='storage':
                    original=Path.write_text
                    def write(path,*args,**kwargs):
                        if path.name=='traces.otlp.json.tmp':raise OSError('private storage detail')
                        return original(path,*args,**kwargs)
                    with patch.object(Path,'write_text',new=write):exec(steps[5],env)
                    self.assertEqual(env['trace_export_error_stage'],'storage')
                    self.assertEqual(env['trace_export'],'unavailable')
                else:
                    exec(steps[5],env)
                    self.assertEqual(env['trace_export'],'not_ready')
                    self.assertEqual(env['trace_span_count'],0)
                self.assertNotIn('private storage detail',output.getvalue())
                self.assertEqual(query.call_args.kwargs['timeout'],15)
                exec(steps[6],env)
                self.assertEqual(env['_validation_summary']['status'],'passed')

    def test_local_checks_are_explicit_and_do_not_overwrite_api_telemetry(self):
        notebook=nbformat.read(ROOT/'notebooks/chapters/13_hooks_telemetry.ipynb',4)
        source=next(c.source for c in notebook.cells if c.id=='e6221c08')
        hooks=object();env=dict(docker_enabled=True,RUN_LOCAL_CHECKS=False,hooks=hooks,
                              build_images=Mock(side_effect=AssertionError('No local build expected')))
        with contextlib.redirect_stdout(io.StringIO()):exec(source,env)
        self.assertIs(env['hooks'],hooks)
        env['build_images'].assert_not_called()
        self.assertIn('local_hooks',source)
        self.assertIn('local_metrics',source)

    def test_cli_separates_live_collector_from_local_checks(self):
        sys.path.insert(0,str(ROOT/'scripts'))
        import run_deployment
        for live, enabled in [(True,False),(False,True)]:
            with self.subTest(live=live), tempfile.TemporaryDirectory() as folder:
                root=Path(folder);target=root/'notebooks/chapters';target.mkdir(parents=True)
                shutil.copyfile(ROOT/'notebooks/chapters/13_hooks_telemetry.ipynb',target/'13_hooks_telemetry.ipynb')
                captured=[]
                def notebook_client(notebook,**kwargs):
                    captured.append(notebook)
                    return SimpleNamespace(execute=Mock(side_effect=RuntimeError('stop before execution')))
                with patch.object(run_deployment,'ROOT',root),patch.object(run_deployment,'update'), \
                     patch.object(run_deployment,'NotebookClient',side_effect=notebook_client), \
                     contextlib.redirect_stdout(io.StringIO()):
                    self.assertFalse(run_deployment.run(13,docker=True,live=live))
                config=next(c.source for c in captured[0].cells if 'deployment_configuration' in c.metadata.get('tags',[]))
                self.assertIn('RUN_LOCAL_CHECKS = '+str(enabled),config)
                self.assertIn('RUN_DOCKER = True',config)

    def test_final_validation_error_survives_session_cleanup_error(self):
        with telemetry(instrumented=True) as (env,steps,clean,calls,clock,output,lab):
            for step in range(1,6):exec(steps[step],env)
            env['_validate_lesson']=Mock(side_effect=ValueError('original validation'))
            clean.side_effect=RuntimeError('cleanup fixture')
            with self.assertRaisesRegex(ValueError,'original validation') as raised:exec(steps[6],env)
            self.assertTrue(raised.exception.__notes__)
            self.assertTrue(env['hooks'].closed)


if __name__=='__main__':unittest.main()
