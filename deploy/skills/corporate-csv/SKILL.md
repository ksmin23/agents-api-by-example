---
name: corporate-csv
description: Analyze the provided sales CSV using the preinstalled internal acme-sales package and generate a verified Korean sales report.
---

# Corporate sales report

Use the already installed acme-sales package. Do not install from public PyPI or rewrite its calculations.
Read this skill and run its bundled scripts/run_report.py with the exact virtual-environment interpreter used during installation.
Login shells can reset PATH, so do not rely on an unqualified python command:

```bash
/opt/venv/bin/python /opt/capabilities/skills/corporate-csv/scripts/run_report.py --input /workspace/sales.csv --output-dir /workspace/outputs
```

Inspect summary.json, report.md, and package_evidence.json. Return the exact summary JSON.
The evidence must identify the installed package version, package file, and input SHA-256.
Never read or copy executor credentials into the report. Package installation belongs to provisioning.
