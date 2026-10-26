"""Heavy page-specific libraries must not consume every page's mobile JS budget."""

from html.parser import HTMLParser

import pytest
from django.urls import reverse

from apps.members.models import WorkspaceMembership
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace


class ScriptSources(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.sources = []
        self.scripts = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "script" and (src := dict(attrs).get("src")):
            self.sources.append(src)
            self.scripts.append(dict(attrs))


@pytest.fixture
def pages(client, org_owner, organization):
    workspace = Workspace.objects.create(organization=organization, name="Script budgets")
    WorkspaceMembership.objects.create(user=org_owner, workspace=workspace, workspace_role="owner")
    account = SocialAccount.objects.create(
        workspace=workspace,
        platform="linkedin_company",
        account_platform_id="script-budget-account",
        account_name="Script budget account",
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
    )
    client.force_login(org_owner)
    return client, workspace, account


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("route", "query", "chart", "sortable"),
    [
        ("studio:index", "", False, False),
        ("calendar:calendar", "?mode=calendar&view=week", False, True),
        ("calendar:calendar", "?mode=list&tab=approvals", False, True),
        ("analytics:account", "", True, False),
    ],
)
def test_only_pages_that_use_a_vendor_library_load_it(pages, route, query, chart, sortable):
    client, workspace, account = pages
    kwargs = {"workspace_id": workspace.pk}
    if route == "analytics:account":
        kwargs["account_id"] = account.pk
    response = client.get(reverse(route, kwargs=kwargs) + query)
    assert response.status_code == 200
    sources = ScriptSources(response.content.decode()).sources
    assert any("chart.umd" in src for src in sources) is chart
    assert any("Sortable.min" in src for src in sources) is sortable
    assert sum("chart.umd" in src for src in sources) <= 1
    assert sum("Sortable.min" in src for src in sources) <= 1


@pytest.mark.django_db
def test_calendar_dnd_download_does_not_block_parsing_and_executes_before_alpine(pages):
    client, workspace, _ = pages
    response = client.get(reverse("calendar:calendar", kwargs={"workspace_id": workspace.pk}))
    assert response.status_code == 200
    scripts = ScriptSources(response.content.decode()).scripts
    sortable = next(script for script in scripts if "Sortable.min" in script["src"])
    alpine = next(script for script in scripts if "/alpine.min" in script["src"])
    assert "defer" in sortable
    assert "defer" in alpine
    assert scripts.index(sortable) < scripts.index(alpine)
