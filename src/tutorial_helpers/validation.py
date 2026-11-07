"""Validation-only CSV oracles and receipts. Imported by tests and execution copies."""

from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import re
import shlex
from pathlib import Path


def analyze_csv(text):
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames != ["date", "product", "quantity", "unit_price"]:
        raise ValueError("CSV columns must be date,product,quantity,unit_price in order")
    products = defaultdict(int)
    rows = list(reader)
    quantity = 0
    for row in rows:
        amount, price = (int(row["quantity"]), int(row["unit_price"]))
        if amount < 0 or price < 0:
            raise ValueError("Negative quantity or unit_price is not allowed in this exercise")
        quantity += amount
        products[row["product"]] += amount * price
    return {
        "row_count": len(rows),
        "total_quantity": quantity,
        "total_revenue": sum(products.values()),
        "by_product": dict(sorted(products.items())),
    }


def daily_revenue(text):
    totals = defaultdict(int)
    for row in csv.DictReader(io.StringIO(text)):
        totals[row["date"]] += int(row["quantity"]) * int(row["unit_price"])
    return {
        "daily_revenue": dict(sorted(totals.items())),
        "highest_revenue_date": max(totals, key=totals.get),
    }


def render_markdown(metrics):
    rows = [
        "# 매출 분석 보고서",
        "",
        f"- 거래 행 수: {metrics['row_count']}",
        f"- 판매 수량: {metrics['total_quantity']}",
        f"- 총매출: {metrics['total_revenue']:,}",
        "",
        "| 상품 | 매출 |",
        "| --- | ---: |",
    ]
    rows += [f"| {product} | {revenue:,} |" for product, revenue in metrics["by_product"].items()]
    return "\n".join(rows) + "\n"


def verify_metrics(actual, expected):
    if actual != expected:
        raise ValueError("Calculated metrics differ from the client-side CSV oracle")
    return actual


def verify_report(path, expected):
    text = Path(path).read_text()
    normalized = text.replace(",", "")
    if (
        not text.startswith("# 매출 분석 보고서")
        or str(expected["total_revenue"]) not in normalized
    ):
        raise ValueError("Report heading or total revenue is missing")
    for product, revenue in expected["by_product"].items():
        if product not in text or str(revenue) not in normalized:
            raise ValueError("A product or its revenue is missing from the report")
    return {"report_heading_checked": True, "report_totals_checked": True}


def verify_report_target(path, revenue, target):
    """Check the two target-comparison lines explicitly requested in Chapter 10."""
    text = Path(path).read_text(encoding="utf-8")
    targets = re.findall(r"^Target revenue: ([0-9,]+)[ \t]*$", text, re.M)
    percentages = re.findall(r"^Attainment: ([0-9]+\.[0-9]{2})%[ \t]*$", text, re.M)
    if (len(targets) != 1 or int(targets[0].replace(",", "")) != target
        or percentages != [f"{revenue / target * 100:.2f}"]):
        raise ValueError("Report target or percentage comparison differs")
    return {"target_revenue": target, "attainment_percent": percentages[0]}


def save_validation(
    output_dir,
    *,
    chapter,
    run_id,
    settings,
    sessions,
    agents,
    turns,
    checks,
    failure,
    cleanup_errors,
    **extra,
):
    """Write one verification receipt; no event logs, tracing or API execution."""
    summary = dict(
        chapter=chapter,
        run_id=run_id,
        model=settings.model,
        sessions=sessions,
        agents=agents,
        turns=turns,
        checks=checks,
        failure=failure,
        cleanup_errors=cleanup_errors,
        status="failed" if failure or cleanup_errors else "passed",
        creation_attempts=(
            json.loads((Path(output_dir) / "creation.json").read_text())
            if (Path(output_dir) / "creation.json").exists()
            else []
        ),
        recorded_at=datetime.now(timezone.utc).isoformat(),
        **extra,
    )
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    if settings.api_key and settings.api_key in text:
        raise RuntimeError("Refusing to persist a secret")
    for p in [Path(output_dir) / "summary.json", Path(output_dir).parent / "latest.json"]:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return summary


