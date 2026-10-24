"""The harness's JSON views: ping, named fixtures and named probes.

Mounted only by ``tests.e2e.server.urls`` (``ROOT_URLCONF`` of ``config.settings.e2e``). Each view
answers 404, like a path that does not exist, unless the settings module is ``config.settings.e2e``,
and 403 to any address that is not loopback. CSRF-exempt: the callers are the Playwright runner and
its request context, never a page.
"""

from __future__ import annotations

import ipaddress
import json
import logging
from collections.abc import Callable
from typing import Any

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

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


def harness_only(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    def wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if not guard.is_e2e_settings():
            raise Http404
        if not _is_loopback(str(request.META.get("REMOTE_ADDR", ""))):
            return _json({"error": "The e2e harness answers loopback only."}, status=403)
        return view(request, *args, **kwargs)

    wrapped.__name__ = view.__name__
    wrapped.__doc__ = view.__doc__
    return csrf_exempt(wrapped)


def _run(step: registry.Step, payload: dict[str, Any], *, atomic: bool) -> JsonResponse:
    try:
        if atomic:
            with transaction.atomic():
                result = step(payload)
        else:
            result = step(payload)
    except registry.PayloadError as exc:
        return _json({"error": str(exc)}, status=400)
    except Exception as exc:
        logger.exception("e2e step failed")
        return _json({"error": f"{type(exc).__name__}: {exc}"}, status=500)
    return _json(result)


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
@require_POST
def run_fixture(request: HttpRequest, name: str) -> HttpResponse:
    step = registry.get_fixture(name)
    if step is None:
        return _json({"error": f"No e2e fixture named {name!r}."}, status=404)
    try:
        payload = json.loads(request.body or b"{}")
    except ValueError:
        return _json({"error": "The body must be a JSON object."}, status=400)
    if not isinstance(payload, dict):
        return _json({"error": "The body must be a JSON object."}, status=400)
    return _run(step, payload, atomic=True)


@harness_only
@require_GET
def run_probe(request: HttpRequest, name: str) -> HttpResponse:
    step = registry.get_probe(name)
    if step is None:
        return _json({"error": f"No e2e probe named {name!r}."}, status=404)
    params = {key: request.GET.get(key) for key in request.GET}
    return _run(step, params, atomic=False)
