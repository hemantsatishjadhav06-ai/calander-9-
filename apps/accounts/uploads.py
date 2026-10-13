"""Validate account/workspace images before storing them on the media origin."""

import uuid

from django import forms
from django.core.exceptions import ValidationError

_IMAGE_EXTENSIONS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "GIF": ".gif"}


def validate_profile_image(upload, *, minimum_dimension=0):
    """Verify image bytes and assign the suffix of their detected format.

    Uploaded Content-Type and filenames are untrusted. In particular, a valid
    image named ``.html`` can otherwise be served as active HTML from /media/.
    Django's ImageField uses Pillow to verify the image and resets its pointer.
    """
    # Use the byte-verification step directly: the default filename-extension
    # validator would reject a correctly encoded PNG whose name ends in .html.
    # The detected format allowlist below replaces that untrusted suffix check.
    image_file = forms.ImageField().to_python(upload)
    image = image_file.image
    extension = _IMAGE_EXTENSIONS.get(image.format)
    if extension is None:
        raise ValidationError("Choose a JPEG, PNG, WebP, or GIF image.")
    if image.width * image.height > 20_000_000:
        raise ValidationError("Image dimensions are too large. Choose an image under 20 megapixels.")
    if min(image.width, image.height) < minimum_dimension:
        raise ValidationError(f"Photo must be at least {minimum_dimension}×{minimum_dimension} pixels.")
    image_file.name = f"{uuid.uuid4().hex}{extension}"
    return image_file
