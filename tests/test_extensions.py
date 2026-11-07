import asyncio
import base64
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock
import zipfile

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from tutorial_helpers.validation import analyze_csv, render_markdown, verify_report, verify_enriched
from tutorial_helpers.extensions import (
    ResultCache,
    PolicyError,
    Approval,
    validation_approval,
    archive_folder,
)
from notebook_code import definition, required_action_code
from types import SimpleNamespace

namespace = {
    "PolicyError": PolicyError,
    "Path": Path,
    "json": json,
    "hashlib": hashlib,
    "verify_report": verify_report,
    "interactive_approval": validation_approval,
}
ROOT = Path(__file__).resolve().parents[1]
namespace.update(settings=SimpleNamespace(root=ROOT), ACTOR_ROLE="analyst")
get_sales_target = definition(7, "get_sales_target", namespace)
from openai.lib.beta.agents import function_tool

pending_responder = definition(
    11, "respond_to_pending", {"json": json, "PolicyError": PolicyError}
)
PublicationGate = definition(11, "PublicationGate", namespace)
REQUIRED_ACTION = required_action_code()


def respond(handlers, directory, session_id, action):
    client = Mock()
    env = {
        "cache": ResultCache(directory),
        "handlers": handlers,
        "json": json,
        "PolicyError": PolicyError,
        "event": SimpleNamespace(
            session=SimpleNamespace(
                id=session_id, required_actions=[SimpleNamespace(**action)]
            )
        ),
        "function_results": [],
        "respond_to_pending": pending_responder,
        "client": client,
    }
    exec(REQUIRED_ACTION, env)
    return client.beta.agents.sessions.events.create.call_args.kwargs["events"][0]


ROOT = Path(__file__).resolve().parents[1]
EXPECTED = analyze_csv((ROOT / "data/sales.csv").read_text())


class FunctionTests(unittest.TestCase):
    def test_durable_cache_preserves_original_ids_and_avoids_duplicate_handler(self):
        with tempfile.TemporaryDirectory() as directory:
            handler = Mock(return_value={"target_revenue": 150000})
            action = {
                "type": "function_call",
                "turn_id": "turn_fixture",
                "call_id": "call_fixture",
                "name": "get_sales_target",
                "arguments": {"period": "2026-01"},
            }
            first = respond(
                {"get_sales_target": handler}, directory, "sess_fixture", action
            )
            second = respond(
                {"get_sales_target": handler}, directory, "sess_fixture", action
            )
            self.assertEqual(first, second)
            self.assertEqual(first["turn_id"], "turn_fixture")
            self.assertEqual(first["call_id"], "call_fixture")
            handler.assert_called_once()
            changed = {**action, "arguments": {"period": "2026-02"}}
            with self.assertRaisesRegex(ValueError, "call_identity_changed"):
                respond(
                    {"get_sales_target": handler}, directory, "sess_fixture", changed
                )

    def test_target_role_and_argument_checks(self):
        tool = function_tool(get_sales_target)
        self.assertEqual(get_sales_target("2026-01")["target_revenue"], 150000)
        self.assertEqual(
            json.loads(tool({"period": "2026-01"}))["target_revenue"], 150000
        )
        with self.assertRaises(PolicyError):
            get_sales_target("2026-02")
        namespace["ACTOR_ROLE"] = "viewer"
        try:
            with self.assertRaises(PolicyError):
                get_sales_target("2026-01")
        finally:
            namespace["ACTOR_ROLE"] = "analyst"
        from pydantic import ValidationError

        for args in ({}, {"period": "2026-01", "approved": True}):
            with self.assertRaises(ValidationError):
                tool(args)

    def test_enriched_metrics_reject_nested_product_values_and_wrong_attainment(self):
        value = {"metrics": EXPECTED, "target_revenue": 150000, "attainment_rate": 0.85}
        self.assertEqual(
            verify_enriched(value, EXPECTED, {"target_revenue": 150000}), value
        )
        malformed = {
            **value,
            "metrics": {
                **EXPECTED,
                "by_product": {"A": {"total_revenue": 30000}, "B": 75000, "C": 22500},
            },
        }
        with self.assertRaises(ValueError):
            verify_enriched(malformed, EXPECTED, {"target_revenue": 150000})
        for invalid_rate in (0.9, 85.0):
            with self.assertRaises(ValueError):
                verify_enriched(
                    {**value, "attainment_rate": invalid_rate},
                    EXPECTED,
                    {"target_revenue": 150000},
                )

    def test_handler_failure_does_not_return_private_error_body(self):
        with tempfile.TemporaryDirectory() as directory:
            handler = Mock(side_effect=RuntimeError("private-credential-fixture"))
            action = {
                "type": "function_call",
                "turn_id": "t",
                "call_id": "c",
                "name": "lookup",
                "arguments": {},
            }
            result = respond({"lookup": handler}, directory, "s", action)
            self.assertFalse(result["success"])
            self.assertNotIn("private-credential-fixture", json.dumps(result))


