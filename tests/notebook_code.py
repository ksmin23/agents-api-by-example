"""Read lesson code without running a notebook or creating API resources."""

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def cells(number):
    path = next((ROOT / "notebooks/chapters").glob(f"{number:02d}_*.ipynb"))
    return [c for c in json.loads(path.read_text())["cells"] if c["cell_type"] == "code"]


def tree(number):
    return ast.parse("\n".join("".join(c["source"]) for c in cells(number)))


def definition(number, name, namespace):
    node = next(
        n
        for n in tree(number).body
        if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == name
    )
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
            f"chapter-{number}-{name}",
            "exec",
        ),
        namespace,
    )
    return namespace[name]


def required_action_code(number=11):
    branch = next(
        n
        for n in ast.walk(tree(number))
        if isinstance(n, ast.If)
        and ast.unparse(n.test) == "event.type == 'agent.session.requires_action'"
    )
    return compile(
        ast.Module(body=branch.body, type_ignores=[]), "notebook-required-actions", "exec"
    )


def cleanup_code(number=2):
    node = next(
        n
        for n in ast.walk(tree(number))
        if isinstance(n, ast.Try)
        and any("client.beta.agents.sessions.list" in ast.unparse(b) for b in n.finalbody)
    )
    return compile(ast.Module(body=node.finalbody, type_ignores=[]), "notebook-finally", "exec")
