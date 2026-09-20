import hashlib

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

# Paths that are rate-limited for unauthenticated POST requests (auth flows)
AUTH_RATE_LIMITED_PATHS = (
    "/accounts/login/",
    "/accounts/signup/",
    "/accounts/password/reset/",
    "/accounts/password/reset/key/",
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
    "/health/",
    "/static/",
    # Uploaded media, served by config/urls.py when SERVE_MEDIA is on. No view
    # backs these URLs, so a redirect here just turns every <img>/<video> on
    # the accept-terms page into a 302 — and the platforms that fetch
    # attachment URLs server-side (see config/urls.py) are anonymous anyway.
    "/media/",
    "/admin/",
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
            return redirect(reverse("accounts:accept_terms"))

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
        """Return the client IP, trusting X-Forwarded-For only from known proxies.

        A remote client can set X-Forwarded-For to any value, so honouring it
        unconditionally lets an attacker rotate the header per request to land
        in a fresh rate-limit bucket every time — defeating the throttle (and,
        by extension, brute-force / password-reset email-bombing protection).
        Only trust XFF when the socket peer (REMOTE_ADDR) is a proxy we run,
        listed in ``settings.BB_TRUSTED_PROXIES``; otherwise use REMOTE_ADDR,
        the only IP we can vouch for. Mirrors ``apps/api/limits._client_ip``.
        """
        remote = request.META.get("REMOTE_ADDR", "")
        trusted = set(getattr(settings, "BB_TRUSTED_PROXIES", ()) or ())
        if trusted and remote in trusted:
            forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
            if forwarded:
                # Leftmost hop that isn't itself a trusted proxy is the client.
                for hop in (h.strip() for h in forwarded.split(",") if h.strip()):
                    if hop not in trusted:
                        return hop
        return remote
