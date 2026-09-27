"""Rewrite retired IANA zone names ("Asia/Calcutta") to current ones ("Asia/Kolkata").

Both names resolve to identical rules, so this only changes what is displayed.
"""

from django.db import migrations

from apps.common.timezones import LEGACY_ZONE_NAMES


def forwards(apps, schema_editor):
    Organization = apps.get_model("organizations", "Organization")
    Workspace = apps.get_model("workspaces", "Workspace")
    for old, new in LEGACY_ZONE_NAMES.items():
        Organization.objects.filter(default_timezone=old).update(default_timezone=new)
        Workspace.objects.filter(timezone=old).update(timezone=new)


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0002_organization_billing_email"),
        ("workspaces", "0003_alter_workspace_primary_color_and_more"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
