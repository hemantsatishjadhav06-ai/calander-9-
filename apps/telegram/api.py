"""Bounded Telegram Bot API transport; credentials never enter errors or logs."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests

from apps.common.background import check_worker_lease

ORIGIN = "https://api.telegram.org"
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_PHOTO_BYTES = 10 * 1024 * 1024
TOKEN_PATTERN = re.compile(r"^[0-9]{5,16}:[A-Za-z0-9_-]{25,100}$")
_LOG_TOKEN_PATTERN = re.compile(r"[0-9]{5,16}:[A-Za-z0-9_-]{25,100}")


class _CredentialFilter(logging.Filter):
    """urllib3 debug logs include the Bot API credential in the request path."""

    def filter(self, record):
        record.msg = _LOG_TOKEN_PATTERN.sub("[redacted-bot-token]", record.getMessage())
        record.args = ()
        return True


for _logger_name in ("urllib3.connectionpool", "requests.packages.urllib3.connectionpool"):
    _http_logger = logging.getLogger(_logger_name)
    if not any(isinstance(item, _CredentialFilter) for item in _http_logger.filters):
        _http_logger.addFilter(_CredentialFilter())

_METHODS = frozenset(
    {
        "getMe",
        "getWebhookInfo",
        "setWebhook",
        "getChatMember",
        "getChat",
        "getFile",
        "getUpdates",
        "sendMessage",
        "sendPhoto",
        "sendDocument",
        "answerCallbackQuery",
        "editMessageReplyMarkup",
        "setMyCommands",
        "getManagedBotToken",
        "getManagedBotAccessSettings",
    }
)
_READ_METHODS = frozenset(
    {
        "getMe",
        "getWebhookInfo",
        "getChatMember",
        "getChat",
        "getFile",
        "getUpdates",
        "getManagedBotToken",
        "getManagedBotAccessSettings",
    }
)


class TelegramAPIError(RuntimeError):
    def __init__(
        self,
        message: str = "Telegram could not complete this request.",
        *,
        kind: str = "unavailable",
        retry_after: int | None = None,
        ambiguous: bool = False,
        migrate_to_chat_id: int | None = None,
    ):
        super().__init__(message)
        self.safe_message = message
        self.kind = kind
        self.retry_after = retry_after
        self.ambiguous = ambiguous
        self.migrate_to_chat_id = migrate_to_chat_id


def valid_token(value: str) -> bool:
    return bool(isinstance(value, str) and TOKEN_PATTERN.fullmatch(value))


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


class BotAPI:
    def __init__(self, token: str, *, session=None):
        if not valid_token(token):
            raise TelegramAPIError("Enter a valid Telegram bot credential.", kind="invalid_token")
        self._token = token
        self._session = session or requests.Session()

    def _response(self, response, *, write: bool):
        try:
            raw = bytearray()
            for chunk in response.iter_content(16384):
                if chunk:
                    raw.extend(chunk)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise TelegramAPIError(
                        "Telegram returned an oversized response.", kind="invalid_response", ambiguous=write
                    )
            try:
                data = json.loads(raw)
            except (TypeError, ValueError, UnicodeError):
                raise TelegramAPIError(
                    "Telegram returned an unreadable response.", kind="invalid_response", ambiguous=write
                ) from None
            if not isinstance(data, dict):
                raise TelegramAPIError(
                    "Telegram returned an invalid response.", kind="invalid_response", ambiguous=write
                )
            code = _integer(data.get("error_code")) or response.status_code
            if response.status_code == 200 and data.get("ok") is True and "result" in data:
                return data["result"]
            parameters = data.get("parameters")
            parameters = parameters if isinstance(parameters, dict) else {}
            retry = _integer(parameters.get("retry_after"))
            migration = _integer(parameters.get("migrate_to_chat_id"))
            if migration is not None and migration < 0:
                raise TelegramAPIError(
                    "The Telegram group changed; verify its new connection.",
                    kind="chat_migrated",
                    migrate_to_chat_id=migration,
                )
            if code == 429:
                raise TelegramAPIError(
                    "Telegram is rate limiting updates.",
                    kind="rate_limited",
                    retry_after=max(1, retry or 60),
                )
            if code == 401:
                raise TelegramAPIError("Telegram rejected this bot credential.", kind="unauthorized")
            if code == 403:
                raise TelegramAPIError(
                    "The bot cannot reach this chat. Check its membership and permissions.", kind="forbidden"
                )
            if code == 409:
                raise TelegramAPIError(
                    "Another receiver is handling this bot. Check its webhook or polling setup.", kind="conflict"
                )
            if code >= 500 or response.status_code >= 500:
                raise TelegramAPIError("Telegram is temporarily unavailable.", kind="unavailable", ambiguous=write)
            raise TelegramAPIError("Telegram rejected the request. Check the bot and chat setup.", kind="rejected")
        except requests.RequestException:
            raise TelegramAPIError(
                "The Telegram response was interrupted.", kind="transport", ambiguous=write
            ) from None
        finally:
            response.close()

    def _request(self, method: str, params: dict | None = None, *, files=None):
        if method not in _METHODS:
            raise TelegramAPIError("This Telegram operation is unavailable.", kind="invalid_method")
        write = method not in _READ_METHODS
        check_worker_lease()
        try:
            kwargs: dict[str, Any] = {"timeout": (5, 15), "allow_redirects": False, "stream": True}
            if files is None:
                response = self._session.post(f"{ORIGIN}/bot{self._token}/{method}", json=params or {}, **kwargs)
            else:
                response = self._session.post(
                    f"{ORIGIN}/bot{self._token}/{method}", data=params or {}, files=files, **kwargs
                )
        except requests.ConnectTimeout:
            raise TelegramAPIError(
                "A connection to Telegram could not be established.", kind="connect", ambiguous=False
            ) from None
        except requests.RequestException:
            raise TelegramAPIError(
                "The Telegram connection failed. Inspect the delivery outcome before retrying.",
                kind="transport",
                ambiguous=write,
            ) from None
        return self._response(response, write=write)

    def call(self, method: str, params: dict | None = None):
        return self._request(method, params)

    def get_me(self) -> dict:
        data = self.call("getMe")
        if (
            not isinstance(data, dict)
            or data.get("is_bot") is not True
            or _integer(data.get("id")) != int(self._token.split(":", 1)[0])
            or not isinstance(data.get("username"), str)
            or not re.fullmatch(r"[A-Za-z0-9_]{5,64}", data["username"])
        ):
            raise TelegramAPIError("The Telegram bot identity could not be verified.", kind="invalid_identity")
        return data

    def get_webhook_info(self) -> dict:
        data = self.call("getWebhookInfo")
        if not isinstance(data, dict):
            raise TelegramAPIError("The Telegram receiver could not be inspected.", kind="invalid_response")
        return data

    def get_managed_bot_token(self, bot_id: int) -> str:
        """Retrieve an existing managed token; this never creates or rotates it."""
        if _integer(bot_id) is None or not 0 < bot_id < 2**63:
            raise TelegramAPIError("A valid managed bot identity is required.", kind="invalid_identity")
        token = self.call("getManagedBotToken", {"user_id": bot_id})
        if not valid_token(token) or int(token.split(":", 1)[0]) != bot_id:
            raise TelegramAPIError("The managed bot credential could not be verified.", kind="invalid_identity")
        return token

    def get_managed_bot_access_settings(self, bot_id: int) -> dict:
        if _integer(bot_id) is None or not 0 < bot_id < 2**63:
            raise TelegramAPIError("A valid managed bot identity is required.", kind="invalid_identity")
        data = self.call("getManagedBotAccessSettings", {"user_id": bot_id})
        if not isinstance(data, dict) or not isinstance(data.get("is_access_restricted"), bool):
            raise TelegramAPIError("The managed bot access settings could not be verified.", kind="invalid_response")
        return data

    def set_webhook(self, url: str, secret: str):
        return self.call(
            "setWebhook",
            {
                "url": url,
                "secret_token": secret,
                "allowed_updates": ["message", "callback_query", "my_chat_member", "managed_bot"],
            },
        )

    def get_chat_member(self, chat_id: int, user_id: int) -> dict:
        data = self.call("getChatMember", {"chat_id": chat_id, "user_id": user_id})
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("user"), dict)
            or _integer(data["user"].get("id")) != user_id
        ):
            raise TelegramAPIError("Telegram chat membership could not be verified.", kind="invalid_response")
        return data

    def get_chat(self, reference: int | str) -> dict:
        if isinstance(reference, bool) or (
            not (isinstance(reference, int) and -(2**63) < reference < 0)
            and not (isinstance(reference, str) and re.fullmatch(r"@[A-Za-z0-9_]{5,32}", reference))
        ):
            raise TelegramAPIError("Enter a channel ID or @username.", kind="invalid_identity")
        data = self.call("getChat", {"chat_id": reference})
        if (
            not isinstance(data, dict)
            or _integer(data.get("id")) is None
            or not -(2**63) < data["id"] < 0
            or (isinstance(reference, int) and data["id"] != reference)
        ):
            raise TelegramAPIError("The Telegram channel could not be verified.", kind="invalid_response")
        return data

    def get_file(self, file_id: str) -> dict:
        if not isinstance(file_id, str) or not 1 <= len(file_id) <= 256:
            raise TelegramAPIError("Choose a supported Telegram reference file.", kind="invalid_file")
        data = self.call("getFile", {"file_id": file_id})
        if not isinstance(data, dict) or not isinstance(data.get("file_path"), str):
            raise TelegramAPIError("The reference file could not be located.", kind="invalid_response")
        return data

    def download(self, file_path: str, max_bytes: int) -> bytes:
        if (
            not isinstance(file_path, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,250}", file_path)
            or any(part in {"", ".", ".."} for part in file_path.split("/"))
            or not isinstance(max_bytes, int)
            or isinstance(max_bytes, bool)
            or not 1 <= max_bytes <= 20 * 1024 * 1024
        ):
            raise TelegramAPIError("The reference file path or size is invalid.", kind="invalid_file")
        response = None
        check_worker_lease()
        try:
            response = self._session.get(
                f"{ORIGIN}/file/bot{self._token}/{file_path}", timeout=(5, 15), allow_redirects=False, stream=True
            )
            if response.status_code != 200:
                raise TelegramAPIError("The Telegram reference file is unavailable.", kind="file_unavailable")
            output = bytearray()
            for chunk in response.iter_content(16384):
                if chunk:
                    output.extend(chunk)
                if len(output) > max_bytes:
                    raise TelegramAPIError("The reference file exceeds the allowed size.", kind="file_too_large")
            if not output:
                raise TelegramAPIError("The reference file is empty.", kind="invalid_file")
            return bytes(output)
        except requests.RequestException:
            raise TelegramAPIError("The Telegram reference download failed.", kind="transport") from None
        finally:
            if response is not None:
                response.close()

    def send_photo(self, chat_id: int, content: bytes, filename: str, caption: str = "", reply_markup=None) -> dict:
        if not isinstance(content, bytes) or not 1 <= len(content) <= MAX_PHOTO_BYTES:
            raise TelegramAPIError("The graphic exceeds Telegram's photo size limit.", kind="invalid_file")
        if len(caption.encode("utf-16-le")) // 2 > 1024:
            raise TelegramAPIError(
                "The photo caption is too long; send its complete text separately.", kind="invalid_caption"
            )
        filename = re.sub(r"[^A-Za-z0-9_.-]", "_", filename.rsplit("/", 1)[-1])[:100] or "graphic.jpg"
        params: dict[str, Any] = {"chat_id": chat_id, "caption": caption}
        if reply_markup is not None:
            params["reply_markup"] = json.dumps(reply_markup)
        data = self._request("sendPhoto", params, files={"photo": (filename, content, "application/octet-stream")})
        if not isinstance(data, dict):
            raise TelegramAPIError(
                "The graphic delivery could not be confirmed.", kind="invalid_response", ambiguous=True
            )
        return data
