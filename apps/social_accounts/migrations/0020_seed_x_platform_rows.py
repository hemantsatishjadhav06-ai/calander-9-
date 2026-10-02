"""Give X (and any other unseeded platform) its admin toggle rows.

The admin can neither add nor delete ``PlatformVisibility`` or
``AnalyticsPlatformConfig`` rows, so a platform without a row cannot be hidden
from the connect page or seen in the analytics list. For X that matters more
than usual: its API is pay-per-use, and an operator who doesn't want to pay
for it needs a way to switch the connect option off.

Rows are created with the defaults a missing row already implies (visible,
enabled), so nothing changes until an admin flips one. Idempotent.
"""

from django.db import migrations


def seed_missing_platform_rows(apps, schema_editor):
    PlatformVisibility = apps.get_model("social_accounts", "PlatformVisibility")
    AnalyticsPlatformConfig = apps.get_model("social_accounts", "AnalyticsPlatformConfig")
    PlatformCredential = apps.get_model("credentials", "PlatformCredential")
    for value, _label in PlatformCredential._meta.get_field("platform").choices:
        PlatformVisibility.objects.get_or_create(platform=value, defaults={"is_visible": True})
        AnalyticsPlatformConfig.objects.get_or_create(platform=value, defaults={"is_enabled": True})


class Migration(migrations.Migration):
    dependencies = [
        ("social_accounts", "0019_add_x_platform"),
        ("credentials", "0006_add_x_platform"),
    ]

    operations = [
        migrations.RunPython(seed_missing_platform_rows, migrations.RunPython.noop),
    ]
