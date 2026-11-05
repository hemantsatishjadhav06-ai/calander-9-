"""``studio:create`` answers the New post sheet (Phase 3, screen 1, T15).

A request from the sheet (``HX-Request``) gets 204 with ``HX-Redirect`` to the idea's own thread when
the idea is saved, whether or not a job started; every refusal answers 400 with its sentence alone,
which the sheet's error line shows (``base.html``'s ``data-inline-error`` writes the response's text).
Without HTMX the view behaves as it always has: ``test_agency_pages.py`` and
``test_conversation_manager.py`` pin that path, and the tests here only add the parity checks.
Past the rate limit the sheet gets 429 with a sentence of its own (T16b; screen 1's open decision 8),
and the page keeps the decorator's own refusal, the 403 page.
"""

from __future__ import annotations

import html
import re

import pytest
from django.conf import settings as django_settings
from django.contrib.messages import get_messages
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.members.models import WorkspaceMembership
from apps.studio import budget, chat, customer_workflow, engine, llm
from apps.studio.forms import BriefForm
from apps.studio.models import AgencyJob, AgencySettings, Conversation, Message, StudioBrief

NOT_CONNECTED = "Your team isn't connected yet. Ask the workspace owner to finish Set up."
ALLOWANCE_USED = "This month's allowance for the team is used up. An owner can raise it in Settings → Autopilot."
WITH_YOUR_MANAGER = "Your idea is with your manager. What we're making appears here in a moment."
TOO_MANY_SENDS = "You've sent a lot in the last minute. Try again in a moment."
IDEA = "Tell buyers about the new covered parking"
#: A money amount in any form the copy could show one.
AMOUNT = re.compile(r"[$€£]\s?\d|\d+(?:[.,]\d+)?\s?(?:USD|EUR|GBP|dollars?)\b", re.IGNORECASE)


def _url(world, name="studio:create"):
    return reverse(name, kwargs={"workspace_id": world.workspace.id})


def _post(client, world, data=None, *, htmx=True):
    payload = {"idea": IDEA, "accounts": [world.linkedin.pk]} if data is None else data
    extra = {"HTTP_HX_REQUEST": "true"} if htmx else {}
    return client.post(_url(world), payload, **extra)


def _sheet_text(response) -> str:
    """The body as the sheet's error line shows it: the HTML's text, trimmed (``base.html``'s handler)."""
    return html.unescape(re.sub(r"<[^>]*>", "", response.content.decode())).strip()


def _vendor_words() -> set[str]:
    """The model and vendor words, read from the adapters' own defaults so this file names none (invariant 9)."""
    from apps.blog import ai_images

    sources = [llm.DEFAULT_MODEL, ai_images.DEFAULT_MODEL]
    for provider in ("", "openrouter"):
        with override_settings(STUDIO_PROVIDER=provider, STUDIO_MODEL=""):
            sources += [llm.provider_name(), llm.model_id()]
    words = {word.lower() for source in sources for word in re.findall(r"[A-Za-z]{3,}", source)} - {"dev"}
    assert len(words) >= 3, words  # the defaults moved: read them again rather than pass on an empty list
    return words


def assert_plain_words(text: str) -> None:
    """No "AI", no amount, no model or vendor name (CLAUDE.md naming rules)."""
    assert not re.search(r"\bAI\b", text), text
    assert not AMOUNT.search(text), text
    lowered = text.lower()
    for word in _vendor_words():
        assert not re.search(rf"\b{re.escape(word)}\b", lowered), (word, text)


def assert_nothing_made():
    assert not Conversation.objects.exists()
    assert not Message.objects.exists()
    assert not AgencyJob.objects.exists()
    assert not StudioBrief.objects.exists()


def _client_member(world):
    user = world.viewer.__class__.objects.create_user(
        email="client@example.com", password="pw-12345678", name="Client", tos_accepted_at=timezone.now()
    )
    WorkspaceMembership.objects.create(user=user, workspace=world.workspace, workspace_role="client")
    return user


@pytest.fixture
def queued(monkeypatch):
    stages = []
    monkeypatch.setattr(engine, "enqueue", lambda job, stage: stages.append((job.pk, job.revision, stage)))
    return stages


# ---------------------------------------------------------------------------
# The idea is saved: 204 to its own thread
# ---------------------------------------------------------------------------


