"""Start the e2e server: ``python -m tests.e2e.server [--reset] [--port N] [--no-worker] [--static manifest]``.

In order: the settings and database guards (``config.settings.e2e`` only, a database named ``*_e2e``
on this machine only, refused before a single statement runs); the fakes, the provider mock and the socket guard;
with ``--reset``, the database dropped and re-created, migrated and seeded; with ``--static
manifest``, ``collectstatic`` into ``e2e_media/static`` for the compressed manifest storage; the
worker thread (unless ``--no-worker``); then ``runserver`` on 127.0.0.1 without the reloader (the
fakes and the worker live in this one process).

Environment: ``E2E_PORT`` (default 8150), ``DB_NAME`` (default ``brightbean_e2e``), and the usual
``DB_USER``, ``DB_PASSWORD``, ``DB_HOST``, ``DB_PORT``. The flags decide ``E2E_STATIC`` and
``E2E_BASE_URL`` (kept only when it names this server's port), so a value left in the shell by an
earlier run never changes this one.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlsplit

from . import guard


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m tests.e2e.server", description="Start the e2e server.")
    parser.add_argument("--reset", action="store_true", help="drop, re-create, migrate and seed the e2e database")
    parser.add_argument("--port", type=int, default=int(os.environ.get("E2E_PORT", "8150")))
    parser.add_argument("--no-worker", action="store_true", help="do not start the in-process worker")
    parser.add_argument(
        "--static",
        choices=("manifest",),
        default=None,
        help="collect the static files and serve them through the compressed manifest storage",
    )
    return parser.parse_args(argv)


def reset_database() -> None:
    """Drop and re-create the e2e database, after both guards have agreed it is the e2e database."""
    import psycopg
    from django.conf import settings
    from psycopg import sql

    guard.assert_e2e_settings()
    database = settings.DATABASES["default"]
    name = database["NAME"]
    guard.assert_e2e_database(name)
    guard.assert_local_database_host(database.get("HOST"))
    params = {
        "dbname": "postgres",
        "user": database.get("USER"),
        "password": database.get("PASSWORD"),
        "host": database.get("HOST"),
        "port": database.get("PORT"),
    }
    with psycopg.connect(**{key: value for key, value in params.items() if value}, autocommit=True) as connection:
        connection.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))


def _base_url(port: int, given: str | None) -> str:
    """``E2E_BASE_URL`` when it names this server (http, loopback, ``port``); otherwise derived from ``port``."""
    if given:
        parts = urlsplit(given)
        try:
            given_port = parts.port
        except ValueError:
            given_port = None
        if parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost") and given_port == port:
            return given.rstrip("/")
    return f"http://127.0.0.1:{port}"


def prepare_environment(args: argparse.Namespace) -> None:
    """What the e2e settings read, from the flags: a value left in the shell by an earlier run never wins."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", guard.E2E_SETTINGS_MODULE)
    os.environ["E2E_PORT"] = str(args.port)
    os.environ["E2E_BASE_URL"] = _base_url(args.port, os.environ.get("E2E_BASE_URL"))
    os.environ["E2E_STATIC"] = args.static or ""


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    prepare_environment(args)

    import django

    django.setup()

    from django.conf import settings

    try:
        guard.assert_e2e_settings()
        guard.assert_e2e_database(settings.DATABASES["default"]["NAME"])
        guard.assert_local_database_host(settings.DATABASES["default"].get("HOST"))
    except guard.GuardError as exc:
        print(f"e2e server: {exc}", file=sys.stderr)
        return 2

    from django.core.management import call_command

    from . import fakes, mocks, netguard, seed, worker

    database = settings.DATABASES["default"]
    fakes.install()
    mocks.install()
    stripped = netguard.strip_proxy_environment()
    netguard.install(
        allowed_ports=(args.port, int(database.get("PORT") or 5432)),
        allowed_hosts=(str(database.get("HOST") or "localhost"),),
    )
    print(
        f"[e2e] fakes, provider mock and socket guard installed (proxy variables dropped: {len(stripped)})", flush=True
    )

    if args.reset:
        reset_database()
        call_command("migrate", interactive=False, verbosity=0)
        seed.run()
        print(f"[e2e] database {database['NAME']} reset, migrated and seeded", flush=True)
    try:
        seed.ids()
    except seed.SeedMissingError as exc:
        print(f"e2e server: {exc}", file=sys.stderr)
        return 2

    Path(settings.STATIC_ROOT).mkdir(parents=True, exist_ok=True)  # WhiteNoise reads it either way
    if args.static == "manifest":
        call_command("collectstatic", interactive=False, verbosity=0)
        print(f"[e2e] static files collected into {settings.STATIC_ROOT}", flush=True)
    if not args.no_worker:
        worker.start()
    print(f"[e2e] serving http://127.0.0.1:{args.port}/ (database {database['NAME']})", flush=True)
    call_command(
        "runserver",
        f"127.0.0.1:{args.port}",
        use_reloader=False,
        use_threading=True,
        skip_checks=True,
        insecure_serving=True,
        use_static_handler=args.static != "manifest",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
