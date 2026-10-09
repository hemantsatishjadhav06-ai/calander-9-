"""The ``learn`` job. Not built yet: its one stage fails with a sentence for people."""

from __future__ import annotations

from .. import engine


def not_ready(job):
    raise engine.JobError("This part of the agency isn't switched on yet.")


JOB = engine.JobType(kind="learn", stages=(engine.Stage("start", "account_manager", not_ready),))
