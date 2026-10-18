"""Private Telegram history never enters ordinary Agency or client-portal flows."""

from __future__ import annotations

import pytest
from django.core.exceptions import PermissionDenied
from django.test import Client, RequestFactory
from django.urls import reverse

from apps.client_portal.models import MagicLinkToken
from apps.composer.models import PlatformPost, Post
from apps.members.models import WorkspaceMembership
from apps.studio import chat
from apps.studio.models import AgencyJob, Conversation, Message, StudioBrief
from apps.telegram import conversations, provisioning
from apps.telegram.models import TelegramChat
from apps.telegram.tests.test_conversations import hub as hub
from apps.telegram.tests.test_conversations import payload

pytestmark = pytest.mark.django_db


def _studio_url(hub, name, **kwargs):
    return reverse(f"studio:{name}", kwargs={"workspace_id": hub.ws.pk, **kwargs})


def _login(hub, role, *, portal=False):
    client = Client()
    client.force_login(hub.users[role])
    if portal:
        session = client.session
        session["is_portal_session"] = True
        session["portal_workspace_id"] = str(hub.ws.pk)
        session["portal_token_id"] = str(
            MagicLinkToken.objects.create(user=hub.users[role], workspace=hub.ws, is_consumed=True).id
        )
        session.save()
    return client


def _message(conversation, body, *, author=None):
    result = Message.objects.create(
        conversation=conversation, author=author, author_kind="agent" if author is None else "staff", body=body
    )
    conversation.last_message_at = result.created_at
    conversation.save(update_fields=["last_message_at"])
    return result


@pytest.fixture
def histories(hub):
    _message(hub.client_chat.conversation, "PUBLIC CLIENT REPLY")
    _message(hub.team_chat.conversation, "PUBLIC TEAM REPLY")
    private = []
    for audience in ("internal", "client"):
        for index, lifecycle in enumerate(("active", "inactive", "orphan")):
            conversation = Conversation.objects.create(
                workspace=hub.ws,
                audience=audience,
                is_private=True,
                title=f"PRIVATE {audience} {lifecycle}",
                created_by=hub.users["owner" if audience == "internal" else "client"],
            )
            _message(conversation, f"HIDDEN SECRET {audience} {lifecycle}")
            if lifecycle != "orphan":
                role = (
                    ("owner" if index == 0 else "editor")
                    if audience == "internal"
                    else ("client" if index == 0 else "viewer")
                )
                TelegramChat.objects.create(
                    connection=hub.connection,
                    chat_id=hub.links[role].telegram_user_id,
                    chat_type="private",
                    audience="private",
                    private_user=hub.users[role],
                    conversation=conversation,
                    is_active=lifecycle == "active",
                )
            private.append(conversation)
    # An older unflagged row with an inactive private transport remains private,
    # even before a historical backfill or after an operator disables the chat.
    legacy = Conversation.objects.create(
        workspace=hub.ws, audience="client", is_private=False, title="LEGACY PRIVATE BINDING"
    )
    _message(legacy, "HIDDEN SECRET legacy binding")
    TelegramChat.objects.create(
        connection=hub.connection,
        chat_id=900001,
        chat_type="private",
        audience="private",
        private_user=hub.users["client"],
        conversation=legacy,
        is_active=False,
    )
    private.append(legacy)
    return private


def _assert_no_private_content(response, histories):
    content = response.content.decode()
    assert "HIDDEN SECRET" not in content and "LEGACY PRIVATE BINDING" not in content
    for conversation in histories:
        assert conversation.title not in content and str(conversation.pk) not in content


@pytest.mark.parametrize("role", ["owner", "editor"])
def test_agency_overview_and_thread_list_never_render_private_owner_client_or_orphan_history(hub, histories, role):
    browser = _login(hub, role)
    overview = browser.get(_studio_url(hub, "index"))
    assert overview.status_code == 200
    _assert_no_private_content(overview, histories)
    listing = browser.get(_studio_url(hub, "thread"))
    assert listing.status_code == 200
    _assert_no_private_content(listing, histories)
    assert {row["conversation"].pk for row in listing.context["rows"]} == {
        hub.client_chat.conversation_id,
        hub.team_chat.conversation_id,
    }


