"""The enforced response policy must keep inline scripts behind a nonce."""

import pytest
from django.test import override_settings


@pytest.mark.django_db
@override_settings(CSP_REPORT_ONLY=False)
def test_login_response_enforces_csp_without_unsafe_inline_scripts(client):
    response = client.get("/accounts/login/")

    assert response.status_code == 200
    assert "Content-Security-Policy-Report-Only" not in response
    directives = {
        tokens[0]: tokens[1:]
        for directive in response["Content-Security-Policy"].split(";")
        if (tokens := directive.strip().split())
    }
    scripts = directives["script-src"]
    assert "'self'" in scripts
    assert "'unsafe-inline'" not in scripts
    assert any(source.startswith("'nonce-") for source in scripts)
    assert "'unsafe-inline'" not in directives.get("script-src-elem", scripts)
