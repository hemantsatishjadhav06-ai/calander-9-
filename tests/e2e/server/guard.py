"""The refusals the e2e server makes before it touches anything.

The server drops and re-creates its database on ``--reset``, installs fakes over the model clients
and answers named fixtures over HTTP. None of that may ever happen under another settings module or
against a database that is not its own, so both are checked before the first statement runs.
"""

from __future__ import annotations

import re

from django.conf import settings

E2E_SETTINGS_MODULE = "config.settings.e2e"
_E2E_DATABASE = re.compile(r"[a-z0-9_]+_e2e")


class GuardError(RuntimeError):
    """The e2e server was pointed at something that is not its own."""


def is_e2e_settings() -> bool:
    return getattr(settings, "SETTINGS_MODULE", None) == E2E_SETTINGS_MODULE


def assert_e2e_settings() -> None:
    if not is_e2e_settings():
        current = getattr(settings, "SETTINGS_MODULE", None)
        raise GuardError(
            f"The e2e server runs only with DJANGO_SETTINGS_MODULE={E2E_SETTINGS_MODULE}; this process has {current!r}."
        )


def assert_e2e_database(name: object) -> None:
    if not isinstance(name, str) or not _E2E_DATABASE.fullmatch(name):
        raise GuardError(
            f"Refusing the database {name!r}: the e2e server uses, and drops on --reset, only a database "
            "whose name is lower-case letters, digits and underscores ending in _e2e (for example brightbean_e2e)."
        )
