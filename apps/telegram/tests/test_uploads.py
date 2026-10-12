"""Scoped canonical storage with controlled bytes and adversarial revocations."""

from __future__ import annotations

import io
import traceback
from types import SimpleNamespace

import pytest
from django.utils import timezone
from PIL import Image

from apps.accounts.models import User
from apps.media_library.models import MediaAsset
from apps.members.models import CustomRole, OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.studio.models import AgencyJob, Conversation, StudioBrief
from apps.telegram.models import TelegramChat, TelegramConnection, TelegramUserLink
from apps.telegram.uploads import (
    MAX_DOCUMENT_BYTES,
    MAX_PHOTO_BYTES,
    MAX_TEXT_BYTES,
    ReferenceUploadError,
    receive_reference,
)
from apps.workspaces.models import Workspace

pytestmark = pytest.mark.django_db


def image_bytes(format="PNG", size=(64, 48), *, exif=None):
    output = io.BytesIO()
    Image.new("RGB", size, (40, 80, 120)).save(output, format=format, **({"exif": exif} if exif else {}))
    return output.getvalue()


class FileAPI:
    def __init__(self, data, *, path="photos/file_1.png", size=None, after_get=None, after_download=None):
        self.data, self.path = data, path
        self.size = len(data) if size is None else size
        self.after_get, self.after_download, self.calls = after_get, after_download, []

    def get_file(self, file_id):
        self.calls.append(("get_file", file_id))
        if self.after_get:
            self.after_get()
        return {"file_path": self.path, "file_size": self.size}

    def download(self, path, max_bytes):
        self.calls.append(("download", path, max_bytes))
        if self.after_download:
            self.after_download()
        return self.data


@pytest.fixture
def world(settings, tmp_path, monkeypatch):
    settings.MEDIA_ROOT = tmp_path
    settings.STORAGE_QUOTA_ENABLED = True
    settings.STORAGE_QUOTA_DEFAULT = 1024 * 1024
    from apps.media_library import tasks
    from apps.telegram import api

    monkeypatch.setattr(tasks, "process_media_asset", lambda asset_id: None)

    def no_network(*args, **kwargs):
        raise AssertionError("Telegram transport must be mocked")

    monkeypatch.setattr(api.BotAPI, "get_file", no_network)
    org = Organization.objects.create(name="Reference agency")
    ws = Workspace.objects.create(organization=org, name="Reference brand")
    users, members = {}, {}
    for role in ("owner", "editor", "client", "viewer"):
        user = User.objects.create_user(
            email=f"upload-{role}@example.test", password="fixture-password", tos_accepted_at=timezone.now()
        )
        OrgMembership.objects.create(organization=org, user=user, org_role="owner" if role == "owner" else "member")
        members[role] = WorkspaceMembership.objects.create(workspace=ws, user=user, workspace_role=role)
        users[role] = user
    conn = TelegramConnection.objects.create(
        workspace=ws,
        bot_id=4001,
        token="upload-fixture-token",
        webhook_secret="fixture-hook",
        is_active=True,
        created_by=users["owner"],
    )
    convo = Conversation.objects.create(workspace=ws, audience="client")
    chat = TelegramChat.objects.create(
        connection=conn, chat_id=-123001, chat_type="supergroup", audience="client", conversation=convo
    )
    links = {
        role: TelegramUserLink.objects.create(connection=conn, user=user, telegram_user_id=5001 + index)
        for index, (role, user) in enumerate(users.items())
    }
    return SimpleNamespace(org=org, ws=ws, users=users, members=members, conn=conn, convo=convo, chat=chat, links=links)


def message(world, role="editor", data=None, *, mime=None, name="source", message_id=1):
    data = image_bytes() if data is None else data
    result = {
        "message_id": message_id,
        "from": {"id": world.links[role].telegram_user_id, "is_bot": False},
        "chat": {"id": world.chat.chat_id},
    }
    if mime:
        result["document"] = {"file_id": "document-id", "file_name": name, "mime_type": mime, "file_size": len(data)}
    else:
        result["photo"] = [{"file_id": "photo-id", "width": 64, "height": 48, "file_size": len(data)}]
    return result


