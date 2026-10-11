"""Give every existing agent run the workspace of its brief (runs now also belong to jobs)."""

from django.db import migrations
from django.db.models import OuterRef, Subquery


def backfill(apps, schema_editor):
    AgentRun = apps.get_model("studio", "AgentRun")
    StudioBrief = apps.get_model("studio", "StudioBrief")
    AgentRun.objects.filter(workspace__isnull=True, brief__isnull=False).update(
        workspace=Subquery(StudioBrief.objects.filter(pk=OuterRef("brief_id")).values("workspace_id")[:1])
    )


class Migration(migrations.Migration):
    dependencies = [("studio", "0002_agency")]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
