"""The client's side of the team thread, in the portal: Talk to the team, Ask the team on a post, the nav badge.

Lives with the studio tests to share their world (a workspace with staff and
accounts) and fake team.
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.composer.models import PlatformPost, Post
from apps.members.models import WorkspaceMembership
from apps.notifications.models import EventType, Notification
from apps.organizations.models import Organization
from apps.studio import chat, engine
from apps.studio.models import AgencyJob, Conversation, Message
from apps.workspaces.models import Workspace


@pytest.fixture
def client_user(world):
    user = User.objects.create_user(
        email="client@example.com", password="pw-12345678", name="Priya", tos_accepted_at=timezone.now()
    )
    WorkspaceMembership.objects.create(user=user, workspace=world.workspace, workspace_role="client")
    return user


@pytest.fixture
def jobs(monkeypatch):
    queued = []
    monkeypatch.setattr(engine, "enqueue", lambda job, stage: queued.append((job.pk, job.revision, stage)))
    return queued


def portal_login(client, user, workspace):
    client.force_login(user)
    session = client.session
    session["is_portal_session"] = True
    session["portal_workspace_id"] = str(workspace.id)
    session.save()


def _post(world, status="pending_client", caption="Site visit Saturday, 10 am to 5 pm."):
    post = Post.objects.create(workspace=world.workspace, author=world.owner, caption=caption, title="Site visit")
    PlatformPost.objects.create(post=post, social_account=world.linkedin, status=status)
    return post


def test_talk_to_the_team_page_and_first_message(client, world, jobs, client_user, django_capture_on_commit_callbacks):
    portal_login(client, client_user, world.workspace)

    page = client.get(reverse("client_portal:team"))
    assert page.status_code == 200
    html = page.content.decode()
    assert "Talk to the team" in html and reverse("client_portal:team_send") in html
    assert not Conversation.objects.exists()  # reading never creates a thread

    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(
            reverse("client_portal:team_send"), {"body": "Can we post about Diwali?"}, HTTP_HX_REQUEST="true"
        )

    assert response.status_code == 200
    conversation = Conversation.objects.get()
    assert conversation.audience == Conversation.Audience.CLIENT and conversation.workspace == world.workspace
    assert "Can we post about Diwali?" in response.content.decode()
    assert 'hx-trigger="every 5s"' in response.content.decode()
    job = AgencyJob.objects.get(kind=AgencyJob.Kind.CHAT)
    assert job.requested_by == client_user
    assert Notification.objects.filter(user=world.owner, event_type=EventType.TEAM_MESSAGE).exists()
    assert not Notification.objects.filter(user=client_user).exists()


def test_clients_never_see_internal_notes_or_other_threads(client, world, jobs, client_user):
    thread = chat.general_conversation(world.workspace, audience=Conversation.Audience.CLIENT)
    chat.post_message(thread, client_user, "Hello")
    chat.post_message(thread, world.owner, "Internal: they're late on payment", is_internal=True)
    chat.post_message(thread, world.owner, "Hi Priya, happy to help.")
    internal = chat.general_conversation(world.workspace)
    chat.post_message(internal, world.owner, "Team-only plans")
    portal_login(client, client_user, world.workspace)

    html = client.get(reverse("client_portal:team")).content.decode()
    polled = client.get(reverse("client_portal:team_messages", kwargs={"conversation_id": thread.pk})).content.decode()

    for body in (html, polled):
        assert "Hi Priya, happy to help." in body
        assert "late on payment" not in body and "Team-only plans" not in body
    assert client.get(reverse("client_portal:team") + f"?c={internal.pk}").status_code == 404
    assert (
        client.get(reverse("client_portal:team_messages", kwargs={"conversation_id": internal.pk})).status_code == 404
    )
    response = client.post(reverse("client_portal:team_send"), {"body": "x", "c": str(internal.pk)})
    assert response.status_code == 404
    assert not Message.objects.filter(conversation=internal, author=client_user).exists()


def test_another_workspaces_post_and_thread_are_not_found(client, world, jobs, client_user):
    other = Workspace.objects.create(organization=Organization.objects.create(name="Other"), name="Other")
    foreign_post = Post.objects.create(workspace=other, author=world.owner, caption="Theirs")
    PlatformPost.objects.create(post=foreign_post, social_account=world.linkedin, status="pending_client")
    foreign_thread = chat.general_conversation(other, audience=Conversation.Audience.CLIENT)
    portal_login(client, client_user, world.workspace)

    ask = reverse("client_portal:post_ask", kwargs={"post_id": foreign_post.pk})
    assert client.post(ask, {"kind": "change", "body": "Change it"}).status_code == 404
    assert client.get(reverse("client_portal:post_thread", kwargs={"post_id": foreign_post.pk})).status_code == 404
    assert (
        client.post(reverse("client_portal:team_send"), {"body": "x", "c": str(foreign_thread.pk)}).status_code == 404
    )
    assert foreign_post.platform_posts.get().status == "pending_client"
    assert not Message.objects.exists()


def test_asking_a_question_about_a_post_keeps_its_status(client, world, jobs, client_user):
    post = _post(world)
    portal_login(client, client_user, world.workspace)

    response = client.post(
        reverse("client_portal:post_ask", kwargs={"post_id": post.pk}),
        {"kind": "question", "body": "Can we say free cab pickup?"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert "portalAction" not in response["HX-Trigger"] and "showToast" in response["HX-Trigger"]
    assert post.platform_posts.get().status == "pending_client"
    conversation = Conversation.objects.get(post=post)
    assert conversation.audience == Conversation.Audience.CLIENT
    assert AgencyJob.objects.get(conversation=conversation).input["kind"] == "question"
    html = response.content.decode()
    # On the card, the card's own "Request a change" button asks for changes; the thread form only sends.
    assert f'name="d" value="post-thread-{post.pk}"' in html and 'value="change"' not in html
    poll_url = reverse("client_portal:team_messages", kwargs={"conversation_id": conversation.pk})
    assert f"{poll_url}?d=post-thread-{post.pk}" in html  # the card polls while the account manager answers
    polled = client.get(f"{poll_url}?d=post-thread-{post.pk}").content.decode()
    assert f'id="post-thread-{post.pk}-messages"' in polled
    assert 'id="team-thread-messages"' in client.get(f"{poll_url}?d=%22%3E%3Cscript%3E").content.decode()
    page = client.get(reverse("client_portal:team") + f"?c={conversation.pk}").content.decode()
    assert 'name="kind" value="change"' in page and "Site visit" in page


def test_request_a_change_records_the_clients_decision_first(client, world, jobs, client_user):
    post = _post(world)
    portal_login(client, client_user, world.workspace)

    response = client.post(
        reverse("client_portal:post_ask", kwargs={"post_id": post.pk}),
        {"kind": "change", "comment": "Warmer photo please"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200 and "portalAction" in response["HX-Trigger"]
    assert post.platform_posts.get().status == "changes_requested"
    action = post.approval_actions.get()
    assert action.action == "changes_requested" and action.channel == "portal" and action.user == client_user
    assert AgencyJob.objects.get(kind=AgencyJob.Kind.CHAT).input["kind"] == "change"


def test_an_empty_change_request_changes_nothing(client, world, jobs, client_user):
    post = _post(world)
    portal_login(client, client_user, world.workspace)

    response = client.post(
        reverse("client_portal:post_ask", kwargs={"post_id": post.pk}),
        {"kind": "change", "body": "   "},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200 and "Write a message first" in response.content.decode()
    assert post.platform_posts.get().status == "pending_client"
    assert not Message.objects.exists() and not AgencyJob.objects.exists()


def test_a_draft_post_is_not_reachable_from_the_portal(client, world, jobs, client_user):
    post = _post(world, status="draft")
    portal_login(client, client_user, world.workspace)
    response = client.post(reverse("client_portal:post_ask", kwargs={"post_id": post.pk}), {"body": "Hi"})
    assert response.status_code == 404

    # A thread about a post that went back to the team still works, through the general send.
    thread = chat.conversation_for(world.workspace, post, audience=Conversation.Audience.CLIENT)
    page = client.get(reverse("client_portal:team") + f"?c={thread.pk}").content.decode()
    assert reverse("client_portal:team_send") in page and f'name="c" value="{thread.pk}"' in page
    sent = client.post(reverse("client_portal:team_send"), {"body": "Any news?", "c": str(thread.pk)})
    assert sent.status_code == 302 and thread.messages.filter(body="Any news?").exists()


def test_the_card_offers_ask_the_team_and_loads_the_thread(client, world, jobs, client_user):
    post = _post(world)
    portal_login(client, client_user, world.workspace)

    html = client.get(reverse("client_portal:approval_queue")).content.decode()

    assert reverse("client_portal:post_thread", kwargs={"post_id": post.pk}) in html
    assert "Ask a question" in html and "Request a change" in html
    assert reverse("client_portal:post_ask", kwargs={"post_id": post.pk}) in html
    # The queue's wrapper sets hx-target/hx-select for its own refresh; the thread must not inherit them,
    # or loading it would replace the whole list with nothing.
    assert 'hx-trigger="intersect once" hx-target="this" hx-select="unset"' in html
    thread = client.get(reverse("client_portal:post_thread", kwargs={"post_id": post.pk}))
    assert thread.status_code == 200 and "Write to the team" in thread.content.decode()


def test_the_nav_badge_counts_unread_replies(client, world, jobs, client_user):
    thread = chat.general_conversation(world.workspace, audience=Conversation.Audience.CLIENT)
    chat.post_message(thread, client_user, "Hello")
    chat.post_agent_message(thread, "Hi! Happy to help.")
    portal_login(client, client_user, world.workspace)

    badge = client.get(reverse("client_portal:team_unread")).content.decode()
    assert '<span class="sr-only"> unread</span>' in badge and ">1<" in badge
    assert 'id="team-unread-mobile" hx-swap-oob="true"' in badge

    client.get(reverse("client_portal:team"))  # opening the thread marks it read
    badge = client.get(reverse("client_portal:team_unread")).content.decode()
    assert "sr-only" not in badge

    client.logout()
    assert client.get(reverse("client_portal:team_unread")).status_code == 204


def test_the_portal_nav_links_to_the_team(client, world, client_user):
    portal_login(client, client_user, world.workspace)
    html = client.get(reverse("client_portal:dashboard")).content.decode()
    assert reverse("client_portal:team") in html and reverse("client_portal:team_unread") in html


def test_a_client_who_has_not_accepted_the_terms_is_sent_there_not_swallowed(client, world, jobs):
    user = User.objects.create_user(email="new-client@example.com", password="pw-12345678", name="New")
    WorkspaceMembership.objects.create(user=user, workspace=world.workspace, workspace_role="client")
    portal_login(client, user, world.workspace)

    response = client.post(
        reverse("client_portal:team_send"),
        {"body": "Hello?"},
        HTTP_HX_REQUEST="true",
        HTTP_HX_CURRENT_URL="http://testserver/portal/team/",
    )

    assert response.status_code == 204
    assert response["HX-Redirect"] == reverse("accounts:accept_terms") + "?next=%2Fportal%2Fteam%2F"
    assert not Message.objects.exists()

    page = client.get(reverse("client_portal:team"))
    assert page.status_code == 302 and "accept-terms" in page["Location"]


def test_an_accepted_clients_htmx_post_goes_through(client, world, jobs, client_user):
    portal_login(client, client_user, world.workspace)
    response = client.post(reverse("client_portal:team_send"), {"body": "Hello?"}, HTTP_HX_REQUEST="true")
    assert response.status_code == 200 and "HX-Redirect" not in response
    assert Message.objects.filter(author=client_user).exists()


def test_the_portal_approve_toast_does_not_claim_scheduling(client, world, client_user):
    post = _post(world)
    portal_login(client, client_user, world.workspace)

    response = client.post(reverse("client_portal:approve", kwargs={"post_id": post.pk}), HTTP_HX_REQUEST="true")

    assert response.status_code == 204
    assert "scheduled to publish" not in response["HX-Trigger"]
    assert "your agency team will schedule it" in response["HX-Trigger"]
    assert post.platform_posts.get().status == "approved"


def test_portal_reports_show_the_weekly_report_and_nothing_internal(client, world, client_user):
    other_org = Organization.objects.create(name="Other agency")
    other = Workspace.objects.create(organization=other_org, name="Someone else")
    result = {
        "title": "Your week: 4 posts, one standout",
        "summary": "The site visit post did twice as well as usual.",
        "period": {"label": "2–8 Oct"},
        "went_out": {"LinkedIn": 3, "Instagram": 1},
        "sections": [
            {"kind": "best", "heading": "What worked", "body": "The site visit carousel."},
            {"kind": "internal", "heading": "Costs", "body": "We spent $4.20 on agents."},
        ],
        "cost_usd": 4.2,
    }
    now = timezone.now()
    AgencyJob.objects.create(
        workspace=world.workspace,
        kind=AgencyJob.Kind.REPORT,
        status=AgencyJob.Status.DONE,
        result=result,
        error="An internal error the client must not read",
        finished_at=now,
    )
    AgencyJob.objects.create(
        workspace=other,
        kind=AgencyJob.Kind.REPORT,
        status=AgencyJob.Status.DONE,
        result={**result, "title": "Another client's week"},
        finished_at=now,
    )
    portal_login(client, client_user, world.workspace)

    html = client.get(reverse("client_portal:reports")).content.decode()

    assert "Your week: 4 posts, one standout" in html and "twice as well as usual" in html
    assert "LinkedIn · 3 posts" in html and "Instagram · 1 post<" in html
    assert "What worked" in html and "site visit carousel" in html
    assert "Costs" not in html and "$4.20" not in html and "4.2" not in html
    assert "internal error" not in html
    assert "Another client" not in html


def test_portal_reports_say_when_there_are_none(client, world, client_user):
    portal_login(client, client_user, world.workspace)
    html = client.get(reverse("client_portal:reports")).content.decode()
    assert "No reports yet" in html