def verify_tool_execution(items):
    """Check saved tool evidence; detailed execution history belongs in native Trace."""
    if not any(
        (
            i.type == "command_execution"
            and i.status == "completed"
            and (i.exit_code == 0)
            or (i.type == "mcp_call" and i.status == "completed" and (not i.error))
            or i.type == "function_call"
            for i in items
        )
    ):
        raise RuntimeError("No successful tool execution")


def skill_script_commands(items, turn_id, *, script_path=None, interpreter=None):
    """Match this lesson's explicit Python CLI, not arbitrary shell programs."""
    matches = []
    for item in items:
        if (item.type != "command_execution" or item.turn_id != turn_id
            or item.status != "completed" or item.exit_code != 0):
            continue
        try:
            lexer = shlex.shlex(item.command, posix=True, punctuation_chars=";&|<>")
            lexer.whitespace_split = True
            tokens = list(lexer)
        except ValueError:
            continue
        # Only inspect command boundaries; echo/cat mentioning a script is not execution.
        for start in [0] + [i + 1 for i, token in enumerate(tokens) if token in {"&&", ";", "||"}]:
            command = tokens[start:]
            if not command or (command[0] != interpreter if interpreter is not None else
                               not re.fullmatch(r"python(?:3(?:\.\d+)?)?", Path(command[0]).name)):
                continue
            command = command[1:]
            while command and command[0] in {"-u", "-B"}:
                command = command[1:]
            if not command:
                continue
            script = command.pop(0)
            if script_path is not None:
                if script != script_path:
                    continue
            elif script != "scripts/analyze_sales.py" and not script.endswith("/scripts/analyze_sales.py"):
                continue
            end = next((i for i, token in enumerate(command) if token in {"&&", ";", "||"}), len(command))
            # A later fallback or unconditional command can mask the script's failure.
            if any(token in {";", "||", "|", "&", ">", ">>", "<", "<<"} for token in command[end:]):
                continue
            args = command[:end]
            if len(args) != 4:
                continue
            flags = dict(zip(args[::2], args[1::2]))
            if flags == {"--input": "/workspace/sales.csv", "--output-dir": "/workspace/outputs"}:
                matches.append(item)
                break
    return matches


def verify_enriched(value, expected, target):
    if set(value) != {"metrics", "target_revenue", "attainment_rate"}:
        raise ValueError("Unexpected enriched output fields")
    verify_metrics(value["metrics"], expected)
    if value["target_revenue"] != target["target_revenue"]:
        raise ValueError("Target differs from the actual business lookup")
    if abs(value["attainment_rate"] - expected["total_revenue"] / target["target_revenue"]) > 1e-09:
        raise ValueError("Attainment rate is incorrect")
    return value


def verify_execution(result, commands):
    expected = {"count": 3, "total": 60}
    if result.turn.status != "completed":
        raise RuntimeError("The root turn did not complete successfully")
    answer = json.loads(result.output_text)
    if answer != expected:
        raise ValueError("The final answer did not match the expected calculation")
    for command in commands:
        if command["status"] != "completed" or command["exit_code"] != 0:
            continue
        for line in (command["output"] or "").splitlines():
            try:
                observed = json.loads(line.strip().removeprefix("stdout:").strip())
            except json.JSONDecodeError:
                continue
            if observed == expected:
                return {"answer": answer, "command_output_verified": True}
    raise RuntimeError("No successful command output matched the expected calculation")


def verify_private_package(evidence, csv_bytes):
    if evidence["distribution"] != "acme-sales" or evidence["version"] != "0.1.0":
        raise ValueError("Private package identity differs")
    if "/opt/venv/" not in evidence["module_file"]:
        raise ValueError("Private package is outside the installed environment")
    if evidence["input_sha256"] != hashlib.sha256(csv_bytes).hexdigest():
        raise ValueError("Private package input digest differs")


def validate_docker_lesson(chapter, lab):
    """Check local Docker results in execution copies before recording success."""
    csv_bytes = (lab.root / "data/sales.csv").read_bytes()
    expected = analyze_csv(csv_bytes.decode())
    downloaded = lab.output_dir / "downloaded"
    verify_metrics(json.loads((downloaded / "summary.json").read_text()), expected)
    verify_report(downloaded / "report.md", expected)
    verify_private_package(
        json.loads((downloaded / "package_evidence.json").read_text()), csv_bytes
    )
    if chapter == "14_operations":
        verify_metrics(json.loads((lab.output_dir / "restored-summary.json").read_text()), expected)


