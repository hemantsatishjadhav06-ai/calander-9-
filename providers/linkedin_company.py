"""LinkedIn provider variant for Company Page posting.

Lists the organizations the authenticated member administers, lets the user
pick one, and publishes to that Company Page via the organization URN.

The token is the member's and can administer several Pages. Once an account
exists, ``apps.publisher.engine._resolve_publish_credentials`` passes its Page
as ``credentials["organization_id"]``, and everything that is about the Page —
its profile, comments, inbox and statistics — goes through it. Without it (while
connecting) the provider answers for the member.

Endpoints are the versioned ``/rest`` ones. The legacy
``/v2/organizationalEntityAcls`` lookup with its ``organizationalTarget~``
decoration is gone from LinkedIn's current docs, and decoration isn't supported
by versioned APIs: Pages are listed with ``/rest/organizationAcls`` and then
looked up in one batch call.
"""

from __future__ import annotations

import logging
from datetime import datetime
from urllib.parse import quote

import httpx

from .exceptions import APIError, ProviderError
from .linkedin import API_BASE, LINKEDIN_HEADERS, LinkedInProvider, _encode_urn
from .types import AccountProfile, InboxMessage, PostMetrics

logger = logging.getLogger(__name__)

#: The Page scopes of LinkedIn's Community Management API product. LinkedIn
#: fails the whole sign-in when a single requested scope isn't granted to the
#: app, so ``PLATFORM_LINKEDIN_COMPANY_SCOPES`` can replace this list with the
#: one on the app's Auth tab.
DEFAULT_SCOPES = [
    "r_basicprofile",
    "w_member_social",
    "w_organization_social",
    "r_organization_social",
    "rw_organization_admin",
    # Comments use the _feed scopes: the first comment posted as the Page,
    # reading comments for the inbox, and replying to them.
    "w_organization_social_feed",
    "r_organization_social_feed",
]

_ACL_PAGE_SIZE = 100
#: Most Pages one member can administer that the picker will list.
_MAX_PAGES = 500
_LOOKUP_BATCH = 50
_STATS_BATCH = 20


def _org_id(urn_or_id) -> str:
    return str(urn_or_id or "").strip().rsplit(":", 1)[-1]