def receive(world, payload=None, api=None, role="editor"):
    return receive_reference(
        world.conn,
        world.chat,
        world.links[role],
        message(world, role) if payload is None else payload,
        api=FileAPI(image_bytes()) if api is None else api,
    )


@pytest.mark.parametrize(("format", "mime"), [("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")])
def test_scoped_still_photos_store_actual_actor_without_verification_or_jobs(world, format, mime):
    data = image_bytes(format)
    api = FileAPI(data)
    result = receive(world, message(world, data=data), api)
    assert result.kind == "photo" and result.mime_type == mime
    asset = result.asset
    assert asset.workspace_id == world.ws.pk and asset.organization_id == world.org.pk
    assert asset.uploaded_by_id == world.users["editor"].pk
    assert asset.source == "telegram-reference" and asset.authenticity == "unknown" and asset.verified_by is None
    assert (asset.width, asset.height) == (64, 48)
    assert api.calls[-1] == ("download", "photos/file_1.png", MAX_PHOTO_BYTES)
    assert not AgencyJob.objects.exists() and not StudioBrief.objects.exists()


def test_client_reference_requires_no_internal_create_or_upload_permission(world):
    assert not world.members["client"].effective_permissions["upload_media"]
    result = receive(world, role="client")
    assert result.asset.uploaded_by_id == world.users["client"].pk
    assert not AgencyJob.objects.exists() and not StudioBrief.objects.exists()


def test_custom_client_facing_is_client_despite_create_and_upload_permissions(world):
    custom = CustomRole.objects.create(
        organization=world.org,
        name="Custom client",
        permissions={"client_facing": True, "create_posts": True, "upload_media": True},
    )
    WorkspaceMembership.objects.filter(pk=world.members["editor"].pk).update(custom_role=custom)
    assert receive(world).asset.uploaded_by_id == world.users["editor"].pk
    Conversation.objects.filter(pk=world.convo.pk).update(audience="internal")
    TelegramChat.objects.filter(pk=world.chat.pk).update(audience="team")
    with pytest.raises(ReferenceUploadError, match="Internal"):
        receive(world, message(world, message_id=2))


def test_viewer_cannot_use_client_exception(world):
    api = FileAPI(image_bytes())
    with pytest.raises(ReferenceUploadError, match="current role"):
        receive(world, api=api, role="viewer")
    assert not api.calls and not MediaAsset.objects.exists()


@pytest.mark.parametrize("role", ["client", "editor"])
def test_private_reference_requires_exact_paired_owner(world, role):
    world.chat.audience = "private"
    world.chat.chat_type = "private"
    world.chat.chat_id = world.links[role].telegram_user_id
    world.chat.private_user = world.users[role]
    world.chat.save()
    shared = message(world, role)
    shared["caption"] = "/reference shared"
    assert receive(world, shared, role=role).asset.uploaded_by_id == world.users[role].pk
    TelegramChat.objects.filter(pk=world.chat.pk).update(private_user=world.users["owner"])
    with pytest.raises(ReferenceUploadError, match="different paired"):
        receive(world, message(world, role, message_id=2), role=role)


@pytest.mark.parametrize(
    "change",
    [
        "client_team",
        "client_internal",
        "foreign_conversation",
        "foreign_connection",
        "inactive_chat",
        "inactive_connection",
    ],
)
def test_invalid_scope_rejects_before_transport(world, change):
    if change == "client_team":
        TelegramChat.objects.filter(pk=world.chat.pk).update(audience="team")
        Conversation.objects.filter(pk=world.convo.pk).update(audience="internal")
    elif change == "client_internal":
        Conversation.objects.filter(pk=world.convo.pk).update(audience="internal")
    elif change == "foreign_conversation":
        foreign = Workspace.objects.create(
            organization=Organization.objects.create(name="Other agency"), name="Other brand"
        )
        Conversation.objects.filter(pk=world.convo.pk).update(workspace=foreign)
    elif change == "foreign_connection":
        ws = Workspace.objects.create(organization=world.org, name="Other brand")
        conn = TelegramConnection.objects.create(workspace=ws, bot_id=4002, token="other-fixture-token", is_active=True)
        TelegramChat.objects.filter(pk=world.chat.pk).update(connection=conn)
    elif change == "inactive_chat":
        TelegramChat.objects.filter(pk=world.chat.pk).update(is_active=False)
    else:
        TelegramConnection.objects.filter(pk=world.conn.pk).update(is_active=False)
    api = FileAPI(image_bytes())
    with pytest.raises(ReferenceUploadError):
        receive(world, api=api, role="client")
    assert not api.calls and not MediaAsset.objects.exists()


