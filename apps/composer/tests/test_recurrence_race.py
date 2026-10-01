"""Two workers running the recurrence cycle at once must clone each date once.

During a deploy the outgoing worker can still be mid-cycle when the incoming
one boots and clears every task lock, so both run ``run_recurrence_cycle``
together. Each holds its own copy of the rule loaded before the other wrote
the ledger.
"""

import threading
import time
from datetime import timedelta
from unittest import mock

import pytest
from django.db import connection
from django.utils import timezone

from apps.accounts.models import User
from apps.calendar import tasks
from apps.calendar.models import RecurrenceRule
from apps.composer.models import PlatformPost, Post
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace


def _rule():
    org = Organization.objects.create(name="Org")
    ws = Workspace.objects.create(organization=org, name="WS")
    user = User.objects.create_user(email="race@example.com", password="pw", tos_accepted_at=timezone.now())
    account = SocialAccount.objects.create(
        workspace=ws,
        platform="bluesky",
        account_platform_id="did:race",
        account_name="race",
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
    )
    when = timezone.now() + timedelta(days=1)
    post = Post.objects.create(workspace=ws, author=user, caption="c", scheduled_at=when)
    PlatformPost.objects.create(post=post, social_account=account, status="scheduled", scheduled_at=when)
    return RecurrenceRule.objects.create(post=post, frequency="weekly", interval=1)


@pytest.mark.django_db(transaction=True)
def test_two_workers_at_once_clone_each_date_once():
    rule = _rule()
    copies = [RecurrenceRule.objects.select_related("post__workspace").get(pk=rule.pk) for _ in range(2)]
    barrier = threading.Barrier(2)
    real_clone = tasks._clone_occurrence
    results = []

    def slow_clone(source, scheduled_dt):
        time.sleep(0.05)  # hold the row lock long enough for the other worker to collide
        return real_clone(source, scheduled_dt)

    def worker(copy):
        try:
            barrier.wait()
            results.append(tasks._generate_for_rule(copy, timezone.now()))
        finally:
            connection.close()

    with mock.patch.object(tasks, "_clone_occurrence", slow_clone):
        threads = [threading.Thread(target=worker, args=(c,)) for c in copies]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    clones = Post.objects.exclude(pk=rule.post_id)
    dates = {p.scheduled_at for p in clones}
    rule.refresh_from_db()
    assert clones.count() > 0
    assert clones.count() == len(dates) == len(rule.generated_dates) == sum(results)


@pytest.mark.django_db
def test_a_rule_deleted_mid_cycle_stops_quietly():
    rule = _rule()
    stale = RecurrenceRule.objects.select_related("post__workspace").get(pk=rule.pk)
    real_clone = tasks._clone_occurrence
    calls = []

    def clone_then_delete(source, scheduled_dt):
        real_clone(source, scheduled_dt)
        calls.append(1)
        if len(calls) == 1:
            RecurrenceRule.objects.filter(pk=rule.pk).update(is_active=False)

    with mock.patch.object(tasks, "_clone_occurrence", clone_then_delete):
        generated = tasks._generate_for_rule(stale, timezone.now())

    assert generated == 1 == len(calls)
