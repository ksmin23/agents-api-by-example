"""Real source policy and callback with simulated API calls; no paid requests."""
import contextlib
import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from notebook_code import definition
from test_approval_steps import lesson
from test_approval_walkthrough import Gate
from test_extensions import respond
from tutorial_helpers.extensions import Approval, PolicyError, ResultCache
from tutorial_helpers.validation import analyze_csv, render_markdown, validate_lesson

ROOT = Path(__file__).resolve().parents[1]
Callback = definition(11, 'interactive_approval', {'Approval': Approval})
ValidateInput = definition(11, 'validate_input', {'csv': csv, 'io': io, 'PolicyError': PolicyError})


@contextlib.contextmanager
def completed(entered='APPROVE'):
    with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
        root = Path(directory)
        expected = analyze_csv((ROOT / 'data/sales.csv').read_text())
        (root / 'summary.json').write_text(json.dumps(expected))
        (root / 'report.md').write_text(render_markdown(expected))
        gate = Gate('sales-2026-01', root / 'report.md', root / 'registered', approver=Callback)
        history = [SimpleNamespace(type='command_execution', turn_id='analysis', status='completed', exit_code=0)]
        outputs = {}
        for channel in ['external', 'training']:
            action = dict(type='function_call', name='publish_report',
                          arguments={'report_id': gate.report_id, 'channel': channel},
                          turn_id=channel, call_id=channel+'-call')
            with patch('builtins.input', return_value=entered):
                response = respond({'publish_report': gate.publish}, root / 'cache', 'session', action)
            outputs[channel] = json.loads(response['output']) if response['success'] else {
                'publication_status': 'denied', 'reason': response['error']}
            history.append(SimpleNamespace(**(action | {'status': 'completed' if response['success'] else 'failed'})))
        def result(turn_id, value):
            return SimpleNamespace(session_id='session', turn_id=turn_id,
                                   turn=SimpleNamespace(id=turn_id, status='completed', usage=None),
                                   output_text=json.dumps(value))
        env = dict(settings=SimpleNamespace(root=ROOT), gate=gate, downloads=root,
                   analysis=result('analysis', expected), denied=result('external', outputs['external']),
                   approval_result=result('training', outputs['training']), denial=outputs['external'],
                   outcome=outputs['training'], cache=ResultCache(root / 'cache'))
        yield env, history


