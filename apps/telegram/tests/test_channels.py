"""Channel setup proves both native administrators, current authority and privacy."""

from datetime import timedelta
from unittest.mock import Mock

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.members.models import CustomRole, OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.studio.models import Conversation
from apps.telegram import processing, provisioning, tasks
from apps.telegram.models import (
    TelegramChannel,
    TelegramChannelDelivery,
    TelegramChat,
    TelegramConnection,
    TelegramUpdate,
    TelegramUserLink,
    TelegramWorkflowPrompt,
)
from apps.telegram.permissions import TelegramPermissionDenied
from apps.workspaces.models import Workspace

pytestmark = pytest.mark.django_db
TOKEN = "123456:" + "f" * 32
CHANNEL_ID = -100987654321


@pytest.fixture
def hub(organization, org_owner, monkeypatch):
    workspace = Workspace.objects.create(organization=organization, name="Channel workspace")
    member = WorkspaceMembership.objects.create(workspace=workspace, user=org_owner, workspace_role="owner")
    conn = TelegramConnection.objects.create(
        workspace=workspace,
        token=TOKEN,
        webhook_secret="test-secret",
        bot_id=123456,
        bot_username="fake_test_bot",
        is_active=True,
        webhook_status="active",
        created_by=org_owner,
    )
    link = TelegramUserLink.objects.create(connection=conn, user=org_owner, telegram_user_id=909)
    private = provisioning.private_chat(conn, link)
    api = Mock()
    api.get_me.return_value = {"id": conn.bot_id, "is_bot": True, "username": conn.bot_username}
    api.get_chat.return_value = {
        "id": CHANNEL_ID,
        "type": "channel",
        "username": "status_feed",
        "title": "Status channel",
    }
    api.get_chat_member.side_effect = lambda chat_id, user_id: (
        {"status": "administrator", "can_post_messages": True, "user": {"id": conn.bot_id, "is_bot": True}}
        if user_id == conn.bot_id
        else {"status": "creator", "user": {"id": link.telegram_user_id, "is_bot": False}}
    )
    monkeypatch.setattr(provisioning, "BotAPI", Mock(return_value=api))
    return workspace, org_owner, conn, link, private, member, api


def connect(hub, reference="@status_feed"):
    return provisioning.connect_channel(hub[2], hub[1], reference, visibility_confirmed=True)


def test_setup_requires_both_native_administrators_without_sending_or_rebinding(hub):
    workspace, user, conn, link, private, _, api = hub
    original = private.conversation_id
    channel = connect(hub)
    assert channel.connection == conn and channel.organization_id == workspace.organization_id
    assert channel.user_link == link and channel.telegram_user_id == link.telegram_user_id
    assert channel.created_by == user and channel.chat_id == CHANNEL_ID and channel.is_active
    assert channel.connection_epoch == conn.updated_at and channel.pairing_epoch == link.updated_at
    assert channel.visibility_confirmed_at and channel.authority_digest
    private.refresh_from_db()
    assert private.conversation_id == original and private.conversation.is_private
    assert not TelegramChat.objects.filter(chat_id=CHANNEL_ID).exists()
    assert not TelegramChannelDelivery.objects.exists()
    api.get_chat.assert_called_once_with("@status_feed")
    assert api.get_chat_member.call_args_list[0].args == (CHANNEL_ID, conn.bot_id)
    assert api.get_chat_member.call_args_list[1].args == (CHANNEL_ID, link.telegram_user_id)
    api.set_webhook.assert_not_called()
    api.call.assert_not_called()


@pytest.mark.parametrize("confirmed", [False, None, "on", 1])
def test_visibility_confirmation_is_explicit(hub, confirmed):
    with pytest.raises(provisioning.ProvisioningError):
        provisioning.connect_channel(hub[2], hub[1], CHANNEL_ID, visibility_confirmed=confirmed)
    hub[-1].get_me.assert_not_called()


@pytest.mark.parametrize(
    "reference", [True, 0, 909, "https://t.me/status_feed", "@bad", "-9223372036854775808", {}, "-0"]
)
def test_invalid_channel_reference_is_local_only(hub, reference):
    with pytest.raises(provisioning.ProvisioningError):
        connect(hub, reference)
    hub[-1].get_me.assert_not_called()


@pytest.mark.parametrize("kind", ["private", "supergroup", "group"])
def test_other_chat_types_cannot_be_connected_as_broadcast_channels(hub, kind):
    hub[-1].get_chat.return_value["type"] = kind
    with pytest.raises(provisioning.ProvisioningError):
        connect(hub)
    assert not TelegramChannel.objects.exists()


