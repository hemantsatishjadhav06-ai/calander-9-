"""``feature_enabled``: one workspace's switch, else the key's default.

- A typo in a key fails loudly instead of hiding a feature.
- A switch set for one workspace says nothing about another.
- Blog is on where the workspace already has an enabled blog website, unless
  its switch says otherwise; every other key starts off.
- A workspace without agency settings gets the defaults, and no row is made.
- Read-only, at most two small queries.

``features_for`` gives every key at once under the same rules, still in at most
two queries, and none without a workspace. ``request_features`` reads it once
per request, and templates get the same answer as ``features``.
"""

import pytest
from django.db import connection
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.blog.models import BlogSite
from apps.common.context_processors import sidebar_context
from apps.common.features import FEATURE_KEYS, feature_enabled, features_for, request_features
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.studio.models import AgencySettings
from apps.workspaces.models import Workspace

ALL_OFF = dict.fromkeys(FEATURE_KEYS, False)
FEATURE_TABLES = (AgencySettings._meta.db_table, BlogSite._meta.db_table)


@pytest.fixture
def org():
    return Organization.objects.create(name="Org")


@pytest.fixture
def workspace(org):
    return Workspace.objects.create(organization=org, name="WS")


@pytest.fixture
def other_workspace(org):
    return Workspace.objects.create(organization=org, name="Other")


def _switches(workspace, **features):
    return AgencySettings.objects.create(workspace=workspace, features=features)


def _blog_site(workspace, *, is_enabled=True):
    return BlogSite.objects.create(
        workspace=workspace,
        name="Site",
        kind=BlogSite.Kind.NEOPOLIS_STATIC,
        site_url="https://www.example.com",
        repo="example/site",
        workflow_file="publish.yml",
        is_enabled=is_enabled,
    )


def test_the_keys_are_the_beta_cut():
    assert FEATURE_KEYS == ("blog", "queues", "templates", "extra_providers", "advanced_settings")


@pytest.mark.django_db
def test_an_unknown_key_raises(workspace):
    with pytest.raises(ValueError):
        feature_enabled(workspace, "queue")


@pytest.mark.django_db
def test_a_switch_is_for_its_own_workspace_only(workspace, other_workspace):
    _switches(workspace, queues=True)
    _switches(other_workspace)

    assert feature_enabled(workspace, "queues") is True
    assert feature_enabled(other_workspace, "queues") is False


@pytest.mark.django_db
def test_a_blog_switch_set_off_wins_over_an_enabled_site(workspace):
    _blog_site(workspace)
    _switches(workspace, blog=False)

    assert feature_enabled(workspace, "blog") is False


@pytest.mark.django_db
def test_blog_defaults_to_on_with_an_enabled_site(workspace):
    _blog_site(workspace)
    _switches(workspace)

    assert feature_enabled(workspace, "blog") is True


@pytest.mark.django_db
def test_blog_defaults_to_off_with_a_disabled_site(workspace):
    _blog_site(workspace, is_enabled=False)
    _switches(workspace)

    assert feature_enabled(workspace, "blog") is False


@pytest.mark.django_db
def test_blog_defaults_to_off_without_a_site(workspace, other_workspace):
    _blog_site(other_workspace)
    _switches(workspace)

    assert feature_enabled(workspace, "blog") is False


@pytest.mark.django_db
def test_a_value_that_is_not_a_boolean_takes_the_default(workspace):
    _switches(workspace, queues="yes", blog="no")
    _blog_site(workspace)

    assert feature_enabled(workspace, "queues") is False
    assert feature_enabled(workspace, "blog") is True  # the default, not "anything else is off"


@pytest.mark.django_db
def test_a_stored_value_that_is_not_an_object_takes_the_defaults(workspace):
    settings = _switches(workspace)
    AgencySettings.objects.filter(pk=settings.pk).update(features=["queues"])
    _blog_site(workspace)

    assert feature_enabled(workspace, "queues") is False
    assert feature_enabled(workspace, "blog") is True


@pytest.mark.django_db
def test_no_settings_row_means_defaults_and_creates_none(workspace):
    _blog_site(workspace)

    assert feature_enabled(workspace, "queues") is False
    assert feature_enabled(workspace, "blog") is True
    assert AgencySettings.objects.count() == 0


@pytest.mark.django_db
def test_at_most_two_queries(workspace, django_assert_max_num_queries):
    _blog_site(workspace)
    _switches(workspace)

    with django_assert_max_num_queries(2):
        assert feature_enabled(workspace, "blog") is True


@pytest.mark.django_db
def test_one_query_when_the_switch_is_set(workspace, django_assert_num_queries):
    _blog_site(workspace)
    _switches(workspace, blog=True)

    with django_assert_num_queries(1):
        assert feature_enabled(workspace, "blog") is True


# --- features_for: every key at once ------------------------------------------


def _feature_queries(captured):
    """The captured statements that read a switch or the blog default."""
    return [query["sql"] for query in captured.captured_queries if any(t in query["sql"] for t in FEATURE_TABLES)]


