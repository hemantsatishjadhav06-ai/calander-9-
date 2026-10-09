import hashlib
import ipaddress
from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.core.cache import cache
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

from apps.common.net import client_ip

# Paths that are rate-limited for unauthenticated POST requests (auth flows)
AUTH_RATE_LIMITED_PATHS = (
    "/accounts/login/",
    "/accounts/signup/",
    "/accounts/password/reset/",
    "/accounts/password/reset/key/",
    # The Django admin's own login had no throttle at all.
    "/" + getattr(settings, "ADMIN_URL", "admin/").lstrip("/") + "login/",
)

# Rate limit: 10 POST requests per minute per IP for auth endpoints
AUTH_RATE_LIMIT = 10
AUTH_RATE_WINDOW = 60  # seconds

EXEMPT_PATH_PREFIXES = (
    "/accounts/accept-terms/",
    "/accounts/logout/",
    "/accounts/google/",
    "/accounts/3rdparty/",
    # Public policy pages: a not-yet-accepted user must be able to read the
    # Terms/Privacy linked from the acceptance page without being redirected
    # back to it.
    "/terms/",
    "/privacy/",
    "/pricing/",
    "/support/",
    "/health/",
    "/static/",
    # Uploaded media, served by config/urls.py when SERVE_MEDIA is on. No view
    # backs these URLs, so a redirect here just turns every <img>/<video> on
    # the accept-terms page into a 302 — and the platforms that fetch
    # attachment URLs server-side (see config/urls.py) are anonymous anyway.
    "/media/",
    "/" + getattr(settings, "ADMIN_URL", "admin/").lstrip("/"),
)


class TosAcceptanceMiddleware:
    """Redirect authenticated users to the ToS acceptance page if they haven't accepted yet."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Path check first: ``request.user`` is lazy, and touching it forces a
        # session read plus a user query. On an exempt path — /static/, /media/
        # — that work buys nothing, and media is requested once per file.
        if (
            not request.path.startswith(EXEMPT_PATH_PREFIXES)
            and hasattr(request, "user")
            and request.user.is_authenticated
            and request.user.tos_accepted_at is None
        ):
            url = reverse("accounts:accept_terms")
            if request.headers.get("HX-Request"):
                # A 302 here is followed inside htmx's request, and the terms
                # page lands in whatever the fragment was for (or nowhere, for
                # hx-swap="none") — a portal message would vanish silently. Ask
                # htmx to navigate the whole page instead, back to where the
                # person was once they've accepted.
                current = request.headers.get("HX-Current-URL", "")
                path = urlsplit(current).path if current else ""
                if path and path != "/" and path.startswith("/"):
                    url += "?" + urlencode({"next": path})
                return HttpResponse(status=204, headers={"HX-Redirect": url})
            # Someone who just signed up with Google lands here on the way to
            # the page they asked for; carry it so accepting takes them there.
            if request.method == "GET" and request.path != "/":
                url += "?" + urlencode({"next": request.get_full_path()})
            return redirect(url)

        return self.get_response(request)


class AuthRateLimitMiddleware:
    """Rate-limit POST requests to authentication endpoints (login, signup, password reset)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "POST" and any(request.path.startswith(p) for p in AUTH_RATE_LIMITED_PATHS):
            ip = self._get_client_ip(request)
            cache_key = f"auth_ratelimit:{hashlib.md5(ip.encode()).hexdigest()}"

            # Anchor the window at the first attempt (add seeds the TTL; incr
            # bumps without touching it) so a steady stream of requests can't
            # keep pushing the expiry out. cache.add returns False when the key
            # already exists.
            if not cache.add(cache_key, 1, AUTH_RATE_WINDOW):
                try:
                    attempts = cache.incr(cache_key)
                except ValueError:
                    # Key's TTL lapsed between add and incr — re-seed.
                    cache.set(cache_key, 1, AUTH_RATE_WINDOW)
                    attempts = 1
                if attempts > AUTH_RATE_LIMIT:
                    return HttpResponse("Too many requests. Please try again later.", status=429)

        return self.get_response(request)

    @staticmethod
    def _get_client_ip(request):
        """The client IP, trusting X-Forwarded-For only from a proxy we run.

        Shared with ``apps.api.limits`` so the throttle and the audit log can
        never disagree about who a request came from.
        """
        return client_ip(request) or ""


class AdminIPAllowlistMiddleware:
    """Hide the Django admin from every address outside ``ADMIN_ALLOWED_IPS``.

    The admin login is public by default and is the one form on the site that
    grants superuser. When the setting holds addresses or CIDR ranges, anyone
    else gets a plain 404 there, so the page is not even discoverable. Empty
    keeps the admin reachable (throttled by AuthRateLimitMiddleware) for
    self-hosters who never set it.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.networks = []
        for entry in getattr(settings, "ADMIN_ALLOWED_IPS", []) or []:
            try:
                self.networks.append(ipaddress.ip_network(entry.strip(), strict=False))
            except ValueError:
                continue
        self.prefix = "/" + getattr(settings, "ADMIN_URL", "admin/").lstrip("/")

    def __call__(self, request):
        if self.networks and request.path.startswith(self.prefix) and not self._allowed(request):
            raise Http404
        return self.get_response(request)

    def _allowed(self, request) -> bool:
        try:
            ip = ipaddress.ip_address(client_ip(request) or "")
        except ValueError:
            return False
        return any(ip in network for network in self.networks)
