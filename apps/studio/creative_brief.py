"""Conversational intake data, separate from permission to create a draft.

The model can propose these fields. Only a person's explicit confirmation of
the stored summary can start work; a sentence or model flag is never consent.
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
GOALS = {"awareness", "education", "engagement", "leads", "announcement"}
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


def missing(data) -> list[str]:
    clean = normalized(data)
    return [key for key in REQUIRED if not clean[key]]


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
