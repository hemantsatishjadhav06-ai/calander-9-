"""The brand profile a workspace starts with.

The two brand workspaces (``apps.workspaces.brands``) start from what their own
websites say — the same verified facts the seeded drafts in
``apps.workspaces.brand_content`` were written from — and from the look their
blog covers already use (``apps.blog.covers.BRANDS``). Any other workspace
starts from its name, description, colours and default hashtags. Everything is
editable in Studio → Brand profile; nothing here is re-applied over edits.
"""

from __future__ import annotations

from typing import Any

#: Rules that keep real-estate posts honest; stated as rules, not facts.
_REAL_ESTATE_COMPLIANCE = (
    "Never promise returns, appreciation, rental yield or 'guaranteed' anything.\n"
    "Quote a price, discount, size, unit count or date only when it appears in the facts.\n"
    "Do not call a project RERA-registered unless its registration number is in the facts.\n"
    "No 'best', 'No. 1' or 'cheapest' claims that cannot be checked."
)

BRAND_PROFILES: dict[str, dict[str, Any]] = {
    "neopolis": {
        "brand_name": "Neopolis Infra",
        "about": "Neopolis Infra LLP deals only in landlord-share flats in West Hyderabad, priced direct.",
        "audience": (
            "Home buyers and investors in Hyderabad looking at premium flats in the western corridors — "
            "often IT professionals and families who want a fair price and clean paperwork."
        ),
        "voice": (
            "Plain-spoken and trustworthy. Explains before it sells. Short sentences, concrete facts, "
            "no hype and no exclamation marks. Sounds like a knowledgeable local advisor."
        ),
        "facts": (
            "A landlord's share is the landowner's allocation of finished flats in a joint development: same "
            "tower, same specification and amenities as the developer's units.\n"
            "Landlord shares are typically 8–14% under comparable resale (the actual difference depends on the "
            "flat, floor and negotiation).\n"
            "After registration, a landlord-share flat is legally identical to any other flat in the project.\n"
            "Every share Neopolis shows is title-verified first: clear marketable title, a registered development "
            "agreement, approved plans and the owner's flat allocation in writing, no competing claims.\n"
            "Corridors: Kokapet (financial-district edge), Narsingi (ORR connectivity), Neopolis (planned layout), "
            "Manchirevula (lake views), Tellapur (IT-corridor proximity), Kollur (value entry).\n"
            "Contact: WhatsApp or call +91 95336 86567, Mon–Sun 9 AM–9 PM.\n"
            "How the share works: https://www.neopolisinfra.com/#/the-share\n"
            "Projects: https://www.neopolisinfra.com/projects/\n"
            "Documents checklist: https://www.neopolisinfra.com/blog/property-documents-verification-checklist-hyderabad-2026"
        ),
        "dos": "Lead with the buyer's question. Name the corridor. Invite a WhatsApp or call.",
        "donts": "No investment-return promises. No pressure tactics or fake urgency. No emojis in the first line.",
        "compliance": _REAL_ESTATE_COMPLIANCE,
        "default_cta": "WhatsApp or call +91 95336 86567",
        "website": "https://www.neopolisinfra.com",
        "hashtags": ["#LandlordShare", "#WestHyderabad", "#HyderabadRealEstate", "#NeopolisInfra"],
        "primary_color": "#081D4A",
        "accent_color": "#FF6600",
        "display_font": "oswald",
        "wordmark": "NEOPOLIS INFRA",
        "domain": "neopolisinfra.com",
        "photo_style": (
            "Architectural photograph of modern residential towers in West Hyderabad (Kokapet, Narsingi, "
            "Financial District skyline) at blue hour, long exposure, glass and concrete, cool crisp light, "
            "premium and believable"
        ),
        "default_template": "editorial",
        "default_format": "portrait",
        "default_grade": "brand_tint",
    },
    "morespace": {
        "brand_name": "More Space",
        "about": "More Space helps buyers into premium high-rise homes in Hyderabad through three routes.",
        "audience": (
            "Families and professionals buying a premium home in Hyderabad, and investors comparing "
            "under-construction and resale options."
        ),
        "voice": (
            "Warm, confident and clear. Aspirational but honest — the lifestyle, then the facts. "
            "Friendly sentences, no jargon, no hard sell."
        ),
        "facts": (
            "Three routes: Landlord Shares (early access to landlord-held units in under-construction and "
            "pre-launch phases), Investor Flats (resale of units acquired by early-stage investors), Builder "
            "Inventory (select premium units marketed directly with reputed developers).\n"
            "Upcoming launch: Soul of Earth, Kukatpally — 25 acres, 11 towers, an 8-acre Central-Park-inspired "
            "courtyard, 3 & 4 BHK Vastu homes, 3 clubhouses. https://morespace.netlify.app/kukatpally.html\n"
            "Rajendra Nagar (Gaganpahad), now accepting EOI: two prelaunch gated communities — 8 acres (724 "
            "units) and 13 acres (9 towers, G+33) — minutes from the PVNR Expressway. "
            "https://morespace.netlify.app/rajendra-nagar.html\n"
            "How we work: transparency first; data-driven advice; personal attention from first visit to "
            "handover.\n"
            "Contact: WhatsApp +91 70751 68306. Consultations: https://morespace.netlify.app/contact.html"
        ),
        "dos": "Paint the home, then give the facts. One clear next step.",
        "donts": "No investment-return promises. No fake scarcity. No more than two emojis.",
        "compliance": _REAL_ESTATE_COMPLIANCE,
        "default_cta": "WhatsApp +91 70751 68306",
        "website": "https://morespace.netlify.app",
        "hashtags": ["#HyderabadRealEstate", "#HyderabadHomes", "#MoreSpace"],
        "primary_color": "#2D236D",
        "accent_color": "#0300C7",
        "display_font": "outfit",
        "wordmark": "MORE SPACE",
        "domain": "morespace.netlify.app",
        "photo_style": (
            "Bright, airy lifestyle photograph of premium high-rise residences in Hyderabad — glass towers, "
            "rooftop views, landscaped podiums, sunlit interiors — golden-hour warmth, aspirational but believable"
        ),
        "default_template": "split",
        "default_format": "portrait",
        "default_grade": "natural",
    },
}

