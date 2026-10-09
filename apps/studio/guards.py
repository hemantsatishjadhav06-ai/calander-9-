"""The rule that no agent approves, schedules or publishes — enforced in code.

The approval gate (``apps.approvals.gate``) refuses a worker in workspaces
that require dashboard approval. In workspaces that don't, nothing in the
composer would stop code running as the system actor from moving a post to
approved or scheduled. So every piece of agency work runs inside
:func:`agent_work`, and the few functions that approve, schedule or publish
call :func:`forbid_in_agent_work` first: if an agent ever reaches one, it is a
bug, and it fails loudly instead of publishing.
"""

from __future__ import annotations

import contextlib
from contextvars import ContextVar

_IN_AGENT_WORK: ContextVar[str | None] = ContextVar("studio_agent_work", default=None)


class AgentMayNotApproveError(RuntimeError):
    """Agency code reached an approve, schedule or publish path."""


@contextlib.contextmanager
def agent_work(label: str):
    token = _IN_AGENT_WORK.set(label)
    try:
        yield
    finally:
        _IN_AGENT_WORK.reset(token)


def in_agent_work() -> str | None:
    return _IN_AGENT_WORK.get()


def forbid_in_agent_work(action: str) -> None:
    label = _IN_AGENT_WORK.get()
    if label is not None:
        raise AgentMayNotApproveError(f"Agency work ({label}) tried to {action}. Only a person may do that.")