@pytest.mark.parametrize("change", [{"id": True}, {"id": -1}, {"is_bot": False}, {"username": "foreign_bot"}])
def test_wrong_bot_identity_cannot_authorize_channel(hub, change):
    hub[-1].get_me.return_value.update(change)
    with pytest.raises(provisioning.ProvisioningError):
        connect(hub)
    assert not TelegramChannel.objects.exists()


@pytest.mark.parametrize(
    "change",
    [
        {"can_post_messages": False},
        {"can_post_messages": "true"},
        {"status": "member"},
        {"user": {"id": 123456, "is_bot": False}},
    ],
)
def test_bot_requires_actual_post_messages_privilege(hub, change):
    conn, link, api = hub[2], hub[3], hub[-1]
    bot = {"status": "administrator", "can_post_messages": True, "user": {"id": conn.bot_id, "is_bot": True}}
    bot.update(change)
    api.get_chat_member.side_effect = lambda chat_id, user_id: (
        bot if user_id == conn.bot_id else {"status": "creator", "user": {"id": link.telegram_user_id, "is_bot": False}}
    )
    with pytest.raises(provisioning.ProvisioningError):
        connect(hub)
    assert not TelegramChannel.objects.exists()


@pytest.mark.parametrize(
    "actor",
    [
        {"status": "member", "user": {"id": 909, "is_bot": False}},
        {"status": "administrator", "user": {"id": 910, "is_bot": False}},
        {"status": "creator", "user": {"id": 909, "is_bot": True}},
        {"status": "creator", "user": {"id": True, "is_bot": False}},
    ],
)
def test_channel_query_does_not_prove_the_paired_person_is_an_admin(hub, actor):
    api, original = hub[-1], hub[-1].get_chat_member.side_effect
    api.get_chat_member.side_effect = lambda chat_id, user_id: (
        original(chat_id, user_id) if user_id == hub[2].bot_id else actor
    )
    with pytest.raises(TelegramPermissionDenied):
        connect(hub)
    assert not TelegramChannel.objects.exists()


@pytest.mark.parametrize("which", ["private", "link", "bot", "user", "org", "member"])
def test_inactive_or_removed_authority_cannot_verify_a_channel(hub, which):
    workspace, user, conn, link, private, member, api = hub
    if which == "private":
        TelegramChat.objects.filter(pk=private.pk).update(is_active=False)
    elif which == "link":
        TelegramUserLink.objects.filter(pk=link.pk).update(is_active=False)
    elif which == "bot":
        TelegramConnection.objects.filter(pk=conn.pk).update(is_active=False)
    elif which == "user":
        User.objects.filter(pk=user.pk).update(is_active=False)
    elif which == "org":
        OrgMembership.objects.filter(organization=workspace.organization, user=user).delete()
    else:
        member.delete()
    with pytest.raises((TelegramPermissionDenied, provisioning.ProvisioningError)):
        connect(hub)
    api.get_me.assert_not_called()


@pytest.mark.parametrize("change", ["pairing", "connection", "role", "org_membership"])
def test_authority_changes_during_native_verification_reject_the_result(hub, change):
    workspace, user, conn, link, _, member, api = hub
    original = api.get_chat_member.side_effect

    def mutate(chat_id, user_id):
        result = original(chat_id, user_id)
        if user_id == link.telegram_user_id:
            if change == "pairing":
                link.save()
            elif change == "connection":
                conn.save()
            elif change == "role":
                member.workspace_role = "viewer"
                member.save()
            else:
                OrgMembership.objects.filter(organization=workspace.organization, user=user).delete()
                OrgMembership.objects.create(organization=workspace.organization, user=user, org_role="owner")
        return result

    api.get_chat_member.side_effect = mutate
    with pytest.raises(TelegramPermissionDenied):
        connect(hub)
    assert not TelegramChannel.objects.exists()


def test_settings_manager_custom_role_can_connect_but_client_facing_cannot(hub):
    workspace, _, _, _, _, member, _ = hub
    role = CustomRole.objects.create(
        organization=workspace.organization, name="Settings", permissions={"manage_workspace_settings": True}
    )
    member.workspace_role, member.custom_role = "editor", role
    member.save()
    assert connect(hub).is_active
    role.permissions["client_facing"] = True
    role.save()
    with pytest.raises(TelegramPermissionDenied):
        connect(hub)


