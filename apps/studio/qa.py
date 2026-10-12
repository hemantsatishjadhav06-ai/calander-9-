"""The QA inspector: plain checks on a finished post, before a person sees it.

These are rules, not opinions, so they are code: the caption fits each
network, hashtags stay within the house limit, the link sits where the network
can use it, the graphic has alt text and its text is readable. Caption and
style checks are notes for the approver; measured loss of essential graphic
copy stops handoff until the team corrects the design.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from . import design

URL = re.compile(r"https?://\S+", re.IGNORECASE)
MAX_HASHTAGS = 5
INSTAGRAM_PLATFORMS = frozenset({"instagram", "instagram_login"})
MAX_PUBLICATION_TEXT_CHARS = 24000
MAX_PUBLICATION_DESTINATIONS = 24


def publication_payload(post_copy: dict[str, Any], accounts) -> list[dict[str, str]]:
    """The exact caption/comment that handoff will persist for every selected account."""
    from .pipeline import account_overrides, full_caption

    caption = full_caption(post_copy)
    first_comment = (post_copy.get("first_comment") or "").strip()
    payload = []
    for account in accounts:
        override, comment_override = account_overrides(account, caption, post_copy)
        payload.append(
            {
                "account_id": str(account.pk),
                "account_name": account.account_name,
                "account_platform_id": account.account_platform_id,
                "platform": account.platform,
                "caption": caption if override is None else override,
                "first_comment": first_comment if comment_override is None else comment_override,
            }
        )
    return sorted(payload, key=lambda row: row["account_id"])


def publication_fingerprint(payload: list[dict[str, str]], spec: dict[str, Any], graphic: bytes, revision: int) -> str:
    """Tie model review to complete outbound text, design, rendered image and brief revision."""
    evidence = {
        "payload": payload,
        "spec": spec,
        "graphic_sha256": hashlib.sha256(graphic).hexdigest(),
        "revision": revision,
    }
    return hashlib.sha256(json.dumps(evidence, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _check(name: str, passed: bool, note: str, *, warn: bool = False) -> dict[str, Any]:
    return {"name": name, "passed": passed, "level": "pass" if passed else ("warn" if warn else "fail"), "note": note}


def inspect(
    post_copy: dict[str, Any],
    spec: dict[str, Any],
    accounts,
    look: design.Look | None = None,
    *,
    render_issues: list[dict[str, Any]] | None = None,
    publication_reviewed: bool | None = None,
) -> dict[str, Any]:
    """Run every check. Returns ``{"checks": [...], "passed": int, "total": int}``."""
    from .pipeline import account_overrides, full_caption

    checks: list[dict[str, Any]] = []
    if publication_reviewed is not None:
        check = _check(
            "Final publication content reviewed",
            publication_reviewed,
            "The model reviewed the exact selected captions, comments and graphic; human approval is still required."
            if publication_reviewed
            else "The final selected captions, comments or graphic need a current review before handoff.",
        )
        check["blocks_handoff"] = not publication_reviewed
        checks.append(check)
    caption = full_caption(post_copy)
    channels = post_copy.get("channels") or {}

    for account in accounts:
        text = channels.get(account.platform) or caption
        override, _ = account_overrides(account, text, post_copy)
        final = override or text
        length = account.caption_wire_length(final)
        name = account.account_name or account.get_platform_display()
        checks.append(
            _check(
                f"Length on {name}",
                length <= account.char_limit,
                f"{length} of {account.char_limit} characters"
                + (" (the short version is used)" if override and override != text else ""),
            )
        )
        if account.platform in INSTAGRAM_PLATFORMS and URL.search(final):
            checks.append(_check(f"Links on {name}", False, "Links in Instagram captions don't click.", warn=True))

    tags = post_copy.get("hashtags") or []
    checks.append(
        _check(
            "Hashtags",
            len(tags) <= MAX_HASHTAGS,
            f"{len(tags)} hashtags (house rule: at most {MAX_HASHTAGS})",
            warn=True,
        )
    )
    first_line = (post_copy.get("caption") or "").strip().splitlines()[:1]
    hook = first_line[0] if first_line else ""
    checks.append(
        _check(
            "Hook length",
            0 < len(hook) <= 140,
            f"The first line is {len(hook)} characters (under 140 shows before '…see more')",
            warn=True,
        )
    )
    checks.append(
        _check("No hashtags in the hook", "#" not in hook, "Hashtags in the first line hide the hook", warn=True)
    )
    alt = (post_copy.get("alt_text") or "").strip()
    checks.append(
        _check("Alt text", 10 <= len(alt) <= 1000, "Describes the graphic for screen readers" if alt else "Missing")
    )
    if look is not None and spec:
        ratio = design.contrast((255, 255, 255), look.panel)
        checks.append(
            _check("Text contrast", ratio >= 4.5, f"{ratio:.1f}:1 on the brand panel (4.5:1 or more reads well)")
        )
    if render_issues is not None:
        for issue in render_issues:
            check = _check(
                f"Graphic {str(issue.get('field', 'text')).replace('_', ' ')}",
                False,
                str(issue.get("note") or "The renderer could not preserve this text."),
                warn=not issue.get("blocking", False),
            )
            check["blocks_handoff"] = bool(issue.get("blocking", False))
            checks.append(check)
        if not render_issues:
            checks.append(
                _check("Graphic text fits", True, "No text was truncated, ellipsized or omitted by the renderer.")
            )
    passed = sum(1 for c in checks if c["passed"])
    return {"checks": checks, "passed": passed, "total": len(checks)}
