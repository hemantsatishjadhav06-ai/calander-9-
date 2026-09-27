"""QA round 1 BUG-07: the Django admin can be hidden behind an IP allowlist."""

from django.test import RequestFactory, SimpleTestCase, override_settings

from apps.accounts.middleware import AdminIPAllowlistMiddleware


def _ok(request):
    from django.http import HttpResponse

    return HttpResponse("ok")


class AdminIPAllowlistTests(SimpleTestCase):
    def _call(self, path, addr):
        request = RequestFactory().get(path, REMOTE_ADDR=addr)
        return AdminIPAllowlistMiddleware(_ok)(request)

    @override_settings(ADMIN_ALLOWED_IPS=[], ADMIN_URL="admin/")
    def test_empty_allowlist_leaves_admin_reachable(self):
        self.assertEqual(self._call("/admin/login/", "203.0.113.9").status_code, 200)

    @override_settings(ADMIN_ALLOWED_IPS=["198.51.100.0/24"], ADMIN_URL="admin/")
    def test_outsider_gets_404(self):
        from django.http import Http404

        with self.assertRaises(Http404):
            self._call("/admin/login/", "203.0.113.9")

    @override_settings(ADMIN_ALLOWED_IPS=["198.51.100.0/24"], ADMIN_URL="admin/")
    def test_allowed_range_and_other_paths_pass(self):
        self.assertEqual(self._call("/admin/login/", "198.51.100.7").status_code, 200)
        self.assertEqual(self._call("/accounts/login/", "203.0.113.9").status_code, 200)