def test_channel_global_ownership_does_not_transfer_even_after_disabled(hub):
    old = connect(hub)
    provisioning.disconnect_channel(hub[2], hub[1], old.pk)
    another = Workspace.objects.create(organization=hub[0].organization, name="Other tenant")
    WorkspaceMembership.objects.create(workspace=another, user=hub[1], workspace_role="owner")
    conn = TelegramConnection.objects.create(
        workspace=another,
        token="456789:" + "g" * 32,
        bot_id=456789,
        bot_username="second_bot",
        webhook_status="active",
        is_active=True,
    )
    link = TelegramUserLink.objects.create(connection=conn, user=hub[1], telegram_user_id=909)
    provisioning.private_chat(conn, link)
    api = hub[-1]
    api.get_me.return_value = {"id": conn.bot_id, "is_bot": True, "username": conn.bot_username}
    api.get_chat_member.side_effect = lambda chat_id, user_id: {
        "status": "administrator",
        "can_post_messages": True,
        "user": {"id": user_id, "is_bot": user_id == conn.bot_id},
    }
    with pytest.raises(provisioning.ProvisioningError, match="another workspace"):
        provisioning.connect_channel(conn, hub[1], "@status_feed", visibility_confirmed=True)
    old.refresh_from_db()
    assert not old.is_active and old.connection_id == hub[2].pk


@pytest.mark.parametrize("action", ["disconnect", "bot_disconnect", "unpair", "private_disable", "reverify"])
def test_revocation_and_reverification_hold_old_status_intents(hub, action):
    channel = connect(hub)
    pending = TelegramChannelDelivery.objects.create(channel=channel, source_key="pending", payload={})
    sending = TelegramChannelDelivery.objects.create(
        channel=channel, source_key="sending", payload={}, status="sending"
    )
    if action == "disconnect":
        provisioning.disconnect_channel(hub[2], hub[1], channel.pk)
    elif action == "bot_disconnect":
        provisioning.disconnect(hub[2], hub[1])
    elif action == "unpair":
        provisioning.unpair(hub[2], hub[1])
    elif action == "private_disable":
        provisioning.deactivate_chat(hub[2], hub[1], hub[4].pk)
    else:
        connect(hub)
    pending.refresh_from_db()
    sending.refresh_from_db()
    channel.refresh_from_db()
    assert pending.status == "failed" and sending.status == "unknown"
    assert channel.is_active == (action == "reverify")


def test_unrelated_group_disable_preserves_status_channel(hub):
    channel = connect(hub)
    conversation = Conversation.objects.create(workspace=hub[0], created_by=hub[1], audience="internal")
    group = TelegramChat.objects.create(
        connection=hub[2], chat_id=-100345, chat_type="supergroup", audience="team", conversation=conversation
    )
    provisioning.deactivate_chat(hub[2], hub[1], group.pk)
    channel.refresh_from_db()
    assert channel.is_active


def lifecycle(hub, channel, *, bot_id=None, rights=False):
    return TelegramUpdate.objects.create(
        connection=hub[2],
        update_id=999,
        payload={
            "my_chat_member": {
                "chat": {"id": channel.chat_id, "type": "channel"},
                "new_chat_member": {
                    "user": {"id": bot_id or hub[2].bot_id},
                    "status": "administrator",
                    "can_post_messages": rights,
                },
            },
        },
    )


def test_lost_posting_rights_promptly_disable_channel_and_hold_inflight_send(hub):
    channel = connect(hub)
    sending = TelegramChannelDelivery.objects.create(
        channel=channel, source_key="inflight", payload={}, status="sending"
    )
    assert processing._lifecycle(lifecycle(hub, channel))
    channel.refresh_from_db()
    sending.refresh_from_db()
    assert not channel.is_active and sending.status == "unknown"


@pytest.mark.parametrize("kind", ["foreign_bot", "stale", "retained"])
def test_foreign_stale_or_retained_permission_update_cannot_revoke_channel(hub, kind):
    channel = connect(hub)
    row = lifecycle(hub, channel, bot_id=333 if kind == "foreign_bot" else None, rights=kind == "retained")
    if kind == "stale":
        TelegramUpdate.objects.filter(pk=row.pk).update(created_at=channel.updated_at - timedelta(seconds=1))
        row.refresh_from_db()
    processing._lifecycle(row)
    channel.refresh_from_db()
    assert channel.is_active