class BundleTests(unittest.TestCase):
    def test_skill_bundle_is_deterministic_and_has_one_root(self):
        raw = archive_folder(ROOT / "skills/csv-report")
        self.assertEqual(raw, archive_folder(ROOT / "skills/csv-report"))
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = archive.namelist()
            self.assertIn("csv-report/SKILL.md", names)
            self.assertTrue(all(name.startswith("csv-report/") for name in names))
            self.assertTrue(
                all(".env" not in name and ".venv" not in name for name in names)
            )

    def test_plugin_declares_skill_and_stdio_configuration(self):
        raw = archive_folder(ROOT / "plugins/sales-reporting")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            manifest = json.loads(
                archive.read("sales-reporting/.codex-plugin/plugin.json")
            )
            self.assertEqual(manifest["skills"], "./skills/")
            config = json.loads(archive.read("sales-reporting/.mcp.json"))
            self.assertEqual(config["mcpServers"]["sales_targets"]["cwd"], ".")
            self.assertIn(
                "sales-reporting/servers/sales_targets_server.py", archive.namelist()
            )

    def test_actual_skill_script_produces_verified_report_and_input_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "skills/csv-report/scripts/analyze_sales.py"),
                    "--input",
                    str(ROOT / "data/sales.csv"),
                    "--output-dir",
                    directory,
                ],
                check=True,
                capture_output=True,
            )
            folder = Path(directory)
            self.assertEqual(
                json.loads((folder / "summary.json").read_text()), EXPECTED
            )
            evidence = json.loads((folder / "skill_evidence.json").read_text())
            self.assertEqual(
                evidence["input_sha256"],
                hashlib.sha256((ROOT / "data/sales.csv").read_bytes()).hexdigest(),
            )


class ApprovalTests(unittest.TestCase):
    def make_gate(self, folder, approver=validation_approval, role="analyst"):
        report = Path(folder) / "report.md"
        report.write_text(render_markdown(EXPECTED))
        return PublicationGate(
            "sales-2026-01",
            report,
            Path(folder) / "published",
            approver=approver,
            actor_role=role,
        )

    def test_forbidden_channel_is_denied_before_approval_and_before_any_write(self):
        with tempfile.TemporaryDirectory() as directory:
            approve = Mock()
            gate = self.make_gate(directory, approve)
            with self.assertRaisesRegex(PolicyError, "channel_not_allowed"):
                gate.publish({"report_id": gate.report_id, "channel": "external"})
            approve.assert_not_called()
            self.assertFalse(gate.destination.exists())

    def test_model_supplied_approval_flag_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            gate = self.make_gate(directory)
            with self.assertRaisesRegex(PolicyError, "invalid_arguments"):
                gate.publish(
                    {
                        "report_id": gate.report_id,
                        "channel": "training",
                        "approved": True,
                    }
                )
            self.assertFalse(gate.destination.exists())

    def test_denial_and_digest_mismatch_prevent_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            gate = self.make_gate(
                directory,
                lambda rid, digest, channel: Approval(
                    False, rid, digest, channel, "fixture", "fixture"
                ),
            )
            with self.assertRaisesRegex(PolicyError, "approval_denied"):
                gate.publish({"report_id": gate.report_id, "channel": "training"})
            gate.approver = lambda rid, digest, channel: Approval(
                True, rid, "wrong-digest", channel, "fixture", "fixture"
            )
            with self.assertRaisesRegex(PolicyError, "binding_mismatch"):
                gate.publish({"report_id": gate.report_id, "channel": "training"})
            self.assertFalse(gate.destination.exists())

    def test_mutated_report_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            gate = self.make_gate(directory)
            gate.path.write_text(gate.path.read_text() + "changed")
            with self.assertRaisesRegex(PolicyError, "report_changed"):
                gate.publish({"report_id": gate.report_id, "channel": "training"})

    def test_fixture_approval_writes_exact_bytes_and_is_labelled_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            gate = self.make_gate(directory)
            receipt = gate.publish({"report_id": gate.report_id, "channel": "training"})
            self.assertEqual(receipt["approval_origin"], "fixture")
            self.assertEqual(
                (gate.destination / f"{gate.digest}.md").read_bytes(),
                gate.path.read_bytes(),
            )


class McpProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_stdio_protocol_tool_discovery_and_call(self):
        params = StdioServerParameters(
            command=sys.executable,
            args=[
                str(ROOT / "examples/mcp/sales_targets_server.py"),
                "--data",
                str(ROOT / "data/sales_targets.json"),
            ],
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                self.assertIn("get_sales_target", [tool.name for tool in tools.tools])
                result = await session.call_tool(
                    "get_sales_target", {"period": "2026-01"}
                )
                self.assertFalse(result.isError)
                payload = result.structuredContent or json.loads(
                    next(item.text for item in result.content if item.type == "text")
                )
                self.assertEqual(payload["target_revenue"], 150000)
                denied = await session.call_tool(
                    "get_sales_target", {"period": "2026-02"}
                )
                self.assertTrue(denied.isError)


if __name__ == "__main__":
    unittest.main()