@pytest.mark.django_db
def test_features_for_gives_every_key_as_a_boolean(workspace):
    _switches(workspace, queues=True)

    features = features_for(workspace)

    assert tuple(features) == FEATURE_KEYS
    assert all(type(value) is bool for value in features.values())


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("stored", "enabled_site", "expected_on"),
    [
        pytest.param(None, False, set(), id="no-row-no-site"),
        pytest.param(None, True, {"blog"}, id="no-row-enabled-site"),
        pytest.param({}, True, {"blog"}, id="empty-enabled-site"),
        pytest.param({}, False, set(), id="empty-disabled-site"),
        pytest.param({"blog": False}, True, set(), id="blog-off-wins"),
        pytest.param({"blog": True, "queues": True}, False, {"blog", "queues"}, id="explicit-on"),
        pytest.param(
            {"templates": True, "extra_providers": True, "advanced_settings": True},
            False,
            {"templates", "extra_providers", "advanced_settings"},
            id="the-other-three",
        ),
        pytest.param({"queues": "yes", "blog": "no"}, True, {"blog"}, id="not-booleans"),
        pytest.param(["queues"], True, {"blog"}, id="not-an-object"),
    ],
)
def test_features_for_follows_the_feature_enabled_rules(workspace, stored, enabled_site, expected_on):
    if stored is not None:
        row = _switches(workspace)
        AgencySettings.objects.filter(pk=row.pk).update(features=stored)
    _blog_site(workspace, is_enabled=enabled_site)
    expected = {key: key in expected_on for key in FEATURE_KEYS}

    assert features_for(workspace) == expected
    assert {key: feature_enabled(workspace, key) for key in FEATURE_KEYS} == expected


@pytest.mark.django_db
def test_features_for_without_a_settings_row_creates_none(workspace):
    _blog_site(workspace)

    assert features_for(workspace) == {**ALL_OFF, "blog": True}
    assert AgencySettings.objects.count() == 0


@pytest.mark.django_db
def test_features_for_is_for_its_own_workspace_only(workspace, other_workspace):
    _switches(workspace, queues=True, templates=True)
    _blog_site(workspace)
    _switches(other_workspace)

    assert features_for(workspace) == {**ALL_OFF, "blog": True, "queues": True, "templates": True}
    assert features_for(other_workspace) == ALL_OFF


@pytest.mark.django_db
def test_features_for_reads_at_most_two_queries(workspace, django_assert_max_num_queries):
    _blog_site(workspace)
    _switches(workspace, queues=True)

    with django_assert_max_num_queries(2):
        assert features_for(workspace)["blog"] is True


@pytest.mark.django_db
def test_features_for_reads_one_query_when_blog_is_set(workspace, django_assert_num_queries):
    _blog_site(workspace)
    _switches(workspace, blog=False)

    with django_assert_num_queries(1):
        assert features_for(workspace)["blog"] is False


@pytest.mark.django_db
def test_features_for_without_a_workspace_is_the_defaults_without_a_query(django_assert_num_queries):
    with django_assert_num_queries(0):
        assert features_for(None) == ALL_OFF


# --- request_features: one read per request -------------------------------------


def _request(workspace):
    request = RequestFactory().get("/")
    request.workspace = workspace
    return request


@pytest.mark.django_db
def test_a_request_reads_the_switches_once(workspace, django_assert_max_num_queries, django_assert_num_queries):
    _blog_site(workspace)
    _switches(workspace, queues=True)
    request = _request(workspace)

    with django_assert_max_num_queries(2):
        first = request_features(request)
    with django_assert_num_queries(0):
        second = request_features(request)

    assert first == second == {**ALL_OFF, "blog": True, "queues": True}


@pytest.mark.django_db
def test_a_request_without_a_workspace_reads_nothing(django_assert_num_queries):
    with django_assert_num_queries(0):
        assert request_features(_request(None)) == ALL_OFF
        assert request_features(RequestFactory().get("/")) == ALL_OFF


@pytest.mark.django_db
def test_a_request_that_moves_to_another_workspace_reads_that_one(workspace, other_workspace):
    _switches(workspace, queues=True)
    _switches(other_workspace)
    request = _request(workspace)

    assert request_features(request)["queues"] is True
    request.workspace = other_workspace
    assert request_features(request)["queues"] is False


# --- templates: ``features`` from the sidebar context -------------------------


@pytest.mark.django_db
def test_templates_get_the_requests_switches_read_once(workspace, user, django_assert_num_queries):
    _blog_site(workspace)
    _switches(workspace, templates=True)
    request = _request(workspace)
    request.user = user

    context = sidebar_context(request)

    assert context["features"] == {**ALL_OFF, "blog": True, "templates": True}
    with django_assert_num_queries(0):
        assert request_features(request) == context["features"]


@pytest.mark.django_db
def test_the_sidebar_reads_no_switch_until_a_template_asks(workspace, user):
    _switches(workspace, queues=True)
    request = _request(workspace)
    request.user = user

    with CaptureQueriesContext(connection) as captured:
        context = sidebar_context(request)
    assert _feature_queries(captured) == []

    assert context["features"]["queues"] is True


@pytest.mark.django_db
def test_the_sidebar_without_a_workspace_gives_the_defaults_without_a_lookup(user):
    request = _request(None)
    request.user = user

    with CaptureQueriesContext(connection) as captured:
        context = sidebar_context(request)
        assert context["features"] == ALL_OFF
    assert _feature_queries(captured) == []


@pytest.mark.django_db
def test_a_workspace_page_hands_features_to_its_templates(client, org, workspace, user):
    OrgMembership.objects.create(user=user, organization=org, org_role=OrgMembership.OrgRole.OWNER)
    WorkspaceMembership.objects.create(
        user=user, workspace=workspace, workspace_role=WorkspaceMembership.WorkspaceRole.OWNER
    )
    _switches(workspace, extra_providers=True)
    client.force_login(user)

    response = client.get(reverse("calendar:calendar", kwargs={"workspace_id": workspace.id}))

    assert response.status_code == 200
    assert response.context["features"] == {**ALL_OFF, "extra_providers": True}
