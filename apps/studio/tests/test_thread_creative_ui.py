"""Guided creative work stays in the staff thread and behind a human confirmation.

Queue callbacks are recorded, and finished intake jobs are constructed directly.
These tests never call a source website, model provider, or image service.
"""

from __future__ import annotations

import uuid
from base64 import b64decode

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.client_portal.models import MagicLinkToken
from apps.media_library.models import MediaAsset
from apps.members.models import WorkspaceMembership
from apps.organizations.models import Organization
from apps.studio import chat, engine
from apps.studio.models import AgencyJob, Conversation, Message, StudioBrief
from apps.studio.tests.conftest import jpeg_bytes
from apps.workspaces.models import Workspace


@pytest.fixture
def jobs(monkeypatch):
    queued = []
    monkeypatch.setattr(engine, "enqueue", lambda job, stage: queued.append((job.pk, job.revision, stage)))
    return queued


@pytest.fixture
def client_user(world):
    user = User.objects.create_user(
        email="creative-client@example.com",
        password="pw-12345678",
        name="Client",
        tos_accepted_at=timezone.now(),
    )
    WorkspaceMembership.objects.create(user=user, workspace=world.workspace, workspace_role="client")
    return user


def _url(name, world, **kwargs):
    return reverse(name, kwargs={"workspace_id": world.workspace.pk, **kwargs})


def _other_workspace():
    return Workspace.objects.create(organization=Organization.objects.create(name="Other agency"), name="Other brand")


def _job(conversation, requester, *, result=None, status=AgencyJob.Status.DONE, kind=AgencyJob.Kind.CHAT):
    return AgencyJob.objects.create(
        workspace=conversation.workspace,
        conversation=conversation,
        requested_by=requester,
        kind=kind,
        status=status,
        result=result or {},
    )


def _reply(conversation, job, body="Here is the brief for you to check."):
    return Message.objects.create(
        conversation=conversation,
        author_kind=Message.AuthorKind.AGENT,
        agent="account_manager",
        job=job,
        body=body,
    )


def _complete_intake(**overrides):
    fields = {
        "topic": "Saturday's site visit",
        "goal": "leads",
        "audience": "Families looking for a home in Hyderabad",
        "key_message": "Come and see the actual site",
        "call_to_action": "Ask the team to arrange a visit",
        "channels": ["linkedin_company"],
        "visual_direction": "Use authentic photography with the brand's navy palette",
        "references": "The designer's saved creative memory",
        "constraints": "Confirm the visit date and avoid unsupported price claims",
    }
    fields.update(overrides)
    return fields


def _intake_reply(conversation, requester, *, intake=None, sources=None, awaiting_confirmation=True):
    result = {
        "creative_brief": _complete_intake() if intake is None else intake,
        "sources": sources or {},
        "awaiting_confirmation": awaiting_confirmation,
    }
    job = _job(conversation, requester, result=result)
    return _reply(conversation, job)


def _linked_brief(conversation, requester, idea="Site visit draft"):
    return StudioBrief.objects.create(
        workspace=conversation.workspace,
        author=requester,
        requested_by=requester,
        origin=StudioBrief.Origin.CHAT,
        job=_job(conversation, requester),
        idea=idea,
        status=StudioBrief.Status.READY,
    )


