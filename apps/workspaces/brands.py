"""The owner's two brands, as confirmed by the owner and checked against their
websites and the Meta Pages their login manages.

``setup_brands`` creates (or reuses) one workspace per brand from this table,
and stores each brand's expected accounts on its workspace so the account
picker can point at the right Page, and ``live_verify`` can check that what got
connected is what was expected.

Facebook Pages have two numbers. The one in the Page's URL
(``facebook.com/profile.php?id=...``) is the profile id; the Graph API's Page
id is a different number. Both are recorded; the connection stores the Graph
id, and ``live_verify`` checks the Page's ``link`` for the profile id.
"""

from typing import Any

BRANDS: list[dict[str, Any]] = [
    {
        "key": "neopolis",
        "name": "Neopolis",
        "match_names": ["neopolis", "neopolis infra", "neopolis infra llp"],
        "description": "Neopolis Infra LLP — landlord-share flats in West Hyderabad. neopolisinfra.com",
        "timezone": "Asia/Kolkata",
        "primary_color": "#081D4A",
        "website": "https://www.neopolisinfra.com",
        "expected_accounts": {
            "facebook": {
                "page_id": "585141221346435",
                "profile_id": "61595008380228",
                "name": "Neopolis Infra",
                "url": "https://www.facebook.com/profile.php?id=61595008380228",
            },
            "instagram": {"username": "neopolis_infra", "url": "https://www.instagram.com/neopolis_infra/"},
            "x": {"username": "neopolisinfra", "url": "https://x.com/neopolisinfra"},
        },
    },
    {
        "key": "morespace",
        "name": "More Space",
        "match_names": ["more space", "morespace", "more space hyderabad"],
        "description": "More Space — premium high-rise residences and landlord shares, Hyderabad. morespace.netlify.app",
        "timezone": "Asia/Kolkata",
        "primary_color": "#2D236D",
        "secondary_color": "#0300C7",
        "website": "https://morespace.netlify.app",
        "expected_accounts": {
            "facebook": {
                "page_id": "1282011328339050",
                "profile_id": "61577172604485",
                "name": "More Space",
                "url": "https://www.facebook.com/61577172604485",
            },
            "instagram": {"username": "morespace.ai", "url": "https://www.instagram.com/morespace.ai/"},
            "x": {"username": "morespaceai", "url": "https://x.com/morespaceai"},
        },
    },
]

#: WorkspaceSetting key holding a brand's expected accounts.
EXPECTED_ACCOUNTS_KEY = "brand.expected_accounts"
#: WorkspaceSetting key naming which brand a workspace is.
BRAND_KEY = "brand.key"


def expected_accounts(workspace) -> dict:
    from apps.settings_manager.models import WorkspaceSetting

    row = WorkspaceSetting.objects.filter(workspace=workspace, key=EXPECTED_ACCOUNTS_KEY).first()
    return (row.value or {}) if row else {}


def expected_identifiers(workspace, platform) -> set[str]:
    """Every id/handle that identifies the expected account on *platform*, lower-cased."""
    entry = expected_accounts(workspace).get("instagram" if platform == "instagram_login" else platform) or {}
    values = {entry.get("page_id"), entry.get("profile_id"), entry.get("username"), entry.get("name")}
    return {str(v).lower().lstrip("@") for v in values if v}


def other_brand_identifiers(workspace, platform) -> set[str]:
    """Ids/handles that belong to the *other* brands — connecting one here is a mistake."""
    from apps.settings_manager.models import WorkspaceSetting

    row = WorkspaceSetting.objects.filter(workspace=workspace, key=BRAND_KEY).first()
    mine = row.value if row else None
    platform = "instagram" if platform == "instagram_login" else platform
    found = set()
    for brand in BRANDS:
        if brand["key"] == mine:
            continue
        entry = brand["expected_accounts"].get(platform) or {}
        for field in ("page_id", "profile_id", "username"):
            if entry.get(field):
                found.add(str(entry[field]).lower())
    return found
