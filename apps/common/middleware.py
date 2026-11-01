"""Response headers Django's SecurityMiddleware does not set, and compression for HTML pages."""

from django.middleware.gzip import GZipMiddleware

PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()"


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
