"""Exercise failure/cleanup and evidence checks without creating real sessions."""
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import httpx2
from openai import ConflictError, NotFoundError
from tutorial_helpers.common import delete_session_safely

ROOT = Path(__file__).resolve().parents[1]
from tutorial_helpers.validation import verify_execution
from tutorial_helpers.common import safe_error as error_metadata


def api_error(kind, status):
    request = httpx2.Request('GET', 'https://api.openai.com/v1/agents/sessions/sess_fixture')
    return kind('fixture', response=httpx2.Response(status, request=request), body=None)


class QuickstartTests(unittest.TestCase):
    def test_idle_session_deletes_and_confirms_404(self):
        client = Mock()
        api = client.beta.agents.sessions
        api.retrieve.side_effect = [SimpleNamespace(status='idle'), api_error(NotFoundError, 404)]
        api.delete.return_value = SimpleNamespace(deleted=True)
        result = delete_session_safely(client, 'sess_fixture')
        self.assertTrue(result['verified_absent'])
        api.events.create.assert_not_called()

    def test_active_work_is_cancelled_before_retrying_delete(self):
        client = Mock()
        api = client.beta.agents.sessions
        api.retrieve.side_effect = [SimpleNamespace(status='in_progress'),
                                   SimpleNamespace(status='idle'), api_error(NotFoundError, 404)]
        api.delete.side_effect = [api_error(ConflictError, 409), SimpleNamespace(deleted=True)]
        pause = Mock()
        result = delete_session_safely(client, 'sess_fixture', sleep=pause)
        self.assertTrue(result['cancel_sent'])
        self.assertEqual(result['attempts'], 2)
        api.events.create.assert_called_once_with('sess_fixture', events=[{'type':'agent.session.input.cancel'}], timeout=15)
        self.assertEqual(api.mock_calls[1][0], 'events.create')
        self.assertEqual(api.mock_calls[2][0], 'delete')
        pause.assert_called_once_with(1)

    def test_conflict_retries_are_bounded_and_do_not_claim_deletion(self):
        client = Mock()
        api = client.beta.agents.sessions
        api.retrieve.return_value = SimpleNamespace(status='idle')
        api.delete.side_effect = api_error(ConflictError, 409)
        with self.assertRaisesRegex(RuntimeError, 'pending'):
            delete_session_safely(client, 'sess_fixture', attempts=2, sleep=Mock())
        self.assertEqual(api.delete.call_count, 2)

    def test_already_absent_session_needs_no_cancel_or_delete(self):
        client = Mock()
        api = client.beta.agents.sessions
        api.retrieve.side_effect = api_error(NotFoundError, 404)
        result = delete_session_safely(client, 'sess_fixture')
        self.assertTrue(result['verified_absent'])
        api.delete.assert_not_called()

    def result(self, status='completed'):
        return SimpleNamespace(turn=SimpleNamespace(status=status), output_text='{"count":3,"total":60}')

    def test_final_answer_without_command_evidence_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'command output'):
            verify_execution(self.result(), [])

    def test_failed_command_is_rejected_even_if_output_claims_success(self):
        commands = [{'status':'failed','exit_code':1,'output':'{"count":3,"total":60}'}]
        with self.assertRaises(RuntimeError):
            verify_execution(self.result(), commands)

    def test_failed_turn_is_rejected_even_if_answer_is_correct(self):
        with self.assertRaisesRegex(RuntimeError, 'root turn'):
            verify_execution(self.result('failed'), [])

    def test_success_requires_matching_stdout_and_final_answer(self):
        commands = [{'status':'completed','exit_code':0,'output':'{"count": 3, "total": 60}\n'}]
        self.assertTrue(verify_execution(self.result(), commands)['command_output_verified'])

    def test_stdout_label_does_not_hide_a_valid_command_result(self):
        commands = [{'status':'completed','exit_code':0,'output':'stdout: {"count":3,"total":60}\nexit_code: 0\n'}]
        self.assertTrue(verify_execution(self.result(), commands)['command_output_verified'])

    def test_wrong_stdout_is_rejected_despite_correct_final_answer(self):
        commands = [{'status':'completed','exit_code':0,'output':'stdout: {"count":3,"total":61}'}]
        with self.assertRaises(RuntimeError):
            verify_execution(self.result(), commands)

    def test_error_body_is_not_logged(self):
        error = RuntimeError('private request details must not be recorded')
        self.assertNotIn('private', json.dumps(error_metadata(error)))


if __name__ == '__main__':
    unittest.main()