def test_the_sheet_sends_one_idea_to_its_own_thread_with_one_chat_job(client, world, fake_team, queued):
    client.force_login(world.editor)

    response = _post(client, world)

    assert response.status_code == 204 and response.content == b""
    conversation = Conversation.objects.get()
    assert response["HX-Redirect"] == chat.staff_thread_url(conversation)
    assert AgencyJob.objects.count() == 1
    job = AgencyJob.objects.get(kind=AgencyJob.Kind.CHAT, conversation=conversation)
    assert job.input["kind"] == "create"
    trigger = Message.objects.get(pk=job.input["message_id"], conversation=conversation)
    assert trigger.body == IDEA
    assert conversation.messages.filter(action=customer_workflow.IDEA_ACTION).count() == 1
    assert not StudioBrief.objects.exists()  # nothing is made before Go ahead
    assert [str(m) for m in get_messages(response.wsgi_request)] == [WITH_YOUR_MANAGER]
    assert queued == [(job.pk, job.revision, queued[0][2])]


def test_at_the_daily_cap_the_idea_is_saved_and_the_thread_says_why(client, world, fake_team, queued, monkeypatch):
    monkeypatch.setattr(chat, "replies_today", lambda workspace: chat.DAILY_REPLY_CAP)
    client.force_login(world.editor)

    response = _post(client, world)

    assert response.status_code == 204
    conversation = Conversation.objects.get()
    assert response["HX-Redirect"] == chat.staff_thread_url(conversation)
    assert conversation.messages.filter(action=customer_workflow.IDEA_ACTION, body=IDEA).exists()
    assert not AgencyJob.objects.exists() and not queued
    note = chat.refusal_text(world.workspace, "cap", audience=Conversation.Audience.INTERNAL)
    shown = [str(m) for m in get_messages(response.wsgi_request)]
    assert shown == [note]
    thread = client.get(response["HX-Redirect"]).content.decode()
    for text in (response.content.decode(), *shown, thread):
        assert "is with your manager" not in text


# ---------------------------------------------------------------------------
# Refusals: 400 with the sentence alone
# ---------------------------------------------------------------------------


def _not_connected(world, settings):
    settings.ANTHROPIC_API_KEY = ""


def _over_budget(world, settings):
    AgencySettings.objects.create(workspace=world.workspace, monthly_budget_usd=0)


@pytest.mark.parametrize(
    ("arrange", "expected"),
    [
        pytest.param(_not_connected, NOT_CONNECTED, id="not-connected"),
        pytest.param(_over_budget, ALLOWANCE_USED, id="over-budget"),
    ],
)
def test_a_refusal_before_the_idea_is_saved_is_its_sentence_alone(client, world, settings, queued, arrange, expected):
    arrange(world, settings)
    client.force_login(world.editor)

    response = _post(client, world)

    assert response.status_code == 400
    assert "<" not in response.content.decode()  # the sentence alone, no page around it
    assert _sheet_text(response) == expected
    assert_plain_words(response.content.decode())
    assert_nothing_made()
    assert not queued
    assert list(get_messages(response.wsgi_request)) == []  # the sheet shows it; no toast on the next page


def test_an_invalid_form_answers_with_each_error_in_the_forms_words(client, world, queued):
    client.force_login(world.editor)

    response = _post(client, world, {"idea": "", "accounts": [world.linkedin.pk]})

    assert response.status_code == 400
    assert "<" not in response.content.decode()
    assert _sheet_text(response) == "Your idea: This field is required."
    assert_plain_words(response.content.decode())
    assert_nothing_made()
    assert not queued


def test_every_error_of_an_invalid_form_is_in_the_answer_in_the_forms_order(client, world, queued):
    client.force_login(world.editor)

    response = _post(client, world, {"idea": "", "goal": "not-a-goal", "accounts": [world.linkedin.pk]})

    assert response.status_code == 400
    text = _sheet_text(response)
    form = BriefForm({"idea": "", "goal": "not-a-goal"}, workspace=world.workspace)
    form.fields.pop("accounts")
    assert not form.is_valid()
    expected = [f"{form.fields[name].label}: {error}" for name, errors in form.errors.items() for error in errors]
    assert len(expected) == 2 and text == " ".join(expected)
    assert_plain_words(text)
    assert_nothing_made()
    assert not queued