def is_python_command(command):
    """Recognize an explicit Python invocation, not a mention inside echo or code."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    return bool(tokens and Path(tokens[0]).name in {"python", "python3"})


def is_worker_script(command, path):
    """Match the two-token worker CLI requested by this lesson."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    return is_python_command(command) and len(tokens) == 2 and tokens[1] == path


def validate_multi_agent(namespace, items):
    """Validate API evidence captured by the notebook; never issue API requests."""
    settings = namespace['settings']
    csv_text = (settings.root / 'data/sales.csv').read_text()
    expected = analyze_csv(csv_text)
    period = namespace['PERIOD']
    target = json.loads((settings.root / 'data/sales_targets.json').read_text())[period]
    root = namespace['turn']
    if (root.status != 'completed' or root.subagent_id is not None
        or root.id != namespace['result'].turn_id):
        raise ValueError('Expected the original completed root turn')
    children = namespace['subagents']
    ids = {child.id for child in children}
    if len(ids) != 2 or set(namespace['created_subagent_ids']) != ids:
        raise ValueError('Expected exactly two observed subagents')
    roles = {}
    for script in ['structure.py', 'target.py']:
        evidence = []
        for sid in ids:
            completed = {t.id for t in namespace['child_turns'][sid]
                         if t.status == 'completed' and t.subagent_id == sid}
            if namespace['command_actors'].get(sid) != sid:
                raise ValueError('Command actor differs from the subagent')
            evidence += [dict(subagent_id=sid, turn_id=i.turn_id, command_item_id=i.id,
                              script=script, exit_code=i.exit_code)
                         for i in namespace['child_items'][sid]
                         if i.type == 'command_execution' and i.status == 'completed'
                         and i.exit_code == 0 and i.turn_id in completed
                         and is_worker_script(i.command, '/workspace/workers/' + script)]
        if not evidence:
            raise ValueError('Missing successful subagent Python execution: ' + script)
        owners = {entry['subagent_id'] for entry in evidence}
        if len(owners) != 1:
            raise ValueError('Role script was run by multiple workers')
        roles[script] = evidence[-1]
    if len({e['subagent_id'] for e in roles.values()}) != 2:
        raise ValueError('The two roles must run in different subagents')
    if not any(i.type == 'command_execution' and i.status == 'completed'
               and i.exit_code == 0 and i.turn_id == root.id and is_python_command(i.command)
               for i in items):
        raise ValueError('Root Python integration command is missing')
    downloads = namespace['downloads']
    structure = json.loads((downloads / 'sales_breakdown.json').read_text())
    if structure != {'metrics': expected, 'by_date': daily_revenue(csv_text)['daily_revenue']}:
        raise ValueError('Sales structure differs from the CSV oracle')
    assessment = json.loads((downloads / 'target_assessment.json').read_text())
    expected_target = dict(period=period, total_revenue=expected['total_revenue'],
                           target_revenue=target['target_revenue'], currency=target['currency'],
                           attainment_rate=expected['total_revenue'] / target['target_revenue'],
                           shortfall=max(target['target_revenue'] - expected['total_revenue'], 0))
    if assessment != expected_target:
        raise ValueError('Target assessment differs from the CSV and target oracle')
    verify_metrics(json.loads(namespace['result'].output_text), expected)
    verify_metrics(json.loads((downloads / 'summary.json').read_text()), expected)
    verify_report(downloads / 'report.md', expected)
    report = (downloads / 'report.md').read_text().replace(',', '')
    percentages = [float(value) for value in re.findall(r'([0-9]+(?:\.[0-9]+)?)\s*%', report)]
    expected_percentage = round(expected_target['attainment_rate'] * 100, 2)
    if (not any(abs(value - expected_percentage) < 0.005 for value in percentages)
        or not all(str(v) in report for v in [target['target_revenue'], expected_target['shortfall']])):
        raise ValueError('Target results are missing from the integrated report')
    daily = daily_revenue(csv_text)['daily_revenue']
    if (not all(date in report and str(revenue) in report for date, revenue in daily.items())
        or not all(name in report for name in ['sales_breakdown.json', 'target_assessment.json'])):
        raise ValueError('Daily results or worker file references are missing from the report')
    if not namespace['history_checked'] or not namespace['commands_checked'] or not namespace['report_downloaded']:
        raise ValueError('Multi-agent history, commands, or downloads were not confirmed')
    for script, selected in namespace['role_executions'].items():
        if script not in roles or any(selected.get(key) != roles[script][key]
            for key in ['subagent_id', 'turn_id', 'command_item_id']):
            raise ValueError('Displayed role evidence differs from saved worker history')
    if set(namespace['role_executions']) != set(roles):
        raise ValueError('Displayed role evidence is incomplete')
    known_turns = {root.id} | {t.id for turns in namespace['child_turns'].values() for t in turns
                             if t.status == 'completed' and t.subagent_id in ids}
    files = namespace['downloaded_artifacts']
    paths = {'/workspace/outputs/' + name for name in
             ['sales_breakdown.json', 'target_assessment.json', 'summary.json', 'report.md']}
    if (len(files) != 4 or {a['path'] for a in files} != paths
        or any(a['turn_id'] not in known_turns or not any(
            p.id == a['id'] and p.turn_id == a['turn_id'] and p.path == a['path']
            for p in namespace['published']) for a in files)):
        raise ValueError('Downloaded artifacts differ from this run publication history')
    if (namespace['csv_bytes'] != (settings.root / 'data/sales.csv').read_bytes()
        or namespace['targets_bytes'] != (settings.root / 'data/sales_targets.json').read_bytes()):
        raise ValueError('Multi-agent inputs differ from the source data')
    checks = dict(csv_oracle_verified=True, metrics=expected, target=assessment,
                  subagent_count=2, role_execution=roles, command_actors=namespace['command_actors'],
                  shared_environment_verified=True, report_downloaded=True)
    turns = [dict(session_id=namespace['result'].session_id, turn_id=root.id,
                  status=root.status, usage=root.usage.to_dict() if root.usage else None)]
    return checks, turns