@pytest.mark.parametrize("role", ["owner", "editor"])
@pytest.mark.parametrize("surface", ["selection", "poll", "send"])
def test_staff_direct_uuid_routes_cannot_open_poll_or_write_any_private_history(hub, histories, role, surface):
    browser = _login(hub, role)
    before = Message.objects.count()
    for conversation in histories:
        if surface == "selection":
            response = browser.get(_studio_url(hub, "thread"), {"c": str(conversation.pk)})
        elif surface == "poll":
            response = browser.get(
                _studio_url(hub, "thread_messages", conversation_id=conversation.pk), HTTP_HX_REQUEST="true"
            )
        else:
            response = browser.post(
                _studio_url(hub, "thread_send", conversation_id=conversation.pk),
                {"body": "Ordinary web must not enter private history"},
                HTTP_HX_REQUEST="true",
            )
        assert response.status_code in {403, 404}
        _assert_no_private_content(response, histories)
    assert Message.objects.count() == before and not AgencyJob.objects.exists()


@pytest.mark.parametrize("role", ["client", "owner"])
def test_portal_default_and_list_exclude_private_client_and_internal_history_even_for_original_actor(
    hub, histories, role
):
    response = _login(hub, role, portal=True).get(reverse("client_portal:team"))
    if role == "owner":
        assert response.status_code == 302
        _assert_no_private_content(response, histories)
        return
    assert response.status_code == 200
    _assert_no_private_content(response, histories)
    assert {row["conversation"].pk for row in response.context["rows"]} == {hub.client_chat.conversation_id}
    selected = response.context["pt"]["conversation"]
    assert selected is None or selected.pk not in {conversation.pk for conversation in histories}


@pytest.mark.parametrize("role", ["client", "owner"])
@pytest.mark.parametrize("surface", ["selection", "poll", "send"])
def test_portal_direct_uuid_routes_cannot_open_poll_or_write_private_history(hub, histories, role, surface):
    browser = _login(hub, role, portal=True)
    before = Message.objects.count()
    for conversation in histories:
        if surface == "selection":
            response = browser.get(reverse("client_portal:team"), {"c": str(conversation.pk)})
        elif surface == "poll":
            response = browser.get(
                reverse("client_portal:team_messages", kwargs={"conversation_id": conversation.pk}),
                HTTP_HX_REQUEST="true",
            )
        else:
            response = browser.post(
                reverse("client_portal:team_send"),
                {"c": str(conversation.pk), "body": "Ordinary portal must not enter private history"},
                HTTP_HX_REQUEST="true",
            )
        assert response.status_code in ({302} if role == "owner" else {403, 404})
        _assert_no_private_content(response, histories)
    assert Message.objects.count() == before and not AgencyJob.objects.exists()


