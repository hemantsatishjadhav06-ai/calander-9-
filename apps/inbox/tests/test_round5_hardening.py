"""Round-5 inbox and webhook findings, each pinned by the thing that went wrong.

- A poll refreshed ``extra`` wholesale and wiped ``sla_notified``, so the SLA
  sweep re-alerted every overdue message every cycle.
- A 300-character display name was a DataError that killed the account's poll.
- Backlog messages (already overdue when first seen) alerted every owner.
- Webhook rate limits were keyed on the proxy's address: one shared bucket.
- A non-ASCII signature header was a 500; a signed-but-malformed body was a 500.
- The YouTube hub GET confirmed *unsubscribe* intents; its POSTs filed the
  channel's own uploads as comments.
- A member removed from a workspace kept its messages assigned to them.
- Anyone with inbox access could discard a teammate's draft.
- An SLA target of 0 minutes was accepted.
"""

import hashlib
import hmac
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.test import RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.common.net import ratelimit_client_ip
from apps.inbox.forms import SLAConfigForm
from apps.inbox.models import InboxMessage, InboxReply, InboxSLAConfig
from apps.inbox.tasks import InboxSyncEngine
from apps.members.models import WorkspaceMembership
from apps.notifications.models import Notification

WR = WorkspaceMembership.WorkspaceRole


