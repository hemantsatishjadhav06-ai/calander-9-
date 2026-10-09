"""The agency's Claude agents beyond the original four, one module per department.

Each role is a function that builds one agent's turn — instructions, the
brand block, this turn's material — and returns the validated answer from
:func:`apps.studio.roles.base.ask`. Roles never touch the database; the job
stages and pipeline steps decide when they run and what happens to the answer.
"""
