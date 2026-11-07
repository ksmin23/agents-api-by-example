"""Run the actual continuation cells with fake API streams and paginated history."""
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
from tutorial_helpers.common import cleanup_on_error, check_event, new_session_metadata, safe_error
from tutorial_helpers.validation import analyze_csv, daily_revenue, validate_lesson, save_validation

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
        calls = []
        clock = SimpleNamespace(now=0)
        turns = [SimpleNamespace(id=f'turn-{i}', status='completed', subagent_id=None, usage=None) for i in [1,2]]
        results = [SimpleNamespace(session_id='session-fixture', turn_id=t.id, turn=t,
                   output_text=json.dumps(value)) for t,value in zip(turns,[analyze_csv(csv_text),daily_revenue(csv_text)])]
        streams=[]
        for index,result in enumerate(results):
            events = [SimpleNamespace(type='agent.session.turn.output_text.delta', delta=result.output_text),
                      SimpleNamespace(type='agent.session.turn.completed', turn=result.turn)]
            if index==0:
                events.insert(0,SimpleNamespace(type='agent.session.created',session=SimpleNamespace(
                    id=result.session_id,environment=SimpleNamespace(id='environment-fixture'))))
            stream=Mock()
            stream.with_result_collection.return_value=stream
            stream.__enter__=Mock(return_value=stream)
            stream.__exit__=Mock(return_value=False)
            stream.__iter__=Mock(side_effect=lambda events=events: iter(events))
            stream.get_final_result.return_value=result
            streams.append(stream)
        client=Mock()
        client.beta.agents.sessions.create.side_effect=lambda **kw: calls.append('create') or streams[0]
        client.beta.agents.sessions.stream.side_effect=lambda *a,**kw: calls.append('submit') or streams[1]
        def retrieve(tid,**kw):
            calls.append('retrieve:'+tid)
            return next(t for t in turns if t.id==tid)
        client.beta.agents.sessions.turns.retrieve.side_effect=retrieve
        commands=[SimpleNamespace(type='command_execution', turn_id=t.id, status='completed',
                                  exit_code=0, command='python analyze.py') for t in turns]
        class Pages:
            def __init__(self, name, values):self.name,self.values=name,values
            def __iter__(self):
                for index,value in enumerate(self.values):
                    calls.append(f'{self.name}.page.{index+1}')
                    yield value
        client.beta.agents.sessions.turns.list.side_effect=lambda *a,**kw: Pages('turns',turns)
        client.beta.agents.sessions.items.list.side_effect=lambda *a,**kw: Pages('items',commands)
        def cleanup(client,sessions,agents,attempts):
            calls.append('cleanup')
            for value in sessions.values():value.update(deleted=True,verified_absent=True)
            client.close()
            return []
        clean=Mock(side_effect=cleanup)
        env=dict(settings=SimpleNamespace(root=root,model='fixture',api_key=None),CHAPTER='03_sessions',
                 client=client,uuid4=uuid4,json=json,sys=sys,csv_text=csv_text,task='raw CSV fixture',
                 follow_up='Read existing /workspace/sales.csv; calculate daily sales.',BASE_INSTRUCTIONS='fixture',
                 time=SimpleNamespace(monotonic=lambda:clock.now),cleanup_on_error=cleanup_on_error,
                 cleanup_resources=clean,new_session_metadata=new_session_metadata,check_event=check_event,safe_error=safe_error)
        nb=nbformat.read(ROOT/'notebooks/chapters/03_sessions.ipynb',as_version=4)
        if instrumented:instrument_notebook(nb,'03_sessions',live=True)
        steps={i:next(c.source for c in nb.cells if f'session_step_{i}' in c.metadata.get('tags',[])) for i in range(1,5)}
        with patch('tutorial_helpers.common.cleanup_resources',clean),contextlib.redirect_stdout(io.StringIO()) as output:
            if instrumented:
                exec(nb.cells[0].source,env)
                def validate(*a):
                    calls.append('validate')
                    return validate_lesson(*a)
                env.update(_validate_lesson=validate,_save_validation=save_validation)
            exec(next(c.source for c in nb.cells if c.id=='3f0c8ec1e389'),env)
            try:yield env,steps,clean,calls,clock,output,streams
            finally:
                env.pop('_validation_error',None)
                env.clear()


