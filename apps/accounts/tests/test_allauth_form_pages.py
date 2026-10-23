"""allauth pages that render a whole form through ``{% element fields %}`` draw working fields.

The element override handed each bound field to ``field.html``, which only reads
explicit attributes, so the password change, password set, reauthenticate and
email pages showed inputs with no name, id, type or label: nothing could be
submitted and a screen reader heard unlabelled boxes.
"""

import re

import pytest
from django.urls import reverse


def _inputs(html):
    return re.findall(r"<input\b[^>]*>", html, flags=re.S)


def _attr(tag, name):
    found = re.search(rf'\b{name}="([^"]*)"', tag)
    return found.group(1) if found else None


def _labelled_fields(html):
    labels = set(re.findall(r'<label[^>]*\bfor="([^"]+)"', html))
    fields = {}
    for tag in _inputs(html):
        kind = _attr(tag, "type")
        if kind in ("hidden", "submit"):
            continue
        fields[_attr(tag, "name")] = {"type": kind, "id": _attr(tag, "id"), "labelled": _attr(tag, "id") in labels}
    return fields


@pytest.mark.django_db
def test_password_change_page_draws_named_labelled_password_fields(client, user):
    user.set_password("Old-pass-123!")
    user.save()
    client.force_login(user)

    html = client.get(reverse("account_change_password")).content.decode()

    fields = _labelled_fields(html)
    for name in ("oldpassword", "password1", "password2"):
        assert fields.get(name, {}).get("type") == "password", fields
        assert fields[name]["labelled"], f"{name} has no label"
    assert 'type=""' not in html


@pytest.mark.django_db
def test_password_change_form_actually_changes_the_password(client, user):
    user.set_password("Old-pass-123!")
    user.save()
    client.force_login(user)

    response = client.post(
        reverse("account_change_password"),
        {"oldpassword": "Old-pass-123!", "password1": "New-pass-456!xyz", "password2": "New-pass-456!xyz"},
    )

    assert response.status_code in (200, 302)
    user.refresh_from_db()
    assert user.check_password("New-pass-456!xyz")


@pytest.mark.django_db
def test_wrong_current_password_is_shown_and_never_echoed(client, user):
    user.set_password("Old-pass-123!")
    user.save()
    client.force_login(user)

    response = client.post(
        reverse("account_change_password"),
        {"oldpassword": "wrong-one-999", "password1": "New-pass-456!xyz", "password2": "New-pass-456!xyz"},
    )

    html = response.content.decode()
    assert response.status_code == 200
    assert 'aria-invalid="true"' in html
    assert "wrong-one-999" not in html
    assert "New-pass-456!xyz" not in html


@pytest.mark.django_db
def test_reauthenticate_and_email_pages_draw_their_fields(client, user):
    client.force_login(user)

    reauth = _labelled_fields(client.get(reverse("account_reauthenticate")).content.decode())
    email = _labelled_fields(client.get(reverse("account_email")).content.decode())

    assert reauth.get("password", {}).get("type") == "password" and reauth["password"]["labelled"], reauth
    assert email.get("email", {}).get("type") == "email" and email["email"]["labelled"], email
