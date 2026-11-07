"""User approval and rejection exercise the real callback/handler without an API."""
import ast
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from tutorial_helpers.validation import analyze_csv, render_markdown, validate_lesson

from notebook_code import cells, definition, tree
from test_extensions import respond
from tutorial_helpers.extensions import PolicyError, interactive_approval, validation_approval, ResultCache

Gate = definition(11, "PublicationGate", {
    "Path": Path, "json": json, "hashlib": hashlib,
    "PolicyError": PolicyError, "interactive_approval": interactive_approval,
})


def outcome_check():
    branch = next(n for n in ast.walk(tree(11))
                  if isinstance(n, ast.If) and ast.unparse(n.test) == "gate.decision.approved")
    return compile(ast.fix_missing_locations(ast.Module(body=[branch], type_ignores=[])),
                   "chapter11-outcome", "exec")


class ApprovalWalkthroughTests(unittest.TestCase):
    def test_console_guidance_and_strict_approval_input(self):
        for entered, approved in [("APPROVE", True), ("REJECT", False), ("APPROVE ", False)]:
            with self.subTest(entered=entered), patch("builtins.input", return_value=entered), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                result = interactive_approval("report", "digest", "training")
            self.assertEqual(result.approved, approved)
            self.assertIn("top of the window", output.getvalue())
            self.assertIn("REJECT", output.getvalue())
            self.assertIn("no automatic timeout", output.getvalue())

    def test_visible_mode_ignores_legacy_fixture_environment(self):
        source = next("".join(c["source"]) for c in cells(11) if c["id"] == "397aa19831a5")
        for mode, expected in [("interactive", interactive_approval), ("fixture", validation_approval)]:
            env = {"APPROVAL_MODE": mode, "PolicyError": PolicyError,
                   "interactive_approval": interactive_approval, "validation_approval": validation_approval,
                   "csv_text": "date,product,quantity,unit_price\n2026-01-01,A,2,10000\n", "REVIEW_MODE": "none"}
            with patch.dict("os.environ", {"TUTORIAL_APPROVAL_FIXTURE": "1"}), \
                    contextlib.redirect_stdout(io.StringIO()):
                exec(source, env)
            self.assertIs(env["approver"], expected)

    def test_user_decision_flows_to_tool_result_and_expected_outcome(self):
        for entered, approved in [("APPROVE", True), ("REJECT", False)]:
            with self.subTest(entered=entered), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                report = root / "report.md"
                project = Path(__file__).resolve().parents[1]
                expected = analyze_csv((project / "data/sales.csv").read_text())
                report.write_text(render_markdown(expected))
                (root / "summary.json").write_text(json.dumps(expected))
                gate = Gate("report", report, root / "registered", approver=interactive_approval)
                action = {"type": "function_call", "name": "publish_report",
                          "arguments": {"report_id": "report", "channel": "training"},
                          "turn_id": "turn-fixture", "call_id": "call-fixture"}
                with patch("builtins.input", return_value=entered) as input_mock, \
                        contextlib.redirect_stdout(io.StringIO()):
                    result = respond({"publish_report": gate.publish}, root / "cache", "session-fixture", action)
                    repeated = respond({"publish_report": gate.publish}, root / "cache", "session-fixture", action)
                input_mock.assert_called_once()
                self.assertEqual(result, repeated)
                self.assertEqual(result["success"], approved)
                outcome = json.loads(result["output"]) if approved else {
                    "publication_status": "denied", "reason": result["error"]}
                env = {"gate": gate, "outcome": outcome, "downloads": root, "using_fixture": False}
                exec(outcome_check(), env)
                self.assertEqual(env["registered"], approved)
                self.assertEqual(env["decision_label"], "approved" if approved else "rejected")
                env.update(settings=SimpleNamespace(root=project),
                           denial={"publication_status": "denied", "reason": "channel_not_allowed"})
                for name in ["analysis", "denied", "approval_result"]:
                    env[name] = SimpleNamespace(
                        session_id="session-fixture", turn_id=name,
                        turn=SimpleNamespace(id=name, status="completed", usage=None),
                        output_text=json.dumps(expected),
                    )
                cache = ResultCache(root / "validation-cache")
                history = [SimpleNamespace(type="command_execution", turn_id="analysis", status="completed", exit_code=0)]
                for turn_id, channel, tool_response in [
                    ("denied", "external", {"success": False, "error": "channel_not_allowed"}),
                    ("approval_result", "training", {"success": approved, **({"output": json.dumps(outcome)} if approved else {"error": "approval_denied"})}),
                ]:
                    arguments = {"report_id": "report", "channel": channel}
                    cache.save(["session-fixture", turn_id, turn_id],
                               {"name": "publish_report", "arguments": arguments},
                               dict(type="agent.session.input.tool_result", turn_id=turn_id, call_id=turn_id, **tool_response))
                    history.append(SimpleNamespace(type="function_call", turn_id=turn_id, call_id=turn_id,
                                                   name="publish_report", arguments=arguments, status="completed"))
                env["cache"] = cache
                checks, turns = validate_lesson("11_guardrails_approvals", env, history)
                self.assertEqual(checks["approval_decision"], env["decision_label"])
                self.assertEqual(len(turns), 3)
                if not approved:
                    self.assertFalse(gate.destination.exists())
                    env["outcome"] = {"publication_status": "published"}
                    with self.assertRaises(AssertionError):
                        exec(outcome_check(), env)


if __name__ == "__main__":
    unittest.main()
