# sales-reporting training plugin

This Agents API example uses the documented `.codex-plugin/plugin.json`
compatibility manifest. The stdio MCP process starts with cwd relative to this
plugin root. Its dependencies are installed through environment.packages.

`scripts/build_bundles.py` refreshes the generated skills/, servers/ and assets/
copies from the canonical skill and MCP fixtures before producing ZIP files.
The ZIP is attached to a session; the lesson does not install a desktop plugin.