class SessionStepTests(unittest.TestCase):
    def test_continuation_order_key_pagination_and_cleanup(self):
        for instrumented in [False,True]:
            with self.subTest(instrumented=instrumented),lesson(instrumented) as (env,steps,clean,calls,clock,output,streams):
                key=env['message_key']
                clock.now=2000
                exec(steps[1],env)
                self.assertEqual(env['started'],2000)
                clean.assert_not_called()
                clock.now=5000
                exec(steps[2],env)
                self.assertEqual(env['started'],5000)
                env['client'].beta.agents.sessions.create.assert_called_once()
                env['client'].beta.agents.sessions.stream.assert_called_once_with(
                    'session-fixture',input=env['follow_up'],idempotency_key=key)
                self.assertLess(calls.index('retrieve:turn-1'),calls.index('submit'))
                exec(steps[3],env)
                clean.assert_not_called()
                self.assertTrue(env['same_session'] and env['distinct_turns'])
                self.assertIn('turns.page.2',calls)
                self.assertIn('items.page.2',calls)
                self.assertIn('First analysis:',output.getvalue())
                self.assertIn('Follow-up analysis:',output.getvalue())
                self.assertIn('Stored turns:',output.getvalue())
                exec(steps[4],env)
                clean.assert_called_once()
                self.assertTrue(env['sessions']['session-fixture']['verified_absent'])
                if instrumented:
                    self.assertLess(calls.index('validate'),calls.index('cleanup'))
                    self.assertEqual(env['_validation_summary']['status'],'passed')

    def test_follow_up_requires_first_completion(self):
        with lesson(True) as (env,steps,clean,*rest):
            with self.assertRaisesRegex(RuntimeError,'Complete the first'):
                exec(steps[2],env)
            env['client'].beta.agents.sessions.stream.assert_not_called()
            clean.assert_called_once()

    def test_repeated_first_or_follow_up_submission_is_blocked(self):
        for step in [1,2]:
            with self.subTest(step=step),lesson() as (env,steps,clean,*rest):
                for i in range(1,step+1):exec(steps[i],env)
                key=env['message_key']
                with self.assertRaises(RuntimeError):exec(steps[step],env)
                self.assertEqual(env['message_key'],key)
                env['client'].beta.agents.sessions.create.assert_called_once()
                self.assertEqual(env['client'].beta.agents.sessions.stream.call_count,step-1)
                clean.assert_called_once()

    def test_failed_first_turn_never_submits_follow_up(self):
        with lesson(True) as (env,steps,clean,calls,clock,output,streams):
            streams[0].get_final_result.return_value.turn.status='failed'
            with self.assertRaisesRegex(RuntimeError,'completion'):
                exec(steps[1],env)
            env['client'].beta.agents.sessions.stream.assert_not_called()
            self.assertEqual(env['_validation_summary']['status'],'failed')

    def test_follow_up_interruption_cleans_up_and_keeps_attempt_record(self):
        with lesson(True) as (env,steps,clean,calls,clock,output,streams):
            exec(steps[1],env)
            streams[1].__iter__.side_effect=SimulatedInterruption('fixture')
            with self.assertRaises(SimulatedInterruption):exec(steps[2],env)
            self.assertTrue(env['follow_up_attempted'])
            clean.assert_called_once()
            self.assertEqual(env['_validation_summary']['status'],'failed')

    def test_session_or_turn_mismatch_and_missing_history_fail(self):
        for mode in ['session','turn','history']:
            with self.subTest(mode=mode),lesson(True) as (env,steps,clean,*rest):
                exec(steps[1],env);exec(steps[2],env)
                if mode=='session':env['second'].session_id='wrong-session'
                elif mode=='turn':env['second'].turn_id=env['first'].turn_id
                else:env['client'].beta.agents.sessions.turns.list.return_value=[];env['client'].beta.agents.sessions.turns.list.side_effect=None
                with self.assertRaises(RuntimeError):exec(steps[3],env)
                clean.assert_called_once()
                self.assertEqual(env['_validation_summary']['status'],'failed')

    def test_json_and_cleanup_failure_keep_original_error(self):
        with lesson(True) as (env,steps,clean,calls,clock,output,streams):
            exec(steps[1],env)
            streams[1].get_final_result.return_value.output_text='not json'
            clean.side_effect=RuntimeError('cleanup fixture')
            with self.assertRaises(json.JSONDecodeError) as raised:exec(steps[2],env)
            self.assertTrue(raised.exception.__notes__)
            self.assertEqual(env['_validation_summary']['status'],'failed')

    def test_partial_run_can_cleanup_without_follow_up(self):
        for count in [0,1]:
            with self.subTest(count=count),lesson() as (env,steps,clean,*rest):
                if count:exec(steps[1],env)
                exec(steps[4],env)
                env['client'].beta.agents.sessions.stream.assert_not_called()
                clean.assert_called_once()

    def test_validation_failure_still_cleans_up_and_saves_failure(self):
        with lesson(True) as (env,steps,clean,*rest):
            for i in [1,2,3]:exec(steps[i],env)
            env['_validate_lesson']=Mock(side_effect=ValueError('validation fixture'))
            clean.side_effect=RuntimeError('cleanup fixture')
            with self.assertRaisesRegex(ValueError,'validation fixture') as raised:exec(steps[4],env)
            clean.assert_called_once()
            self.assertTrue(raised.exception.__notes__)
            self.assertEqual(env['_validation_summary']['status'],'failed')


if __name__=='__main__':unittest.main()
