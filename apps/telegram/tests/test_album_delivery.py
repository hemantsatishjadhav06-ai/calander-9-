"""Albums: 2–10 pictures go out as one media group, each checked against the workspace first."""

import pytest

from apps.media_library.models import MediaAsset
from apps.telegram import outbox
from apps.telegram.models import TelegramDelivery
from apps.telegram.tests.test_delivery import controlled_api, hub, photo  # noqa: F401
from apps.workspaces.models import Workspace

pytestmark = pytest.mark.django_db


def test_album_preview_sends_every_picture_once_and_reports_the_first_receipt(hub, controlled_api):  # noqa: F811
    conn, chat = hub
    first, second = photo(conn), photo(conn)
    controlled_api.send_media_group.return_value = [{"message_id": 501}, {"message_id": 502}]
    row = outbox.queue_album(chat, [first.pk, second.pk], caption="Two graphics", source_key="album:1")
    assert row.kind == "album" and row.payload["method"] == "sendMediaGroup"
    assert outbox.queue_album(chat, [first.pk], source_key="album:single") is None
    assert outbox.send_one(row.pk) == "sent"
    row.refresh_from_db()
    assert row.native_message_id == 501
    chat_id, photos = controlled_api.send_media_group.call_args.args
    assert chat_id == chat.chat_id and len(photos) == 2 and all(item.startswith(b"\x89PNG") for item in photos)
    assert "Two graphics" in controlled_api.send_media_group.call_args.kwargs["caption"]
    for asset in (first, second):
        asset.file.delete(save=False)


def test_album_with_a_foreign_or_repeated_picture_is_never_queued(hub, controlled_api):  # noqa: F811
    conn, chat = hub
    own = photo(conn)
    foreign = Workspace.objects.create(organization=conn.workspace.organization, name="Other")
    other = MediaAsset.objects.create(
        workspace=foreign,
        organization=foreign.organization,
        filename="foreign.png",
        media_type="image",
        file_size=10,
        processing_status="completed",
    )
    assert outbox.queue_album(chat, [own.pk, other.pk], source_key="album:foreign") is None
    assert outbox.queue_album(chat, [own.pk, own.pk], source_key="album:dup") is None
    assert not TelegramDelivery.objects.exists()
    controlled_api.send_media_group.assert_not_called()
    own.file.delete(save=False)