def _chunks(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _rest_list(urns: list[str]) -> str:
    """Rest.li 2.0 ``List(a,b)``: the values encoded, the syntax around them not."""
    return "List(" + ",".join(quote(urn, safe="") for urn in urns) + ")"


def _metrics(stats: dict) -> PostMetrics:
    likes = max(int(stats.get("likeCount") or 0), 0)  # LinkedIn documents it can go negative
    comments = int(stats.get("commentCount") or 0)
    shares = int(stats.get("shareCount") or 0)
    clicks = int(stats.get("clickCount") or 0)
    return PostMetrics(
        impressions=int(stats.get("impressionCount") or 0),
        reach=int(stats.get("uniqueImpressionsCount") or 0),
        engagements=likes + comments + shares + clicks,
        likes=likes,
        comments=comments,
        shares=shares,
        clicks=clicks,
        extra={"raw_statistics": stats},
    )


class LinkedInCompanyProvider(LinkedInProvider):
    """LinkedIn provider scoped to Company Page posting."""

    post_metrics_batch_size = _STATS_BATCH

    @property
    def platform_name(self) -> str:
        return "LinkedIn (Company Page)"

    @property
    def required_scopes(self) -> list[str]:
        return self._configured_scopes(DEFAULT_SCOPES)

    @property
    def organization_urn(self) -> str:
        org_id = _org_id(self.credentials.get("organization_id"))
        return f"urn:li:organization:{org_id}" if org_id else ""

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------

    def get_user_pages(self, access_token: str) -> list[dict]:
        """The Pages this member administers, for the account picker."""
        org_ids = self._administered_organization_ids(access_token)
        try:
            organizations = self._lookup_organizations(access_token, org_ids)
        except ProviderError as exc:
            # The ids are enough to connect; the health check fills names in.
            logger.warning("LinkedIn Page lookup failed, listing Pages by id: %s", exc)
            organizations = {}
        pages: list[dict] = []
        for org_id in org_ids:
            org = organizations.get(org_id, {})
            pages.append(
                {
                    "id": org_id,
                    "name": org.get("localizedName", "") or f"LinkedIn Page {org_id}",
                    "handle": org.get("vanityName", ""),
                    "access_token": access_token,
                    "picture": self._logo_url(access_token, org),
                }
            )
        return pages

    def _administered_organization_ids(self, access_token: str) -> list[str]:
        ids: list[str] = []
        start = 0
        while start < _MAX_PAGES:
            resp = self._request(
                "GET",
                f"{API_BASE}/rest/organizationAcls",
                access_token=access_token,
                headers=LINKEDIN_HEADERS,
                params={
                    "q": "roleAssignee",
                    "role": "ADMINISTRATOR",
                    "state": "APPROVED",
                    "start": start,
                    "count": _ACL_PAGE_SIZE,
                },
            )
            elements = resp.json().get("elements", [])
            for element in elements:
                # "organization" in current versions; older ones said
                # "organizationTarget" (and /v2 "organizationalTarget").
                urn = (
                    element.get("organization")
                    or element.get("organizationTarget")
                    or element.get("organizationalTarget")
                )
                org_id = _org_id(urn)
                if org_id and org_id not in ids:
                    ids.append(org_id)
            if len(elements) < _ACL_PAGE_SIZE:
                break
            start += _ACL_PAGE_SIZE
        return ids

    def _lookup_organizations(self, access_token: str, org_ids: list[str]) -> dict[str, dict]:
        """``{id: organization}`` from LinkedIn's batch lookup; ids it refuses are absent."""
        found: dict[str, dict] = {}
        for chunk in _chunks(org_ids, _LOOKUP_BATCH):
            resp = self._request(
                "GET",
                # Built by hand: List(...) has to reach LinkedIn unencoded.
                f"{API_BASE}/rest/organizations?ids=List({','.join(quote(i, safe='') for i in chunk)})",
                access_token=access_token,
                headers=LINKEDIN_HEADERS,
            )
            for key, org in (resp.json().get("results") or {}).items():
                if isinstance(org, dict):
                    found[_org_id(key)] = org
        return found

    def _logo_url(self, access_token: str, org: dict) -> str | None:
        """A download URL for the Page's logo, or None. Best effort: a logo never blocks anything."""
        logo = org.get("logoV2") or {}
        asset = logo.get("cropped") or logo.get("original") or ""
        if not isinstance(asset, str) or not asset:
            return None
        # LinkedIn's rule: urn:li:digitalmediaAsset:X is fetched as urn:li:image:X.
        image_urn = "urn:li:image:" + asset.rsplit(":", 1)[-1]
        try:
            resp = self._request(
                "GET",
                f"{API_BASE}/rest/images/{_encode_urn(image_urn)}",
                access_token=access_token,
                headers=LINKEDIN_HEADERS,
            )
            url = str(resp.json().get("downloadUrl") or "")
        except (ProviderError, httpx.HTTPError, ValueError) as exc:
            logger.info("LinkedIn logo lookup failed for %s: %s", image_urn, exc)
            return None
        return url if url.startswith("https://") else None

    def _follower_count(self, access_token: str) -> int:
        try:
            resp = self._request(
                "GET",
                f"{API_BASE}/rest/networkSizes/{_encode_urn(self.organization_urn)}",
                access_token=access_token,
                headers=LINKEDIN_HEADERS,
                params={"edgeType": "COMPANY_FOLLOWED_BY_MEMBER"},
            )
            return int(resp.json().get("firstDegreeSize") or 0)
        except (ProviderError, httpx.HTTPError, ValueError, TypeError) as exc:
            logger.info("LinkedIn follower count failed for %s: %s", self.organization_urn, exc)
            return 0

    # ------------------------------------------------------------------
    # Profile
    # ------------------------------------------------------------------

    def get_profile(self, access_token: str) -> AccountProfile:
        """The Page, once the account exists; the signed-in member while connecting.

        The health check refreshes the account's name and picture from this, so
        answering with the member renamed every Company Page after its admin.
        """
        org_id = _org_id(self.credentials.get("organization_id"))
        if not org_id:
            return super().get_profile(access_token)
        org = self._lookup_organizations(access_token, [org_id]).get(org_id)
        if org is None:
            raise APIError(
                f"LinkedIn didn't return Page {org_id}: the member who connected it may no longer be one of its admins.",
                status_code=403,
                platform=self.platform_name,
            )
        return AccountProfile(
            platform_id=org_id,
            name=org.get("localizedName", ""),
            handle=org.get("vanityName") or None,
            avatar_url=self._logo_url(access_token, org),
            follower_count=self._follower_count(access_token),
            extra=org,
        )

    # ------------------------------------------------------------------
    # Comments and inbox
    # ------------------------------------------------------------------

    def _comment_actor(self, access_token: str) -> str:
        # A Page's first comment (where the link usually goes) and its inbox
        # replies are the Page speaking, not whichever admin connected it.
        return self.organization_urn or super()._comment_actor(access_token)

    def get_messages(self, access_token: str, since: datetime | None = None) -> list[InboxMessage]:
        """Comments on the Page's recent posts, leaving out the Page's own."""
        if not self.organization_urn:
            return []
        return self._comments_on_posts_by(access_token, self.organization_urn, since)

    def find_own_comment(self, access_token: str, post_id: str, text: str) -> str | None:
        """The Page's comment on ``post_id`` reading ``text``, so a retried first comment isn't doubled."""
        if not self.organization_urn:
            raise NotImplementedError("LinkedIn needs the Page to look up its comments")
        wanted = (text or "").strip()
        for comment in self._post_comments(access_token, post_id):
            if (
                comment.get("actor") == self.organization_urn
                and (comment.get("message") or {}).get("text", "").strip() == wanted
            ):
                return self._comment_urn(comment)
        return None

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    def get_post_metrics(self, access_token: str, post_id: str) -> PostMetrics:
        """Organic statistics for one of the Page's posts.

        LinkedIn leaves out posts nobody has seen or touched yet, so for a
        single post that absence reads as zeros.
        """
        return self.get_post_metrics_batch(access_token, [post_id]).get(post_id, PostMetrics())

    def get_post_metrics_batch(self, access_token: str, post_ids: list[str]) -> dict[str, PostMetrics]:
        """Share statistics, up to 20 posts per call: ``shares=`` for share URNs, ``ugcPosts=`` for ugcPost URNs."""
        if not self.organization_urn:
            raise NotImplementedError("LinkedIn statistics are kept per Page; this account has no Page id")
        results: dict[str, PostMetrics] = {}
        for param, prefix in (("shares", "urn:li:share:"), ("ugcPosts", "urn:li:ugcPost:")):
            urns = [post_id for post_id in post_ids if post_id.startswith(prefix)]
            for chunk in _chunks(urns, _STATS_BATCH):
                resp = self._request(
                    "GET",
                    f"{API_BASE}/rest/organizationalEntityShareStatistics"
                    f"?q=organizationalEntity&organizationalEntity={quote(self.organization_urn, safe='')}"
                    f"&{param}={_rest_list(chunk)}",
                    access_token=access_token,
                    headers=LINKEDIN_HEADERS,
                )
                for element in resp.json().get("elements", []):
                    urn = element.get("share") or element.get("ugcPost")
                    if urn in chunk:
                        results[urn] = _metrics(element.get("totalShareStatistics") or {})
        return results