@pytest.mark.parametrize(
    "change",
    [
        "link",
        "user",
        "workspace_member",
        "org_member",
        "role",
        "custom_role",
        "chat",
        "conversation",
        "bot",
        "token",
        "workspace",
        "organization",
    ],
)
def test_revocation_or_destination_change_during_download_prevents_storage(world, change):
    def revoke():
        if change == "link":
            TelegramUserLink.objects.filter(pk=world.links["editor"].pk).update(is_active=False)
        elif change == "user":
            User.objects.filter(pk=world.users["editor"].pk).update(is_active=False)
        elif change == "workspace_member":
            WorkspaceMembership.objects.filter(pk=world.members["editor"].pk).delete()
        elif change == "org_member":
            OrgMembership.objects.filter(user=world.users["editor"], organization=world.org).delete()
        elif change == "role":
            WorkspaceMembership.objects.filter(pk=world.members["editor"].pk).update(workspace_role="viewer")
        elif change == "custom_role":
            custom = CustomRole.objects.create(organization=world.org, name="No upload", permissions={})
            WorkspaceMembership.objects.filter(pk=world.members["editor"].pk).update(custom_role=custom)
        elif change == "chat":
            TelegramChat.objects.filter(pk=world.chat.pk).update(is_active=False)
        elif change == "conversation":
            convo = Conversation.objects.create(workspace=world.ws, audience="client")
            TelegramChat.objects.filter(pk=world.chat.pk).update(conversation=convo)
        elif change == "bot":
            TelegramConnection.objects.filter(pk=world.conn.pk).update(bot_id=4003)
        elif change == "token":
            TelegramConnection.objects.filter(pk=world.conn.pk).update(token="rotated-fixture-token")
        elif change == "workspace":
            Workspace.objects.filter(pk=world.ws.pk).update(is_archived=True)
        else:
            Organization.objects.filter(pk=world.org.pk).update(deletion_requested_at=timezone.now())

    api = FileAPI(image_bytes(), after_download=revoke)
    with pytest.raises(ReferenceUploadError):
        receive(world, api=api)
    assert any(call[0] == "download" for call in api.calls) and not MediaAsset.objects.exists()


def test_revocation_after_get_file_prevents_download(world):
    api = FileAPI(
        image_bytes(),
        after_get=lambda: TelegramUserLink.objects.filter(pk=world.links["editor"].pk).update(is_active=False),
    )
    with pytest.raises(ReferenceUploadError):
        receive(world, api=api)
    assert len(api.calls) == 1 and not MediaAsset.objects.exists()


@pytest.mark.parametrize("change", ["anonymous", "forwarded_impersonation", "wrong_chat", "bot", "string_id"])
def test_only_actual_paired_numeric_sender_authorizes(world, change):
    payload = message(world)
    if change == "anonymous":
        payload["sender_chat"] = {"id": world.chat.chat_id}
    elif change == "forwarded_impersonation":
        payload["from"]["id"] = 999999
        payload["forward_from"] = {"id": world.links["editor"].telegram_user_id}
    elif change == "wrong_chat":
        payload["chat"]["id"] = -99999
    elif change == "bot":
        payload["from"]["is_bot"] = True
    else:
        payload["from"]["id"] = str(payload["from"]["id"])
    api = FileAPI(image_bytes())
    with pytest.raises(ReferenceUploadError):
        receive(world, payload, api)
    assert not api.calls