class TestGuidedMessageInputs:
    @pytest.mark.parametrize("style_mode", ["brand", "fresh"])
    def test_staff_can_choose_a_workspace_photo_and_style(self, world, photo, jobs, style_mode):
        conversation = chat.general_conversation(world.workspace)
        reference = photo()

        posted = chat.post_message(
            conversation,
            world.editor,
            "Use this photo for the post",
            reference_id=str(reference.pk),
            style_mode=style_mode,
        )

        assert posted.message.author_kind == Message.AuthorKind.STAFF
        assert posted.job.input["reference_id"] == str(reference.pk)
        assert posted.job.input["style_mode"] == style_mode
        assert jobs == [(posted.job.pk, 1, "answer")]

    def test_staff_can_explicitly_clear_the_photo(self, world, jobs):
        conversation = chat.general_conversation(world.workspace)
        posted = chat.post_message(conversation, world.editor, "Make a new picture", reference_id="none")
        assert posted.job.input["reference_id"] == "none"

    @pytest.mark.parametrize("reference_id", ["not-a-uuid", str(uuid.uuid4())])
    def test_invalid_photo_ids_are_rejected_before_writing(self, world, jobs, reference_id):
        conversation = chat.general_conversation(world.workspace)
        with pytest.raises(chat.ChatError, match="workspace.*media library"):
            chat.post_message(conversation, world.editor, "Use it", reference_id=reference_id)
        assert not Message.objects.exists() and not AgencyJob.objects.exists() and not jobs

    def test_a_different_workspaces_photo_is_rejected_before_writing(self, world, photo, jobs):
        conversation = chat.general_conversation(world.workspace)
        foreign = photo()
        MediaAsset.objects.filter(pk=foreign.pk).update(workspace=_other_workspace())
        with pytest.raises(chat.ChatError, match="workspace.*media library"):
            chat.post_message(conversation, world.editor, "Use it", reference_id=str(foreign.pk))
        assert not Message.objects.exists() and not AgencyJob.objects.exists() and not jobs

    @pytest.mark.parametrize(
        "media_type", [MediaAsset.MediaType.VIDEO, MediaAsset.MediaType.GIF, MediaAsset.MediaType.DOCUMENT]
    )
    def test_non_photo_assets_are_rejected_before_writing(self, world, photo, jobs, media_type):
        conversation = chat.general_conversation(world.workspace)
        reference = photo()
        MediaAsset.objects.filter(pk=reference.pk).update(media_type=media_type)
        with pytest.raises(chat.ChatError, match="workspace.*media library"):
            chat.post_message(conversation, world.editor, "Use it", reference_id=str(reference.pk))
        assert not Message.objects.exists() and not AgencyJob.objects.exists() and not jobs

    @pytest.mark.parametrize("extra", [{"reference_id": "none"}, {"style_mode": "fresh"}])
    @pytest.mark.parametrize("who", ["client", "staff_in_client_thread", "internal_note"])
    def test_graphic_choices_are_only_for_staff_creating_in_internal_threads(
        self, world, client_user, jobs, extra, who
    ):
        conversation = chat.general_conversation(
            world.workspace,
            audience=Conversation.Audience.INTERNAL if who == "internal_note" else Conversation.Audience.CLIENT,
        )
        author = client_user if who == "client" else world.editor
        with pytest.raises(chat.ChatError, match="agency team thread"):
            chat.post_message(conversation, author, "Use the fresh look", is_internal=who == "internal_note", **extra)
        assert not Message.objects.exists() and not AgencyJob.objects.exists() and not jobs

    def test_invalid_style_is_rejected_before_writing(self, world, jobs):
        conversation = chat.general_conversation(world.workspace)
        with pytest.raises(chat.ChatError, match="brand look or a fresh layout"):
            chat.post_message(conversation, world.editor, "Style it", style_mode="unrestricted")
        assert not Message.objects.exists() and not AgencyJob.objects.exists() and not jobs

    @pytest.mark.parametrize(
        "extra",
        [
            {"confirmation_message_id": str(uuid.uuid4()), "facts_confirmed": False},
            {"confirmation_message_id": "", "facts_confirmed": True},
            {"confirmation_message_id": "not-a-uuid", "facts_confirmed": True},
        ],
    )
    def test_confirmation_needs_checked_facts_and_a_valid_message_id(self, world, jobs, extra):
        conversation = chat.general_conversation(world.workspace)
        with pytest.raises(chat.ChatError):
            chat.post_message(conversation, world.editor, "Make the draft", kind="confirm_brief", **extra)
        assert not Message.objects.exists() and not AgencyJob.objects.exists() and not jobs

    @pytest.mark.parametrize(
        "audience,is_internal", [(Conversation.Audience.CLIENT, False), (Conversation.Audience.INTERNAL, True)]
    )
    def test_confirmation_cannot_be_a_client_reply_or_internal_note(self, world, jobs, audience, is_internal):
        conversation = chat.general_conversation(world.workspace, audience=audience)
        with pytest.raises(chat.ChatError, match="Check the brief"):
            chat.post_message(
                conversation,
                world.editor,
                "Make the draft",
                kind="confirm_brief",
                confirmation_message_id=str(uuid.uuid4()),
                facts_confirmed=True,
                is_internal=is_internal,
            )
        assert not Message.objects.exists() and not AgencyJob.objects.exists() and not jobs

    def test_checked_confirmation_is_queued_for_worker_validation(self, world, jobs):
        conversation = chat.general_conversation(world.workspace)
        confirmation_message_id = str(uuid.uuid4())
        posted = chat.post_message(
            conversation,
            world.editor,
            "Make the review draft",
            kind="confirm_brief",
            confirmation_message_id=confirmation_message_id,
            facts_confirmed=True,
        )
        assert posted.job.input["kind"] == "confirm_brief"
        assert posted.job.input["confirmation_message_id"] == confirmation_message_id
        assert posted.job.input["facts_confirmed"] is True
        assert not StudioBrief.objects.exists()

    @pytest.mark.parametrize(
        "mutation", [{"reference_id": "none"}, {"style_mode": "fresh"}, {"target_brief_id": str(uuid.uuid4())}]
    )
    def test_confirmation_cannot_mutate_the_creative_choices(self, world, jobs, mutation):
        conversation = chat.general_conversation(world.workspace)
        with pytest.raises(chat.ChatError, match="creative changes as a message first"):
            chat.post_message(
                conversation,
                world.editor,
                "Confirm the draft",
                kind="confirm_brief",
                confirmation_message_id=str(uuid.uuid4()),
                facts_confirmed=True,
                **mutation,
            )
        assert not Message.objects.exists() and not AgencyJob.objects.exists() and not jobs


