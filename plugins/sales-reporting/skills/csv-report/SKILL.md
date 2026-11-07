---
name: csv-report
description: Analyze a sales CSV and write a verified JSON summary and Korean Markdown report using the bundled standard-library script.
---

# Sales CSV report

Use this skill for a CSV with date, product, quantity and unit_price columns.
See [the report contract](references/report-schema.md) for field meanings and output files.

Run the bundled `scripts/analyze_sales.py` with `--input` set to the supplied CSV
and `--output-dir` set to the requested report directory. Resolve the script path
from this skill directory, not from the current working directory.

Read back summary.json, report.md and skill_evidence.json after execution. Report
execution failures rather than substituting invented results. Return the JSON
shape requested by the user; keep summary.json in the documented base format.

If an MCP sales-target tool is available and the user asks for target comparison,
call it and append the target and attainment information to the Markdown report.
The CSV metrics still come from the bundled script. Do not publish or transmit
the report to a third party as part of this skill.
