"""/ops/email/: connect the Gmail account the instance sends from, and test it."""

import secrets
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.mail import EmailMultiAlternatives
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods

from . import gmail
from .mail import transactional
from .models import OutboundMailbox

_STATE_KEY = "gmail_connect_state"

superuser_required = user_passes_test(lambda u: u.is_active and u.is_superuser)


def _redirect_uri(request) -> str:
    base = (getattr(settings, "APP_URL", "") or request.build_absolute_uri("/")).rstrip("/")
    return base + reverse("ops_email_callback")


@login_required
@superuser_required
@require_http_methods(["GET", "POST"])
def email_settings(request):
    if request.method == "POST" and request.POST.get("action") == "test":
        msg = EmailMultiAlternatives(
            subject=f"{settings.SITE_NAME} test email",
            body="Outbound email from this instance works.",
            to=[request.user.email],
            headers=transactional(),
        )
        try:
            sent = msg.send(fail_silently=False)
        except Exception as exc:  # noqa: BLE001 - shown to the operator verbatim
            messages.error(request, f"Sending failed: {exc}")
        else:
            if sent:
                messages.success(request, f"Test email sent to {request.user.email}.")
            else:
                messages.error(request, "The message was held back by the outbound email budget.")
        return redirect("ops_email")

    client_id, _secret = gmail.client_credentials()
    return render(
        request,
        "ops/email.html",
        {
            "backend_type": settings.EMAIL_BACKEND_TYPE,
            "mailbox": OutboundMailbox.objects.order_by("-connected_at").first(),
            "env_token": bool(getattr(settings, "GMAIL_REFRESH_TOKEN", "")),
            "client_configured": bool(client_id),
            "redirect_uri": _redirect_uri(request),
            "from_email": settings.DEFAULT_FROM_EMAIL,
        },
    )


@login_required
@superuser_required
@require_GET
def gmail_connect(request):
    client_id, _secret = gmail.client_credentials()
    state = secrets.token_urlsafe(24)
    request.session[_STATE_KEY] = state
    params = {
        "client_id": client_id,
        "redirect_uri": _redirect_uri(request),
        "response_type": "code",
        "scope": gmail.SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return redirect(f"{gmail.AUTH_URL}?{urlencode(params)}")


@login_required
@superuser_required
@require_GET
def gmail_callback(request):
    expected = request.session.pop(_STATE_KEY, None)
    if not expected or request.GET.get("state") != expected:
        messages.error(request, "That Google response didn't match a connect request. Try again.")
        return redirect("ops_email")
    if request.GET.get("error"):
        messages.error(request, f"Google said: {request.GET['error']}")
        return redirect("ops_email")
    try:
        token, email = gmail.exchange_code(request.GET.get("code", ""), _redirect_uri(request))
    except RuntimeError as exc:
        messages.error(request, str(exc))
        return redirect("ops_email")
    OutboundMailbox.objects.all().delete()
    OutboundMailbox.objects.create(email=email, refresh_token=token, connected_by=request.user)
    from django.core.cache import cache

    cache.delete(gmail._ACCESS_TOKEN_CACHE_KEY)
    messages.success(request, f"Connected {email}. Send a test email to confirm.")
    return redirect("ops_email")
