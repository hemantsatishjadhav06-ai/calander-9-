"""The public host behind the front door, response headers Django's SecurityMiddleware does not
set, and compression for HTML pages."""

from urllib.parse import urlsplit

from django.conf import settings
from django.http.request import split_domain_port
from django.middleware.gzip import GZipMiddleware

PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()"


class FrontDoorHostMiddleware:
    """Answer a request that arrives under the platform's own hostname as the public host.

    Netlify proxies the public address to the Render web service and sends that service's own name
    (``*.onrender.com``) as ``Host``; it sends no ``X-Forwarded-Host`` and strips one a client
    sends, so ``USE_X_FORWARDED_HOST`` has nothing to read. Left alone, every absolute URL built
    from the request (OAuth redirect URIs, onboarding links, the sitemap) would name the platform
    host, where the visitor's session cookie does not exist. A request whose host is one of
    ``PLATFORM_HOSTNAMES`` (Render's ``RENDER_EXTERNAL_HOSTNAME``) is therefore treated as if it
    had arrived at ``APP_URL``'s host. The result is always that one host, so a client cannot steer
    it; any other host is left exactly as it came. First in ``MIDDLEWARE``: the https redirect and
    the CSRF origin check read the host.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        platform = {name.lower() for name in getattr(settings, "PLATFORM_HOSTNAMES", ()) if name}
        public = _public_host()
        if platform and public:
            domain, _port = split_domain_port(request.META.get("HTTP_HOST", ""))
            if domain in platform:
                request.META["HTTP_HOST"] = public
        return self.get_response(request)


def _public_host() -> str:
    """``APP_URL``'s host (with its port, if it names one), or "" when it gives none."""
    try:
        origin = urlsplit(getattr(settings, "APP_URL", "") or "")
        port = origin.port
    except ValueError:
        return ""
    host = origin.hostname or ""
    if not host:
        return ""
    if ":" in host:  # an IPv6 literal keeps its brackets in a Host header
        host = f"[{host}]"
    return f"{host}:{port}" if port else host


class PermissionsPolicyMiddleware:
    """Turn off browser features the app never uses, so injected script can't either."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
        return response


class HtmlGZipMiddleware(GZipMiddleware):
    """Gzip HTML pages and HTMX fragments for browsers that ask; leave everything else as it is.

    Django's middleware with two limits: only ``text/html``, and never a streamed response (file
    downloads: media, attachments, exports), so pictures and videos are not compressed twice and
    nothing is held back. JSON (the Agent API, MCP, webhooks) stays as before. Django's own BREACH
    padding (``max_random_bytes``) applies. Static files never reach it: WhiteNoise, listed
    before it, answers them with their own compressed copies.
    """

    def process_response(self, request, response):
        if response.streaming or not response.get("Content-Type", "").startswith("text/html"):
            return response
        return super().process_response(request, response)