def test_a_chat_error_answers_with_its_words(client, world, queued, monkeypatch):
    def refuse(*args, **kwargs):
        raise chat.ChatError("Write a message first.")

    monkeypatch.setattr(customer_workflow, "save_idea", refuse)
    client.force_login(world.editor)

    response = _post(client, world)

    assert response.status_code == 400
    assert _sheet_text(response) == "Write a message first."
    assert_plain_words(response.content.decode())
    assert_nothing_made()
    assert not queued


def test_a_workflow_error_answers_with_its_words(client, world, queued, monkeypatch):
    def refuse(*args, **kwargs):
        raise customer_workflow.WorkflowError("That saved idea is unavailable in this workspace.")

    monkeypatch.setattr(customer_workflow, "start_idea", refuse)
    client.force_login(world.editor)

    response = _post(client, world)

    assert response.status_code == 400
    assert _sheet_text(response) == "That saved idea is unavailable in this workspace."
    assert_plain_words(response.content.decode())
    assert not AgencyJob.objects.exists() and not StudioBrief.objects.exists() and not queued


def test_the_shared_over_budget_sentence_is_unchanged_for_its_other_callers(world):
    AgencySettings.objects.create(workspace=world.workspace, monthly_budget_usd=0)

    assert budget.over_budget_message(world.workspace) == (
        f"The team has used this month's AI budget (${budget.monthly_budget(world.workspace)}). "
        "An owner can raise it under Agency → Autopilot, or it resets on the 1st."
    )


# ---------------------------------------------------------------------------
# Without HTMX nothing changes
# ---------------------------------------------------------------------------


def test_without_htmx_a_refusal_still_redirects_home_with_the_message(client, world, settings, queued):
    settings.ANTHROPIC_API_KEY = ""
    client.force_login(world.editor)

    response = _post(client, world, htmx=False)

    assert response.status_code == 302 and response["Location"] == _url(world, "studio:index")
    assert [str(m) for m in get_messages(response.wsgi_request)] == [NOT_CONNECTED]
    assert_nothing_made()


def test_without_htmx_success_still_redirects_to_the_thread(client, world, fake_team, queued):
    client.force_login(world.editor)

    response = _post(client, world, htmx=False)

    assert response.status_code == 302 and "HX-Redirect" not in response
    assert response["Location"] == chat.staff_thread_url(Conversation.objects.get())


# ---------------------------------------------------------------------------
# Who may post, and how
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("htmx", [False, True], ids=["page", "htmx"])
@pytest.mark.parametrize("who", ["viewer", "client"])
def test_a_viewer_and_a_plain_client_are_refused(client, world, queued, who, htmx):
    client.force_login(world.viewer if who == "viewer" else _client_member(world))

    response = _post(client, world, htmx=htmx)

    assert response.status_code == 403
    assert_nothing_made()
    assert not queued


@pytest.mark.parametrize("htmx", [False, True], ids=["page", "htmx"])
def test_a_signed_out_visitor_is_sent_to_sign_in(client, world, htmx):
    response = _post(client, world, htmx=htmx)

    assert response.status_code == 302
    assert response["Location"].startswith(django_settings.LOGIN_URL)
    assert_nothing_made()


@pytest.mark.parametrize("htmx", [False, True], ids=["page", "htmx"])
def test_get_is_not_allowed(client, world, htmx):
    client.force_login(world.owner)

    response = client.get(_url(world), **({"HTTP_HX_REQUEST": "true"} if htmx else {}))

    assert response.status_code == 405


# ---------------------------------------------------------------------------
# The form's words
# ---------------------------------------------------------------------------


def test_the_photo_choice_says_the_team_makes_the_picture(world, photo):
    photo(title="Tower at dusk")
    form = BriefForm(workspace=world.workspace)

    assert form.fields["source_picture"].choices[0] == ("", "The team makes the picture")
    rendered = str(form)
    assert "The team makes the picture" in rendered and "Tower at dusk" in rendered
    assert_plain_words(html.unescape(re.sub(r"<[^>]*>", " ", rendered)))


# ---------------------------------------------------------------------------
# The guards keep their order
# ---------------------------------------------------------------------------


def _spy(monkeypatch, module, name, calls, *, result=None):
    real = getattr(module, name)

    def spy(*args, **kwargs):
        calls.append(name)
        return real(*args, **kwargs) if result is None else result

    monkeypatch.setattr(module, name, spy)


