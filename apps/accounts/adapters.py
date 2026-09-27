from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django import forms

from apps.accounts.models import OAuthConnection
from apps.accounts.signup_policy import may_sign_up
from apps.common.mail import transactional

NOT_INVITED_MESSAGE = "This address hasn't been invited yet. Ask your team for an invitation link."


class AccountAdapter(DefaultAccountAdapter):
    """Marks allauth's own mail as transactional.

    Password resets, email confirmations and login codes are mail a person is
    sitting in front of waiting for. Without this they would carry the default
    ``notification`` class and be subject to the per-recipient cap in
    ``apps.common.mail`` — so a user who had already received their allowance of
    publish-failure notices that hour could not reset their own password. The
    global daily cap still applies; nothing bypasses that.

    ``render_mail`` is the single seam every allauth email passes through, so
    overriding it here covers all of them without touching a template.
    """

    def render_mail(self, template_prefix, email, context, headers=None):
        return super().render_mail(
            template_prefix,
            email,
            context,
            headers={**(headers or {}), **transactional()},
        )

    def get_client_ip(self, request):
        """allauth keys its login/signup/reset rate limits on this.

        The default is REMOTE_ADDR, which behind the platform edge is the edge:
        one bucket for everybody, so ten failed logins from anyone locked
        everyone out. Use the trusted-proxy-aware address instead.
        """
        from apps.common.net import client_ip

        return client_ip(request) or super().get_client_ip(request)

    def is_open_for_signup(self, request):
        """Honour settings.SIGNUP_MODE; an invitation link always gets through."""
        return may_sign_up(request)

    def clean_email(self, email):
        email = super().clean_email(email)
        request = getattr(self, "request", None)
        if request is not None and not may_sign_up(request, email):
            raise forms.ValidationError(NOT_INVITED_MESSAGE)
        return email


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """Custom adapter that syncs Google social logins to OAuthConnection."""

    def is_open_for_signup(self, request, sociallogin):
        """Same rule as email signup; the provider's address is known up front."""
        email = ""
        for address in sociallogin.email_addresses:
            email = address.email
            break
        return may_sign_up(request, email or None) if email else may_sign_up(request)

    def populate_user(self, request, sociallogin, data):
        """Set user.name from Google profile (custom User model has 'name', not first/last)."""
        user = super().populate_user(request, sociallogin, data)
        first_name = data.get("first_name", "")
        last_name = data.get("last_name", "")
        full_name = f"{first_name} {last_name}".strip()
        if full_name and not user.name:
            user.name = full_name
        return user

    def save_user(self, request, sociallogin, form=None):
        """Create OAuthConnection after saving a new social signup."""
        user = super().save_user(request, sociallogin, form)
        self._sync_oauth_connection(user, sociallogin)
        return user

    def pre_social_login(self, request, sociallogin):
        """Sync OAuthConnection for returning users and auto-connected accounts."""
        super().pre_social_login(request, sociallogin)
        if sociallogin.is_existing:
            self._sync_oauth_connection(sociallogin.user, sociallogin)

    def _sync_oauth_connection(self, user, sociallogin):
        account = sociallogin.account
        if account.provider != "google":
            return
        provider_email = ""
        for ea in sociallogin.email_addresses:
            provider_email = ea.email
            break
        OAuthConnection.objects.update_or_create(
            provider=OAuthConnection.Provider.GOOGLE,
            provider_user_id=account.uid,
            defaults={"user": user, "provider_email": provider_email},
        )
