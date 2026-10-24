"""``feature_enabled``: one workspace's switch, else the key's default.

- A typo in a key fails loudly instead of hiding a feature.
- A switch set for one workspace says nothing about another.
- Blog is on where the workspace already has an enabled blog website, unless
  its switch says otherwise; every other key starts off.
- A workspace without agency settings gets the defaults, and no row is made.
- Read-only, at most two small queries.
"""

import pytest

from apps.blog.models import BlogSite
from apps.common.features import FEATURE_KEYS, feature_enabled
from apps.organizations.models import Organization
from apps.studio.models import AgencySettings
from apps.workspaces.models import Workspace


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
    _switches(workspace, queues="yes")

    assert feature_enabled(workspace, "queues") is False


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
