"""Bounded Telegram references attributed to their current paired sender.

Photos and passive PDF files use the canonical scoped media service. Plain
UTF-8 references return untrusted text for the conversation bridge, because the
media library does not support text assets. No upload verifies a property photo
or a commercial fact, creates a draft, or approves publication.
"""

from __future__ import annotations

import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction

from apps.media_library.models import MediaAsset
from apps.media_library.quotas import StorageQuotaExceededError
from apps.media_library.services import create_asset, open_image
from apps.media_library.validators import sniff_mime

MAX_PHOTO_BYTES = 10 * 1024 * 1024
MAX_DOCUMENT_BYTES = 4 * 1024 * 1024
MAX_TEXT_BYTES = 64 * 1024
MAX_PHOTO_PIXELS = 20_000_000
MAX_TEXT_EXCERPT = 3000
IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_DOCUMENT_MIMES = IMAGE_MIMES | {"application/pdf", "text/plain"}
_SAFE_PATH = re.compile(r"(?:[A-Za-z0-9_-]+/)+[A-Za-z0-9_.-]+\Z")


class ReferenceUploadError(ValueError):
    """A deliberately safe user-facing error, without transport URLs or tokens."""

    def __init__(self, message: str, *, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


@dataclass(frozen=True)
class ReferenceUpload:
    asset: MediaAsset | None
    kind: str
    filename: str
    mime_type: str
    text_excerpt: str = ""
    warning: str = "Unverified reference. The team must check its facts and photo provenance."


@dataclass(frozen=True)
class _Binding:
    connection_id: Any
    workspace_id: Any
    bot_id: int
    token_hash: bytes
    chat_id: Any
    native_chat_id: int
    conversation_id: Any
    link_id: Any
    user_id: Any
    telegram_user_id: int


def _token_hash(connection) -> bytes:
    return hashlib.sha256((connection.token or "").encode()).digest()


def _fresh_scope(binding: _Binding, message: dict, *, locked=False):
    from apps.studio.models import Conversation

    from .models import TelegramChat, TelegramConnection, TelegramUserLink
    from .permissions import fresh_member, internal_member

    link = TelegramUserLink.objects.filter(pk=binding.link_id).first()
    if link is None or link.connection_id != binding.connection_id or link.user_id != binding.user_id:
        raise ReferenceUploadError("Your paired workspace access changed. Pair your account again.")
    try:
        member = fresh_member(link, locked=locked)
    except PermissionDenied:
        raise ReferenceUploadError("Your current paired workspace access is required for references.") from None
    if member is None:
        raise ReferenceUploadError("Your current paired workspace access is required for references.")

    # fresh_member obtains workspace/org/user/connection/link locks in the shared
    # order. Chat and conversation follow; no Telegram request runs in this block.
    connection = TelegramConnection.objects.filter(pk=binding.connection_id, is_active=True).first()
    link = TelegramUserLink.objects.filter(pk=binding.link_id, is_active=True).first()
    chats = TelegramChat.objects.select_for_update(of=("self",)) if locked else TelegramChat.objects.all()
    chat = chats.filter(pk=binding.chat_id, connection_id=binding.connection_id, is_active=True).first()
    if (
        connection is None
        or link is None
        or chat is None
        or connection.workspace_id != binding.workspace_id
        or connection.bot_id != binding.bot_id
        or _token_hash(connection) != binding.token_hash
        or member.workspace_id != binding.workspace_id
        or member.user_id != binding.user_id
        or link.connection_id != binding.connection_id
        or link.user_id != binding.user_id
        or link.telegram_user_id != binding.telegram_user_id
        or chat.chat_id != binding.native_chat_id
        or chat.conversation_id != binding.conversation_id
    ):
        raise ReferenceUploadError("This reference no longer belongs to the paired workspace conversation.")
    conversations = Conversation.objects.select_for_update(of=("self",)) if locked else Conversation.objects.all()
    conversation = conversations.filter(pk=chat.conversation_id, workspace_id=binding.workspace_id).first()
    if conversation is None:
        raise ReferenceUploadError("This chat is not bound to a current workspace conversation.")
    sender = message.get("from")
    native_chat = message.get("chat")
    if (
        not isinstance(sender, dict)
        or type(sender.get("id")) is not int
        or sender["id"] != link.telegram_user_id
        or sender.get("is_bot")
        or message.get("sender_chat") is not None
        or not isinstance(native_chat, dict)
        or type(native_chat.get("id")) is not int
        or native_chat["id"] != chat.chat_id
    ):
        raise ReferenceUploadError("Send the reference yourself from your paired account in its linked chat.")
    is_client = not internal_member(member)
    if chat.audience == TelegramChat.Audience.CLIENT:
        if conversation.audience != Conversation.Audience.CLIENT:
            raise ReferenceUploadError("Client references must stay in the client conversation.")
    elif chat.audience == TelegramChat.Audience.PRIVATE:
        if chat.private_user_id != link.user_id or chat.chat_id != link.telegram_user_id:
            raise ReferenceUploadError("This private chat belongs to a different paired person.")
        if is_client and conversation.audience != Conversation.Audience.CLIENT:
            raise ReferenceUploadError("Client references must stay in the client conversation.")
    elif chat.audience == TelegramChat.Audience.TEAM:
        if is_client or conversation.audience != Conversation.Audience.INTERNAL:
            raise ReferenceUploadError("Internal team references require current internal workspace access.")
    else:
        raise ReferenceUploadError("This chat is not an enabled reference destination.")
    if not is_client and not member.effective_permissions.get("upload_media"):
        raise ReferenceUploadError("Your current role does not allow reference uploads.")
    return connection, chat, link, member


def _safe_filename(raw: Any, fallback: str) -> str:
    if not isinstance(raw, str):
        return fallback
    leaf = raw.replace("\\", "/").rsplit("/", 1)[-1]
    leaf = "".join(character for character in leaf if unicodedata.category(character) not in {"Cc", "Cf"})
    return leaf.strip().lstrip(".")[:180] or fallback


def _check_size(value: Any, limit: int):
    if value is not None and (type(value) is not int or value <= 0 or value > limit):
        raise ReferenceUploadError("This reference is too large or has invalid file metadata.")


def _selection(message: dict):
    photos = message.get("photo")
    document = message.get("document")
    if photos and document:
        raise ReferenceUploadError("Send one supported reference type at a time.")
    if photos:
        if not isinstance(photos, list) or len(photos) > 20:
            raise ReferenceUploadError("Send a JPEG, PNG or WebP still photo.")
        valid = []
        for photo in photos:
            if not isinstance(photo, dict):
                continue
            width, height = photo.get("width"), photo.get("height")
            if type(width) is not int or type(height) is not int or min(width, height) <= 0:
                continue
            if width * height > MAX_PHOTO_PIXELS:
                continue
            try:
                _check_size(photo.get("file_size"), MAX_PHOTO_BYTES)
            except ReferenceUploadError:
                continue
            valid.append(photo)
        if not valid:
            raise ReferenceUploadError("Use a still photo under 10 MiB and 20 megapixels.")
        selected = max(valid, key=lambda photo: photo["width"] * photo["height"])
        return selected, "photo", "telegram-reference.jpg", "", MAX_PHOTO_BYTES
    if not isinstance(document, dict):
        raise ReferenceUploadError("References support JPEG, PNG, WebP, PDF or plain UTF-8 text only.")
    mime = document.get("mime_type", "")
    mime = mime.split(";", 1)[0].strip().lower() if isinstance(mime, str) else ""
    raw_name = document.get("file_name", "")
    suffix = PurePosixPath(raw_name if isinstance(raw_name, str) else "").suffix.lower()
    if not mime:
        mime = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".pdf": "application/pdf",
            ".txt": "text/plain",
        }.get(suffix, "")
    if mime not in ALLOWED_DOCUMENT_MIMES:
        raise ReferenceUploadError("References support JPEG, PNG, WebP, PDF or plain UTF-8 text only.")
    kind = "photo" if mime in IMAGE_MIMES else "text" if mime == "text/plain" else "document"
    limit = MAX_PHOTO_BYTES if kind == "photo" else MAX_TEXT_BYTES if kind == "text" else MAX_DOCUMENT_BYTES
    _check_size(document.get("file_size"), limit)
    return document, kind, _safe_filename(raw_name, "telegram-reference"), mime, limit