@pytest.mark.parametrize("audience", ["internal", "client"])
def test_general_find_create_and_default_send_start_public_thread_when_only_private_histories_exist(hub, audience):
    hub.client_chat.conversation.delete()
    hub.team_chat.conversation.delete()
    private = Conversation.objects.create(
        workspace=hub.ws, audience=audience, is_private=True, title="Telegram private conversation"
    )
    _message(private, "HIDDEN SECRET old private default")
    assert chat.find_general(hub.ws, audience=audience) is None
    actor = "owner" if audience == "internal" else "client"
    browser = _login(hub, actor, portal=audience == "client")
    url = _studio_url(hub, "thread_start") if audience == "internal" else reverse("client_portal:team_send")
    response = browser.post(url, {"body": "Public general question"}, HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    _assert_no_private_content(response, [private])
    public = chat.find_general(hub.ws, audience=audience)
    assert public is not None and public.pk != private.pk and not public.is_private
    assert chat.general_conversation(hub.ws, audience=audience).pk == public.pk
    assert Message.objects.filter(conversation=public, body="Public general question").count() == 1
    assert Message.objects.filter(conversation=private).count() == 1


@pytest.mark.parametrize("audience", ["internal", "client"])
def test_telegram_groups_are_not_selected_as_ordinary_general_thread(hub, audience):
    bound = hub.team_chat if audience == "internal" else hub.client_chat
    _message(bound.conversation, "Permitted group history")
    assert chat.find_general(hub.ws, audience=audience) is None
    public = chat.general_conversation(hub.ws, audience=audience, created_by=hub.users["owner"])
    assert public.pk != bound.conversation_id and not public.telegram_chats.exists()
    assert chat.dom_id(bound.conversation) == f"thread-{bound.conversation_id}"
    assert chat.dom_id(public) == ("thread-home" if audience == "internal" else f"thread-{public.pk}")


@pytest.mark.parametrize("audience", ["internal", "client"])
def test_post_target_finders_and_portal_cards_never_reuse_private_conversation(hub, audience):
    post = Post.objects.create(workspace=hub.ws, author=hub.users["owner"], caption="Public approved caption")
    PlatformPost.objects.create(post=post, social_account=hub.account, status="pending_client")
    private = Conversation.objects.create(
        workspace=hub.ws, audience=audience, is_private=True, post=post, title="PRIVATE POST NOTES"
    )
    _message(private, "HIDDEN SECRET post target")
    assert chat.find_conversation(hub.ws, post, audience=audience) is None
    if audience == "client":
        browser = _login(hub, "client", portal=True)
        card = browser.get(reverse("client_portal:post_thread", kwargs={"post_id": post.pk}), HTTP_HX_REQUEST="true")
        assert card.status_code == 200
        _assert_no_private_content(card, [private])
        response = browser.post(
            reverse("client_portal:post_ask", kwargs={"post_id": post.pk}),
            {"body": "A public post question"},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        _assert_no_private_content(response, [private])
        public = chat.find_conversation(hub.ws, post, audience=audience)
    else:
        public = chat.conversation_for(hub.ws, post, audience=audience, created_by=hub.users["owner"])
    assert public is not None and public.pk != private.pk and not public.is_private
    assert Message.objects.filter(conversation=private).count() == 1


def test_brief_target_find_panel_and_send_skip_private_history(hub):
    brief = StudioBrief.objects.create(
        workspace=hub.ws,
        author=hub.users["owner"],
        requested_by=hub.users["owner"],
        idea="Public brief",
        status="ready",
    )
    private = Conversation.objects.create(
        workspace=hub.ws, audience="internal", is_private=True, brief=brief, title="PRIVATE BRIEF NOTES"
    )
    _message(private, "HIDDEN SECRET brief target")
    assert chat.brief_conversation(brief) is None and chat.find_conversation(hub.ws, brief, audience="internal") is None
    browser = _login(hub, "owner")
    detail = browser.get(_studio_url(hub, "detail", brief_id=brief.pk))
    assert detail.status_code == 200
    _assert_no_private_content(detail, [private])
    sent = browser.post(
        _studio_url(hub, "brief_thread_send", brief_id=brief.pk),
        {"body": "Public brief question"},
        HTTP_HX_REQUEST="true",
    )
    assert sent.status_code == 200
    _assert_no_private_content(sent, [private])
    public = chat.brief_conversation(brief)
    assert public is not None and public.pk != private.pk and not public.is_private
    assert Message.objects.filter(conversation=private).count() == 1


@pytest.mark.parametrize("for_client", [False, True])
def test_unread_helpers_defensively_exclude_private_histories_even_from_unfiltered_callers(hub, histories, for_client):
    actor = hub.users["client" if for_client else "owner"]
    counts = chat.unread_counts(
        actor, hub.ws, list(Conversation.objects.filter(workspace=hub.ws)), for_client=for_client
    )
    assert not set(counts).intersection(conversation.pk for conversation in histories)
    assert chat.portal_unread_total(hub.users["client"], hub.ws) == 1
    response = _login(hub, "client", portal=True).get(reverse("client_portal:team_unread"))
    assert response.status_code == 200
    _assert_no_private_content(response, histories)
    assert response.context["count"] == 1


@pytest.mark.parametrize("role", ["owner", "editor", "client"])
def test_private_get_panel_and_plain_post_services_reject_direct_objects_and_stale_flags(hub, histories, role):
    before = Message.objects.count()
    factory = RequestFactory()
    for conversation in histories:
        assert chat.get_conversation(hub.ws, conversation.pk) is None
        assert chat.get_conversation(hub.ws, conversation.pk, client_only=True) is None
        # Neither a direct model object nor a cached false flag is authority.
        conversation.is_private = False
        request = factory.get("/")
        request.user = hub.users[role]
        try:
            result = chat.thread_context(request, conversation, workspace=hub.ws)
        except (PermissionDenied, chat.ChatError):
            pass
        else:
            assert result is None
        with pytest.raises(chat.ChatError):
            chat.post_message(conversation, hub.users[role], "Unsafe ordinary service call")
    assert Message.objects.count() == before and not AgencyJob.objects.exists()


def test_private_telegram_owner_still_works_and_another_paired_person_cannot_read_its_status(hub):
    private = provisioning.private_chat(hub.connection, hub.links["owner"])
    assert private.conversation.is_private
    own = payload(hub, "/brief Private creative question", role="owner", bound=private)
    own["message"]["chat"] = {"id": hub.links["owner"].telegram_user_id, "type": "private"}
    response = conversations.handle_message(hub.connection, own)
    assert (
        response["job_id"]
        and Message.objects.filter(conversation=private.conversation, author=hub.users["owner"]).count() == 1
    )
    outsider = payload(hub, "/status", role="editor", bound=private)
    outsider["message"]["chat"] = {"id": hub.links["owner"].telegram_user_id, "type": "private"}
    before = Message.objects.count()
    response = conversations.handle_message(hub.connection, outsider)
    assert "access" in response["text"] and "Private creative question" not in response["text"]
    assert Message.objects.count() == before
    assert _login(hub, "owner").get(_studio_url(hub, "thread"), {"c": str(private.conversation_id)}).status_code in {
        403,
        404,
    }


def test_role_rebound_leaves_old_orphan_and_new_private_history_hidden_from_web(hub):
    old = provisioning.private_chat(hub.connection, hub.links["owner"])
    _message(old.conversation, "HIDDEN SECRET before role rebound")
    WorkspaceMembership.objects.filter(workspace=hub.ws, user=hub.users["owner"]).update(workspace_role="client")
    current = provisioning.private_chat(hub.connection, hub.links["owner"])
    assert current.conversation_id != old.conversation_id
    old.conversation.refresh_from_db()
    assert old.conversation.is_private and not old.conversation.telegram_chats.exists()
    assert current.conversation.is_private and current.conversation.audience == "client"
    _message(current.conversation, "HIDDEN SECRET after role rebound")
    for browser, url in [
        (_login(hub, "editor"), _studio_url(hub, "thread")),
        (_login(hub, "owner", portal=True), reverse("client_portal:team")),
    ]:
        response = browser.get(url)
        assert response.status_code == 200
        _assert_no_private_content(response, [old.conversation, current.conversation])
    assert chat.find_general(hub.ws, audience="client") not in [old.conversation, current.conversation]


def test_public_group_history_remains_accessible_in_the_correct_web_surface(hub, histories):
    staff = _login(hub, "editor")
    for bound, body in [(hub.client_chat, "PUBLIC CLIENT REPLY"), (hub.team_chat, "PUBLIC TEAM REPLY")]:
        response = staff.get(_studio_url(hub, "thread"), {"c": str(bound.conversation_id)})
        assert response.status_code == 200 and body in response.content.decode()
        _assert_no_private_content(response, histories)
    response = _login(hub, "client", portal=True).get(
        reverse("client_portal:team"), {"c": str(hub.client_chat.conversation_id)}
    )
    assert response.status_code == 200 and "PUBLIC CLIENT REPLY" in response.content.decode()
    assert "PUBLIC TEAM REPLY" not in response.content.decode()
    _assert_no_private_content(response, histories)
