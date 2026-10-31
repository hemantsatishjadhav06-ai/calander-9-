"""Named, typed fixtures and probes: the only things a browser test can ask the e2e server to do.

A *fixture* creates fresh rows for one test and returns their ids (``POST /__e2e__/fixture/<name>``
with a JSON object). A *probe* reads the rows a test asserts on (``GET /__e2e__/probe/<name>?k=v``).
Each is a plain Python function ``(payload: dict[str, Any]) -> dict[str, Any]``, registered with
:func:`fixture` or :func:`probe` in a module under ``steps/``, and linted and type-checked with the
rest of ``tests/``. There is no endpoint that runs code from a request.

A step that is given a bad payload raises :class:`PayloadError`; the view answers 400 with its message.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

Step = Callable[[dict[str, Any]], dict[str, Any]]

FIXTURES: dict[str, Step] = {}
PROBES: dict[str, Step] = {}


class PayloadError(ValueError):
    """The payload a test sent does not fit the step; answered with 400 and this message."""


def _register(table_name: str, name: str) -> Callable[[Step], Step]:
    def decorate(step: Step) -> Step:
        table = FIXTURES if table_name == "fixture" else PROBES
        if name in table:
            raise ValueError(f"An e2e {table_name} named {name!r} is already registered.")
        table[name] = step
        return step

    return decorate


def fixture(name: str) -> Callable[[Step], Step]:
    """Register ``(payload) -> dict`` as the fixture ``name``."""
    return _register("fixture", name)


def probe(name: str) -> Callable[[Step], Step]:
    """Register ``(params) -> dict`` as the probe ``name``."""
    return _register("probe", name)


def get_fixture(name: str) -> Step | None:
    return FIXTURES.get(name)


def get_probe(name: str) -> Step | None:
    return PROBES.get(name)


def load_steps() -> None:
    """Import every module in ``steps/`` (each registers its own steps on import)."""
    from . import steps  # noqa: F401


# ---------------------------------------------------------------------------
# Payload helpers for steps
# ---------------------------------------------------------------------------


def require_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PayloadError(f"'{key}' must be a non-empty string.")
    return value.strip()


def optional_str(payload: dict[str, Any], key: str, default: str = "") -> str:
    value = payload.get(key, default)
    if not isinstance(value, str):
        raise PayloadError(f"'{key}' must be a string.")
    return value.strip()


def require_number(payload: dict[str, Any], key: str) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise PayloadError(f"'{key}' must be a number.")
    try:
        return float(value)
    except ValueError as exc:
        raise PayloadError(f"'{key}' must be a number.") from exc


def optional_number(payload: dict[str, Any], key: str) -> float | None:
    if payload.get(key) in (None, ""):
        return None
    return require_number(payload, key)
