"""One-line JSON log records on stdout, for Railway's log explorer.

Railway tags everything written to stderr as severity "error", and Python's
StreamHandler writes to stderr by default, so a 404 warning looked exactly like
a crash. Railway reads the severity from a JSON record's ``level`` field when
the line is JSON, so we write JSON to stdout and let the level speak for itself.
"""

import json
import logging
from datetime import UTC, datetime


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        status_code = getattr(record, "status_code", None)
        if status_code is not None:
            payload["status_code"] = status_code
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)
