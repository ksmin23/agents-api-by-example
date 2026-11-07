"""Prevent API orchestration from becoming opaque project helpers again."""

import ast
from pathlib import Path
import unittest
from notebook_code import ROOT, tree, cells


class ApiVisibilityTests(unittest.TestCase):
    def test_helpers_do_not_hide_agent_execution(self):
        allowed = {"cleanup_resources", "delete_session_safely"}
        for path in (ROOT / "src/tutorial_helpers").glob("*.py"):
            parsed = ast.parse(path.read_text())
            for fn in (n for n in ast.walk(parsed) if isinstance(n, ast.FunctionDef)):
                for node in ast.walk(fn):
                    if isinstance(node, ast.Call) and ".beta.agents" in ast.unparse(
                        node.func
                    ):
                        self.assertEqual(path.name, "common.py")
                        self.assertIn(fn.name, allowed)

    def test_api_chapters_show_creation_stream_turn_lookup_and_deletion(self):
        for number in range(2, 16):
            with self.subTest(chapter=number):
                text = ast.unparse(tree(number))
                for api in [
                    "client.beta.agents.sessions.create",
                    "client.beta.agents.sessions.turns.retrieve",
                    "cleanup_resources",
                    "for event in",
                ]:
                    self.assertIn(api, text)
                self.assertIn("finally:", text)

    def test_function_response_is_in_the_lesson_and_uses_pending_call_ids(self):
        for number in [11]:
            text = ast.unparse(tree(number))
            self.assertIn("client.beta.agents.sessions.events.create", text)
            self.assertIn("'turn_id': action.turn_id", text)
            self.assertIn("'call_id': action.call_id", text)

    def test_recovery_subscribes_before_saved_state_and_sends_input_once(self):
        parsed = tree(14)
        streams = [
            n
            for n in ast.walk(parsed)
            if isinstance(n, ast.With)
            and any(
                "client.beta.agents.sessions.events.stream"
                in ast.unparse(i.context_expr)
                for i in n.items
            )
        ]
        self.assertEqual(len(streams), 2)
        recovery = streams[1]
        self.assertIn(
            "client.beta.agents.sessions.retrieve", ast.unparse(recovery.body[0])
        )
        message_calls = [
            n
            for n in ast.walk(parsed)
            if isinstance(n, ast.Call)
            and ast.unparse(n.func) == "client.beta.agents.sessions.events.create"
            and any(k.arg == "idempotency_key" for k in n.keywords)
        ]
        self.assertEqual(len(message_calls), 1)


class SimplificationTests(unittest.TestCase):
    def test_sdk_handlers_and_no_run_record(self):
        text = ast.unparse(tree(7))
        self.assertIn("function_tool(get_sales_target)", text)
        self.assertIn("tool_handlers=handlers", text)
        for number in range(1, 16):
            source = ast.unparse(tree(number))
            self.assertNotIn("RunRecord", source)
            self.assertNotIn("def new_session_metadata", source)
            self.assertNotIn("def delete_session_safely", source)

    def test_custom_skill_inventory_before_cleanup(self):
        source = ast.unparse(tree(9))
        self.assertLess(
            source.index("client.beta.agents.environments.retrieve"),
            source.index("cleanup_resources(client"),
        )