@pytest.mark.parametrize(
    "path",
    [
        "https://evil.test/photo.jpg",
        "//evil.test/a",
        "/photos/a.jpg",
        "photos/../a.jpg",
        "photos/%2e%2e/a.jpg",
        "photos/a.jpg?token=secret",
        "photos\\a.jpg",
        "photos/a.jpg\x00",
        "photos/./a.jpg",
    ],
)
def test_provider_path_cannot_become_arbitrary_fetch(world, path):
    api = FileAPI(image_bytes(), path=path)
    with pytest.raises(ReferenceUploadError, match="file location"):
        receive(world, api=api)
    assert len(api.calls) == 1


@pytest.mark.parametrize(
    ("mime", "name", "data"),
    [
        ("image/svg+xml", "photo.svg", b"<svg/>"),
        ("image/gif", "a.gif", b"GIF89a"),
        ("application/zip", "a.zip", b"PK00"),
        ("video/mp4", "a.mp4", b"video"),
        ("audio/ogg", "a.ogg", b"OggS"),
    ],
)
def test_unsupported_documents_never_download(world, mime, name, data):
    api = FileAPI(data)
    with pytest.raises(ReferenceUploadError):
        receive(world, message(world, data=data, mime=mime, name=name), api)
    assert not api.calls


@pytest.mark.parametrize(
    ("data", "mime"),
    [
        (b"<html>script</html>", "image/png"),
        (b"\x89PNG\r\n\x1a\n<script>bad</script>", "image/png"),
        (image_bytes("JPEG"), "image/png"),
    ],
)
def test_magic_and_full_decode_mismatch_rejects(world, data, mime):
    with pytest.raises(ReferenceUploadError):
        receive(world, message(world, data=data, mime=mime, name="photo.png"), FileAPI(data))
    assert not MediaAsset.objects.exists()


def test_photo_reencoding_removes_polyglot_tail_and_unsafe_filename_controls(world):
    data = image_bytes() + b"<script>never-store-this-tail</script>"
    result = receive(world, message(world, data=data, mime="image/png", name="../../photo.html\u202e\n"), FileAPI(data))
    with result.asset.file.open("rb") as file:
        assert b"never-store-this-tail" not in file.read()
    assert result.asset.file.name.endswith(".png")
    assert all(control not in result.filename for control in ["/", "\n", "\u202e"])


def test_actual_pixels_override_declared_dimensions(world, monkeypatch):
    from apps.telegram import uploads

    monkeypatch.setattr(uploads, "MAX_PHOTO_PIXELS", 100)
    data = image_bytes(size=(20, 20))
    payload = message(world, data=data)
    payload["photo"][0].update(width=8, height=8)
    with pytest.raises(ReferenceUploadError, match="20 megapixels"):
        receive(world, payload, FileAPI(data))
    assert not MediaAsset.objects.exists()


def test_exif_orientation_survives_metadata_removal(world):
    exif = Image.Exif()
    exif[274] = 6
    data = image_bytes("JPEG", size=(40, 20), exif=exif)
    result = receive(world, message(world, data=data), FileAPI(data))
    assert (result.asset.width, result.asset.height) == (20, 40)
    with result.asset.file.open("rb") as file, Image.open(file) as photo:
        assert photo.size == (20, 40) and not photo.getexif().get(274)


@pytest.mark.parametrize("phase", ["declared", "provider", "actual", "incomplete"])
def test_each_byte_bound_is_enforced(world, phase):
    data = image_bytes()
    payload = message(world, data=data)
    api = FileAPI(data)
    if phase == "declared":
        payload["photo"][0]["file_size"] = MAX_PHOTO_BYTES + 1
    elif phase == "provider":
        api.size = MAX_PHOTO_BYTES + 1
    elif phase == "actual":
        api.data = b"x" * (MAX_PHOTO_BYTES + 1)
        api.size = 1
    else:
        api.size = len(data) + 1
    with pytest.raises(ReferenceUploadError):
        receive(world, payload, api)
    assert not MediaAsset.objects.exists()


def test_client_uploads_obey_canonical_storage_quota(world, settings):
    settings.STORAGE_QUOTA_DEFAULT = 1
    with pytest.raises(ReferenceUploadError, match="storage limits"):
        receive(world, role="client")
    assert not MediaAsset.objects.exists()


