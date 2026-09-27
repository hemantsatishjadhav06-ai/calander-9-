"""Copy media that still lives on the previous deployment's disk into default storage.

Before object storage, uploads were written to the web container's own disk,
which a redeploy wipes. During the release that switches to S3, the old
deployment keeps serving /media/ until the new one is healthy, so this command
reads every file path the database knows about and, for any that storage does
not have yet, fetches it from ``--source-url`` and saves it under the same key.

Best effort by design: a file that can no longer be fetched is reported and
skipped, and the command always exits 0 so it can never block a release.
"""

import httpx
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand

SOURCES = [
    ("media_library", "MediaAsset", "file"),
    ("media_library", "MediaAsset", "thumbnail"),
    ("media_library", "MediaAssetVersion", "file"),
    ("media_library", "MediaAssetVersion", "thumbnail"),
    ("accounts", "User", "avatar"),
    ("workspaces", "Workspace", "icon"),
]


class Command(BaseCommand):
    help = "Fetch files missing from default storage from the previous deployment's /media/ URL."

    def add_arguments(self, parser):
        parser.add_argument("--source-url", required=True, help="e.g. https://old-host/media/")

    def handle(self, *args, source_url, **options):
        from django.apps import apps

        base = source_url.rstrip("/") + "/"
        copied = present = missing = 0
        with httpx.Client(timeout=120, follow_redirects=True) as client:
            for app_label, model_name, field in SOURCES:
                try:
                    model = apps.get_model(app_label, model_name)
                    names = set(model._base_manager.exclude(**{field: ""}).values_list(field, flat=True))
                except Exception as exc:  # noqa: BLE001 - never block a release
                    self.stderr.write(f"Skipping {model_name}.{field}: {exc}")
                    continue
                for name in sorted(n for n in names if n):
                    try:
                        if default_storage.exists(name):
                            present += 1
                            continue
                        response = client.get(base + name)
                        if response.status_code != 200:
                            missing += 1
                            self.stderr.write(f"Not fetched ({response.status_code}): {name}")
                            continue
                        saved = default_storage.save(name, ContentFile(response.content))
                        if saved != name:
                            self.stderr.write(f"Saved {name} as {saved}")
                        copied += 1
                    except Exception as exc:  # noqa: BLE001
                        missing += 1
                        self.stderr.write(f"Failed {name}: {exc}")
        self.stdout.write(f"Legacy media: {copied} copied, {present} already present, {missing} not recoverable")
