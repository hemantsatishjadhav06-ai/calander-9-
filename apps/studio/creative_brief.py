"""Conversational intake data, separate from permission to create a draft.

The model can propose these fields. For the agency's own people the code then
fills whatever is still empty from the brand's defaults (:func:`defaults` and
:func:`complete`), so the only thing a person must supply is the topic; the
card shows which fields were defaulted so they can change them. Clients keep
the full question round (:func:`questions`). Only a person's explicit
confirmation of the stored summary — or the workspace's "go ahead" setting for
its own staff — can start work; a sentence or model flag is never consent.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Goal = Literal["", "awareness", "education", "engagement", "leads", "announcement"]
FIELDS = (
    "topic",
    "goal",
    "audience",
    "key_message",
    "call_to_action",
    "channels",
    "visual_direction",
    "references",
    "constraints",
)
REQUIRED = tuple(key for key in FIELDS if key != "constraints")
#: What a team member must supply themselves; everything else has a default.
STAFF_REQUIRED = ("topic",)
GOALS = {"awareness", "education", "engagement", "leads", "announcement"}
#: The defaults in words, for the model and the card.
DEFAULT_AUDIENCE = "The brand's usual audience"
DEFAULT_REFERENCES = "No uploaded reference; follow saved creative memory."
VISUAL_DIRECTION = {
    "brand": "Match the current brand series and its saved creative memory.",
    "fresh": "Use a fresh layout within the brand's colours and typography.",
}
LABELS = {
    "topic": "Topic",
    "goal": "Goal",
    "audience": "Audience",
    "key_message": "Key message",
    "call_to_action": "Call to action",
    "channels": "Channels",
    "visual_direction": "Visual direction",
    "references": "References",
    "constraints": "Constraints",
}


class CreativeBrief(BaseModel):
    """Every schema field is required; unknown answers are empty strings/lists."""

    model_config = ConfigDict(extra="forbid")
    topic: str = Field(description="The person's topic for this post. Empty when unknown.")
    goal: Goal = Field(description="The chosen campaign goal; empty when the person has not chosen.")
    audience: str = Field(description="Who the person wants to reach. Empty when unknown.")
    key_message: str = Field(description="The single message, from the person and supplied facts. Empty when unknown.")
    call_to_action: str = Field(description="What viewers should do. 'No CTA' when the person explicitly wants none.")
    channels: list[str] = Field(
        description="Unique platforms or exact connected account names/IDs explicitly chosen from available_channels; [] when unknown."
    )
    visual_direction: str = Field(description="The person's creative direction. Empty when unknown.")
    references: str = Field(
        description="Fresh references or saved creative memory the person wants used. Empty when unknown."
    )
    constraints: str = Field(
        description="Facts, claims, language or design restrictions; empty when none were supplied."
    )


def normalized(data) -> dict:
    if isinstance(data, BaseModel):
        data = data.model_dump()
    data = data if isinstance(data, dict) else {}
    clean: dict[str, Any] = {}
    for key in FIELDS:
        value = data.get(key)
        if key == "channels":
            clean[key] = (
                list(
                    dict.fromkeys(
                        str(item).strip().lower()[:320]
                        for item in value or []
                        if isinstance(item, str) and item.strip()
                    )
                )
                if isinstance(value, list)
                else []
            )
        else:
            clean[key] = value.strip()[:1000] if isinstance(value, str) else ""
    if clean["goal"] not in GOALS:
        clean["goal"] = ""
    return clean


def merge(previous, proposed) -> dict:
    clean = normalized(previous)
    updates = normalized(proposed)
    for key, value in updates.items():
        if value:
            clean[key] = value
    return clean


def missing(data, *, required: tuple[str, ...] = REQUIRED) -> list[str]:
    clean = normalized(data)
    return [key for key in required if not clean[key]]


def channel_label(account, accounts) -> str:
    """How a connected account is named in ``channels``: its platform when that is unique, else name, else id."""
    same_platform = [a for a in accounts if a.platform == account.platform]
    if len(same_platform) == 1:
        return account.platform
    name = (account.account_name or account.account_handle or "").strip()
    if name and sum(1 for a in accounts if (a.account_name or a.account_handle or "").strip() == name) == 1:
        return name
    return str(account.pk)


def defaults(workspace, profile, accounts, *, style_mode: str = "", memory_house_style: str = "") -> dict:
    """What the brief uses for every field the person did not mention.

    ``accounts`` are the workspace's connected studio accounts the post may go
    to. Channels default to the autopilot's accounts when it has some, else to
    all of them. The goal stays empty: the strategist decides.
    """
    from .models import AgencySettings

    accounts = list(accounts)
    row = AgencySettings.objects.filter(workspace=workspace).first()
    chosen = []
    if row is not None:
        usual = {a.pk for a in row.accounts.filter(workspace=workspace)}
        chosen = [a for a in accounts if a.pk in usual]
    chosen = chosen or accounts
    visual = VISUAL_DIRECTION["fresh" if style_mode == "fresh" else "brand"]
    house = " ".join(str(memory_house_style or "").split())[:200]
    if house:
        visual = f"{visual} House style: {house}"
    audience = " ".join(str(getattr(profile, "audience", "") or "").split())[:1000]
    return {
        "goal": "",
        "audience": audience or DEFAULT_AUDIENCE,
        "call_to_action": " ".join(str(getattr(profile, "default_cta", "") or "").split())[:1000],
        "channels": [channel_label(account, accounts) for account in chosen],
        "visual_direction": visual[:1000],
        "references": DEFAULT_REFERENCES,
    }


def complete(data, defaults_for: dict) -> tuple[dict, list[str]]:
    """Fill the empty required fields from ``defaults_for``; the key message defaults to the topic.

    Returns the completed brief and the keys that were filled, in field order,
    so the card can say "defaults you can change".
    """
    clean = normalized(data)
    filled = []
    for key in REQUIRED:
        if clean[key]:
            continue
        value = clean["topic"] if key == "key_message" else defaults_for.get(key)
        if key == "channels":
            value = [str(item) for item in value or [] if str(item).strip()]
        if not value:
            continue
        clean[key] = value
        filled.append(key)
    return normalized(clean), filled


def summary(data) -> str:
    clean = normalized(data)
    return "\n".join(
        f"{LABELS[key]}: {', '.join(clean[key]) if key == 'channels' else clean[key] or 'None specified'}"
        for key in FIELDS
    )


def questions(data, available_channels) -> str:
    absent = set(missing(data))
    groups = []
    for keys in (
        ("topic", "goal"),
        ("audience", "key_message", "call_to_action"),
        ("channels",),
        ("visual_direction", "references"),
    ):
        required = [key for key in keys if key in absent]
        if not required:
            continue
        if required == ["channels"]:
            choices = ", ".join(available_channels) or "no supported account is connected yet"
            groups.append(f"Which connected channels should this draft be made for ({choices})?")
        elif keys == ("visual_direction", "references"):
            if required == ["references"]:
                groups.append(
                    "Do you want to choose a fresh reference, use saved creative memory, or use no reference?"
                )
            elif required == ["visual_direction"]:
                groups.append("What visual direction should the designer follow?")
            else:
                groups.append(
                    "What visual direction should the designer follow, and should it use a fresh reference or saved creative memory?"
                )
        else:
            labels = [LABELS[key].lower() for key in required]
            groups.append(f"What {' and '.join(labels)} should this post use?")
    return "Before the team creates a draft, " + " ".join(groups[:3])


def latest_intake(conversation, requester, *, before=None):
    """Only this person's completed intake in this workspace/thread is reusable."""
    from .models import AgencyJob

    if requester is None:
        return None
    rows = AgencyJob.objects.filter(
        workspace_id=conversation.workspace_id,
        conversation=conversation,
        requested_by=requester,
        kind=AgencyJob.Kind.CHAT,
        status=AgencyJob.Status.DONE,
    ).order_by("-created_at", "-pk")
    if before is not None:
        rows = rows.filter(created_at__lt=before)
    for row in rows[:100]:
        if isinstance((row.result or {}).get("creative_brief"), dict):
            return row
    return None
