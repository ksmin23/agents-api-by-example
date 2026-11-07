"""Deterministic checks for tutorial CSV logic, artifact evidence and resource ownership."""

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from tutorial_helpers.common import load_settings, Settings, cleanup_resources, delete_session_safely, new_session_metadata
from tutorial_helpers.validation import analyze_csv, daily_revenue, render_markdown, verify_metrics, verify_report, save_validation
from openai import NotFoundError
import httpx2

CSV = (Path(__file__).resolve().parents[1] / "data/sales.csv").read_text()


class CommonDataTests(unittest.TestCase):
    def test_revenue_and_daily_totals_are_consistent(self):
        actual = analyze_csv(CSV)
        daily = daily_revenue(CSV)
        self.assertEqual(actual["total_revenue"], 127500)
        self.assertEqual(actual["total_quantity"], 11)
        self.assertEqual(
            sum(actual["by_product"].values()), sum(daily["daily_revenue"].values())
        )
        self.assertEqual(daily["highest_revenue_date"], "2026-01-01")

    def test_unknown_columns_and_negative_inputs_are_rejected(self):
        with self.assertRaises(ValueError):
            analyze_csv("product,total\nA,100\n")
        with self.assertRaises(ValueError):
            analyze_csv(CSV.replace("A,2,10000", "A,-2,10000"))

    def test_correctly_formatted_but_wrong_numbers_are_rejected(self):
        expected = analyze_csv(CSV)
        wrong = {**expected, "total_revenue": 0}
        with self.assertRaises(ValueError):
            verify_metrics(wrong, expected)

    def test_report_is_checked_from_downloaded_bytes_not_a_model_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.md"
            expected = analyze_csv(CSV)
            path.write_text(render_markdown(expected))
            self.assertTrue(verify_report(path, expected)["report_totals_checked"])
            path.write_text("# 매출 분석 보고서\n완료했습니다.\n")
            with self.assertRaises(ValueError):
                verify_report(path, expected)

    def test_offline_guard_does_not_read_local_credentials(self):
        with patch.dict("os.environ", {"TUTORIAL_OFFLINE_CHECK": "1"}):
            with patch(
                "tutorial_helpers.common.dotenv_values",
                side_effect=AssertionError("must not read key"),
            ):
                self.assertFalse(load_settings(True).enabled)

    def test_settings_repr_never_displays_key(self):
        settings = Settings(True, "fixture", Path("."), api_key="secret-fixture-value")
        self.assertNotIn("secret-fixture-value", repr(settings))


class CommonLifecycleTests(unittest.TestCase):
    def not_found(self):
        return NotFoundError(
            "fixture",
            response=httpx2.Response(
                404, request=httpx2.Request("GET", "https://api.openai.com/fixture")
            ),
            body=None,
        )

    def test_cleanup_failure_does_not_skip_other_resources(self):
        sessions = {"bad": {}, "good": {}}
        agents = {"agent_owned": {}}
        client = Mock()
        client.beta.agents.delete.return_value = SimpleNamespace(deleted=True)
        client.beta.agents.retrieve.side_effect = self.not_found()
        with patch(
            "tutorial_helpers.common.delete_session_safely",
            side_effect=[OSError("private"), {"verified_absent": True}],
        ) as remove:
            errors = cleanup_resources(client, sessions, agents, [])
        self.assertEqual(remove.call_count, 2)
        self.assertTrue(sessions["good"]["verified_absent"])
        self.assertTrue(agents["agent_owned"]["verified_absent"])
        self.assertEqual(len(errors), 1)
        self.assertNotIn("private", str(errors))
        client.close.assert_called_once()

    def test_recovery_ignores_foreign_creation_metadata(self):
        metadata = new_session_metadata("test", "owned")
        client = Mock()
        client.beta.agents.sessions.list.return_value = [
            SimpleNamespace(id="owned", metadata=metadata),
            SimpleNamespace(
                id="foreign", metadata={**metadata, "tutorial_run_id": "foreign"}
            ),
        ]
        sessions = {}
        with patch(
            "tutorial_helpers.common.delete_session_safely",
            return_value={"verified_absent": True},
        ) as remove:
            errors = cleanup_resources(client, sessions, {}, [metadata])
        remove.assert_called_once_with(client, "owned")
        self.assertNotIn("foreign", sessions)
        self.assertEqual(errors, [])

    def test_creation_marker_saved_before_api_call_and_receipt_rejects_key(self):
        import json

        with tempfile.TemporaryDirectory() as directory:
            attempts = []
            metadata = new_session_metadata(
                "fixture", "run", attempts=attempts, output_dir=directory
            )
            self.assertEqual(
                json.loads((Path(directory) / "creation.json").read_text()), [metadata]
            )
            settings = Settings(
                True, "model", Path(directory), api_key="secret-fixture"
            )
            with self.assertRaisesRegex(RuntimeError, "persist a secret"):
                save_validation(
                    directory,
                    chapter="fixture",
                    run_id="run",
                    settings=settings,
                    sessions={},
                    agents={},
                    turns=[],
                    checks={"bad": "secret-fixture"},
                    failure=None,
                    cleanup_errors=[],
                )


if __name__ == "__main__":
    unittest.main()