_GENERIC_PHOTO_STYLE = (
    "Clean editorial photograph with natural light, real places and people at work, shallow depth of field, "
    "calm uncluttered composition"
)


def brand_key(workspace) -> str | None:
    from apps.settings_manager.models import WorkspaceSetting
    from apps.workspaces.brands import BRAND_KEY

    row = WorkspaceSetting.objects.filter(workspace=workspace, key=BRAND_KEY).first()
    return row.value if row and isinstance(row.value, str) else None


def defaults_for(workspace) -> dict[str, Any]:
    """The starting values for *workspace*'s brand profile."""
    known = BRAND_PROFILES.get(brand_key(workspace) or "")
    if known:
        return dict(known)
    name = (workspace.name or "Our brand").strip()
    return {
        "brand_name": name[:100],
        "about": (workspace.description or "")[:500],
        "hashtags": [tag for tag in (workspace.default_hashtags or []) if isinstance(tag, str)][:8],
        "primary_color": workspace.primary_color or "#1F2937",
        "accent_color": workspace.secondary_color or "#F97316",
        "display_font": "outfit",
        "wordmark": name.upper()[:60],
        "photo_style": _GENERIC_PHOTO_STYLE,
    }


def ensure_profile(workspace):
    """The workspace's brand profile, created from :func:`defaults_for` the first time."""
    from .models import BrandProfile

    profile = BrandProfile.objects.filter(workspace=workspace).first()
    if profile is not None:
        return profile
    profile, _created = BrandProfile.objects.get_or_create(workspace=workspace, defaults=defaults_for(workspace))
    return profile
