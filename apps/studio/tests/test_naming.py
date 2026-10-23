"""No user-facing string calls the agency "AI Studio" (CLAUDE.md, naming rules for UI copy).

Media titles, notification titles, approval comments, style labels and setup messages are read by
people: the section is Agency and the helpers are "your team". Docstrings and comments may keep the
old name; string values, templates and the app's JavaScript may not.
"""

import ast
from pathlib import Path

from django.conf import settings

ROOT = Path(settings.BASE_DIR)
OLD_NAME = "AI Studio"


def _string_values(path: Path):
    tree = ast.parse(path.read_text(), filename=str(path))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docstrings.add(id(first.value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            yield node.lineno, node.value


def test_no_string_value_in_the_apps_says_ai_studio():
    offenders = []
    for path in sorted((ROOT / "apps").rglob("*.py")):
        rel = path.relative_to(ROOT)
        if "tests" in rel.parts or "migrations" in rel.parts or rel.name.startswith("test_"):
            continue
        offenders += [f"{rel}:{line}" for line, value in _string_values(path) if OLD_NAME in value]
    assert offenders == []


def test_no_template_or_app_script_says_ai_studio():
    files = [*(ROOT / "templates").rglob("*.html"), *(ROOT / "apps").rglob("templates/**/*.html")]
    files += [path for path in (ROOT / "static" / "js").glob("*.js") if not path.name.endswith(".min.js")]
    assert [str(path.relative_to(ROOT)) for path in files if OLD_NAME in path.read_text()] == []
