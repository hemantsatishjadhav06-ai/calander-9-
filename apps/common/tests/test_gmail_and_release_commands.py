"""Gmail API mail backend, the /ops/email/ page, and the release-time commands."""

import base64
import json
from unittest import mock

import pytest
from django.core import mail
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from apps.accounts.models import User
from apps.common import gmail
from apps.common.models import OutboundMailbox

REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parents[3]


class _Resp:
    def __init__(self, status, payload=None, content=b""):
        self.status_code = status
        self._payload = payload or {}
        self.text = json.dumps(self._payload)
        self.content = content

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _clear_token_cache():
    cache.delete(gmail._ACCESS_TOKEN_CACHE_KEY)
    yield
    cache.delete(gmail._ACCESS_TOKEN_CACHE_KEY)


@pytest.mark.django_db
@override_settings(GMAIL_REFRESH_TOKEN="", GOOGLE_AUTH_CLIENT_ID="cid", GOOGLE_AUTH_CLIENT_SECRET="sec")
def test_backend_refreshes_a_token_and_posts_base64_mime():
    OutboundMailbox.objects.create(email="ops@example.com", refresh_token="rt-1")
    sent_bodies = []

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers, json):
            assert headers["Authorization"] == "Bearer at-1"
            sent_bodies.append(base64.urlsafe_b64decode(json["raw"]))
            return _Resp(200, {"id": "m1"})

    with (
        mock.patch.object(
            gmail.httpx, "post", return_value=_Resp(200, {"access_token": "at-1", "expires_in": 3600})
        ) as token_post,
        mock.patch.object(gmail.httpx, "Client", _Client),
    ):
        backend = gmail.GmailAPIEmailBackend()
        msg = mail.EmailMessage("Hi", "Body", "ops@example.com", ["to@example.com"])
        assert backend.send_messages([msg]) == 1

    assert token_post.call_args.kwargs["data"]["refresh_token"] == "rt-1"
    assert b"Subject: Hi" in sent_bodies[0] and b"to@example.com" in sent_bodies[0]


@pytest.mark.django_db
@override_settings(GMAIL_REFRESH_TOKEN="")
def test_backend_without_a_connected_mailbox_fails_loudly():
    backend = gmail.GmailAPIEmailBackend(fail_silently=False)
    with pytest.raises(gmail.GmailNotConnectedError):
        backend.send_messages([mail.EmailMessage("Hi", "B", "a@example.com", ["b@example.com"])])


def _superuser(client):
    user = User.objects.create_user(email="root@example.com", password="pw", tos_accepted_at=timezone.now())
    user.is_superuser = True
    user.is_staff = True
    user.save()
    client.force_login(user)
    return user


@pytest.mark.django_db
def test_ops_email_is_superuser_only(client):
    user = User.objects.create_user(email="u@example.com", password="pw", tos_accepted_at=timezone.now())
    client.force_login(user)
    assert client.get("/ops/email/").status_code in (302, 403)


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND_TYPE="gmail_api", GOOGLE_AUTH_CLIENT_ID="cid", APP_URL="https://app.example.com")
def test_connect_flow_stores_the_mailbox(client):
    _superuser(client)
    resp = client.get("/ops/email/connect/")
    assert resp.status_code == 302 and "gmail.send" in resp["Location"]
    assert "redirect_uri=https%3A%2F%2Fapp.example.com%2Fops%2Femail%2Fcallback%2F" in resp["Location"]
    state = client.session["gmail_connect_state"]
    with mock.patch.object(gmail, "exchange_code", return_value=("rt-new", "ops@example.com")):
        resp = client.get("/ops/email/callback/", {"state": state, "code": "c"})
    assert resp.status_code == 302
    assert OutboundMailbox.objects.get().refresh_token == "rt-new"


@pytest.mark.django_db
def test_callback_rejects_a_forged_state(client):
    _superuser(client)
    client.get("/ops/email/callback/", {"state": "nope", "code": "c"})
    assert not OutboundMailbox.objects.exists()


@pytest.mark.django_db
def test_import_legacy_media_copies_only_missing_files(tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    from apps.organizations.models import Organization
    from apps.workspaces.models import Workspace

    org = Organization.objects.create(name="O")
    Workspace.objects.create(organization=org, name="W", icon="workspaces/icons/2026/09/a.png")
    Workspace.objects.create(organization=org, name="W2", icon="workspaces/icons/2026/09/b.png")
    default_storage.save("workspaces/icons/2026/09/b.png", ContentFile(b"already"))

    class _Client:
        def __init__(self, *a, **k):
            self.urls = []

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url):
            assert url == "https://old.example.com/media/workspaces/icons/2026/09/a.png"
            return _Resp(200, content=b"png-bytes")

    with mock.patch("apps.common.management.commands.import_legacy_media.httpx.Client", _Client):
        call_command("import_legacy_media", source_url="https://old.example.com/media")

    with default_storage.open("workspaces/icons/2026/09/a.png") as fh:
        assert fh.read() == b"png-bytes"


@pytest.mark.django_db
def test_backup_database_writes_every_table_and_a_manifest(tmp_path, settings):
    import tarfile

    settings.MEDIA_ROOT = str(tmp_path)
    User.objects.create_user(email="kept@example.com", password="pw", tos_accepted_at=timezone.now())
    call_command("backup_database", required=True)
    (archive,) = (tmp_path / "backups").iterdir()
    with tarfile.open(archive, "r:gz") as tar:
        manifest = json.load(tar.extractfile("manifest.json"))
        users_csv = tar.extractfile("accounts_user.csv").read()
    assert manifest["tables"]["accounts_user"] == 1
    assert b"kept@example.com" in users_csv


@pytest.mark.django_db
def test_release_backs_up_then_migrates_then_imports(tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    calls = []
    with mock.patch(
        "apps.common.management.commands.release.call_command",
        side_effect=lambda name, **kw: calls.append((name, kw.get("required"), kw.get("source_url"))),
    ):
        call_command("release", legacy_media_url="https://old.example.com/media/")
    assert [c[0] for c in calls] == ["backup_database", "migrate", "import_legacy_media"]
    assert calls[0][1] is True and calls[2][2] == "https://old.example.com/media/"


@pytest.mark.django_db
def test_release_stops_before_migrate_when_the_backup_fails():
    from django.core.management.base import CommandError

    calls = []

    def fake(name, **kw):
        calls.append(name)
        if name == "backup_database":
            raise CommandError("no storage")

    with (
        mock.patch("apps.common.management.commands.release.call_command", side_effect=fake),
        pytest.raises(CommandError),
    ):
        call_command("release")
    assert calls == ["backup_database"]


def test_gunicorn_config_logs_to_stdout_without_opening_a_file():
    import logging.config
    import runpy

    cfg = runpy.run_path(str(REPO_ROOT / "gunicorn.conf.py"))["logconfig_dict"]
    logging.config.dictConfig(cfg)  # must not raise
    handler = logging.getLogger("gunicorn.error").handlers[0]
    import sys

    assert handler.stream is sys.stdout