def test_replayed_reference_reuses_scoped_asset(world):
    first = receive(world)
    second = receive(world)
    assert first.asset.pk == second.asset.pk and MediaAsset.objects.count() == 1


def test_passive_pdf_is_stored_without_reading_facts(world):
    data = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\n%%EOF"
    result = receive(
        world,
        message(world, "client", data, mime="application/pdf", name="source.pdf"),
        FileAPI(data, path="documents/file_1.pdf"),
        "client",
    )
    assert result.kind == "document" and result.asset.mime_type == "application/pdf" and not result.text_excerpt
    assert "no PDF text was read" in result.warning and result.asset.uploaded_by_id == world.users["client"].pk


@pytest.mark.parametrize(
    "data",
    [
        b"%PDF-bogus\n%%EOF",
        b"%PDF-1.4\ntruncated",
        b"%PDF-1.4\n/JavaScript (evil)\n%%EOF",
        b"%PDF-1.4\n/#4a#53 (evil)\n%%EOF",
        b"%PDF-1.4\n/EmbeddedFile (payload)\n%%EOF",
        b"%PDF-1.4\n/Encrypt 1 0 R\n%%EOF",
    ],
)
def test_incomplete_or_recognizably_active_pdf_is_rejected(world, data):
    with pytest.raises(ReferenceUploadError):
        receive(world, message(world, data=data, mime="application/pdf", name="source.pdf"), FileAPI(data))
    assert not MediaAsset.objects.exists()


def test_pdf_and_plain_text_have_smaller_declared_download_limits(world):
    for mime, size, name in [
        ("application/pdf", MAX_DOCUMENT_BYTES, "source.pdf"),
        ("text/plain", MAX_TEXT_BYTES, "source.txt"),
    ]:
        payload = message(world, data=b"source", mime=mime, name=name)
        payload["document"]["file_size"] = size + 1
        api = FileAPI(b"source")
        with pytest.raises(ReferenceUploadError):
            receive(world, payload, api)
        assert not api.calls


def test_plain_text_is_untrusted_bounded_excerpt_not_media_or_job(world):
    data = ("Site visits are by appointment. " * 150).encode()
    result = receive(
        world,
        message(world, "client", data, mime="text/plain; charset=utf-8", name="facts.txt"),
        FileAPI(data, path="documents/file_1.txt"),
        "client",
    )
    assert result.asset is None and result.kind == "text" and len(result.text_excerpt) == 3000
    assert "Untrusted" in result.warning and "first 3000" in result.warning
    assert not MediaAsset.objects.exists() and not AgencyJob.objects.exists()


@pytest.mark.parametrize(
    "data", [b"\xff\xfeutf16", b"facts\x00binary", b"<svg><script/></svg>", b"<!DOCTYPE html><html/>", b"  "]
)
def test_plain_text_cannot_smuggle_binary_or_markup(world, data):
    with pytest.raises(ReferenceUploadError):
        receive(world, message(world, "client", data, mime="text/plain", name="facts.txt"), FileAPI(data), "client")
    assert not MediaAsset.objects.exists()


def test_transport_error_traceback_does_not_expose_token_or_url(world):
    class BrokenAPI:
        def get_file(self, file_id):
            raise RuntimeError("secret-fixture-token https://api.telegram.org/botsecret-fixture-token/file")

    try:
        receive(world, api=BrokenAPI())
    except ReferenceUploadError:
        trace = traceback.format_exc()
        assert "secret-fixture-token" not in trace and "api.telegram.org" not in trace
    else:
        pytest.fail("Transport failure was not rejected")


