"""Who may create an account on this instance (settings.SIGNUP_MODE)."""

from django.conf import settings


def signup_is_open() -> bool:
    return getattr(settings, "SIGNUP_MODE", "invite_only") == "open"


def has_pending_invitation(request) -> bool:
    """True when this browser arrived through a live team invitation link."""
    token = request.session.get("pending_invite_token") if hasattr(request, "session") else None
    if not token:
        return False
    from apps.members.models import Invitation

    invitation = Invitation.objects.filter(token=token).first()
    return bool(invitation and not invitation.is_expired and not invitation.is_accepted)


def email_is_allowlisted(email: str) -> bool:
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return False
    domain = "@" + email.rsplit("@", 1)[1]
    allowed = getattr(settings, "SIGNUP_ALLOWLIST", [])
    return email in allowed or domain in allowed


def may_sign_up(request, email: str | None = None) -> bool:
    """Open instance, an invitation in hand, or (once known) an allowlisted address."""
    if signup_is_open() or has_pending_invitation(request):
        return True
    if email is None:
        # The address is not known yet (the form is being shown): let the form
        # render when an allowlist exists; clean_email decides on submit.
        return bool(getattr(settings, "SIGNUP_ALLOWLIST", []))
    return email_is_allowlisted(email)
