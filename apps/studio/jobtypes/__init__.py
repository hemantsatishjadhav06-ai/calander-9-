"""One module per kind of agency job; each defines ``JOB`` (an ``engine.JobType``).

``apps.studio.jobs.JOB_TYPES`` collects them. A stage function takes the job,
does one agent's turn (or one piece of code), writes through
``engine.save``/``engine.update_state`` and returns the next stage, or calls
``engine.finish`` and returns None.
"""
