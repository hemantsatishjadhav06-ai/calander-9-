"""LinkedIn Company Pages: listing them, and everything that speaks as the Page.

LinkedIn is never called: ``_request`` is replaced by a router that answers by
URL and records what was asked, so each test reads as the requests it expects.
"""

import inspect
from unittest.mock import MagicMock

import pytest

from providers.exceptions import APIError
from providers.linkedin_company import DEFAULT_SCOPES, LinkedInCompanyProvider
from providers.linkedin_personal import LinkedInPersonalProvider
from providers.types import PostType, PublishContent

ORG = "urn:li:organization:98765"


def _response(payload=None, headers=None):
    resp = MagicMock()
    resp.json = MagicMock(return_value=payload or {})
    resp.headers = headers or {}
    return resp


class FakeLinkedIn:
    """Answers ``_request`` by URL prefix; anything unexpected fails the test."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        for (want_method, prefix), answer in self.routes.items():
            if method == want_method and url.startswith(prefix):
                # A MagicMock is callable too, so only plain functions compute an answer.
                return answer(url, kwargs) if inspect.isfunction(answer) else answer
        raise AssertionError(f"unexpected LinkedIn call: {method} {url}")

    def urls(self, method=None):
        return [url for m, url, _ in self.calls if method in (None, m)]


def _provider(routes, **credentials):
    provider = LinkedInCompanyProvider(credentials={"client_id": "cid", "client_secret": "sec", **credentials})
    fake = FakeLinkedIn(routes)
    provider._request = fake
    return provider, fake


ACLS = ("GET", "https://api.linkedin.com/rest/organizationAcls")
ORGS = ("GET", "https://api.linkedin.com/rest/organizations?ids=")
IMAGES = ("GET", "https://api.linkedin.com/rest/images/")


def _org(name, vanity, logo=None):
    org = {"localizedName": name, "vanityName": vanity}
    if logo:
        org["logoV2"] = {"cropped": logo, "original": logo + "-orig"}
    return org


class TestGetUserPages:
    def test_lists_administered_pages_with_names_and_logos(self):
        provider, fake = _provider(
            {
                ACLS: _response(
                    {
                        "elements": [
                            {"organization": "urn:li:organization:98765", "role": "ADMINISTRATOR"},
                            # Older versions name the field organizationTarget.
                            {"organizationTarget": "urn:li:organization:11111", "role": "ADMINISTRATOR"},
                        ]
                    }
                ),
                ORGS: _response(
                    {
                        "results": {
                            "98765": _org("Neopolis Infra", "neopolis-infra", "urn:li:digitalmediaAsset:C4D0BAQE"),
                            "11111": _org("More Space", "morespace"),
                        }
                    }
                ),
                IMAGES: _response({"downloadUrl": "https://media.licdn.com/dms/image/logo.png"}),
            }
        )

        pages = provider.get_user_pages("token-xyz")

        assert pages == [
            {
                "id": "98765",
                "name": "Neopolis Infra",
                "handle": "neopolis-infra",
                "access_token": "token-xyz",
                "picture": "https://media.licdn.com/dms/image/logo.png",
            },
            {
                "id": "11111",
                "name": "More Space",
                "handle": "morespace",
                "access_token": "token-xyz",
                "picture": None,
            },
        ]
        acl_call = fake.calls[0]
        assert acl_call[2]["params"]["q"] == "roleAssignee"
        assert acl_call[2]["params"]["role"] == "ADMINISTRATOR"
        assert acl_call[2]["params"]["state"] == "APPROVED"
        # One batch lookup, in Rest.li 2.0 List() syntax, not one call per Page.
        assert fake.urls().count("https://api.linkedin.com/rest/organizations?ids=List(98765,11111)") == 1
        # The logo's digitalmediaAsset is fetched as an image URN, encoded.
        assert "https://api.linkedin.com/rest/images/urn%3Ali%3Aimage%3AC4D0BAQE" in fake.urls()

    def test_no_pages(self):
        provider, fake = _provider({ACLS: _response({"elements": []}), ORGS: _response({"results": {}})})

        assert provider.get_user_pages("token") == []

    def test_pages_still_list_when_the_lookup_or_the_logo_fails(self):
        def refuse(url, kwargs):
            raise APIError("forbidden", status_code=403, platform="LinkedIn")

        provider, _ = _provider(
            {ACLS: _response({"elements": [{"organization": "urn:li:organization:22222"}]}), ORGS: refuse}
        )

        pages = provider.get_user_pages("token")

        assert pages[0]["id"] == "22222"
        assert pages[0]["name"] == "LinkedIn Page 22222"
        assert pages[0]["picture"] is None

    def test_pages_past_the_first_hundred(self):
        def acls(url, kwargs):
            start = kwargs["params"]["start"]
            count = 100 if start == 0 else 3
            return _response({"elements": [{"organization": f"urn:li:organization:{start + i}"} for i in range(count)]})

        provider, _ = _provider({ACLS: acls, ORGS: _response({"results": {}})})

        assert len(provider.get_user_pages("token")) == 103


class TestTheAccountIsThePage:
    def _page_provider(self, extra_routes=None):
        routes = {
            ORGS: _response({"results": {"98765": _org("Neopolis Infra", "neopolis-infra")}}),
            ("GET", "https://api.linkedin.com/rest/networkSizes/"): _response({"firstDegreeSize": 4120}),
            **(extra_routes or {}),
        }
        return _provider(routes, organization_id="98765")

    def test_the_profile_is_the_page_not_the_admin(self):
        provider, fake = self._page_provider()

        profile = provider.get_profile("token")

        assert (profile.platform_id, profile.name, profile.handle) == ("98765", "Neopolis Infra", "neopolis-infra")
        assert profile.follower_count == 4120
        assert not any("/v2/me" in url for url in fake.urls())
        assert "urn%3Ali%3Aorganization%3A98765" in fake.urls()[-1]

    def test_a_page_the_member_no_longer_administers_is_an_error(self):
        provider, _ = _provider(
            {ORGS: _response({"results": {}, "errors": {"98765": {"status": 403}}})}, organization_id="98765"
        )

        with pytest.raises(APIError, match="no longer be one of its admins"):
            provider.get_profile("token")

    def test_while_connecting_the_profile_is_the_member(self):
        provider, fake = _provider(
            {("GET", "https://api.linkedin.com/v2/me"): _response({"id": "abc", "localizedFirstName": "Ana"})}
        )

        assert provider.get_profile("token").platform_id == "abc"

    def test_the_first_comment_is_posted_by_the_page(self):
        provider, fake = self._page_provider(
            {
                ("POST", "https://api.linkedin.com/rest/socialActions/"): _response(
                    {"commentUrn": "urn:li:comment:(urn:li:activity:1,42)"}, {"x-restli-id": "42"}
                )
            }
        )

        result = provider.publish_comment("token", "urn:li:share:7", "Read more: https://neopolis.in")

        method, url, kwargs = fake.calls[-1]
        assert url == "https://api.linkedin.com/rest/socialActions/urn%3Ali%3Ashare%3A7/comments"
        assert kwargs["json"] == {"actor": ORG, "message": {"text": "Read more: https://neopolis.in"}}
        assert result.platform_comment_id == "urn:li:comment:(urn:li:activity:1,42)"

    def test_inbox_replies_are_the_page_too(self):
        provider, fake = self._page_provider({("POST", "https://api.linkedin.com/rest/socialActions/"): _response({})})

        provider.reply_to_message(
            "token", "urn:li:comment:(urn:li:activity:1,9)", "Thank you!", {"post_urn": "urn:li:share:7"}
        )

        assert fake.calls[-1][2]["json"]["actor"] == ORG
        assert fake.calls[-1][2]["json"]["parentComment"] == "urn:li:comment:(urn:li:activity:1,9)"


class TestInbox:
    def test_comments_on_the_pages_posts_without_its_own(self):
        comments = {
            "elements": [
                {
                    "actor": "urn:li:person:fan",
                    "commentUrn": "urn:li:comment:(urn:li:activity:5,1)",
                    "id": "1",
                    "message": {"text": "Is the Kollur plot available?"},
                    "created": {"time": 1_760_000_000_000},
                },
                {
                    # The Page's own first comment: not an inbound message.
                    "actor": ORG,
                    "commentUrn": "urn:li:comment:(urn:li:activity:5,2)",
                    "message": {"text": "Details: https://neopolis.in"},
                    "created": {"time": 1_760_000_001_000},
                },
            ]
        }
        provider, fake = _provider(
            {
                ("GET", "https://api.linkedin.com/rest/posts"): _response({"elements": [{"id": "urn:li:share:5"}]}),
                ("GET", "https://api.linkedin.com/rest/socialActions/"): _response(comments),
            },
            organization_id="98765",
        )

        messages = provider.get_messages("token")

        assert [m.text for m in messages] == ["Is the Kollur plot available?"]
        assert messages[0].platform_message_id == "urn:li:comment:(urn:li:activity:5,1)"
        assert messages[0].extra["post_urn"] == "urn:li:share:5"
        posts_call = fake.calls[0][2]
        assert posts_call["params"]["author"] == ORG and posts_call["params"]["q"] == "author"

    def test_no_page_no_inbox(self):
        provider, fake = _provider({})

        assert provider.get_messages("token") == []
        assert fake.calls == []

    def test_a_retried_first_comment_finds_the_one_already_posted(self):
        provider, _ = _provider(
            {
                ("GET", "https://api.linkedin.com/rest/socialActions/"): _response(
                    {
                        "elements": [
                            {"actor": "urn:li:person:fan", "message": {"text": "Details"}, "id": "1"},
                            {"actor": ORG, "message": {"text": "Details "}, "commentUrn": "urn:li:comment:(x,2)"},
                        ]
                    }
                )
            },
            organization_id="98765",
        )

        assert provider.find_own_comment("token", "urn:li:share:5", "Details") == "urn:li:comment:(x,2)"
        assert provider.find_own_comment("token", "urn:li:share:5", "Something else") is None


class TestStatistics:
    STATS = ("GET", "https://api.linkedin.com/rest/organizationalEntityShareStatistics")

    def test_share_statistics_for_the_page(self):
        def stats(url, kwargs):
            if "shares=List(" in url:
                return _response(
                    {
                        "elements": [
                            {
                                "share": "urn:li:share:1",
                                "totalShareStatistics": {
                                    "impressionCount": 900,
                                    "uniqueImpressionsCount": 700,
                                    "likeCount": 30,
                                    "commentCount": 4,
                                    "shareCount": 2,
                                    "clickCount": 25,
                                    "engagement": 0.067,
                                },
                            }
                        ]
                    }
                )
            return _response(
                {"elements": [{"ugcPost": "urn:li:ugcPost:9", "totalShareStatistics": {"impressionCount": 5}}]}
            )

        provider, fake = _provider({self.STATS: stats}, organization_id="98765")

        result = provider.get_post_metrics_batch("token", ["urn:li:share:1", "urn:li:share:2", "urn:li:ugcPost:9"])

        share_url, ugc_url = fake.urls()
        assert share_url == (
            "https://api.linkedin.com/rest/organizationalEntityShareStatistics?q=organizationalEntity"
            "&organizationalEntity=urn%3Ali%3Aorganization%3A98765"
            "&shares=List(urn%3Ali%3Ashare%3A1,urn%3Ali%3Ashare%3A2)"
        )
        assert ugc_url.endswith("&ugcPosts=List(urn%3Ali%3AugcPost%3A9)")
        one = result["urn:li:share:1"]
        assert (one.impressions, one.reach, one.likes, one.comments, one.shares, one.clicks) == (900, 700, 30, 4, 2, 25)
        assert one.engagements == 61
        # LinkedIn leaves out posts with no activity: absent, never invented zeros.
        assert "urn:li:share:2" not in result
        assert result["urn:li:ugcPost:9"].impressions == 5

    def test_a_single_post_with_no_activity_reads_as_zeros(self):
        provider, _ = _provider({self.STATS: _response({"elements": []})}, organization_id="98765")

        assert provider.get_post_metrics("token", "urn:li:share:3").impressions == 0

    def test_batches_are_announced_to_the_analytics_sync(self):
        assert LinkedInCompanyProvider.post_metrics_batch_size == 20


class TestMultiImage:
    def _publishing_provider(self):
        uploads = iter(range(1, 30))

        def init_upload(url, kwargs):
            n = next(uploads)
            return _response({"value": {"uploadUrl": f"https://upload/{n}", "image": f"urn:li:image:I{n}"}})

        provider, fake = _provider(
            {
                ("POST", "https://api.linkedin.com/rest/images"): init_upload,
                ("POST", "https://api.linkedin.com/rest/posts"): _response({}, {"x-restli-id": "urn:li:share:77"}),
            },
            organization_id="98765",
        )
        provider._upload_binary = MagicMock()
        return provider, fake

    def test_several_images_go_out_as_one_multi_image_post_with_alt_text(self):
        provider, fake = self._publishing_provider()
        content = PublishContent(
            text="Three plots #Hyderabad",
            post_type=PostType.IMAGE,
            media_files=["/tmp/a.jpg", "/tmp/b.jpg", "/tmp/c.mp4", "/tmp/d.gif"],
            media_types=["image", "image", "video", "gif"],
            media_alt_texts=["Plot A at dusk", "", "a video", "Site plan"],
            extra={"author": ORG},
        )

        result = provider.publish_post("token", content)

        body = fake.calls[-1][2]["json"]
        assert body["author"] == ORG
        assert body["commentary"] == "Three plots #Hyderabad"
        assert body["content"] == {
            "multiImage": {
                "images": [
                    {"id": "urn:li:image:I1", "altText": "Plot A at dusk"},
                    {"id": "urn:li:image:I2"},
                    {"id": "urn:li:image:I3", "altText": "Site plan"},
                ]
            }
        }
        assert provider._upload_binary.call_count == 3  # the video is not sent as an image
        assert result.extra["image_urns"] == ["urn:li:image:I1", "urn:li:image:I2", "urn:li:image:I3"]

    def test_one_image_is_a_media_post(self):
        provider, fake = self._publishing_provider()
        content = PublishContent(
            text="One",
            post_type=PostType.IMAGE,
            media_files=["/tmp/a.jpg"],
            media_types=["image"],
            media_alt_texts=["The site entrance"],
            extra={"author": ORG},
        )

        provider.publish_post("token", content)

        assert fake.calls[-1][2]["json"]["content"] == {
            "media": {"id": "urn:li:image:I1", "altText": "The site entrance"}
        }


class TestScopes:
    def test_company_pages_ask_for_the_comment_scopes(self):
        scopes = LinkedInCompanyProvider(credentials={}).required_scopes
        assert scopes == DEFAULT_SCOPES
        assert {"w_organization_social_feed", "r_organization_social_feed"} <= set(scopes)

    def test_a_deployment_can_list_the_scopes_its_app_holds(self):
        provider = LinkedInCompanyProvider(
            credentials={"_scopes": "w_organization_social, r_organization_social rw_organization_admin"}
        )
        assert provider.required_scopes == ["w_organization_social", "r_organization_social", "rw_organization_admin"]

    def test_personal_on_the_community_app_never_asks_for_the_closed_scope(self):
        provider = LinkedInPersonalProvider(credentials={"_oauth_mode": "community_management"})
        assert "r_member_social" not in provider.required_scopes
        assert "w_member_social_feed" in provider.required_scopes
        # Without r_member_social, listing the member's posts is refused: don't try.
        provider._request = FakeLinkedIn({})
        assert provider.get_messages("token") == []