class TestThreadDraftSelection:
    def test_staff_can_select_an_earlier_draft_from_this_thread(self, world, jobs):
        conversation = chat.general_conversation(world.workspace)
        earlier = _linked_brief(conversation, world.editor, "The earlier post")
        _linked_brief(conversation, world.editor, "The later post")

        posted = chat.post_message(
            conversation, world.editor, "Shorten the earlier caption", target_brief_id=str(earlier.pk)
        )

        assert posted.job.input["target_brief_id"] == str(earlier.pk)
        assert posted.job.conversation_id == conversation.pk
        assert jobs == [(posted.job.pk, 1, "answer")]
        conversation.refresh_from_db()
        assert conversation.brief_id is None and chat.find_general(world.workspace).pk == conversation.pk

    def test_invalid_or_unrelated_targets_are_rejected_before_writing(self, world, jobs):
        conversation = chat.general_conversation(world.workspace)
        manual = StudioBrief.objects.create(workspace=world.workspace, author=world.editor, idea="A manual brief")
        other_thread = chat.conversation_for(world.workspace, manual, audience=Conversation.Audience.INTERNAL)
        unrelated = _linked_brief(other_thread, world.editor)
        foreign = _linked_brief(chat.general_conversation(_other_workspace()), world.editor)
        original_job_count = AgencyJob.objects.count()

        for target in ("not-a-uuid", str(uuid.uuid4()), str(manual.pk), str(unrelated.pk), str(foreign.pk)):
            with pytest.raises(chat.ChatError, match="draft created in this thread"):
                chat.post_message(conversation, world.editor, "Change its caption", target_brief_id=target)

        assert not Message.objects.exists() and AgencyJob.objects.count() == original_job_count and not jobs

    def test_target_choices_are_refused_for_client_threads_and_internal_notes(self, world, jobs):
        conversation = chat.general_conversation(world.workspace)
        target = _linked_brief(conversation, world.editor)
        client_thread = chat.general_conversation(world.workspace, audience=Conversation.Audience.CLIENT)
        for thread, is_internal in ((conversation, True), (client_thread, False)):
            with pytest.raises(chat.ChatError, match="draft in the agency team thread"):
                chat.post_message(
                    thread, world.editor, "Change its caption", target_brief_id=str(target.pk), is_internal=is_internal
                )
        assert not Message.objects.exists() and AgencyJob.objects.count() == 1 and not jobs

    def test_selector_and_post_keep_multiple_drafts_in_the_original_channel(self, client, world, jobs):
        conversation = chat.general_conversation(world.workspace)
        earlier = _linked_brief(conversation, world.editor, "Earlier campaign")
        later = _linked_brief(conversation, world.editor, "Later campaign")
        foreign = _linked_brief(chat.general_conversation(_other_workspace()), world.editor, "Private campaign")
        manual = StudioBrief.objects.create(workspace=world.workspace, author=world.editor, idea="Manual campaign")
        client.force_login(world.editor)
        page = client.get(_url("studio:thread", world)).content.decode()

        assert "Draft to discuss or revise" in page and 'name="target_brief_id"' in page
        assert f'<option value="{earlier.pk}">' in page and f'<option value="{later.pk}">' in page
        assert f'<option value="{foreign.pk}">' not in page and f'<option value="{manual.pk}">' not in page

        response = client.post(
            _url("studio:thread_send", world, conversation_id=conversation.pk),
            {"body": "Shorten the earlier caption", "target_brief_id": str(earlier.pk)},
            HTTP_HX_REQUEST="true",
        )

        assert response.status_code == 200 and "Location" not in response
        queued = AgencyJob.objects.get(status=AgencyJob.Status.QUEUED)
        assert queued.input["target_brief_id"] == str(earlier.pk)
        assert queued.conversation_id == conversation.pk
        assert f'<option value="{earlier.pk}" selected>' in response.content.decode()
        conversation.refresh_from_db()
        assert conversation.brief_id is None and chat.find_general(world.workspace).pk == conversation.pk