def test_the_guards_run_in_their_order(client, world, fake_team, queued, monkeypatch):
    calls: list[str] = []
    _spy(monkeypatch, llm, "is_configured", calls)
    _spy(monkeypatch, budget, "can_spend", calls)
    _spy(monkeypatch, customer_workflow, "save_idea", calls)
    _spy(monkeypatch, customer_workflow, "start_idea", calls)
    client.force_login(world.editor)

    response = _post(client, world)

    assert response.status_code == 204
    firsts = [calls.index(name) for name in ("is_configured", "can_spend", "save_idea", "start_idea")]
    assert firsts == sorted(firsts), calls


def test_not_connected_stops_before_the_budget_is_read(client, world, queued, monkeypatch):
    calls: list[str] = []
    _spy(monkeypatch, llm, "is_configured", calls, result=False)
    _spy(monkeypatch, budget, "can_spend", calls)
    _spy(monkeypatch, customer_workflow, "save_idea", calls)
    client.force_login(world.editor)

    assert _post(client, world).status_code == 400
    assert calls == ["is_configured"]


def test_over_budget_stops_before_the_idea_is_saved(client, world, queued, monkeypatch):
    calls: list[str] = []
    _spy(monkeypatch, budget, "can_spend", calls, result=False)
    _spy(monkeypatch, customer_workflow, "save_idea", calls)
    client.force_login(world.editor)

    assert _post(client, world).status_code == 400
    assert calls == ["can_spend"]


@pytest.mark.parametrize(("htmx", "status"), [(False, 403), (True, 429)], ids=["page", "htmx"])
def test_the_rate_limit_comes_before_every_other_check(client, world, queued, monkeypatch, settings, htmx, status):
    settings.RATELIMIT_ENABLE = True
    cache.clear()
    calls: list[str] = []
    _spy(monkeypatch, llm, "is_configured", calls, result=False)
    client.force_login(world.editor)
    for _ in range(10):
        assert _post(client, world).status_code == 400
    calls.clear()

    response = _post(client, world, htmx=htmx)

    assert response.status_code == status
    assert calls == []
    assert_nothing_made()


# ---------------------------------------------------------------------------
# Past the rate limit: the sheet says so; the page answers as it always has
# ---------------------------------------------------------------------------


def _use_up_the_minute(client, world):
    """Ten refused Sends (an empty idea): each counts toward the limit and none makes anything."""
    for _ in range(10):
        assert _post(client, world, {"idea": "", "accounts": [world.linkedin.pk]}).status_code == 400
    assert_nothing_made()


def test_past_the_rate_limit_the_sheet_answers_429_with_one_plain_sentence(client, world, fake_team, queued, settings):
    settings.RATELIMIT_ENABLE = True
    cache.clear()
    client.force_login(world.editor)
    _use_up_the_minute(client, world)

    response = _post(client, world)  # a Send that would otherwise start the team's work

    assert response.status_code == 429
    assert "HX-Redirect" not in response
    assert "<" not in response.content.decode()  # the sentence alone, which the sheet's error line shows
    assert _sheet_text(response) == TOO_MANY_SENDS
    assert not re.search(r"\d", _sheet_text(response))  # no numbers: no rate, no count, no wait
    assert_plain_words(response.content.decode())
    assert_nothing_made()
    assert not queued
    assert list(get_messages(response.wsgi_request)) == []  # the sheet shows it; no toast on the next page


def test_past_the_rate_limit_the_page_still_answers_the_403_page(client, world, fake_team, queued, settings):
    """Without HTMX nothing changes: the decorator's refusal, rendered by the 403 page, as before T16b."""
    settings.RATELIMIT_ENABLE = True
    cache.clear()
    client.force_login(world.editor)
    _use_up_the_minute(client, world)

    response = _post(client, world, htmx=False)

    assert response.status_code == 403
    assert "403.html" in [template.name for template in response.templates]
    page = html.unescape(response.content.decode())
    assert "You don\u2019t have permission to view this page." in page
    assert TOO_MANY_SENDS not in page
    assert_nothing_made()
    assert not queued


def test_the_rate_and_its_key_are_unchanged(client, world, fake_team, queued, settings):
    """Ten Sends a minute for each person: the eleventh is refused, and another person may still send."""
    settings.RATELIMIT_ENABLE = True
    cache.clear()
    client.force_login(world.editor)
    _use_up_the_minute(client, world)
    assert _post(client, world).status_code == 429

    client.force_login(world.owner)
    response = _post(client, world)

    assert response.status_code == 204
    assert Conversation.objects.count() == 1
