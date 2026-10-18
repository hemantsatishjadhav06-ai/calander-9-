"""Approval must cover the real delivery identity, including operator edits."""

from unittest.mock import patch

import pytest

from apps.approvals import gate
from apps.approvals.actor import DASHBOARD, acting_as
from apps.approvals.test_gate import _due_world
from apps.publisher.engine import PublishEngine
from apps.social_accounts.models import SocialAccount


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "changed_identity",
    [
        {"account_platform_id": "1282011328339050"},
        {"platform": "instagram"},
        {"instance_url": "https://a-different-social-server.example"},
    ],
)
def test_same_row_destination_change_after_approval_never_reaches_provider(changed_identity):
    _workspace, _approver, _post, pp = _due_world()
    SocialAccount.objects.filter(pk=pp.social_account_id).update(**changed_identity)

    with patch.object(PublishEngine, "_dispatch_to_provider") as send:
        PublishEngine().poll_and_publish()
        PublishEngine().poll_and_publish()

    send.assert_not_called()
    pp.refresh_from_db()
    assert pp.status == "failed"
    assert "changed after approval" in pp.publish_error


@pytest.mark.django_db
def test_token_refresh_and_display_name_change_preserve_the_approved_native_destination():
    _workspace, _approver, _post, pp = _due_world()
    original_stamp = pp.approved_fingerprint
    SocialAccount.objects.filter(pk=pp.social_account_id).update(
        oauth_access_token="ROTATED-OFFLINE-TOKEN", account_name="Neopolis Infra refreshed display"
    )
    fresh = type(pp).objects.select_related("social_account", "post__workspace").get(pk=pp.pk)

    assert gate.fingerprint(fresh) == original_stamp
    assert gate.publish_blocker(fresh) is None


@pytest.mark.django_db
def test_legacy_approval_without_native_identity_requires_human_reapproval():
    import hashlib
    import json

    workspace, approver, post, pp = _due_world()
    real_dumps = json.dumps

    def legacy_payload(payload, **kwargs):
        payload = dict(payload)
        payload.pop("destination_identity")
        return real_dumps(payload, **kwargs)

    with patch("apps.approvals.gate.json.dumps", side_effect=legacy_payload):
        legacy = gate.fingerprint(pp)
    assert len(legacy) == hashlib.sha256().digest_size * 2
    pp.approved_fingerprint = legacy
    assert gate.publish_blocker(pp) is not None

    from apps.approvals import services

    type(pp).objects.filter(pk=pp.pk).update(status="pending_review", approved_fingerprint=legacy)
    with acting_as(approver, DASHBOARD):
        services.approve_post(post, approver, workspace)
    fresh = type(pp).objects.select_related("social_account", "post__workspace").get(pk=pp.pk)
    assert fresh.approved_fingerprint == gate.fingerprint(fresh)
    assert gate.publish_blocker(fresh) is None