def test_settings_guides_channel_setup_without_native_reads_and_post_connects(hub):
    client = Client()
    client.force_login(hub[1])
    url = reverse("telegram:settings", kwargs={"workspace_id": hub[0].pk})
    result = client.get(url)
    assert result.status_code == 200 and b"Broadcast channel (optional)" in result.content
    assert b"Captions, costs and buttons never go there." in result.content
    assert TOKEN.encode() not in result.content and result["Cache-Control"] == "no-store"
    hub[-1].get_me.assert_not_called()
    result = client.post(
        reverse("telegram:connect_channel", kwargs={"workspace_id": hub[0].pk}),
        {"channel_reference": "@status_feed", "visibility_confirmed": "on"},
    )
    assert result.status_code == 302 and TelegramChannel.objects.count() == 1


def test_client_cannot_see_or_post_channel_settings(hub):
    channel = connect(hub)
    client_user = User.objects.create_user(email="client@channel.test", password="test", tos_accepted_at=timezone.now())
    WorkspaceMembership.objects.create(workspace=hub[0], user=client_user, workspace_role="client")
    client = Client()
    client.force_login(client_user)
    result = client.get(reverse("telegram:settings", kwargs={"workspace_id": hub[0].pk}))
    assert (
        result.status_code == 200
        and b"telegram-channel-setup" not in result.content
        and channel.title.encode() not in result.content
    )
    result = client.post(
        reverse("telegram:connect_channel", kwargs={"workspace_id": hub[0].pk}),
        {"channel_reference": "@status_feed", "visibility_confirmed": "on"},
    )
    assert result.status_code == 403


def test_channel_post_requires_csrf_and_safe_error_does_not_echo_credentials(hub):
    client = Client(enforce_csrf_checks=True)
    client.force_login(hub[1])
    url = reverse("telegram:connect_channel", kwargs={"workspace_id": hub[0].pk})
    assert client.post(url, {"channel_reference": "@status_feed", "visibility_confirmed": "on"}).status_code == 403
    client = Client()
    client.force_login(hub[1])
    hub[-1].get_chat.side_effect = ValueError(TOKEN)
    result = client.post(url, {"channel_reference": "@status_feed", "visibility_confirmed": "on"})
    assert result.status_code == 400 and TOKEN.encode() not in result.content


def test_original_organization_channel_metadata_stays_hidden_after_workspace_moves(hub):
    workspace, user, conn = hub[:3]
    channel = connect(hub)
    TelegramChannelDelivery.objects.create(
        channel=channel, source_key="old", payload={}, status="failed", error="original org failure"
    )
    other = Organization.objects.create(name="New organization")
    OrgMembership.objects.create(organization=other, user=user, org_role="owner")
    workspace.organization = other
    workspace.save()
    client = Client()
    client.force_login(user)
    result = client.get(reverse("telegram:settings", kwargs={"workspace_id": workspace.pk}))
    assert result.status_code == 200
    assert channel.title.encode() not in result.content and channel.username.encode() not in result.content
    assert b"original org failure" not in result.content
    with pytest.raises(provisioning.ProvisioningError):
        provisioning.disconnect_channel(conn, user, channel.pk)
    with pytest.raises(provisioning.ProvisioningError):
        connect(hub)


def test_retention_clears_expired_channel_and_prompt_content_without_resetting_outcome(hub):
    channel = connect(hub)
    old = timezone.now() - timedelta(days=32)
    delivery = TelegramChannelDelivery.objects.create(
        channel=channel,
        source_key="retained-hold",
        status="unknown",
        payload={"text": "old fixed status"},
        native_message_id=44,
    )
    TelegramChannelDelivery.objects.filter(pk=delivery.pk).update(updated_at=old)
    prompt = TelegramWorkflowPrompt.objects.create(
        conversation=hub[4].conversation,
        workspace=hub[0],
        organization=hub[0].organization,
        author=hub[1],
        user_link=hub[3],
        chat=hub[4],
        source_key="old-bridge-question",
        snapshot={"question": "old private question"},
        expires_at=old,
        consumed_at=old,
    )
    assert tasks.cleanup_transient_records() == 2
    delivery.refresh_from_db()
    prompt.refresh_from_db()
    assert delivery.status == "unknown" and delivery.native_message_id == 44 and delivery.payload == {}
    assert prompt.snapshot == {} and prompt.consumed_at == old
    assert tasks.cleanup_transient_records() == 0
