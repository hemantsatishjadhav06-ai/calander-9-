"""A socket guard for the e2e server process: loopback to the database and the server, nothing else.

Installed by ``__main__`` before the seed runs, it replaces ``socket.socket.connect``,
``socket.socket.connect_ex`` and ``socket.getaddrinfo``. A connection to a loopback address on an
allowed port (the database, the server itself) goes through; every other connection, whatever host
or port, and every name lookup outside the machine is refused and recorded, with a short stack tail,
for the ``refused_network`` probe. The database driver resolves its host through ``getaddrinfo``
and then connects in C, so the database's host name may be *looked up* by name; ``__main__`` refuses
to start unless that host is this machine.
"""

from __future__ import annotations

import errno
import ipaddress
import os
import socket
import threading
import time
import traceback
from collections.abc import Callable, Iterable
from typing import Any

_LOOPBACK_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"})
_MAX_RECORDS = 500

_lock = threading.Lock()
_refused: list[dict[str, Any]] = []
_allowed: dict[str, frozenset[Any]] = {"ports": frozenset(), "hosts": frozenset()}
_originals: dict[str, Callable[..., Any]] = {}


def is_loopback(host: str) -> bool:
    """``localhost`` and its aliases, 127.0.0.0/8, ``::1`` and IPv4-mapped loopback."""
    if host.lower() in _LOOPBACK_NAMES:
        return True
    try:
        address = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    if address.is_loopback:
        return True
    mapped = getattr(address, "ipv4_mapped", None)
    return bool(mapped is not None and mapped.is_loopback)


def _lookup_allowed(host: str) -> bool:
    return host in _allowed["hosts"] or is_loopback(host)


def _split(address: Any) -> tuple[str | None, int | None]:
    if isinstance(address, tuple) and address:
        port = address[1] if len(address) > 1 and isinstance(address[1], int) else None
        return str(address[0]), port
    return None, None  # a Unix socket path


def _address_allowed(address: Any) -> bool:
    host, port = _split(address)
    if host is None:
        return True
    return is_loopback(host) and port in _allowed["ports"]


def _record(kind: str, host: str | None, port: int | None) -> None:
    where = "".join(traceback.format_stack(limit=12)[:-3])[-1500:]
    with _lock:
        _refused.append({"kind": kind, "host": host, "port": port, "at": time.time(), "where": where})
        del _refused[:-_MAX_RECORDS]


def install(*, allowed_ports: Iterable[int], allowed_hosts: Iterable[str] = ()) -> None:
    """Refuse every connection but loopback on ``allowed_ports``; ``allowed_hosts`` may only be looked up."""
    _allowed["ports"] = frozenset(int(port) for port in allowed_ports)
    _allowed["hosts"] = frozenset(str(host) for host in allowed_hosts if host)
    if _originals:
        return
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo
    _originals.update(connect=real_connect, connect_ex=real_connect_ex, getaddrinfo=real_getaddrinfo)

    def connect(self: socket.socket, address: Any) -> None:
        if not _address_allowed(address):
            host, port = _split(address)
            _record("connect", host, port)
            raise ConnectionRefusedError(errno.ECONNREFUSED, f"e2e: connections outside this machine are off ({host})")
        return real_connect(self, address)

    def connect_ex(self: socket.socket, address: Any) -> int:
        if not _address_allowed(address):
            host, port = _split(address)
            _record("connect", host, port)
            return errno.ECONNREFUSED
        return real_connect_ex(self, address)

    def getaddrinfo(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
        name = host.decode() if isinstance(host, bytes) else host
        if name is not None and not _lookup_allowed(str(name)):
            _record("resolve", str(name), port if isinstance(port, int) else None)
            raise socket.gaierror(socket.EAI_NONAME, f"e2e: name lookups outside this machine are off ({name})")
        return real_getaddrinfo(host, port, *args, **kwargs)

    setattr(socket.socket, "connect", connect)  # noqa: B010 - mypy refuses a direct method assignment
    setattr(socket.socket, "connect_ex", connect_ex)  # noqa: B010
    setattr(socket, "getaddrinfo", getaddrinfo)  # noqa: B010


def uninstall() -> None:
    if not _originals:
        return
    setattr(socket.socket, "connect", _originals["connect"])  # noqa: B010
    setattr(socket.socket, "connect_ex", _originals["connect_ex"])  # noqa: B010
    setattr(socket, "getaddrinfo", _originals["getaddrinfo"])  # noqa: B010
    _originals.clear()


def is_installed() -> bool:
    return bool(_originals)


def refused(since: float | None = None) -> list[dict[str, Any]]:
    with _lock:
        return [dict(item) for item in _refused if since is None or item["at"] >= since]


def clear() -> None:
    with _lock:
        _refused.clear()


def strip_proxy_environment() -> list[str]:
    """Forget any outbound proxy, so no library even tries one (a proxy on loopback would be refused)."""
    names = [name for name in os.environ if name.lower().endswith("_proxy") or name.lower() == "all_proxy"]
    for name in names:
        os.environ.pop(name, None)
    return sorted(names)
