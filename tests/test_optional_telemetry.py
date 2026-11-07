"""In-memory observation works without importing the optional HTTP exporter."""
import builtins
import unittest
from unittest.mock import patch

from tutorial_helpers.deployment import ApplicationHooks


class OptionalTelemetryTests(unittest.TestCase):
    def test_memory_spans_do_not_import_http_exporter(self):
        original = builtins.__import__

        def guard(name, *args, **kwargs):
            if name.startswith("opentelemetry.exporter"):
                raise ImportError("HTTP exporter deliberately unavailable")
            return original(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=guard):
            hooks = ApplicationHooks(None, "optional-exporter-test")
            try:
                hooks.emit("session.created", session_id="fixture")
                hooks.provider.force_flush()
                spans = hooks.exporter.get_finished_spans()
                self.assertEqual(len(spans), 1)
                self.assertEqual(spans[0].attributes["session_id"], "fixture")
            finally:
                hooks.provider.shutdown()
