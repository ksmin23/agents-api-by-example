"""Add checks to an execution COPY. Source notebooks contain no test runner calls.

Read-only history queries run before session cleanup. Validation failures still
reach cleanup, and a separate receipt records failure and cleanup. Split first-agent, approval, telemetry, and operations
steps save failures after their error-cleanup context has exited.
"""

from __future__ import annotations
import ast
import copy
from pathlib import Path
import nbformat

ROOT = Path(__file__).resolve().parents[1]
DOCKER_RECORDS = {
    "12_self_hosted": "lab.record(exec_server_help_verified=True)\nlab.record(private_index_install_verified=True, hash_mismatch_rejected=True, internal_network_verified=True, skill_execution_verified=True, metrics=local_metrics, package=local_evidence, api_connection='not_run')",
    "13_hooks_telemetry": "lab.record(metrics=local_metrics, real_otlp_collector_verified=True, application_hooks_verified=True, command_hook_protocol_replay_verified=True, native_hook_dispatch='not_run', prompt_and_path_excluded=True, api_connection='not_run')",
    "14_operations": "lab.record(durable_duplicate_claim_verified=True, process_interruption_verified=True, unknown_work_not_replayed=True, same_container_files_retained=True, replacement_requires_restore=True, restored_report_verified=True, api_connection='not_run')",
}
API_RECORDS = {
    "12_self_hosted": "provider.record(private_package_verified=True, actual_api_connected=True)",
    "13_hooks_telemetry": "transport.record(actual_api_events_exported=True, turn_id=turn.id)",
}



def _instrument_split_steps(notebook, chapter, prefix, count):
    """Record split-cell failures after cleanup; inspect history before final deletion."""
    stages = {}
    for cell in notebook.cells:
        for step in range(1, count + 1):
            if f"{prefix}_{step}" in cell.metadata.get("tags", []):
                if step in stages or cell.cell_type != "code":
                    raise ValueError("Duplicate or invalid split step")
                stages[step] = cell
    if set(stages) != set(range(1, count + 1)):
        raise ValueError("Missing or duplicate split execution steps")
    save = """
_validation_error = _validation_sys.exc_info()[1]
_validation_summary = _save_validation(
    output_dir, chapter=_validation_chapter, run_id=run_id, settings=settings,
    sessions=sessions, agents=agents, turns=globals().get("_validation_turns", []),
    checks=globals().get("_validation_checks", {}),
    failure=_safe_error(_validation_error) if _validation_error else None,
    cleanup_errors=cleanup_errors,
)
"""
    for step, cell in stages.items():
        tree = ast.parse(cell.source)
        if step < count:
            if not any(isinstance(n, ast.Call) and ast.unparse(n.func) == "cleanup_on_error"
                       for n in ast.walk(tree)):
                raise ValueError("Split step is missing error cleanup")
            failure = ast.parse(save + "raise\n").body
            tree.body = [ast.Try(body=tree.body,
                                handlers=[ast.ExceptHandler(type=ast.Name(id="BaseException", ctx=ast.Load()),
                                                            name=None, body=failure)],
                                orelse=[], finalbody=[])]
        else:
            boundaries = [n for n in tree.body if isinstance(n, ast.Try) and any(
                isinstance(c, ast.Call) and ast.unparse(c.func) == "cleanup_resources"
                for statement in n.finalbody for c in ast.walk(statement))]
            if len(boundaries) != 1:
                raise ValueError("Expected one final split cleanup boundary")
            boundary = boundaries[0]
            boundary.body.extend(ast.parse("""
_validation_items = []
for _validation_sid in sessions:
    _validation_items.extend(client.beta.agents.sessions.items.list(_validation_sid, order="asc", limit=100, timeout=15))
_validation_checks, _validation_turns = _validate_lesson(_validation_chapter, globals(), _validation_items)
""").body)
            if chapter in API_RECORDS:
                record = API_RECORDS[chapter]
                if chapter == "13_hooks_telemetry":
                    record = "if docker_enabled:\n    " + record
                boundary.body.extend(ast.parse(record).body)
            boundary.finalbody = [ast.Try(body=boundary.finalbody, handlers=[], orelse=[],
                                          finalbody=ast.parse(save).body)]
        ast.fix_missing_locations(tree)
        cell.source = ast.unparse(tree) + "\n"
    setup = f"""import sys as _validation_sys
from tutorial_helpers.validation import validate_lesson as _validate_lesson, save_validation as _save_validation
from tutorial_helpers.common import safe_error as _safe_error
_validation_chapter = {chapter!r}
_validation_checks, _validation_turns = {{}}, []
"""
    notebook.cells.insert(0, nbformat.v4.new_code_cell(
        setup, metadata={"tags": ["validation_only", "requires_api"]}))

