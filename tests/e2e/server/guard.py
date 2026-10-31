"""The refusals the e2e server makes before it touches anything.

The server drops and re-creates its database on ``--reset``, installs fakes over the model clients
and answers named fixtures over HTTP. None of that may ever happen under another settings module or
against a database that is not its own, so the settings module, the database name, the database
host and the libpq variables that could move that host are all checked before the first statement runs.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping

from django.conf import settings

from .netguard import is_loopback

E2E_SETTINGS_MODULE = "config.settings.e2e"
_E2E_DATABASE = re.compile(r"[a-z0-9_]+_e2e")
_LOCAL_ONLY = "the e2e server uses, and drops on --reset, a database on this machine only"


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


def _is_local_host(host: object) -> bool:
    """Empty (the default socket), a socket directory or a loopback name: one host, since libpq splits on commas."""
    if not isinstance(host, str) or "," in host:
        return False
    return host == "" or host.startswith("/") or is_loopback(host)


def assert_local_database_host(host: object) -> None:
    """The database is on this machine: a loopback name or address, or a local socket (empty or a path)."""
    if _is_local_host(host):
        return
    raise GuardError(
        f"Refusing the database host {host!r}: {_LOCAL_ONLY} "
        "(DB_HOST localhost, 127.0.0.1, ::1 or a local socket directory)."
    )


def assert_local_libpq_environment(host: object, environ: Mapping[str, str] | None = None) -> None:
    """No libpq variable sends the connection somewhere other than ``host`` (the database's ``HOST``).

    libpq fills every connection option it is not given from its own environment variables, and
    connects in C, where the socket guard never sees it. ``PGHOSTADDR`` replaces the address
    whatever host is given; ``PGSERVICE`` reads a service entry that can carry its own host or
    address; and when ``DB_HOST`` is empty, Django and ``reset_database`` leave the host out, so
    libpq takes it from ``PGHOST``. Each is refused, naming the variable, unless it keeps the
    connection on this machine.
    """
    environ = os.environ if environ is None else environ
    address = environ.get("PGHOSTADDR")
    if address:
        raise GuardError(
            f"Refusing PGHOSTADDR={address!r}: libpq connects to that address whatever DB_HOST says, and "
            f"{_LOCAL_ONLY}. Unset PGHOSTADDR and name the database's host in DB_HOST."
        )
    service = environ.get("PGSERVICE")
    if service:
        raise GuardError(
            f"Refusing PGSERVICE={service!r}: a libpq service entry can send the connection to another "
            f"host, and {_LOCAL_ONLY}. Unset PGSERVICE and name the database's host in DB_HOST."
        )
    pghost = environ.get("PGHOST")
    if not host and pghost and not _is_local_host(pghost):
        raise GuardError(
            f"Refusing PGHOST={pghost!r}: DB_HOST is empty, so libpq would connect there, and "
            f"{_LOCAL_ONLY}. Unset PGHOST or set DB_HOST to localhost or a local socket directory."
        )
