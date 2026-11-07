"""Install exported Colab dependency profiles in clean temporary environments.

Uses public PyPI and no API keys, models, sandbox, or Docker. This is distinct
from offline notebook validation and from execution in the Colab web runtime.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_colab import ROOT, installer, specs


def check(profile="all", root=ROOT):
    root = Path(root)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = root / "outputs/installation-validation" / run_id
    output.mkdir(parents=True)
    report = {"python": sys.version.split()[0], "platform": sys.platform,
              "index": "https://pypi.org/simple", "api_calls": 0, "profiles": []}
    environment = {k: v for k, v in os.environ.items()
                   if not any(word in k for word in ("API_KEY", "TOKEN", "SECRET"))}
    environment.update(PIP_NO_CACHE_DIR="1", PIP_DISABLE_PIP_VERSION_CHECK="1")
    for key in ("TUTORIAL_OFFLINE_CHECK", "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        environment.pop(key, None)
    with tempfile.TemporaryDirectory(prefix="tutorial-install-") as temp:
        for name, number in [("base", 0), ("telemetry", 13)]:
            if profile not in ("all", name):
                continue
            folder = Path(temp) / name
            python = folder / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            packages = specs(root, number)
            item = {"profile": name, "requested": packages, "passed": False}
            report["profiles"].append(item)
            smoke = """import importlib.metadata as metadata
from openai import OpenAI, DefaultHttpxClient
import dotenv
# Inspect the SDK locally without making an API request or using host proxies.
with OpenAI(api_key="installation-check-placeholder",
            http_client=DefaultHttpxClient(trust_env=False)) as client:
    assert callable(client.beta.agents.sessions.create)
for package in ["mcp", "pandas", "jupyter-book", "opentelemetry-exporter-otlp-proto-http", "socksio"]:
    try:
        metadata.distribution(package)
    except metadata.PackageNotFoundError:
        continue
    raise AssertionError("Unexpected package in Colab profile: " + package)
"""
            if name == "telemetry":
                smoke += ("import sys; sys.path.insert(0, " + repr(str(root / "src")) + ")\n"
                          "from tutorial_helpers.deployment import ApplicationHooks\n"
                          "hooks = ApplicationHooks(None, 'installation-check')\n"
                          "try:\n"
                          "    hooks.emit('session.created', session_id='fixture')\n"
                          "    hooks.provider.force_flush()\n"
                          "    assert len(hooks.exporter.get_finished_spans()) == 1\n"
                          "finally:\n"
                          "    hooks.provider.shutdown()\n")
            commands = [[sys.executable, "-m", "venv", str(folder)],
                        [str(python), "-c", installer(packages)],
                        [str(python), "-m", "pip", "check"],
                        [str(python), "-c", smoke]]
            try:
                with (output / (name + ".log")).open("w") as log:
                    for command in commands:
                        subprocess.run(command, env=environment, check=True,
                                       stdout=log, stderr=subprocess.STDOUT, timeout=300)
                item["passed"] = True
                print("PASS", name, flush=True)
            finally:
                (output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"profiles": len(report["profiles"]), "clean_installation": True,
                      "api_calls": 0, "summary": str((output / "summary.json").relative_to(root))}))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=["base", "telemetry", "all"], default="all")
    check(parser.parse_args().profile)