class ApprovalIntegrityTests(unittest.TestCase):
    def test_visible_callback_returns_only_exact_approval_and_bound_identity(self):
        for text, approved in [('APPROVE', True), ('REJECT', False), ('APPROVE ', False), ('approve', False)]:
            with self.subTest(text=text), patch('builtins.input', return_value=text), contextlib.redirect_stdout(io.StringIO()):
                decision = Callback('report', 'digest', 'training')
            self.assertEqual(decision, Approval(approved, 'report', 'digest', 'training', 'local-learner', 'interactive'))

    def test_actual_input_rejects_missing_columns_empty_invalid_integer_and_negatives(self):
        header = 'date,product,quantity,unit_price\n'
        for text in ['', header, 'product,quantity,unit_price\nA,2,10000\n',
                     header+'2026-01-01,A,no,100\n', header+'2026-01-01,A,-1,100\n',
                     header+'2026-01-01,A,1,-100\n', header+'2026-01-01,A,1\n',
                     header+'2026-01-01,A,1,100,extra\n']:
            with self.subTest(text=text), self.assertRaisesRegex(PolicyError, 'invalid_csv'):
                ValidateInput(text)
        self.assertEqual(len(ValidateInput((ROOT / 'data/sales.csv').read_text())), 6)

    def test_invalid_actual_submission_never_creates_a_session(self):
        with lesson() as (env, stages, cleanup, calls, clock):
            env.update(validate_input=ValidateInput, csv_bytes=b'product,quantity,unit_price\nA,2,10000\n')
            with self.assertRaisesRegex(PolicyError, 'invalid_csv'):
                exec(stages[1], env)
            env['client'].beta.agents.sessions.create.assert_not_called()
            cleanup.assert_called_once()

    def test_report_mutated_during_approval_is_blocked_before_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'report.md'
            path.write_text('# 매출 분석 보고서\nReviewed bytes.\n')
            def mutate(report_id, digest, channel):
                path.write_text(path.read_text()+'Changed while waiting.\n')
                return Approval(True, report_id, digest, channel, 'fixture', 'fixture')
            gate = Gate('report', path, root / 'registered', approver=mutate)
            with self.assertRaisesRegex(PolicyError, 'report_changed'):
                gate.publish({'report_id': 'report', 'channel': 'training'})
            self.assertFalse(gate.destination.exists())
            self.assertFalse(gate.receipts)
            self.assertNotEqual(hashlib.sha256(path.read_bytes()).hexdigest(), gate.digest)

    def test_approved_and_rejected_actual_policy_results_validate_against_history_cache_files(self):
        for entered in ['APPROVE', 'REJECT']:
            with self.subTest(entered=entered), completed(entered) as (env, history):
                checks, turns = validate_lesson('11_guardrails_approvals', env, history)
                self.assertEqual(len(turns), 3)
                self.assertEqual(checks['approval_decision'], 'approved' if entered=='APPROVE' else 'rejected')
                self.assertEqual([v['success'] for v in checks['tool_results']], [False, entered=='APPROVE'])
                self.assertEqual(checks['approval_mode'], 'interactive')

    def test_model_denial_text_alone_cannot_replace_actual_call_and_bound_error_result(self):
        for mode in ['missing', 'wrong_name', 'wrong_channel', 'duplicate', 'call_id', 'pending', 'wrong_error', 'success']:
            with self.subTest(mode=mode), completed() as (env, history):
                external = history[1]
                if mode == 'missing': history.remove(external)
                elif mode == 'wrong_name': external.name = 'other'
                elif mode == 'wrong_channel': external.arguments = {'report_id': env['gate'].report_id, 'channel': 'training'}
                elif mode == 'duplicate': history.append(external)
                elif mode == 'call_id': external.call_id = 'different'
                elif mode == 'pending': external.status = 'in_progress'
                else:
                    cache = env['cache']
                    key = ['session', 'external', 'external-call']
                    request = {'name': 'publish_report', 'arguments': external.arguments}
                    response = cache.load(key, request)
                    response['error' if mode=='wrong_error' else 'success'] = 'different' if mode=='wrong_error' else True
                    cache.save(key, request, response)
                with self.assertRaises(ValueError):
                    validate_lesson('11_guardrails_approvals', env, history)

    def test_session_continuity_receipt_and_model_success_tampering_are_rejected(self):
        for mode in ['session', 'turn', 'receipt', 'model']:
            with self.subTest(mode=mode), completed() as (env, history):
                if mode == 'session': env['approval_result'].session_id = 'different'
                elif mode == 'turn': env['approval_result'].turn_id = env['denied'].turn_id
                elif mode == 'receipt':
                    path = env['gate'].destination / f"{env['gate'].digest}.approval.json"
                    receipt = json.loads(path.read_text());receipt['actor'] = 'tampered'
                    path.write_text(json.dumps(receipt))
                else: env['outcome']['channel'] = 'external'
                with self.assertRaises(ValueError):
                    validate_lesson('11_guardrails_approvals', env, history)

    def test_cleanup_after_approval_without_result_display_reports_actual_registration(self):
        for entered in ['APPROVE', 'REJECT']:
            with self.subTest(entered=entered), lesson(entered) as (env, stages, cleanup, calls, clock):
                for step in range(1, 5): exec(stages[step], env)
                exec(stages[6], env)
                self.assertEqual(env['decision_label'], 'approved' if entered=='APPROVE' else 'rejected')
                self.assertEqual(env['registered'], entered=='APPROVE')
                self.assertEqual(env['gate'].destination.exists(), entered=='APPROVE')
                cleanup.assert_called_once()

    def test_review_modes_are_independent_of_business_callback_and_cleanup_preserves_original_error(self):
        for mode in ['none', 'auto_review']:
            with self.subTest(mode=mode), lesson('REJECT') as (env, stages, cleanup, calls, clock):
                env['REVIEW_MODE'] = mode
                env['client'].beta.agents.sessions.retrieve.return_value.review = mode
                for step in range(1, 6): exec(stages[step], env)
                self.assertEqual(env['client'].beta.agents.sessions.create.call_args.kwargs['review'], mode)
                self.assertEqual(env['decision_label'], 'rejected')
                exec(stages[6], env)
                cleanup.assert_called_once()
        with lesson() as (env, stages, cleanup, calls, clock):
            exec(stages[1], env)
            env['client'].beta.agents.sessions.retrieve.side_effect = ValueError('original review lookup')
            cleanup.side_effect = RuntimeError('cleanup fixture')
            with self.assertRaisesRegex(ValueError, 'original review lookup') as raised:
                exec(stages[6], env)
            self.assertTrue(raised.exception.__notes__)


if __name__ == '__main__': unittest.main()
