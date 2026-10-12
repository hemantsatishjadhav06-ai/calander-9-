import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.media_library.storage import reset_cached_client
from apps.members.models import OrgMembership
from apps.organizations.models import Organization


@pytest.fixture
def user(db):
    return User.objects.create_user(
        email="test@example.com", password="testpass123", name="Test User", tos_accepted_at=timezone.now()
    )


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Test Organization")


@pytest.fixture
def org_owner(db, user, organization):
    OrgMembership.objects.create(user=user, organization=organization, org_role=OrgMembership.OrgRole.OWNER)
    return user


@pytest.fixture(autouse=True)
def _fresh_storage_client():
    """Keep the memoized boto3 client from leaking across tests.

    ``apps.media_library.storage`` caches one client for the life of the
    process — the point is to stop django-storages rebuilding a boto3 Session
    per thread. Without this, the first test to touch S3 would pin its client
    and every later ``override_settings`` on a bucket or endpoint would be
    silently ignored.
    """
    reset_cached_client()
    yield
    reset_cached_client()


@pytest.fixture(autouse=True)
def _no_live_claude(monkeypatch):
    """No test may reach the Anthropic API: a test that needs Claude fakes it.

    ``apps.studio.tests.test_llm`` replaces ``get_client`` with its own stand-in,
    which overrides this.
    """
    from apps.studio import llm

    def refuse():
        raise AssertionError("A test tried to call the Anthropic API; fake the agent instead.")

    monkeypatch.setattr(llm, "get_client", refuse)


@pytest.fixture(autouse=True)
def _no_live_openrouter(monkeypatch):
    """Provider tests explicitly install a MockTransport; never spend credits."""
    from apps.studio import openrouter

    def refuse():
        raise AssertionError("A test tried to call OpenRouter; replace the HTTP transport with a mock.")

    monkeypatch.setattr(openrouter, "get_client", refuse)


@pytest.fixture(autouse=True)
def _no_live_creative_sources(monkeypatch):
    """Source tests install a MockTransport; other tests get an unavailable source."""
    import httpx

    from apps.studio import creative_sources

    def refuse():
        raise httpx.ConnectError("Source networking is disabled in tests; install a mocked transport.")

    monkeypatch.setattr(creative_sources, "get_client", refuse)
