"""Set the Site name/domain from SITE_NAME/APP_URL instead of the old brand.

Migration 0004 hardcoded name="Brightbean" / domain="studio.brightbean.xyz".
The Site name/domain surface in allauth's default emails (e.g. the password-reset
message), so they must reflect the current brand and deployment. This derives
them from settings at deploy time; re-run migrate after changing SITE_NAME/APP_URL.
"""

from urllib.parse import urlparse

from django.conf import settings
from django.db import migrations


def set_site(apps, schema_editor):
    Site = apps.get_model("sites", "Site")
    name = getattr(settings, "SITE_NAME", "") or "SM Bean"
    app_url = getattr(settings, "APP_URL", "") or ""
    host = urlparse(app_url).netloc
    defaults = {"name": name}
    # Only override the domain when APP_URL gives us a real host (not the
    # localhost dev default); otherwise leave whatever is there.
    if host and "localhost" not in host and "127.0.0.1" not in host:
        defaults["domain"] = host
    Site.objects.update_or_create(id=1, defaults=defaults)


def noop(apps, schema_editor):
    # No reverse: we don't want to restore the old brand.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_set_site_brightbean"),
        ("sites", "0002_alter_domain_unique"),
    ]
    operations = [migrations.RunPython(set_site, noop)]
