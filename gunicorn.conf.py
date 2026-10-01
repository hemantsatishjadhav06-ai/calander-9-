"""Gunicorn settings, loaded automatically from the working directory.

Gunicorn's own log lines (boot, worker start/exit, timeouts) go to stdout as
JSON with their real level, like the app's (apps.common.logging). On stderr
Railway files every line as "error". This goes through a logging handler
rather than ``--error-logfile /dev/stdout``, because gunicorn opens that path
with mode "a+", which raises "File or stream is not seekable" on a pipe and
stopped the web service from booting (QA round 1, BUG-31).
"""

logconfig_dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"()": "apps.common.logging.JSONFormatter"}},
    "handlers": {
        "stdout": {"class": "logging.StreamHandler", "stream": "ext://sys.stdout", "formatter": "json"},
    },
    "loggers": {
        "gunicorn.error": {"handlers": ["stdout"], "level": "INFO", "propagate": False},
        "gunicorn.access": {"handlers": ["stdout"], "level": "INFO", "propagate": False},
    },
    "root": {"handlers": ["stdout"], "level": "WARNING"},
}
