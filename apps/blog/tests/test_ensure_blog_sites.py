import pytest
from django.core.management import CommandError, call_command

from apps.blog.management.commands.ensure_blog_sites import ensure_blog_sites
from apps.blog.models import BlogSite
from apps.organizations.models import Organization
from apps.workspaces.models import Workspace


@pytest.fixture
def workspaces(db):
    org = Organization.objects.create(name="Owner")
    return (
        Workspace.objects.create(organization=org, name="Neopolis"),
        Workspace.objects.create(organization=org, name="More Space"),
    )


def test_creates_both_sites_once(workspaces):
    neopolis_ws, morespace_ws = workspaces
    first = ensure_blog_sites(neopolis_ws, morespace_ws)
    assert [outcome for _site, outcome in first] == ["created", "created"]
    second = ensure_blog_sites(str(neopolis_ws.id), str(morespace_ws.id))
    assert [outcome for _site, outcome in second] == ["unchanged", "unchanged"]
    assert BlogSite.objects.count() == 2

    neopolis = BlogSite.objects.get(workspace=neopolis_ws)
    assert neopolis.kind == BlogSite.Kind.NEOPOLIS_STATIC
    assert neopolis.site_url == "https://www.neopolisinfra.com"
    assert neopolis.repo == "hemantsatishjadhav06-ai/neopolis-site-deploy"
    assert neopolis.workflow_file == "publish3.yml"
    assert neopolis.netlify_site_id == "47e0a5cc-d9d9-428b-a36b-beea806bff6f"
    morespace = BlogSite.objects.get(workspace=morespace_ws)
    assert morespace.kind == BlogSite.Kind.MORESPACE_STATIC
    assert morespace.site_url == "https://morespace.netlify.app"
    assert morespace.repo == "hemantsatishjadhav06-ai/morespace-website"
    assert morespace.workflow_file == "netlify-publish.yml"
    assert morespace.netlify_site_id == "964e086b-1cf2-47f7-8b78-16909d268319"


def test_corrects_drift_but_keeps_a_site_switched_off(workspaces):
    neopolis_ws, _ = workspaces
    ensure_blog_sites(neopolis_ws, None)
    BlogSite.objects.update(workflow_file="old.yml", is_enabled=False)
    [(site, outcome)] = ensure_blog_sites(neopolis_ws, None)
    assert outcome == "updated" and site.workflow_file == "publish3.yml" and site.is_enabled is False


def test_command(workspaces, capsys):
    neopolis_ws, morespace_ws = workspaces
    call_command("ensure_blog_sites", neopolis_workspace=str(neopolis_ws.id), morespace_workspace=str(morespace_ws.id))
    call_command("ensure_blog_sites", neopolis_workspace=str(neopolis_ws.id))
    assert BlogSite.objects.count() == 2
    assert "Unchanged: Neopolis Infra website" in capsys.readouterr().out
    with pytest.raises(CommandError):
        call_command("ensure_blog_sites")
    with pytest.raises(CommandError):
        call_command("ensure_blog_sites", neopolis_workspace="not-a-uuid")