def _file_path(value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 512
        or not _SAFE_PATH.fullmatch(value)
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ReferenceUploadError("Telegram returned an unsupported file location.")
    return value


def _photo(data: bytes, expected_mime: str, filename: str):
    uploaded = SimpleUploadedFile(filename, data)
    mime = sniff_mime(uploaded)
    if mime not in IMAGE_MIMES or (expected_mime and mime != expected_mime):
        raise ReferenceUploadError("The reference must be a genuine JPEG, PNG or WebP still image.")
    try:
        with open_image(uploaded) as picture:
            width, height = picture.size
            limit = min(MAX_PHOTO_PIXELS, getattr(settings, "MEDIA_LIBRARY_MAX_IMAGE_PIXELS", MAX_PHOTO_PIXELS))
            if min(width, height) <= 0 or width * height > limit or getattr(picture, "n_frames", 1) != 1:
                raise ReferenceUploadError("Use a still photo under 20 megapixels.")
            picture.verify()
        with open_image(uploaded) as picture:
            from PIL import ImageOps

            picture.load()
            picture = ImageOps.exif_transpose(picture)
            width, height = picture.size
            output = io.BytesIO()
            target_format = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}[mime]
            if target_format == "JPEG" and picture.mode not in {"RGB", "L"}:
                picture = picture.convert("RGB")
            options = {"quality": 95} if target_format in {"JPEG", "WEBP"} else {}
            picture.save(output, format=target_format, **options)
            sanitized = output.getvalue()
        if len(sanitized) > MAX_PHOTO_BYTES:
            raise ReferenceUploadError("The decoded reference exceeds the 10 MiB photo limit.")
    except ReferenceUploadError:
        raise
    except Exception:
        raise ReferenceUploadError("The photo could not be decoded safely. Send a complete still image.") from None
    name = _safe_filename(filename, "telegram-reference")
    return SimpleUploadedFile(name, sanitized, content_type=mime), mime, width, height


