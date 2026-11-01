"""The harness's JSON views: ping, named fixtures and named probes.

Mounted only by ``tests.e2e.server.urls`` (``ROOT_URLCONF`` of ``config.settings.e2e``). Each view
answers 404, like a path that does not exist, unless the settings module is ``config.settings.e2e``,
and 403 to any address that is not loopback.

CSRF-exempt, because the callers are the Playwright runner and its request context, never a page. In
place of the token, a request a browser marks as coming from another site (an ``Origin`` other than
the server's own, or ``Sec-Fetch-Site`` other than ``same-origin`` or ``none``) is refused with 403,
and a fixture body must be ``application/json``, which no page on another site can send without a
preflight this server never answers. So a page open in the developer's browser cannot create rows
here while the server runs.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import time
from collections.abc import Callable
from typing import Any

from django.core.serializers.json import DjangoJSONEncoder
from django.db import OperationalError, transaction
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseNotAllowed, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from . import guard, registry, seed

logger = logging.getLogger("tests.e2e.views")

registry.load_steps()


def _json(data: dict[str, Any], status: int = 200) -> JsonResponse:
    return JsonResponse(data, status=status, encoder=DjangoJSONEncoder)


def _is_loopback(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    mapped = getattr(parsed, "ipv4_mapped", None)
    return parsed.is_loopback or bool(mapped is not None and mapped.is_loopback)


_SAME_SITE_FETCHES = frozenset({"same-origin", "none"})


def _from_another_site(request: HttpRequest) -> bool:
    """Whether the browser says this request comes from a page that is not the server's own."""
    origin = request.headers.get("Origin")
    if origin is not None and origin != f"{request.scheme}://{request.get_host()}":
        return True
    fetch_site = request.headers.get("Sec-Fetch-Site")
    return fetch_site is not None and fetch_site not in _SAME_SITE_FETCHES


def harness_only(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    def wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if not guard.is_e2e_settings():
            raise Http404
        if not _is_loopback(str(request.META.get("REMOTE_ADDR", ""))):
            return _json({"error": "The e2e harness answers loopback only."}, status=403)
        if _from_another_site(request):
            return _json({"error": "The e2e harness does not answer requests from other sites."}, status=403)
        return view(request, *args, **kwargs)

    wrapped.__name__ = view.__name__
    wrapped.__doc__ = view.__doc__
    return csrf_exempt(wrapped)


# A fixture runs while the harness's worker thread keeps working on the same rows, so Postgres can
# end a fixture's transaction as one side of a deadlock (issue #24). Postgres asks the loser to run
# again. The fixture's database work is rolled back whole; work outside the database that ran before
# the deadlock (mail sent after an inner block, cache counters) runs again with it. Each retry is
# logged with the fixture's name and what Postgres said, so an absorbed deadlock can still be traced.
_DEADLOCK_ATTEMPTS = 3
_DEADLOCK_PAUSE_SECONDS = 0.2


def _is_deadlock(exc: BaseException) -> bool:
    if not isinstance(exc, OperationalError):
        return False
    cause = exc.__cause__
    if getattr(cause, "sqlstate", None) == "40P01":
        return True
    return str(exc).startswith("deadlock detected")


def _run(step: registry.Step, payload: dict[str, Any], *, atomic: bool, name: str) -> JsonResponse:
    attempts = _DEADLOCK_ATTEMPTS if atomic else 1
    for attempt in range(1, attempts + 1):
        try:
            if atomic:
                with transaction.atomic():
                    result = step(payload)
            else:
                result = step(payload)
        except registry.PayloadError as exc:
            return _json({"error": str(exc)}, status=400)
        except Exception as exc:
            if attempt < attempts and _is_deadlock(exc):
                logger.warning(
                    "e2e fixture %s met a deadlock; running it again (attempt %s of %s): %s",
                    name,
                    attempt + 1,
                    attempts,
                    exc.__cause__ or exc,
                )
                time.sleep(_DEADLOCK_PAUSE_SECONDS * attempt)
                continue
            logger.exception("e2e step failed")
            return _json({"error": f"{type(exc).__name__}: {exc}"}, status=500)
        return _json(result)
    raise AssertionError("unreachable: the last attempt always returns")


@harness_only
@require_GET
def ping(request: HttpRequest) -> HttpResponse:
    """``{"ok": true, "ids": {...}}`` once the database is seeded; 503 before."""
    try:
        ids = seed.ids()
    except seed.SeedMissingError as exc:
        return _json({"ok": False, "error": str(exc)}, status=503)
    return _json({"ok": True, "ids": ids})


@harness_only
def run_fixture(request: HttpRequest, name: str) -> HttpResponse:
    # The name first: an unknown name is a 404 whatever the method, a known one 405 to anything but POST.
    step = registry.get_fixture(name)
    if step is None:
        return _json({"error": f"No e2e fixture named {name!r}."}, status=404)
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    if request.content_type != "application/json":
        return _json({"error": "Send the fixture's payload as application/json."}, status=415)
    try:
        payload = json.loads(request.body or b"{}")
    except ValueError:
        return _json({"error": "The body must be a JSON object."}, status=400)
    if not isinstance(payload, dict):
        return _json({"error": "The body must be a JSON object."}, status=400)
    return _run(step, payload, atomic=True, name=name)


@harness_only
def run_probe(request: HttpRequest, name: str) -> HttpResponse:
    step = registry.get_probe(name)
    if step is None:
        return _json({"error": f"No e2e probe named {name!r}."}, status=404)
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    params = {key: request.GET.get(key) for key in request.GET}
    return _run(step, params, atomic=False, name=name)
