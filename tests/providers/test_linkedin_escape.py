"""Tests for LinkedIn commentary escaping (reserved little-text characters).

LinkedIn's Posts API silently truncates ``commentary`` at the first unescaped
reserved character (e.g. a ``(`` drops everything after it), which published
posts as just their first sentence. ``escape_commentary`` prefixes each
reserved char with a backslash so the full text renders.

Comments are a different API with a different model — plain text plus a separate
``attributes[]`` array for mentions — so they are deliberately *not* escaped.
"""

from unittest.mock import MagicMock

from providers.linkedin import LINKEDIN_RESERVED_CHARS, LinkedInProvider, escape_commentary, hashtag_spans

# Read from the module under test, so adding a reserved char there extends the
# coverage below instead of silently leaving the new char unchecked.
RESERVED = set(LINKEDIN_RESERVED_CHARS)


class TestEscapeCommentary:
    def test_escapes_reserved_characters(self):
        assert escape_commentary("(a)") == "\\(a\\)"
        assert escape_commentary("pre_commands") == "pre\\_commands"
        assert escape_commentary("We're #1") == "We're \\#1"
        assert escape_commentary("{{x}}") == "\\{\\{x\\}\\}"
        assert escape_commentary("a*b~c<d>e|f@g[h]i") == "a\\*b\\~c\\<d\\>e\\|f\\@g\\[h\\]i"

    def test_escapes_backslash_first(self):
        # A literal backslash is doubled exactly once (not compounded with the
        # escapes we add afterwards).
        assert escape_commentary("a\\b") == "a\\\\b"

    def test_leaves_plain_text_and_urls_untouched(self):
        assert escape_commentary("Hola mundo, ¿qué tal?") == "Hola mundo, ¿qué tal?"
        url = "https://dev.to/agentprojectcontext/mcp-scopes-are-trust-boundaries-not-settings-2i18"
        assert escape_commentary(url) == url

    def test_empty_and_none_are_safe(self):
        assert escape_commentary("") == ""
        assert escape_commentary(None) is None

    def test_no_unescaped_reserved_char_remains(self):
        # Regression: this caption published on LinkedIn as only "Va al repo ".
        caption = "Va al repo (contexto durable y portable):\n- item"
        out = escape_commentary(caption)
        for i, ch in enumerate(out):
            if ch in RESERVED:
                assert i > 0 and out[i - 1] == "\\", f"unescaped {ch!r} at index {i}"


class TestHashtags:
    """An unescaped "#word" is little-text's hashtag element: LinkedIn links it.

    Escaping every "#" published hashtags as dead text, so real hashtags go out
    as they are and every other "#" is still escaped.
    """

    def test_hashtags_are_left_to_link(self):
        assert escape_commentary("#AI #Agents") == "#AI #Agents"
        assert escape_commentary("Plots in #Hyderabad, #RealEstate.") == "Plots in #Hyderabad, #RealEstate."
        assert escape_commentary("#Plot2026 (open)") == "#Plot2026 \\(open\\)"
        assert escape_commentary("#हैदराबाद") == "#हैदराबाद"

    def test_a_hash_that_is_not_a_hashtag_is_escaped(self):
        assert escape_commentary("C# and F#") == "C\\# and F\\#"
        assert escape_commentary("#2026") == "\\#2026"  # no letter
        assert escape_commentary("# of units") == "\\# of units"
        assert escape_commentary("##tag") == "\\#\\#tag"
        # Runs on into an underscore: kept literal instead of linking "#real".
        assert escape_commentary("#real_estate") == "\\#real\\_estate"

    def test_only_hashtags_stay_unescaped(self):
        caption = "Call (now) #RealEstate @agent [x] #1"
        out = escape_commentary(caption)
        tags = {start for start, _end in hashtag_spans(caption)}
        assert out == "Call \\(now\\) #RealEstate \\@agent \\[x\\] \\#1"
        assert len(tags) == 1


class TestBuildPostBodyEscapes:
    def test_commentary_in_body_is_escaped(self):
        provider = LinkedInProvider.__new__(LinkedInProvider)
        body = provider._build_post_body("urn:li:person:abc", "Va al repo (durable)")
        assert body["commentary"] == "Va al repo \\(durable\\)"
        assert body["author"] == "urn:li:person:abc"


class TestCommentsAreNotEscaped:
    """The Comments API is plain text; escaping there is a regression.

    A reply like "Thanks (really)!" would publish with visible backslashes, and
    any mention in ``attributes[]`` would land on the wrong start/length offset.
    """

    def _provider(self):
        provider = LinkedInProvider.__new__(LinkedInProvider)
        provider.get_profile = MagicMock(return_value=MagicMock(platform_id="abc"))
        provider._request = MagicMock(
            return_value=MagicMock(
                json=MagicMock(return_value={"id": "urn:li:comment:1"}),
                headers={"x-restli-id": "urn:li:comment:1"},
            )
        )
        return provider

    def test_publish_comment_sends_the_text_verbatim(self):
        provider = self._provider()

        provider.publish_comment("token", "urn:li:share:1", "Thanks (really)! #wow")

        assert provider._request.call_args.kwargs["json"] == {
            "actor": "urn:li:person:abc",
            "message": {"text": "Thanks (really)! #wow"},
        }

    def test_reply_to_message_sends_the_text_verbatim(self):
        provider = self._provider()

        provider.reply_to_message(
            "token",
            "urn:li:comment:parent",
            "Thanks (really)! #wow",
            extra={"post_urn": "urn:li:share:1"},
        )

        assert provider._request.call_args.kwargs["json"] == {
            "actor": "urn:li:person:abc",
            "message": {"text": "Thanks (really)! #wow"},
            "parentComment": "urn:li:comment:parent",
        }