def test_storage_error_is_safe_and_database_write_rolls_back(world, monkeypatch):
    from apps.telegram import uploads

    real = uploads.create_asset

    def fail(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError("sensitive-bucket-and-token")

    monkeypatch.setattr(uploads, "create_asset", fail)
    with pytest.raises(ReferenceUploadError, match="could not be saved") as error:
        receive(world)
    assert "sensitive" not in str(error.value) and not MediaAsset.objects.exists()


def _private_reference(world, role="client"):
    world.chat.audience = "private"
    world.chat.chat_type = "private"
    world.chat.chat_id = world.links[role].telegram_user_id
    world.chat.private_user = world.users[role]
    world.chat.save()
    world.convo.is_private = True
    world.convo.created_by = world.users[role]
    world.convo.save(update_fields=["is_private", "created_by"])


@pytest.mark.parametrize("caption", [None, "/reference", "/reference sharedish"])
def test_private_photo_requires_exact_sharing_consent_before_any_io(world, caption):
    _private_reference(world)
    payload = message(world, "client")
    if caption is not None:
        payload["caption"] = caption
    api = FileAPI(image_bytes())
    with pytest.raises(ReferenceUploadError, match="shared brand media library"):
        receive(world, payload, api=api, role="client")
    assert api.calls == [] and not MediaAsset.objects.exists()
    assert not AgencyJob.objects.exists() and not StudioBrief.objects.exists()


def test_private_pdf_requires_same_consent_without_downloading(world):
    _private_reference(world)
    data = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\n%%EOF"
    payload = message(world, "client", data, mime="application/pdf", name="private-source.pdf")
    api = FileAPI(data, path="documents/private.pdf")
    with pytest.raises(ReferenceUploadError, match="No file was downloaded or saved"):
        receive(world, payload, api=api, role="client")
    assert not api.calls and not MediaAsset.objects.exists()


def test_private_explicit_shared_photo_records_actual_sender_and_honest_storage_note(world):
    _private_reference(world)
    payload = message(world, "client")
    payload["caption"] = "/reference shared Use this project photo after checking it"
    uploaded = receive(world, payload, api=FileAPI(image_bytes()), role="client")
    assert uploaded.asset.uploaded_by_id == world.users["client"].pk
    assert uploaded.asset.workspace_id == world.ws.pk
    assert "shared brand media library" in uploaded.warning
    assert uploaded.asset.authenticity != "verified"


def test_private_sharing_consent_never_overrides_mid_download_revocation(world):
    _private_reference(world)
    payload = message(world, "client")
    payload["caption"] = "/reference shared"
    api = FileAPI(
        image_bytes(),
        after_download=lambda: TelegramUserLink.objects.filter(pk=world.links["client"].pk).update(is_active=False),
    )
    with pytest.raises(ReferenceUploadError, match="current paired workspace access"):
        receive(world, payload, api=api, role="client")
    assert not MediaAsset.objects.exists()


def test_private_text_excerpt_needs_no_library_sharing_consent_and_creates_no_asset(world):
    _private_reference(world)
    data = b"Private research notes supplied for a question, not a brand asset."
    payload = message(world, "client", data, mime="text/plain", name="private-notes.txt")
    uploaded = receive(world, payload, api=FileAPI(data, path="documents/private.txt"), role="client")
    assert uploaded.kind == "text" and uploaded.asset is None
    assert "Private research notes" in uploaded.text_excerpt
    assert "shared brand media library" not in uploaded.warning
    assert not MediaAsset.objects.exists()


def test_stale_cached_group_audience_cannot_bypass_private_reference_consent(world):
    _private_reference(world)
    payload = message(world, "client")
    world.chat.audience = "client"  # The persisted chat remains private.
    api = FileAPI(image_bytes())
    with pytest.raises(ReferenceUploadError, match="shared brand media library"):
        receive(world, payload, api=api, role="client")
    assert not api.calls and not MediaAsset.objects.exists()


@pytest.mark.parametrize(
    "forward_field", ["forward_origin", "forward_from", "forward_from_chat", "is_automatic_forward"]
)
def test_inherited_forwarded_private_caption_is_not_current_persons_sharing_choice(world, forward_field):
    _private_reference(world)
    payload = message(world, "client")
    payload["caption"] = "/reference shared"
    payload[forward_field] = True if forward_field == "is_automatic_forward" else {"id": 900900}
    api = FileAPI(image_bytes())
    with pytest.raises(ReferenceUploadError, match="forwarded caption cannot confirm your choice"):
        receive(world, payload, api=api, role="client")
    assert not api.calls and not MediaAsset.objects.exists()
