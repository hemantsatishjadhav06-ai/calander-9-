"""Django's ``{# #}`` comment is single-line only.

A ``{#`` whose ``#}`` sits on a later line is not a comment: the template
engine prints it, so a developer note showed up as text under the approval
comment box ("{# sr-only, not hidden: a display:none input…"). Notes that
span lines use ``{% comment %}``.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings

REPO_ROOT = Path(settings.BASE_DIR)
_OPEN_WITHOUT_CLOSE = re.compile(r"\{#(?![^\n]*#\})")


def _template_files():
    for root in [REPO_ROOT / "templates", *sorted(REPO_ROOT.glob("apps/*/templates"))]:
        yield from sorted(root.rglob("*.html"))
        yield from sorted(root.rglob("*.txt"))


def test_no_template_comment_spans_lines():
    offenders = []
    for path in _template_files():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if _OPEN_WITHOUT_CLOSE.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()[:80]}")
    assert not offenders, "Use {% comment %} for notes that span lines:\n" + "\n".join(offenders)