def _text(data: bytes) -> tuple[str, str]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ReferenceUploadError("Send plain UTF-8 text, or paste the exact facts into this chat.") from None
    if not text.strip() or any(unicodedata.category(char) == "Cc" and char not in "\n\r\t" for char in text):
        raise ReferenceUploadError("The reference must contain readable plain UTF-8 text.")
    if re.match(r"\s*<(?:!doctype|html|svg|script|\?xml)\b", text, flags=re.I):
        raise ReferenceUploadError("HTML, XML and SVG are not supported reference documents.")
    text = "".join(char for char in text if unicodedata.category(char) != "Cf")
    truncated = len(text) > MAX_TEXT_EXCERPT
    warning = "Untrusted reference text; its facts require human verification."
    if truncated:
        warning += " Only the first 3000 characters are included; paste any missing facts yourself."
    return text[:MAX_TEXT_EXCERPT], warning


def _pdf(data: bytes, filename: str):
    # Storage-only validation. No PDF parser, rendering, extraction or model
    # read is promised; a human must paste exact claims for the guided brief.
    if not re.match(rb"%PDF-(?:1\.[0-7]|2\.0)(?:\r|\n|\s)", data) or not data.rstrip().endswith(b"%%EOF"):
        raise ReferenceUploadError("Send a complete PDF, or paste the exact source text into this chat.")
    # Reject recognizable interactive/embedded content, including escaped PDF
    # names. This is conservative inspection, not malware scanning or proof of
    # every PDF object's safety; references are never executed by this service.
    names = re.sub(rb"#([0-9a-fA-F]{2})", lambda match: bytes.fromhex(match[1].decode()), data)
    if re.search(rb"/(?:JavaScript|JS|OpenAction|AA|Launch|EmbeddedFile|RichMedia|AcroForm|XFA|Encrypt)\b", names):
        raise ReferenceUploadError(
            "Interactive, encrypted or embedded PDF content is unsupported. Paste the source text."
        )
    return SimpleUploadedFile(filename, data, content_type="application/pdf")


