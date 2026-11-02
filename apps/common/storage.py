"""The media storage used while the bucket does not exist yet.

``STORAGE_BACKEND=s3`` with no ``S3_BUCKET_NAME``: the S3 backend raises on every call, building a
file's URL included, so a page that showed one picture would fail. Settings select this instead. It
holds nothing, finds nothing and refuses every write in plain words; once the bucket's values are
set the S3 backend takes over, with no code change. ``check --deploy`` reports the state (W015).
"""

from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible


class MediaStorageNotReadyError(OSError):
    """A file was to be saved before media storage was set up.

    An ``OSError``, so code that already handles a storage failure handles this one too.
    """


@deconstructible
class PendingMediaStorage(Storage):
    """Saves nothing until the bucket is set up; every read finds nothing."""

    message = "Media storage is not set up yet, so files can't be saved. Ask your owner."

    def _save(self, name, content):
        raise MediaStorageNotReadyError(self.message)

    def _open(self, name, mode="rb"):
        raise FileNotFoundError(name)

    def delete(self, name):
        return None

    def exists(self, name):
        return False

    def listdir(self, path):
        return [], []

    def size(self, name):
        raise FileNotFoundError(name)

    def url(self, name):
        return ""
