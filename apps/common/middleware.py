"""Response headers Django's SecurityMiddleware does not set."""

PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()"


class PermissionsPolicyMiddleware:
    """Turn off browser features the app never uses, so injected script can't either."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
        return response
