"""Media storage that is not set up yet: the app runs, and uploads are refused in plain words.

The owner creates the Cloudflare R2 bucket after the first deploy. With ``STORAGE_BACKEND=s3`` and no
``S3_BUCKET_NAME`` the S3 backend raises on every call, including building a file's URL, so any page
that showed a picture would fail. Settings select a stand-in that saves nothing and fails only the
writes. ``check --deploy`` still stops a deployment that is missing its bucket by accident; one that
says ``MEDIA_STORAGE_PENDING=true`` is told in a warning instead, and setting the bucket's values is
all it takes to switch to R2 (the check itself is in ``test_deployment_checks``).
"""

import pytest
from django.core.files.base import ContentFile

from apps.common.storage import MediaStorageNotReadyError, PendingMediaStorage


@pytest.fixture
def storage():
    return PendingMediaStorage()


def test_saving_is_refused_in_plain_words(storage):
    with pytest.raises(MediaStorageNotReadyError) as caught:
        storage.save("media/upload.png", ContentFile(b"\x89PNG"))
    assert "not set up yet" in str(caught.value)
    # A storage failure, so code that already handles one (OSError) handles this too.
    assert isinstance(caught.value, OSError)


def test_reading_finds_nothing(storage):
    assert storage.exists("media/upload.png") is False
    with pytest.raises(FileNotFoundError):
        storage.open("media/upload.png")
    with pytest.raises(FileNotFoundError):
        storage.size("media/upload.png")
    assert storage.listdir("media") == ([], [])


def test_pages_that_show_a_file_still_render(storage):
    """No URL to give, and no exception either: the page shows an empty picture, not an error."""
    assert storage.url("media/upload.png") == ""


def test_deleting_is_a_no_op(storage):
    storage.delete("media/upload.png")