def validate_lesson(chapter, namespace, items):
    """Check captured SDK results/files while the execution copy still owns its session."""

    number = 0 if chapter == "preface" else int(chapter[:2])
    if number == 15:
        return validate_multi_agent(namespace, items)
    expected = None if number == 0 else analyze_csv((namespace["settings"].root / "data/sales.csv").read_text())
    names = {
        3: ["first", "second"],
        4: ["base_result", "custom_result"],
        11: ["analysis", "denied", "approval_result"],
    }.get(number, ["result"])
    results = [namespace[name] for name in names if name in namespace]
    turns = []
    for result in results:
        t = result.turn
        if t.status != "completed":
            raise ValueError("Root turn did not complete")
        turns.append(
            {
                "session_id": result.session_id,
                "turn_id": t.id,
                "status": t.status,
                "usage": t.usage.to_dict() if t.usage else None,
            }
        )
    if number == 14:
        t = namespace["turn"]
        turns = [
            {
                "session_id": namespace["session"].id,
                "turn_id": t.id,
                "status": t.status,
                "usage": t.usage.to_dict() if t.usage else None,
            }
        ]
    if not turns:
        raise ValueError("No completed turn was captured")
    if any(t["status"] != "completed" for t in turns):
        raise ValueError("An incomplete turn cannot pass validation")
    verify_tool_execution(items)
    analysis_turns = turns[:1] if number == 11 else turns
    for t in analysis_turns:
        if not any(
            i.type == "command_execution"
            and i.turn_id == t["turn_id"]
            and i.status == "completed"
            and i.exit_code == 0
            for i in items
        ):
            raise ValueError("No successful Python command for an analysis turn")
    checks = {"csv_oracle_verified": True}
    if number == 0:
        if (namespace["turn"].id != namespace["result"].turn_id
            or namespace["turn"].subagent_id is not None or namespace["turn"].status != "completed"):
            raise ValueError("Quickstart result differs from the original completed root turn")
        commands = [i.to_dict() for i in items if i.type == "command_execution"
                    and i.turn_id == namespace["result"].turn_id
                    and is_worker_script(i.command, "/workspace/quickstart_sum.py")]
        checks = verify_execution(namespace["result"], commands)
    elif number in {7, 8, 10}:
        target = json.loads((namespace["settings"].root / "data/sales_targets.json").read_text())[
            "2026-01"
        ]
        actual = json.loads(namespace["result"].output_text)
        verify_enriched(actual, expected, target)
        if number == 7:
            calls = [i for i in items if i.type == "function_call" and i.turn_id == namespace["result"].turn_id]
            if len(calls) != 1 or calls[0].name != "get_sales_target" or calls[0].status != "completed":
                raise ValueError("Expected one completed get_sales_target call from the root turn")
            call = calls[0]
            arguments = json.loads(call.arguments) if isinstance(call.arguments, str) else call.arguments
            if arguments != {"period": "2026-01"}:
                raise ValueError("Target lookup arguments differ from the requested period")
            checks["function_call"] = dict(name=call.name, call_id=call.call_id,
                                           turn_id=call.turn_id, status=call.status, arguments=arguments)
        elif number == 8:
            calls = [i for i in items if i.type == "mcp_call" and i.turn_id == namespace["result"].turn_id]
            if (len(calls) != 1 or calls[0].name != "get_sales_target"
                or calls[0].server_label != namespace["mcp_tool"]["server_label"]
                or calls[0].status != "completed" or calls[0].error is not None):
                raise ValueError("Expected one successful MCP target call from the intended server and root turn")
            call = calls[0]
            arguments = json.loads(call.arguments) if isinstance(call.arguments, str) else call.arguments
            if arguments != {"period": "2026-01"}:
                raise ValueError("MCP lookup arguments differ from the requested period")
            checks["mcp_call"] = dict(item_id=call.id, server_label=call.server_label, name=call.name,
                                      turn_id=call.turn_id, status=call.status, arguments=arguments,
                                      error_absent=True)
        else:
            calls = [i for i in items if i.type == "mcp_call" and i.turn_id == namespace["result"].turn_id]
            if (len(calls) != 1 or calls[0].name != "get_sales_target"
                or calls[0].status != "completed" or calls[0].error is not None):
                raise ValueError("Expected one successful Plugin target call from the root Turn")
            call = calls[0]
            arguments = json.loads(call.arguments) if isinstance(call.arguments, str) else call.arguments
            if arguments != {"period": "2026-01"}:
                raise ValueError("Plugin MCP lookup period differs")
            # Preserve the observed label; no guessed runtime Plugin namespace contract.
            checks["plugin_mcp_call"] = dict(item_id=call.id, server_label=call.server_label,
                configured_servers=list(namespace["mcp_config"]["mcpServers"]), name=call.name,
                turn_id=call.turn_id, arguments=arguments, status=call.status, error_absent=True)
        checks.update(
            metrics=actual["metrics"], target=target, attainment_rate=actual["attainment_rate"]
        )
    elif number == 3:
        first, second = namespace["first"], namespace["second"]
        verify_metrics(json.loads(first.output_text), expected)
        daily = json.loads(second.output_text)
        if daily != daily_revenue(namespace["csv_text"]) or first.session_id != second.session_id:
            raise ValueError("Follow-up output or session continuity differs")
        ids = {t.id for t in namespace["saved_turns"]}
        if not {first.turn_id, second.turn_id} <= ids or first.turn_id == second.turn_id:
            raise ValueError("Expected two saved turns")
        checks.update(metrics=expected, daily=daily, same_session_verified=True)
    elif number == 4:
        for result in results:
            verify_metrics(json.loads(result.output_text), expected)
        base, custom, saved = (
            namespace[k] for k in ["base_session", "custom_session", "saved_again"]
        )
        if (
            base.id == custom.id
            or base.agent.instructions != namespace["BASE_INSTRUCTIONS"]
            or saved.instructions != namespace["BASE_INSTRUCTIONS"]
            or custom.agent.instructions != namespace["override_instructions"]
            or any(model != namespace["settings"].model for model in
                   [base.agent.model, custom.agent.model, saved.model])
        ):
            raise ValueError("Saved agent or override settings differ")
        checks.update(metrics=expected, independent_sessions_verified=True)
    elif number == 11:
        analysis, denied, approved = [namespace[name] for name in ("analysis", "denied", "approval_result")]
        if (len({x.session_id for x in (analysis, denied, approved)}) != 1
            or len({x.turn_id for x in (analysis, denied, approved)}) != 3):
            raise ValueError("Expected three distinct Turns in the same approval session")
        verify_metrics(json.loads(analysis.output_text), expected)
        denial, outcome, gate = namespace["denial"], namespace["outcome"], namespace["gate"]
        if denial != {"publication_status": "denied", "reason": "channel_not_allowed"}:
            raise ValueError("Expected channel denial")
        if gate.decision is None:
            raise ValueError("Approval callback did not run")
        tool_results = []
        for result, channel in [(denied, "external"), (approved, "training")]:
            calls = [i for i in items if i.type == "function_call" and i.turn_id == result.turn_id]
            if len(calls) != 1 or calls[0].name != "publish_report":
                raise ValueError("Expected one publish_report call per policy/approval Turn")
            call = calls[0]
            arguments = json.loads(call.arguments) if isinstance(call.arguments, str) else call.arguments
            if arguments != {"report_id": gate.report_id, "channel": channel}:
                raise ValueError("Publication arguments differ from the scenario")
            response = namespace["cache"].load(
                [result.session_id, result.turn_id, call.call_id],
                {"name": call.name, "arguments": arguments},
            )
            if (response is None or response.get("turn_id") != result.turn_id
                or response.get("call_id") != call.call_id):
                raise ValueError("Missing tool result bound to the original Turn/Call")
            should_succeed = channel == "training" and gate.decision.approved
            if response.get("success") is not should_succeed:
                raise ValueError("Tool success differs from policy/approval decision")
            if should_succeed:
                if call.status != "completed" or json.loads(response["output"]) != outcome:
                    raise ValueError("Published outcome differs from the actual tool result")
            elif (call.status not in {"completed", "failed"} or response.get("error") != (
                "channel_not_allowed" if channel == "external" else "approval_denied"
            )):
                raise ValueError("Policy denial was not returned as the expected tool error")
            tool_results.append(dict(turn_id=result.turn_id, call_id=call.call_id, channel=channel,
                                     success=should_succeed, status=call.status))
        if gate.decision.approved:
            if outcome["sha256"] != gate.digest or outcome["publication_status"] != "published":
                raise ValueError("Publication receipt is not bound to the report")
            raw = (gate.destination / f"{gate.digest}.md").read_bytes()
            if raw != gate.reviewed_bytes or raw != (namespace["downloads"] / "report.md").read_bytes():
                raise ValueError("Published bytes differ from the reviewed report")
            receipt = json.loads((gate.destination / f"{gate.digest}.approval.json").read_text())
            if not gate.receipts or receipt != gate.receipts[-1] or receipt["sha256"] != gate.digest:
                raise ValueError("Approval receipt differs from the application decision")
        elif outcome != {"publication_status": "denied", "reason": "approval_denied"} or gate.receipts or gate.destination.exists():
            raise ValueError("User rejection did not prevent registration")
        checks.update(metrics=expected, publication_outcome=outcome, approval_mode=gate.decision.origin,
            approval_decision="approved" if gate.decision.approved else "rejected", tool_results=tool_results)
    else:
        actual = (
            namespace["actual"] if number == 14 else json.loads(namespace["result"].output_text)
        )
        verify_metrics(actual, expected)
        checks["metrics"] = actual
    downloads = namespace.get("downloads")
    if downloads is not None:
        verify_metrics(json.loads((downloads / "summary.json").read_text()), expected)
        verify_report(downloads / "report.md", expected)
        checks["report_downloaded"] = True
    if number == 6:
        info = json.loads((downloads / "environment.json").read_text())
        if (
            info["pandas_version"] != namespace["PANDAS_VERSION"]
            or info["input_rows"] != expected["row_count"]
        ):
            raise ValueError("Setup package evidence differs")
        checks["environment"] = info
    if number in {9, 10}:
        evidence = json.loads((downloads / "skill_evidence.json").read_text())
        input_bytes = namespace["csv_bytes"]
        if (evidence["input_sha256"] != hashlib.sha256(input_bytes).hexdigest()
            or evidence["script_revision"] != "csv-report-v1"
            or evidence.get("skill_name") != "csv-report"):
            raise ValueError("Skill evidence differs")
        commands = skill_script_commands(items, namespace["result"].turn_id)
        if not commands:
            raise ValueError("No successful bundled Skill CLI with the requested input/output in this Turn")
        checks["skill_command_ids"] = [item.id for item in commands]
        checks["skill_evidence"] = evidence
    if number == 9:
        installed = namespace["installed_environment"]
        environment_id = namespace["sessions"][namespace["result"].session_id]["environment_id"]
        if installed.id != environment_id or not any(
            s.name == namespace["skill"]["name"] and s.type == "inline" for s in installed.skills
        ):
            raise ValueError("Custom inline Skill is not registered in the session environment")
        checks["installed_skills"] = [
            {"name": s.name, "type": s.type} for s in installed.skills
        ]
    if number == 10:
        installed = namespace["installed_environment"]
        environment_id = namespace["sessions"][namespace["result"].session_id]["environment_id"]
        if installed.id != environment_id or not any(
            plugin.name == namespace["plugin"]["name"] and plugin.type == "inline"
            for plugin in installed.plugins
        ):
            raise ValueError("Plugin is not registered in the session environment")
        checks["installed_plugins"] = [{"name": p.name, "type": p.type} for p in installed.plugins]
        checks["report_target_comparison"] = verify_report_target(
            downloads / "report.md", expected["total_revenue"], target["target_revenue"]
        )
    if number == 12:
        result, session, turn = (namespace[name] for name in ("result", "session", "turn"))
        if result.session_id != session.id or turn.id != result.turn_id or turn.subagent_id is not None:
            raise ValueError("Self-hosted result differs from the original session/root Turn")
        input_bytes = namespace["csv_bytes"]
        if namespace["image_input_sha256"] != hashlib.sha256(input_bytes).hexdigest():
            raise ValueError("Image build input differs from the fixed CSV bytes")
        evidence = json.loads((downloads / "package_evidence.json").read_text())
        verify_private_package(evidence, input_bytes)
        if not evidence["module_file"].startswith("/opt/venv/"):
            raise ValueError("Corporate package is outside the expected virtual environment")
        commands = skill_script_commands(items, result.turn_id,
            script_path="/opt/capabilities/skills/corporate-csv/scripts/run_report.py",
            interpreter="/opt/venv/bin/python")
        if not commands:
            raise ValueError("No successful corporate Skill CLI in the root Turn with the expected interpreter and arguments")
        if namespace["input_submission_attempts"] != 1 or not namespace["report_downloaded"]:
            raise ValueError("Expected one Self-hosted submission and retained files")
        context = namespace["execution_context"]
        if (not namespace["connected"] or context["environment_id"] != session.environment.id
            or context["container_environment_id"] != session.environment.id
            or context["container_id"] != namespace["executor"]):
            raise ValueError("Self-hosted environment/container binding was not confirmed")
        checks.update(private_package=evidence, self_hosted_command_verified=True,
            self_hosted_command_ids=[item.id for item in commands],
            executor_connection_verified=True, executor_container_id=context["container_id"])
    if number == 13:
        from .deployment import ApplicationHooks

        hooks, result, turn = (namespace[name] for name in ("hooks", "result", "turn"))
        if turn.id != result.turn_id or turn.subagent_id is not None:
            raise ValueError("Telemetry result differs from the root Turn")
        if not namespace["report_downloaded"] or not namespace["application_hooks_checked"]:
            raise ValueError("Report or application telemetry inspection was incomplete")
        records = hooks.records
        if not records or any(r.get("run_id") != namespace["run_id"] for r in records):
            raise ValueError("Application records differ from this run")
        if any(set(r) - (ApplicationHooks.ALLOWED | {"event"}) for r in records):
            raise ValueError("Unexpected telemetry fields")
        for name in ("session.created", "turn.completed", "report.completed"):
            selected = [record for record in records if record["event"] == name]
            if not selected or any(record.get("session_id") != result.session_id for record in selected):
                raise ValueError("Application event is not bound to the completed session")
            if name != "session.created" and any(
                record.get("turn_id") != turn.id or record.get("status") != "completed" for record in selected
            ):
                raise ValueError("Application completion differs from the root Turn")
        usage = turn.usage.to_dict() if turn.usage else {}
        counts = {key: value for key, value in usage.items() if key in {"input_tokens", "output_tokens", "total_tokens"} and value is not None}
        for record in (r for r in records if r["event"] == "report.completed"):
            if record.get("duration_ms") != namespace["api_duration_ms"]:
                raise ValueError("Application duration differs from API creation/streaming time")
            if {k: record[k] for k in ("input_tokens", "output_tokens", "total_tokens") if k in record} != counts:
                raise ValueError("Application usage differs from reported usage")
        actual = namespace["observed_spans"]
        expected_spans = Counter((r["event"], json.dumps({k:v for k,v in r.items() if k!="event"}, sort_keys=True)) for r in records)
        received_spans = Counter((span["name"], json.dumps(span["attributes"], sort_keys=True)) for span in actual)
        if (not actual or expected_spans != received_spans or any(
            span["service_name"] != "tutorial.application-hooks" or not span["trace_id"] or not span["span_id"] for span in actual
        )):
            raise ValueError("Actual OTel spans differ from application records")
        export_status = namespace.get("trace_export", "not_requested")
        if export_status == "exported":
            payload = json.loads((namespace["output_dir"] / "traces.otlp.json").read_text())
            count = sum(len(scope.get("spans", [])) for resource in payload["resourceSpans"] for scope in resource.get("scopeSpans", []))
            if count < 1 or count != namespace["trace_span_count"]:
                raise ValueError("Trace export span count differs from the saved payload")
        checks.update(callbacks_source="actual_agents_api", application_hooks_verified=True,
            application_span_count=len(actual), telemetry_destination="collector" if namespace.get("docker_enabled") else "memory",
            trace_export=export_status, trace_count=namespace.get("trace_count", 0), trace_span_count=namespace.get("trace_span_count", 0))
    if number == 14:
        root = [t for t in namespace["saved_turns"] if t.subagent_id is None]
        if len(root) != 1 or root[0].id != namespace["turn_id"]:
            raise ValueError("Recovery created duplicate work")
        if namespace["input_submission_attempts"] != 1 or not namespace["input_accepted"]:
            raise ValueError("Expected one accepted input submission attempt")
        if not namespace["observer_reconnected"] or not namespace["report_downloaded"]:
            raise ValueError("Observer reconnection or report download was not confirmed")
        request = namespace["request_state"]
        if (request.get("session_id") != namespace["session"].id or request.get("turn_id") != namespace["turn_id"]
            or request.get("idempotency_key") != namespace["input_idempotency_key"]
            or request.get("submission_state") != "accepted"
            or json.loads(namespace["state_path"].read_text()) != request):
            raise ValueError("Recovery request record differs from the original request")
        if namespace["turn"].id != namespace["turn_id"] or namespace["recovered_turn_status"] != "completed":
            raise ValueError("Recovered state differs from the original completed turn")
        messages = namespace["messages"]
        if not messages or any(m.turn_id != namespace["turn_id"] or m.type != "message"
            or m.role != "assistant" or m.phase != "final_answer" for m in messages):
            raise ValueError("Recovered answer is not the original turn's final answer")
        downloads = namespace["downloaded_artifacts"]
        if (len(downloads) != 2 or any(a["turn_id"] != namespace["turn_id"] for a in downloads)
            or {a["path"] for a in downloads} != {"/workspace/outputs/summary.json", "/workspace/outputs/report.md"}
            or any(not any(a.id == saved["id"] and a.turn_id == saved["turn_id"] and a.path == saved["path"]
                           for a in namespace["artifacts"]) for saved in downloads)):
            raise ValueError("Recovered artifacts differ from the original turn's report files")
        checks.update(
            request_record_verified=True, recovered_artifacts_verified=True,
            final_answer_item_ids=[m.id for m in messages],
            root_turn_count=len(root), input_submission_attempts=namespace["input_submission_attempts"],
            input_resubmitted=False, observer_reconnection_verified=namespace["observer_reconnected"],
            result_source=namespace["recovery_source"],
        )
    return checks, turns