def receive_reference(connection, chat, link, message, *, api=None) -> ReferenceUpload:
    """Accept a supported reference from the exact current paired conversation.

    Forwarding metadata never identifies or authorizes a sender: the actual
    paired ``message.from.id`` remains authoritative. PDF files are stored only;
    plain text is returned only for the already-scoped conversation bridge.
    """
    if not isinstance(message, dict) or type(message.get("message_id")) is not int or message["message_id"] <= 0:
        raise ReferenceUploadError("Send a genuine reference message in the linked Telegram conversation.")
    binding = _Binding(
        connection.pk,
        connection.workspace_id,
        connection.bot_id,
        _token_hash(connection),
        chat.pk,
        chat.chat_id,
        chat.conversation_id,
        link.pk,
        link.user_id,
        link.telegram_user_id,
    )
    current_connection, current_chat, _, _ = _fresh_scope(binding, message)
    selected, kind, filename, expected_mime, limit = _selection(message)
    if current_chat.audience == "private" and kind in {"photo", "document"}:
        if any(
            message.get(key) for key in ("forward_origin", "forward_from", "forward_from_chat", "is_automatic_forward")
        ):
            raise ReferenceUploadError(
                "A forwarded caption cannot confirm your choice to use the shared brand media library and publicly accessible publishing storage. "
                "Resend the file yourself with your own /reference shared caption. No file was downloaded or saved."
            )
        caption = message.get("caption")
        sharing_caption = "/reference shared"
        if not isinstance(caption, str) or not (
            caption == sharing_caption or caption.startswith(sharing_caption + " ")
        ):
            raise ReferenceUploadError(
                "Photos and PDFs become part of the shared brand media library and publicly accessible publishing storage, even before post approval. "
                "To share this file, resend it with the exact caption /reference shared (then an optional note), "
                "or send it in the intended group. No file was downloaded or saved."
            )
    file_id = selected.get("file_id")
    if (
        not isinstance(file_id, str)
        or not file_id
        or len(file_id) > 1024
        or not re.fullmatch(r"[A-Za-z0-9_=-]+", file_id)
    ):
        raise ReferenceUploadError("Telegram did not supply a supported reference file.")
    source_key = (
        "tg-ref:"
        + hashlib.sha256(
            f"{binding.connection_id}:{binding.chat_id}:{message['message_id']}:{file_id}".encode()
        ).hexdigest()
    )
    if api is None:
        from .api import BotAPI

        api = BotAPI(current_connection.token)
    try:
        metadata = api.get_file(file_id)
        if not isinstance(metadata, dict):
            raise ReferenceUploadError("Telegram did not supply supported reference metadata.")
        _check_size(metadata.get("file_size"), limit)
        path = _file_path(metadata.get("file_path"))
        _fresh_scope(binding, message)
        data = api.download(path, max_bytes=limit)
    except ReferenceUploadError:
        raise
    except Exception as exc:
        retry_after = getattr(exc, "retry_after", None)
        retry_after = retry_after if type(retry_after) is int and 0 <= retry_after <= 3600 else None
        raise ReferenceUploadError(
            "Telegram could not retrieve this reference. Try again later.", retry_after=retry_after
        ) from None
    _fresh_scope(binding, message)
    if not isinstance(data, bytes) or not data or len(data) > limit:
        raise ReferenceUploadError("Telegram returned an empty or oversized reference.")
    if metadata.get("file_size") is not None and metadata["file_size"] != len(data):
        raise ReferenceUploadError("The reference download is incomplete. Send the file again.")
    if kind == "text":
        excerpt, warning = _text(data)
        with transaction.atomic():
            _fresh_scope(binding, message, locked=True)
        return ReferenceUpload(None, "text", filename, "text/plain", excerpt, warning)
    width = height = 0
    if kind == "photo":
        uploaded, _, width, height = _photo(data, expected_mime, filename)
    else:
        uploaded = _pdf(data, filename)
    asset = None
    try:
        with transaction.atomic():
            _, _, _, member = _fresh_scope(binding, message, locked=True)
            asset = MediaAsset.objects.filter(
                workspace=member.workspace,
                uploaded_by=member.user,
                source="telegram-reference",
                tags__contains=[source_key],
            ).first()
            if asset is None:
                asset = create_asset(
                    member.workspace.organization,
                    member.workspace,
                    uploaded,
                    member.user,
                    title=filename,
                    source="telegram-reference",
                    tags=["telegram", "reference", source_key],
                )
                asset.width, asset.height = width, height
                asset.save(update_fields=["width", "height"])
                from apps.media_library.tasks import process_media_asset

                transaction.on_commit(lambda: process_media_asset(str(asset.pk)))
    except (ValidationError, StorageQuotaExceededError):
        raise ReferenceUploadError(
            "This reference exceeds the allowed media or storage limits. Ask the team to review it."
        ) from None
    except ReferenceUploadError:
        raise
    except Exception:
        raise ReferenceUploadError("This reference could not be saved. Ask the team to try again later.") from None
    warning = (
        "Unverified PDF saved as a reference only. Paste exact facts into this chat; no PDF text was read or verified."
        if kind == "document"
        else "Unverified supplied photo. A current human approver must verify its project and campaign provenance."
    )
    warning += " Saved in the shared brand media library and publicly accessible publishing storage."
    return ReferenceUpload(
        asset,
        kind,
        asset.filename,
        asset.mime_type,
        warning=warning,
    )


upload_reference = receive_reference