def _provider_message(**overrides):
    base = {
        "platform_message_id": "pm-42",
        "sender_id": "u-1",
        "sender_name": "Ada",
        "text": "hello",
        "message_type": InboxMessage.MessageType.COMMENT,
        "timestamp": timezone.now(),
        "extra": {"sender_handle": "ada"},
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.django_db
class TestUpsertKeepsLocalState:
    def test_a_repoll_keeps_sla_notified(self, inbox_account):
        engine = InboxSyncEngine()
        engine._upsert_message(inbox_account, _provider_message(), notify=False)
        row = InboxMessage.objects.get(platform_message_id="pm-42")
        row.extra["sla_notified"] = True
        row.save(update_fields=["extra"])

        engine._upsert_message(inbox_account, _provider_message(extra={"sender_handle": "ada2"}), notify=False)

        row.refresh_from_db()
        assert row.extra["sla_notified"] is True, "the poll clobbered the SLA flag"
        assert row.extra["sender_handle"] == "ada2", "provider fields must still refresh"

    def test_an_overlong_display_name_is_stored_not_raised(self, inbox_account):
        engine = InboxSyncEngine()
        engine._upsert_message(inbox_account, _provider_message(sender_name="x" * 300), notify=False)
        row = InboxMessage.objects.get(platform_message_id="pm-42")
        assert len(row.sender_name) == 255

    def test_an_overlong_avatar_url_is_dropped_not_truncated(self, inbox_account):
        engine = InboxSyncEngine()
        long_url = "https://cdn.example.com/" + "a" * 600
        engine._upsert_message(inbox_account, _provider_message(extra={"sender_avatar_url": long_url}), notify=False)
        assert InboxMessage.objects.get(platform_message_id="pm-42").sender_avatar_url == ""


@pytest.mark.django_db
class TestSlaSweep:
    @pytest.fixture
    def owner(self, inbox_workspace, user):
        WorkspaceMembership.objects.create(user=user, workspace=inbox_workspace, workspace_role=WR.OWNER)
        return user

    def _message(self, inbox_workspace, inbox_account, *, received_ago, pk="pm-sla"):
        return InboxMessage.objects.create(
            workspace=inbox_workspace,
            social_account=inbox_account,
            platform_message_id=pk,
            sender_name="Ada",
            body="hi?",
            received_at=timezone.now() - received_ago,
        )

    def test_a_message_we_could_have_answered_alerts_once(self, inbox_workspace, inbox_account, owner):
        InboxSLAConfig.objects.create(workspace=inbox_workspace, target_response_minutes=60, is_active=True)
        # Received 90 minutes ago, but seen by us 80 minutes ago: overdue on our watch.
        msg = self._message(inbox_workspace, inbox_account, received_ago=timedelta(minutes=90))
        InboxMessage.objects.filter(pk=msg.pk).update(created_at=timezone.now() - timedelta(minutes=80))

        InboxSyncEngine().check_sla()
        InboxSyncEngine().check_sla()

        assert Notification.objects.filter(user=owner, event_type="inbox_sla_overdue").count() == 1
        msg.refresh_from_db()
        assert msg.extra["sla_notified"] is True

    def test_a_backlog_message_is_flagged_without_an_alert(self, inbox_workspace, inbox_account, owner):
        InboxSLAConfig.objects.create(workspace=inbox_workspace, target_response_minutes=60, is_active=True)
        # Received three days ago, first synced just now: nobody could have met the target.
        msg = self._message(inbox_workspace, inbox_account, received_ago=timedelta(days=3))

        InboxSyncEngine().check_sla()

        assert not Notification.objects.filter(user=owner, event_type="inbox_sla_overdue").exists()
        msg.refresh_from_db()
        assert msg.extra["sla_notified"] == "backlog"

    def test_one_bad_message_does_not_stop_the_sweep(self, inbox_workspace, inbox_account, owner):
        InboxSLAConfig.objects.create(workspace=inbox_workspace, target_response_minutes=60, is_active=True)
        bad = self._message(inbox_workspace, inbox_account, received_ago=timedelta(minutes=90), pk="bad")
        good = self._message(inbox_workspace, inbox_account, received_ago=timedelta(minutes=90), pk="good")
        InboxMessage.objects.filter(pk__in=[bad.pk, good.pk]).update(created_at=timezone.now() - timedelta(minutes=80))
        original = InboxSyncEngine._notify_sla_overdue

        def flaky(self, message, config):
            if message.pk == bad.pk:
                raise RuntimeError("template exploded")
            return original(self, message, config)

        with patch.object(InboxSyncEngine, "_notify_sla_overdue", flaky):
            InboxSyncEngine().check_sla()

        good.refresh_from_db()
        bad.refresh_from_db()
        assert good.extra.get("sla_notified") is True
        assert "sla_notified" not in bad.extra, "a failed alert is retried next cycle, not marked done"

    def test_zero_minutes_is_rejected(self, inbox_workspace):
        form = SLAConfigForm(data={"target_response_minutes": 0, "is_active": True, "auto_resolve_on_reply": True})
        assert not form.is_valid()
        assert "target_response_minutes" in form.errors


class TestRateLimitKey:
    @override_settings(BB_TRUSTED_PROXIES=("10.0.0.0/8",))
    def test_the_bucket_is_the_client_behind_our_proxy(self):
        request = RequestFactory().post("/")
        request.META["REMOTE_ADDR"] = "10.0.0.1"
        request.META["HTTP_X_FORWARDED_FOR"] = "203.0.113.9"
        assert ratelimit_client_ip("g", request) == "203.0.113.9"

    @override_settings(BB_TRUSTED_PROXIES=())
    def test_without_a_trusted_proxy_the_peer_is_the_bucket(self):
        request = RequestFactory().post("/")
        request.META["REMOTE_ADDR"] = "198.51.100.7"
        request.META["HTTP_X_FORWARDED_FOR"] = "203.0.113.9"
        assert ratelimit_client_ip("g", request) == "198.51.100.7"

    @pytest.mark.django_db
    @override_settings(
        BB_TRUSTED_PROXIES=("10.0.0.0/8",),
        PLATFORM_CREDENTIALS_FROM_ENV={"instagram_login": {"app_secret": "ig-secret"}},
    )
    def test_two_clients_behind_the_edge_do_not_share_a_bucket(self, client):
        cache.clear()
        url = reverse("inbox_webhooks:webhook_instagram_login")
        body = json.dumps({"entry": []}).encode()
        signature = "sha256=" + hmac.new(b"ig-secret", body, hashlib.sha256).hexdigest()

        def post(forwarded_for):
            return client.post(
                url,
                data=body,
                content_type="application/json",
                HTTP_X_HUB_SIGNATURE_256=signature,
                REMOTE_ADDR="10.0.0.1",
                HTTP_X_FORWARDED_FOR=forwarded_for,
            )

        for _ in range(60):
            assert post("203.0.113.9").status_code == 200
        assert post("203.0.113.9").status_code == 403, "the abuser is throttled"
        assert post("198.51.100.7").status_code == 200, "Meta's own delivery still lands"
        cache.clear()


@pytest.mark.django_db
class TestWebhookInputEdges:
    @override_settings(PLATFORM_CREDENTIALS_FROM_ENV={"instagram_login": {"app_secret": "ig-secret"}})
    def test_a_non_ascii_signature_is_403_not_500(self, client):
        response = client.post(
            reverse("inbox_webhooks:webhook_instagram_login"),
            data=b"{}",
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256="sha256=dé",
        )
        assert response.status_code == 403

    @override_settings(PLATFORM_CREDENTIALS_FROM_ENV={"instagram_login": {"app_secret": "ig-secret"}})
    @pytest.mark.parametrize("body", [b"[]", b'{"entry": "nope"}', b'{"entry": [42, {"id": 7, "changes": 1}]}'])
    def test_a_signed_but_malformed_body_is_not_a_500(self, client, body):
        signature = "sha256=" + hmac.new(b"ig-secret", body, hashlib.sha256).hexdigest()
        response = client.post(
            reverse("inbox_webhooks:webhook_instagram_login"),
            data=body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=signature,
        )
        assert response.status_code in (200, 400)

    @override_settings(RESEND_WEBHOOK_SECRET="whsec_" + "AAAA")
    def test_resend_non_ascii_signature_is_403_not_500(self, client):
        response = client.post(
            reverse("resend_webhook"),
            data=b"{}",
            content_type="application/json",
            HTTP_SVIX_ID="m1",
            HTTP_SVIX_TIMESTAMP=str(int(timezone.now().timestamp())),
            HTTP_SVIX_SIGNATURE="v1,dé",
        )
        assert response.status_code == 403


@pytest.mark.django_db
class TestYouTubeHub:
    def test_only_subscribe_intents_are_confirmed(self, client):
        url = reverse("inbox_webhooks:webhook_youtube")
        ok = client.get(url, {"hub.mode": "subscribe", "hub.challenge": "c1"})
        assert ok.status_code == 200 and ok.content == b"c1"
        denied = client.get(url, {"hub.mode": "unsubscribe", "hub.challenge": "c1"})
        assert denied.status_code == 403
        assert b"c1" not in denied.content

    @override_settings(YOUTUBE_WEBHOOK_SECRET="yt-secret")
    def test_an_upload_notification_is_not_filed_as_a_comment(self, client, inbox_workspace):
        from apps.social_accounts.models import SocialAccount

        SocialAccount.objects.create(
            workspace=inbox_workspace,
            platform="youtube",
            account_platform_id="UC123",
            account_name="Channel",
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )
        body = (
            b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" '
            b'xmlns:yt="http://www.youtube.com/xml/schemas/2015"><entry>'
            b"<id>yt:video:abc</id><yt:videoId>abc</yt:videoId><yt:channelId>UC123</yt:channelId>"
            b"<title>Our new video</title></entry></feed>"
        )
        signature = "sha1=" + hmac.new(b"yt-secret", body, hashlib.sha1).hexdigest()
        response = client.post(
            reverse("inbox_webhooks:webhook_youtube"),
            data=body,
            content_type="application/atom+xml",
            HTTP_X_HUB_SIGNATURE=signature,
        )
        assert response.status_code == 200
        assert not InboxMessage.objects.filter(sender_name="YouTube").exists()

    @override_settings(YOUTUBE_WEBHOOK_SECRET="yt-secret")
    def test_a_non_ascii_signature_is_403_not_500(self, client):
        response = client.post(
            reverse("inbox_webhooks:webhook_youtube"),
            data=b"<feed/>",
            content_type="application/atom+xml",
            HTTP_X_HUB_SIGNATURE="sha1=dé",
        )
        assert response.status_code == 403


@pytest.mark.django_db
class TestAssignmentsFollowMembership:
    def test_removing_a_member_unassigns_their_messages(self, inbox_workspace, inbox_message, user):
        membership = WorkspaceMembership.objects.create(
            user=user, workspace=inbox_workspace, workspace_role=WR.CONTRIBUTOR
        )
        inbox_message.assigned_to = user
        inbox_message.save(update_fields=["assigned_to"])

        membership.delete()

        inbox_message.refresh_from_db()
        assert inbox_message.assigned_to is None

    def test_a_membership_elsewhere_is_untouched(self, inbox_workspace, inbox_message, user, organization):
        from apps.workspaces.models import Workspace

        other = Workspace.objects.create(name="Other", organization=organization)
        WorkspaceMembership.objects.create(user=user, workspace=inbox_workspace, workspace_role=WR.CONTRIBUTOR)
        elsewhere = WorkspaceMembership.objects.create(user=user, workspace=other, workspace_role=WR.CONTRIBUTOR)
        inbox_message.assigned_to = user
        inbox_message.save(update_fields=["assigned_to"])

        elsewhere.delete()

        inbox_message.refresh_from_db()
        assert inbox_message.assigned_to == user


@pytest.mark.django_db
class TestDiscardingDrafts:
    def _url(self, workspace, reply):
        return f"/workspace/{workspace.id}/inbox/replies/{reply.id}/discard/"

    @pytest.fixture
    def triage_role(self, organization):
        """A custom role that may work the inbox but not speak for the brand."""
        from apps.members.models import BUILTIN_ROLE_PERMISSIONS, CustomRole

        permissions = {**BUILTIN_ROLE_PERMISSIONS[WR.CONTRIBUTOR], "use_inbox": True, "reply_from_inbox": False}
        return CustomRole.objects.create(organization=organization, name="Triage", permissions=permissions)

    def test_a_triager_cannot_discard_a_teammates_draft(
        self, client, inbox_workspace, inbox_message, org_owner, user, django_user_model, triage_role
    ):
        author = django_user_model.objects.create_user(
            email="author@example.com", password="pw", name="Author", tos_accepted_at=timezone.now()
        )
        WorkspaceMembership.objects.create(user=author, workspace=inbox_workspace, workspace_role=WR.OWNER)
        WorkspaceMembership.objects.create(
            user=user, workspace=inbox_workspace, workspace_role=WR.CONTRIBUTOR, custom_role=triage_role
        )
        draft = InboxReply.objects.create(inbox_message=inbox_message, author=author, body="mine")
        client.force_login(user)

        response = client.post(self._url(inbox_workspace, draft))

        assert response.status_code == 403
        assert InboxReply.objects.filter(pk=draft.pk).exists()

    def test_the_author_and_a_replier_can(
        self, client, inbox_workspace, inbox_message, org_owner, user, django_user_model, triage_role
    ):
        WorkspaceMembership.objects.create(
            user=user, workspace=inbox_workspace, workspace_role=WR.CONTRIBUTOR, custom_role=triage_role
        )
        own = InboxReply.objects.create(inbox_message=inbox_message, author=user, body="mine")
        client.force_login(user)
        assert client.post(self._url(inbox_workspace, own)).status_code == 200
        assert not InboxReply.objects.filter(pk=own.pk).exists()

        manager = django_user_model.objects.create_user(
            email="mgr@example.com", password="pw", name="Mgr", tos_accepted_at=timezone.now()
        )
        WorkspaceMembership.objects.create(user=manager, workspace=inbox_workspace, workspace_role=WR.MANAGER)
        theirs = InboxReply.objects.create(inbox_message=inbox_message, author=user, body="theirs")
        client.force_login(manager)
        assert client.post(self._url(inbox_workspace, theirs)).status_code == 200
        assert not InboxReply.objects.filter(pk=theirs.pk).exists()
