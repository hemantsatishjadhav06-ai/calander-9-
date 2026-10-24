"""A wrong password says so: the sign-in page shows the errors that belong to the whole form.

allauth reports a failed sign-in as a non-field error; the restyled page only
rendered field errors, so a wrong password reloaded the page with no message.
"""

import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_wrong_password_shows_the_form_error(client, user):
    response = client.post(reverse("account_login"), {"login": user.email, "password": "not-the-password"})

    assert response.status_code == 200
    html = response.content.decode()
    assert "data-form-errors" in html
    assert 'role="alert"' in html
    assert "not correct" in html
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_a_clean_sign_in_page_has_no_error_box(client):
    response = client.get(reverse("account_login"))

    assert response.status_code == 200
    assert "data-form-errors" not in response.content.decode()