class TestGuidedPostViews:
    def test_photo_and_style_controls_only_offer_this_workspaces_supplied_images(self, client, world, photo):
        supplied = photo(filename="authentic-site.jpg")
        generated = photo(filename="generated.jpg", source="ai-studio")
        foreign = photo(filename="private-other-brand.jpg")
        MediaAsset.objects.filter(pk=foreign.pk).update(workspace=_other_workspace())
        document = photo(filename="document.jpg")
        MediaAsset.objects.filter(pk=document.pk).update(media_type=MediaAsset.MediaType.DOCUMENT)
        client.force_login(world.editor)

        html = client.get(_url("studio:thread", world)).content.decode()

        assert f'<option value="{supplied.pk}">' in html
        for asset in (generated, foreign, document):
            assert f'<option value="{asset.pk}">' not in html
        assert 'name="reference_upload"' in html
        assert 'name="reference_id"' in html and 'name="style_mode"' in html
        assert "Match the brand series and saved best work" in html
        assert "Try a fresh layout within the brand" in html
        assert 'enctype="multipart/form-data"' in html
        assert 'hx-encoding="multipart/form-data"' in html

    def test_post_forwards_photo_style_and_request_kind(self, client, world, photo, jobs):
        client.force_login(world.editor)
        reference = photo()
        response = client.post(
            _url("studio:thread_start", world),
            {
                "body": "Use this photo and the brand look",
                "kind": "question",
                "reference_id": str(reference.pk),
                "style_mode": "brand",
            },
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        job = AgencyJob.objects.get()
        assert job.input == {
            "message_id": str(Message.objects.get(author_kind=Message.AuthorKind.STAFF).pk),
            "kind": "question",
            "reference_id": str(reference.pk),
            "style_mode": "brand",
        }

    def test_post_forwards_the_explicit_confirmation(self, client, world, jobs):
        client.force_login(world.editor)
        confirmation_message_id = str(uuid.uuid4())
        response = client.post(
            _url("studio:thread_start", world),
            {
                "body": "Make the review draft",
                "kind": "confirm_brief",
                "confirmation_message_id": confirmation_message_id,
                "facts_confirmed": "1",
            },
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        job = AgencyJob.objects.get()
        assert job.input["kind"] == "confirm_brief"
        assert job.input["confirmation_message_id"] == confirmation_message_id
        assert job.input["facts_confirmed"] is True

    @pytest.mark.parametrize("person", ["viewer", "outsider"])
    def test_people_without_create_permission_cannot_send_graphic_choices(self, client, world, jobs, person):
        client.force_login(getattr(world, person))
        response = client.post(_url("studio:thread_start", world), {"body": "Create it", "style_mode": "fresh"})
        assert response.status_code in (403, 404)
        assert not Message.objects.exists() and not AgencyJob.objects.exists() and not jobs

    def test_plain_clients_cannot_start_a_guided_team_request(self, client, world, client_user, jobs):
        client.force_login(client_user)
        response = client.post(
            _url("studio:thread_start", world), {"body": "Create it", "reference_id": "none", "style_mode": "fresh"}
        )
        assert response.status_code == 403
        assert not Message.objects.exists() and not AgencyJob.objects.exists() and not jobs

    def test_guided_forms_keep_csrf_protection(self, world, jobs):
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(world.editor)
        send_url = _url("studio:thread_start", world)

        assert browser.post(send_url, {"body": "Use the brand look", "style_mode": "brand"}).status_code == 403
        assert not Message.objects.exists() and not AgencyJob.objects.exists()

        page = browser.get(_url("studio:thread", world))
        assert page.status_code == 200
        csrf_token = browser.cookies["csrftoken"].value
        response = browser.post(
            send_url,
            {"body": "Use the brand look", "style_mode": "brand", "csrfmiddlewaretoken": csrf_token},
        )
        assert response.status_code == 302
        assert AgencyJob.objects.get().input["style_mode"] == "brand"


class TestThreadDraftPolling:
    def test_polling_continues_during_graphic_work_then_stops_for_review(self, client, world, photo):
        conversation = chat.general_conversation(world.workspace)
        job = _job(conversation, world.editor)
        graphic = photo()
        brief = StudioBrief.objects.create(
            workspace=world.workspace,
            author=world.editor,
            requested_by=world.editor,
            origin=StudioBrief.Origin.CHAT,
            job=job,
            idea="Saturday's site visit",
            status=StudioBrief.Status.WORKING,
            graphic=graphic,
            post_copy={"caption": "Visit the actual site this Saturday."},
        )
        job.result = {"brief_id": str(brief.pk)}
        job.save(update_fields=["result"])
        _reply(conversation, job, "The team is preparing your review draft.")
        client.force_login(world.editor)
        messages_url = _url("studio:thread_messages", world, conversation_id=conversation.pk)

        assert chat.has_active_job(conversation)
        working = client.get(messages_url).content.decode()
        assert 'hx-trigger="every 3s"' in working

        StudioBrief.objects.filter(pk=brief.pk).update(status=StudioBrief.Status.READY)
        ready = client.get(messages_url).content.decode()
        assert not chat.has_active_job(conversation)
        assert 'hx-trigger="every 3s"' not in ready
        assert graphic.file.url in ready
        assert "Visit the actual site this Saturday." in ready
        assert _url("studio:detail", world, brief_id=brief.pk) in ready
        conversation.refresh_from_db()
        assert conversation.brief_id is None and conversation.post_id is None and conversation.blog_post_id is None
        assert chat.find_general(world.workspace).pk == conversation.pk

    @pytest.mark.parametrize("invalid_link", ["wrong_conversation", "wrong_workspace", "not_chat"])
    def test_only_this_threads_chat_briefs_drive_polling_and_previews(self, client, world, photo, invalid_link):
        conversation = chat.general_conversation(world.workspace)
        foreign_conversation = chat.general_conversation(_other_workspace())
        job = _job(foreign_conversation if invalid_link == "wrong_conversation" else conversation, world.editor)
        brief = StudioBrief.objects.create(
            workspace=foreign_conversation.workspace if invalid_link == "wrong_workspace" else world.workspace,
            author=world.editor,
            origin=StudioBrief.Origin.MANUAL if invalid_link == "not_chat" else StudioBrief.Origin.CHAT,
            job=job,
            idea="Private draft",
            status=StudioBrief.Status.WORKING,
            graphic=photo(),
            post_copy={"caption": "Do not leak this caption."},
        )
        job.result = {"brief_id": str(brief.pk)}
        job.save(update_fields=["result"])
        # A malicious/stale result pointing to an unrelated brief must not attach a preview.
        message_job = _job(conversation, world.editor, result={"brief_id": str(brief.pk)})
        _reply(conversation, message_job)
        client.force_login(world.editor)
        html = client.get(_url("studio:thread_messages", world, conversation_id=conversation.pk)).content.decode()
        assert not chat.has_active_job(conversation)
        assert "Do not leak this caption." not in html
        assert brief.graphic.file.url not in html

    def test_client_threads_do_not_poll_or_preview_internal_graphic_work(self, client, world, client_user, photo):
        conversation = chat.general_conversation(world.workspace, audience=Conversation.Audience.CLIENT)
        job = _job(conversation, world.editor)
        graphic = photo()
        brief = StudioBrief.objects.create(
            workspace=world.workspace,
            author=world.editor,
            origin=StudioBrief.Origin.CHAT,
            job=job,
            idea="Internal campaign draft",
            status=StudioBrief.Status.WORKING,
            graphic=graphic,
            post_copy={"caption": "Agency-only unfinished caption."},
        )
        job.result = {"brief_id": str(brief.pk), "creative_brief": {"topic": "Private strategy"}}
        job.save(update_fields=["result"])
        _reply(conversation, job, "The team will follow up.")

        assert not chat.has_active_job(conversation)
        client.force_login(world.editor)
        staff_html = client.get(_url("studio:thread_messages", world, conversation_id=conversation.pk)).content.decode()
        assert "Agency-only unfinished caption." not in staff_html and graphic.file.url not in staff_html

        client.force_login(client_user)
        session = client.session
        session["is_portal_session"] = True
        session["portal_workspace_id"] = str(world.workspace.pk)
        session["portal_token_id"] = str(
            MagicLinkToken.objects.create(user=client_user, workspace=world.workspace, is_consumed=True).id
        )
        session.save()
        portal_html = client.get(
            reverse("client_portal:team_messages", kwargs={"conversation_id": conversation.pk})
        ).content.decode()
        assert "Agency-only unfinished caption." not in portal_html and graphic.file.url not in portal_html
        assert "Private strategy" not in portal_html


class TestCreativeConfirmationCards:
    def test_complete_intake_shows_one_go_ahead_button_for_its_requester(self, client, world):
        conversation = chat.general_conversation(world.workspace)
        message = _intake_reply(conversation, world.editor)
        client.force_login(world.editor)

        response = client.get(_url("studio:thread_messages", world, conversation_id=conversation.pk))

        html = response.content.decode()
        assert response.status_code == 200
        assert f'data-confirm-brief="{message.pk}"' in html
        assert f'name="confirmation_message_id" value="{message.pk}"' in html
        assert '<input type="hidden" name="facts_confirmed" value="1">' in html
        assert 'type="checkbox" name="facts_confirmed"' not in html
        assert ">Go ahead</button>" in html
        assert "You're confirming the brief and its facts. The finished post still waits for your approval." in html

    def test_only_latest_intake_for_this_person_can_be_confirmed(self, client, world):
        conversation = chat.general_conversation(world.workspace)
        stale = _intake_reply(conversation, world.editor)
        current = _intake_reply(conversation, world.editor)
        other_person = _intake_reply(conversation, world.owner)
        client.force_login(world.editor)

        html = client.get(_url("studio:thread_messages", world, conversation_id=conversation.pk)).content.decode()

        assert f'data-creative-brief="{stale.pk}"' in html
        assert f'data-confirm-brief="{current.pk}"' in html
        assert f'data-confirm-brief="{stale.pk}"' not in html
        assert f'data-confirm-brief="{other_person.pk}"' not in html
        assert html.count("data-confirm-brief=") == 1

    @pytest.mark.parametrize("status", [AgencyJob.Status.QUEUED, AgencyJob.Status.WORKING])
    def test_new_active_question_hides_confirmation_until_updated_reply(self, client, world, status):
        conversation = chat.general_conversation(world.workspace)
        message = _intake_reply(conversation, world.editor)
        _job(conversation, world.editor, status=status)
        client.force_login(world.editor)

        html = client.get(_url("studio:thread_messages", world, conversation_id=conversation.pk)).content.decode()

        assert f'data-creative-brief="{message.pk}"' in html
        assert "data-confirm-brief=" not in html
        assert 'hx-trigger="every 3s"' in html

    def test_an_intake_without_a_topic_cannot_be_confirmed(self, client, world):
        conversation = chat.general_conversation(world.workspace)
        message = _intake_reply(conversation, world.editor, intake=_complete_intake(topic=""))
        client.force_login(world.editor)

        html = client.get(_url("studio:thread_messages", world, conversation_id=conversation.pk)).content.decode()

        assert f'data-creative-brief="{message.pk}"' in html
        assert "data-confirm-brief=" not in html

    @pytest.mark.parametrize("empty_default", ["goal", "call_to_action"])
    def test_a_field_the_team_leaves_to_the_specialists_does_not_block_the_tap(self, client, world, empty_default):
        conversation = chat.general_conversation(world.workspace)
        message = _intake_reply(conversation, world.editor, intake=_complete_intake(**{empty_default: ""}))
        client.force_login(world.editor)

        html = client.get(_url("studio:thread_messages", world, conversation_id=conversation.pk)).content.decode()

        assert f'data-confirm-brief="{message.pk}"' in html

    def test_consumed_confirmation_is_not_offered_again(self, client, world):
        conversation = chat.general_conversation(world.workspace)
        message = _intake_reply(conversation, world.editor, awaiting_confirmation=False)
        client.force_login(world.editor)
        html = client.get(_url("studio:thread_messages", world, conversation_id=conversation.pk)).content.decode()
        assert f'data-creative-brief="{message.pk}"' in html
        assert "data-confirm-brief=" not in html

    @pytest.mark.parametrize("url", ["javascript:alert(document.cookie)", "data:text/html,<script>alert(1)</script>"])
    def test_source_text_is_escaped_and_untrusted_urls_are_not_linked(self, client, world, url):
        conversation = chat.general_conversation(world.workspace)
        sources = {
            "website": {
                "url": url,
                "status": "ok",
                "title": '<script>alert("source-title")</script>',
                "excerpt": '<img src=x onerror="steal()">',
                "error": "",
            },
            "channels": [
                {
                    "account_name": "<script>account()</script>",
                    "platform": "linkedin_company",
                    "posts": [{"caption": "<svg onload=channel()>", "published_at": "2026-10-11"}],
                }
            ],
            "notes": ["<iframe src=evil>"],
            "fetched_at": "2026-10-11T10:00:00+00:00",
        }
        _intake_reply(conversation, world.editor, sources=sources)
        client.force_login(world.editor)

        html = client.get(_url("studio:thread_messages", world, conversation_id=conversation.pk)).content.decode()

        assert "&lt;script&gt;alert(&quot;source-title&quot;)&lt;/script&gt;" in html
        assert "&lt;img src=x onerror=&quot;steal()&quot;&gt;" in html
        assert "&lt;svg onload=channel()&gt;" in html
        assert "&lt;iframe src=evil&gt;" in html
        assert '<script>alert("source-title")</script>' not in html
        assert 'href="javascript:' not in html and 'href="data:' not in html

    def test_https_source_link_and_caption_are_available_for_the_person_to_check(self, client, world):
        conversation = chat.general_conversation(world.workspace)
        _intake_reply(
            conversation,
            world.editor,
            sources={
                "website": {
                    "url": "https://brand.example/about",
                    "status": "ok",
                    "excerpt": "An authentic site visit.",
                },
                "channels": [
                    {"account_name": "Brand account", "platform": "x", "posts": [{"caption": "Our previous post."}]}
                ],
            },
        )
        client.force_login(world.editor)
        html = client.get(_url("studio:thread_messages", world, conversation_id=conversation.pk)).content.decode()
        assert 'href="https://brand.example/about"' in html
        assert "An authentic site visit." in html and "Our previous post." in html


class TestThreadPhotoUpload:
    def test_uploaded_photo_is_scoped_and_used_in_the_queued_message(self, client, world, jobs, monkeypatch):
        from apps.media_library import tasks

        processed = []
        monkeypatch.setattr(tasks, "process_media_asset", lambda asset_id: processed.append(asset_id))
        client.force_login(world.editor)
        upload = SimpleUploadedFile("site.jpg", jpeg_bytes(), content_type="image/jpeg")

        response = client.post(
            _url("studio:thread_start", world),
            {"body": "Use this actual site photo", "reference_upload": upload},
            HTTP_HX_REQUEST="true",
        )

        assert response.status_code == 200
        asset = MediaAsset.objects.get()
        assert asset.workspace == world.workspace and asset.organization == world.org
        assert asset.uploaded_by == world.editor and asset.media_type == MediaAsset.MediaType.IMAGE
        assert asset.source == "studio-brief-photo"
        assert AgencyJob.objects.get().input["reference_id"] == str(asset.pk)
        assert processed == [str(asset.pk)]

    @pytest.mark.parametrize(
        "filename,payload,content_type",
        [
            ("site.jpg", b"This is not a photo", "image/jpeg"),
            ("site.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', "image/svg+xml"),
            ("site.html", b"<html>not a photo</html>", "text/html"),
        ],
    )
    def test_invalid_upload_is_rejected_before_message_job_or_asset(
        self, client, world, jobs, filename, payload, content_type
    ):
        client.force_login(world.editor)
        response = client.post(
            _url("studio:thread_start", world),
            {"body": "Use it", "reference_upload": SimpleUploadedFile(filename, payload, content_type=content_type)},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        assert 'role="alert"' in response.content.decode()
        assert not MediaAsset.objects.exists() and not Message.objects.exists() and not AgencyJob.objects.exists()
        assert not jobs

    def test_valid_gif_is_rejected_before_any_asset_or_message_is_saved(self, client, world, jobs):
        # This is a real, readable 1px GIF, rather than corrupt bytes caught by ImageField.
        gif = b64decode("R0lGODlhAQABAIABAP///wAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==")
        client.force_login(world.editor)
        response = client.post(
            _url("studio:thread_start", world),
            {"body": "Use it", "reference_upload": SimpleUploadedFile("site.gif", gif, content_type="image/gif")},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        assert "JPEG, PNG or WebP" in response.content.decode()
        assert not MediaAsset.objects.exists() and not Message.objects.exists() and not AgencyJob.objects.exists()
        assert not jobs

    @pytest.mark.parametrize("extra", [{"is_internal": "1"}, {"kind": "confirm_brief", "facts_confirmed": "1"}])
    def test_upload_is_refused_in_notes_or_on_the_confirmation_click(self, client, world, jobs, extra):
        client.force_login(world.editor)
        response = client.post(
            _url("studio:thread_start", world),
            {"body": "Use it", "reference_upload": SimpleUploadedFile("site.jpg", jpeg_bytes()), **extra},
            HTTP_HX_REQUEST="true",
        )
        assert "Attach the photo in a message before confirming" in response.content.decode()
        assert not MediaAsset.objects.exists() and not Message.objects.exists() and not AgencyJob.objects.exists()

    def test_staff_upload_in_a_client_thread_is_refused(self, client, world, jobs):
        conversation = chat.general_conversation(world.workspace, audience=Conversation.Audience.CLIENT)
        client.force_login(world.editor)
        response = client.post(
            _url("studio:thread_send", world, conversation_id=conversation.pk),
            {"body": "Use it", "reference_upload": SimpleUploadedFile("site.jpg", jpeg_bytes())},
            HTTP_HX_REQUEST="true",
        )
        assert "Attach the photo in a message before confirming" in response.content.decode()
        assert not MediaAsset.objects.exists() and not Message.objects.exists() and not AgencyJob.objects.exists()

    def test_create_posts_permission_does_not_grant_upload_permission(self, client, world, jobs, monkeypatch):
        from apps.studio import views_chat

        monkeypatch.setattr(views_chat, "_perms", lambda request: {"create_posts": True, "upload_media": False})
        client.force_login(world.editor)
        response = client.post(
            _url("studio:thread_start", world),
            {"body": "Use it", "reference_upload": SimpleUploadedFile("site.jpg", jpeg_bytes())},
        )
        assert response.status_code == 403
        assert not MediaAsset.objects.exists() and not Message.objects.exists() and not AgencyJob.objects.exists()

    def test_same_thread_upload_enforces_storage_quota(self, client, world, jobs, settings):
        settings.STORAGE_QUOTA_ENABLED = True
        settings.STORAGE_QUOTA_DEFAULT = 1
        client.force_login(world.editor)
        response = client.post(
            _url("studio:thread_start", world),
            {"body": "Use it", "reference_upload": SimpleUploadedFile("site.jpg", jpeg_bytes())},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        assert "Storage quota exceeded" in response.content.decode()
        assert not MediaAsset.objects.exists() and not Message.objects.exists() and not AgencyJob.objects.exists()
