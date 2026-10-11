"""The SEO score: deterministic checks with a fix for each."""

from apps.blog import seo

GOOD_BODY = (
    "Land title verification is the first thing a buyer in Hyderabad should do. "
    + "A clear title protects your money and your family. " * 20
    + "\n\n## Why land title verification matters\n\n"
    + "Banks ask for it before a loan. Courts look at it in a dispute. " * 15
    + "\n\n## Get the encumbrance certificate\n\n"
    + "Ask the sub-registrar for thirty years of records. Check each sale. " * 15
    + "\n\n## Check the RERA registration\n\n"
    + "See [our RERA checklist](/blog/rera-checklist) and [the area guide](/blog/kokapet-guide). "
    + "The state portal is at [rera.telangana.gov.in](https://rera.telangana.gov.in). "
    + "Compare the plan with the registered one. " * 12
)


def _good(**overrides):
    fields = {
        "title": "Land title verification: 5 checks before you buy",
        "slug": "land-title-verification",
        "body": GOOD_BODY,
        "seo_title": "Land Title Verification: 5 Checks Before You Buy",
        "meta_description": (
            "Buying in Hyderabad? Do land title verification first: encumbrance, RERA, mutation, tax receipts and "
            "the parent deed, before any token."
        ),
        "excerpt": "Five checks that protect your money before you pay a token.",
        "focus_keyword": "land title verification",
        "faq": [{"q": "How long does it take?", "a": "About a week."}],
        "image_alt": "A buyer reading a title deed at a desk",
        "has_image": True,
        "site_kind": "neopolis_static",
        "site_origin": "https://www.neopolisinfra.com",
    }
    fields.update(overrides)
    return seo.score(**fields)


def _level(report, key):
    return next(c for c in report.checks if c.key == key).level


def test_a_well_built_article_scores_well():
    report = _good()
    assert report.score >= 85, [(c.key, c.level, c.detail) for c in report.to_fix]
    assert report.grade.startswith("Good")
    assert _level(report, "kw_title") == "pass" and _level(report, "internal_links") == "pass"


def test_the_title_tag_drops_the_site_suffix_when_it_would_not_fit():
    assert seo.title_tag("Short title", "", "morespace_static") == "Short title | More Space Blog"
    long = "Land Title Verification: 5 Checks Before You Buy"
    assert seo.title_tag(long, "", "neopolis_static") == long


def test_missing_basics_fail_with_a_fix():
    report = _good(
        meta_description="", excerpt="", seo_title="", title="", body="Too short.", has_image=True, image_alt=""
    )
    assert report.score < 50
    assert _level(report, "meta") == "fail" and _level(report, "title") == "fail"
    assert _level(report, "length") == "fail" and _level(report, "cover_alt") == "fail"
    assert all(c.detail for c in report.to_fix)


def test_keyword_checks_need_a_keyword():
    report = _good(focus_keyword="")
    assert _level(report, "keyword") == "warn"
    assert not any(c.key.startswith("kw_") for c in report.checks)


def test_stuffing_and_vague_links_are_flagged():
    stuffed = "land title verification " * 200 + "\n\nRead [here](/blog/x) and [click here](/blog/y)."
    report = _good(body=stuffed)
    assert _level(report, "kw_density") == "warn"
    assert _level(report, "link_text") == "warn"


def test_a_duplicate_title_on_the_site_fails():
    report = _good(other_titles=["Land title verification: 5 checks before you buy"])
    assert _level(report, "duplicate") == "fail"


def test_things_to_fix_come_failures_first_and_the_tone_follows_the_score():
    report = _good(meta_description="", excerpt="", seo_title="", title="", body="Too short.", image_alt="")
    levels = [c.level for c in report.to_fix]
    assert levels == sorted(levels, key=lambda level: level != "fail")
    assert report.tone == "poor" and _good().tone == "good"
    assert len(report.passing) + len(report.to_fix) == len(report.checks)


def test_the_title_count_includes_the_site_name_when_it_fits():
    report = _good(seo_title="Land title checks")
    assert report.title_tag == "Land title checks | Neopolis Infra Blog" and report.title_fits


# ---------------------------------------------------------------------------
# The SEO monitor's suggestion
# ---------------------------------------------------------------------------


def _trend(**overrides):
    trend = {
        "clicks": 10,
        "impressions": 400,
        "ctr": 0.025,
        "position": 6.0,
        "previous_position": 6.5,
        "position_change": 0.5,
        "queries": [{"query": "land title verification", "clicks": 10, "impressions": 300, "position": 4.0}],
    }
    trend.update(overrides)
    return trend


def test_page_two_queries_get_a_section_suggestion():
    trend = _trend(queries=[{"query": "encumbrance certificate", "clicks": 0, "impressions": 90, "position": 13.4}])
    assert seo.suggestion(_good(), trend).startswith("Stuck on page 2 for “encumbrance certificate”")


def test_a_slipping_article_gets_a_refresh_suggestion():
    assert "Slipped 4 places" in seo.suggestion(_good(), _trend(position_change=-4.2))


def test_the_bottom_of_page_one_gets_a_nudge():
    trend = _trend(queries=[{"query": "rera check", "clicks": 1, "impressions": 50, "position": 9.6}])
    assert "bottom of page 1" in seo.suggestion(_good(), trend)


def test_seen_but_not_clicked_gets_a_snippet_suggestion():
    assert "rarely clicked" in seo.suggestion(_good(), _trend(clicks=1, ctr=0.002, impressions=900))


def test_thin_queries_are_ignored_and_the_score_speaks_next():
    weak = _good(meta_description="", excerpt="", body="Too short.")
    trend = _trend(queries=[{"query": "rare", "clicks": 0, "impressions": 3, "position": 15.0}])
    assert seo.suggestion(weak, trend).startswith(f"Score {weak.score} — fix: search description")


def test_no_impressions_and_no_search_console():
    assert "No Google impressions yet" in seo.suggestion(_good(), _trend(impressions=0, clicks=0, queries=[]))
    assert seo.suggestion(_good(), None) == "Doing well — nothing to change this week."


def test_score_posts_matches_score_post_with_one_titles_query(world, django_assert_num_queries):
    from apps.blog.tests.conftest import make_post

    first = make_post(world)
    second = make_post(world, slug="second", title="Flats in Kokapet 2026")  # a duplicate title
    posts = [type(first).objects.select_related("site").get(pk=p.pk) for p in (first, second)]
    with django_assert_num_queries(1):
        reports = seo.score_posts(posts)
    assert reports[first.pk].score == seo.score_post(first).score
    assert next(c for c in reports[second.pk].checks if c.key == "duplicate").level == "fail"
