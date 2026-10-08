"""What the engine hands the LinkedIn providers.

The Page a LinkedIn Company account is (the token is its admin's and can run
several), the alt text written in the composer, and GIFs, which LinkedIn's
Images API takes but which used to go out as text posts.
"""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.publisher.engine import PublishEngine, _resolve_publish_credentials
from apps.publisher.test_media_handling import _attachment, _dispatch_mocks
from providers.types import PostType


class TheCompanyAccountNamesItsPageTest(SimpleTestCase):
    @patch("apps.publisher.engine.resolve_platform_credentials", return_value={"client_id": "c", "client_secret": "s"})
    def test_the_page_id_rides_with_the_credentials(self, _resolve):
        account = MagicMock(platform="linkedin_company", account_platform_id="98765")

        credentials = _resolve_publish_credentials(account)

        assert credentials["organization_id"] == "98765"
        assert credentials["client_id"] == "c"

    @patch("apps.publisher.engine.resolve_platform_credentials", return_value={})
    def test_personal_accounts_carry_no_page(self, _resolve):
        account = MagicMock(platform="linkedin_personal", account_platform_id="abc")

        assert "organization_id" not in _resolve_publish_credentials(account)


class AltTextReachesTheProviderTest(SimpleTestCase):
    @patch("apps.publisher.engine.download_to_path")
    @patch("apps.publisher.engine.get_provider")
    @patch("apps.publisher.engine._resolve_publish_credentials", return_value={})
    def test_the_attachments_alt_text_or_else_the_assets(self, _creds, get_provider, _download):
        first, second, third = (
            _attachment("a1"),
            _attachment("a2", filename="b.jpg"),
            _attachment("a3", filename="c.jpg"),
        )
        first.alt_text, first.media_asset.alt_text = "Plot A at dusk", "library text"
        second.alt_text, second.media_asset.alt_text = "", "Site plan"
        third.alt_text, third.media_asset.alt_text = "", ""
        engine, platform_post, provider = _dispatch_mocks(
            "linkedin_company", needs_local_media=False, attachments=[first, second, third]
        )
        get_provider.return_value = provider

        engine._dispatch_to_provider(platform_post)

        _token, content = provider.publish_post.call_args.args
        assert content.media_alt_texts == ["Plot A at dusk", "Site plan", ""]
        assert len(content.media_alt_texts) == len(content.media_urls)


class GifsAreImagesOnLinkedInTest(SimpleTestCase):
    def _resolve(self, platform):
        return PublishEngine._resolve_post_type(
            platform=platform, platform_extra={}, media_count=1, first_media_type="gif"
        )

    def test_a_gif_on_linkedin_is_an_image_post(self):
        assert self._resolve("linkedin_company") is PostType.IMAGE
        assert self._resolve("linkedin_personal") is PostType.IMAGE

    def test_other_platforms_are_unchanged(self):
        assert self._resolve("facebook") is PostType.TEXT
