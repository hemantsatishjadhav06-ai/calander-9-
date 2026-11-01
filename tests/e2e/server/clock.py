"""The e2e server's clock: real by default, frozen at one instant while a visual spec photographs a page.

The visual baselines (``tests/e2e/visual/``) must not move with the real date. The server's "now" is
``django.utils.timezone.now``, which every app module reads through the module (``timezone.now()``),
so this module puts its own :func:`now` there, the way ``fakes.py`` puts its stand-ins in place, and
answers the frozen instant while one is set and the real time otherwise. Request threads and the
worker share the process, so they read the same instant.

``from django.utils.timezone import now`` copies the function into the importing module, where a patch
of ``django.utils.timezone`` never reaches. :data:`NOW_IMPORTERS` lists every such copy, found by grep
(no app, settings, provider or e2e module makes one; Django itself does in these), and :func:`install`
also repoints any other module attribute that holds the original, whatever its name, and any model
field whose default is it (``default=timezone.now``). ``tests/test_e2e_steps_visual.py`` fails when an app
module starts importing ``now`` by name without being listed here.

What this does not reach, on purpose: ``{% now %}`` and ``timesince`` read ``datetime.now()``, and the
browser has its own clock (``page.clock``). The templates mark what prints those with
``data-visual-dynamic`` and the visual specs mask it.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

Setter = Callable[[Any, str, Any], None]

#: (module, name) for every copy of ``now`` made with ``from django.utils.timezone import now [as …]``
#: (grep over apps/, config/, providers/, tests/e2e/ and the installed packages the server loads), and
#: the original itself.
NOW_IMPORTERS: tuple[tuple[str, str], ...] = (
    ("django.utils.timezone", "now"),
    ("django.core.cache.backends.db", "tz_now"),
    ("django.core.files.storage.memory", "now"),
    ("django.db.migrations.recorder", "now"),
    ("django.db.migrations.writer", "now"),
)

_lock = threading.Lock()
_state: dict[str, Any] = {"real": None, "frozen": None}


def now() -> datetime:
    """The frozen instant while one is set, else the real ``django.utils.timezone.now()``."""
    frozen = _state["frozen"]
    if frozen is not None:
        return frozen
    real = _state["real"]
    if real is None:  # never installed: nothing to stand in for yet
        from django.utils import timezone

        real = timezone.now
    return real()


def installed() -> bool:
    from django.utils import timezone

    return timezone.now is now


def install(setter: Setter = setattr) -> None:
    """Put :func:`now` wherever the real one is read. Idempotent; tests pass ``monkeypatch.setattr``."""
    import importlib

    from django.apps import apps
    from django.utils import timezone

    with _lock:
        if installed():
            return
        real = timezone.now
        _state["real"] = real
        for module_name, _attribute in NOW_IMPORTERS:
            importlib.import_module(module_name)
        for module in list(sys.modules.values()):
            names = [name for name, value in list(getattr(module, "__dict__", {}).items()) if value is real]
            for name in names:
                setter(module, name, now)
        for model in apps.get_models():
            for field in model._meta.get_fields():
                if getattr(field, "default", None) is real:
                    setter(field, "default", now)
                    # Field._get_default caches the callable it found at first use; point it here too
                    # (through the setter, so a test's monkeypatch puts the cached one back).
                    setter(field, "_get_default", now)


def freeze(at: datetime) -> datetime:
    """Freeze the clock at ``at`` (aware; kept in UTC, as the real clock answers). Installs first."""
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("The instant needs its UTC offset.")
    install()
    instant = at.astimezone(UTC)
    _state["frozen"] = instant
    return instant


def thaw() -> None:
    """The real clock again."""
    _state["frozen"] = None


def frozen() -> datetime | None:
    """The frozen instant, or None while the clock is real."""
    return _state["frozen"]