def instrument_notebook(notebook, chapter, *, live=False, docker=False):
    """Mutate only the runner's nbformat object; never write the source notebook."""
    if not (live or docker):
        return
    split_plugins = chapter == "10_plugins" and any(
        any(tag.startswith("plugin_step_") for tag in cell.metadata.get("tags", []))
        for cell in notebook.cells
    )
    split_skills = chapter == "09_skills" and any(
        any(tag.startswith("skill_step_") for tag in cell.metadata.get("tags", []))
        for cell in notebook.cells
    )
    split_mcp = chapter == "08_mcp" and any(
        any(tag.startswith("mcp_step_") for tag in cell.metadata.get("tags", []))
        for cell in notebook.cells
    )
    split_function_tools = chapter == "07_function_tools" and any(
        any(tag.startswith("function_tool_step_") for tag in cell.metadata.get("tags", []))
        for cell in notebook.cells
    )
    split_environment = chapter == "06_environment" and any(
        any(tag.startswith("environment_step_") for tag in cell.metadata.get("tags", []))
        for cell in notebook.cells
    )
    split_artifacts = chapter == "05_files_artifacts" and any(
        any(tag.startswith("artifact_step_") for tag in cell.metadata.get("tags", []))
        for cell in notebook.cells
    )
    split_configuration = chapter == "04_agent_configuration" and any(
        any(tag.startswith("configuration_step_") for tag in cell.metadata.get("tags", []))
        for cell in notebook.cells
    )
    split_sessions = chapter == "03_sessions" and any(
        any(tag.startswith("session_step_") for tag in cell.metadata.get("tags", []))
        for cell in notebook.cells
    )
    split_first_agent = chapter == "02_first_agent" and any(
        any(tag.startswith("first_agent_step_") for tag in cell.metadata.get("tags", []))
        for cell in notebook.cells
    )
    split_telemetry = chapter == "13_hooks_telemetry" and any(
        any(tag.startswith("telemetry_step_") for tag in cell.metadata.get("tags", []))
        for cell in notebook.cells
    )
    split_operations = chapter == "14_operations" and any(
        any(tag.startswith("operations_step_") for tag in cell.metadata.get("tags", []))
        for cell in notebook.cells
    )
    split_self_hosted = chapter == "12_self_hosted" and any(
        any(tag.startswith("self_hosted_step_") for tag in cell.metadata.get("tags", []))
        for cell in notebook.cells
    )
    if live and (chapter == "11_guardrails_approvals" or split_telemetry or split_operations or split_self_hosted or split_first_agent or split_sessions or split_configuration or split_artifacts or split_environment or split_function_tools or split_mcp or split_skills or split_plugins or chapter == "15_multi_agent"):
        prefix, count = {
            "02_first_agent": ("first_agent_step", 3),
            "03_sessions": ("session_step", 4),
            "04_agent_configuration": ("configuration_step", 5),
            "05_files_artifacts": ("artifact_step", 5),
            "06_environment": ("environment_step", 5),
            "07_function_tools": ("function_tool_step", 5),
            "08_mcp": ("mcp_step", 5),
            "09_skills": ("skill_step", 6),
            "10_plugins": ("plugin_step", 6),
            "11_guardrails_approvals": ("approval_step", 6),
            "12_self_hosted": ("self_hosted_step", 6),
            "13_hooks_telemetry": ("telemetry_step", 6),
            "14_operations": ("operations_step", 6),
            "15_multi_agent": ("multi_agent_step", 6),
        }[chapter]
        _instrument_split_steps(notebook, chapter, prefix, count)
        if docker:
            instrument_notebook(notebook, chapter, live=False, docker=True)
        return
    matched = 0
    for cell in notebook.cells:
        if cell.cell_type != "code":
            continue
        is_api = "requires_api" in cell.metadata.get("tags", [])
        if is_api and not live:
            continue
        tree = ast.parse(cell.source)
        if docker and not is_api:
            for node in ast.walk(tree):
                if isinstance(node, ast.With) and any(
                    "DockerLab(" in ast.unparse(i.context_expr) for i in node.items
                ):
                    source = DOCKER_RECORDS.get(chapter)
                    if source:
                        verification = (
                            "from tutorial_helpers.validation import validate_docker_lesson as _validate_docker_lesson\n"
                            f"_validate_docker_lesson({chapter!r}, lab)\n"
                        )
                        node.body.extend(ast.parse(verification + source).body)
        if live and is_api:
            for node in ast.walk(tree):
                if not isinstance(node, ast.Try) or not any(
                    isinstance(n, ast.Call) and ast.unparse(n.func) == "cleanup_resources"
                    for statement in node.finalbody
                    for n in ast.walk(statement)
                ):
                    continue
                matched += 1
                probe = """
_validation_items = []
for _validation_sid in sessions:
    _validation_items.extend(client.beta.agents.sessions.items.list(_validation_sid, order="asc", limit=100, timeout=15))
_validation_checks, _validation_turns = _validate_lesson(_validation_chapter, globals(), _validation_items)
"""
                node.body.extend(ast.parse(probe).body)
                if chapter in API_RECORDS:
                    record_source = API_RECORDS[chapter]
                    if chapter == "13_hooks_telemetry":
                        import textwrap

                        record_source = "if docker_enabled:\n" + textwrap.indent(
                            record_source, "    "
                        )
                    node.body.extend(ast.parse(record_source).body)
                final = """
_validation_error = _validation_sys.exc_info()[1]
_validation_summary = _save_validation(
    output_dir, chapter=_validation_chapter,
    run_id=globals().get("run_id", globals().get("RUN_ID")), settings=settings,
    sessions=sessions, agents=agents, turns=globals().get("_validation_turns", []),
    checks=globals().get("_validation_checks", {}),
    failure=_safe_error(_validation_error) if _validation_error else None,
    cleanup_errors=cleanup_errors,
)
"""
                node.finalbody = [
                    ast.Try(
                        body=node.finalbody, handlers=[], orelse=[], finalbody=ast.parse(final).body
                    )
                ]
        ast.fix_missing_locations(tree)
        cell.source = ast.unparse(tree) + "\n"
    if live:
        if matched != 1:
            raise ValueError(f"Expected one cleanup boundary, got {matched}")
        setup = f"""import sys as _validation_sys
from tutorial_helpers.validation import validate_lesson as _validate_lesson, save_validation as _save_validation
from tutorial_helpers.common import safe_error as _safe_error
_validation_chapter = {chapter!r}
_validation_checks, _validation_turns = {{}}, []
"""
        notebook.cells.insert(
            0,
            nbformat.v4.new_code_cell(
                setup, metadata={"tags": ["validation_only", "requires_api"]}
            ),
        )
