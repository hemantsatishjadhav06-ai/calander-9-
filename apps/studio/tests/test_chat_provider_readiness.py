"""Missing model configuration preserves intake without futile background work."""

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.studio import chat, engine
from apps.studio.models import AgencyJob, Conversation, Message


@pytest.mark.django_db
@pytest.mark.parametrize("client_request", [False, True])
def test_missing_provider_keeps_message_and_explains_next_action(world, settings, monkeypatch, client_request):
    settings.STUDIO_PROVIDER = "openrouter"
    settings.OPENROUTER_API_KEY = ""
    settings.ANTHROPIC_API_KEY = ""
    queued = []
    monkeypatch.setattr(engine, "enqueue", lambda *args: queued.append(args))
    author = world.owner
    audience = Conversation.Audience.INTERNAL
    if client_request:
        author = User.objects.create_user(
            email="saved-client@example.com", password="test-password-123", tos_accepted_at=timezone.now()
        )
        OrgMembership.objects.create(user=author, organization=world.org, org_role="member")
        WorkspaceMembership.objects.create(user=author, workspace=world.workspace, workspace_role="client")
        audience = Conversation.Audience.CLIENT
    conversation = chat.general_conversation(world.workspace, audience=audience)

    posted = chat.post_message(conversation, author, "Please help turn our project update into a post.")

    assert Message.objects.get(pk=posted.message.pk).body == "Please help turn our project update into a post."
    assert posted.job is None
    assert not queued
    assert not AgencyJob.objects.filter(conversation=conversation).exists()
    assert "saved" in posted.note.lower()
    assert conversation.messages.filter(author_kind=Message.AuthorKind.SYSTEM, body=posted.note).exists()
    assert "OPENROUTER_API_KEY" not in posted.note and "budget" not in posted.note.lower()


@pytest.mark.django_db
def test_reading_saved_message_after_provider_setup_does_not_start_paid_work(world, settings, client):
    settings.STUDIO_PROVIDER = "openrouter"
    settings.OPENROUTER_API_KEY = ""
    conversation = chat.general_conversation(world.workspace)
    posted = chat.post_message(conversation, world.owner, "Our next idea is a project progress update.")
    assert posted.job is None
    settings.OPENROUTER_API_KEY = "controlled-test-key"
    client.force_login(world.owner)

    response = client.get(
        reverse(
            "studio:thread_messages", kwargs={"workspace_id": world.workspace.pk, "conversation_id": conversation.pk}
        )
    )

    assert response.status_code == 200
    assert not AgencyJob.objects.filter(conversation=conversation).exists()
    assert Message.objects.filter(pk=posted.message.pk).exists()
