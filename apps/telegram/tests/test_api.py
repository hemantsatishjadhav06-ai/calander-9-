"""Transport failure tests use invented credentials and never reach Telegram."""

import json
import logging
from unittest.mock import Mock

import pytest
import requests

from apps.telegram.api import MAX_RESPONSE_BYTES, BotAPI, TelegramAPIError

TOKEN = "12345678:" + "a" * 35


def response(result=None, *, status=200, body=None, chunks=None):
    reply = Mock(status_code=status)
    payload = body if body is not None else {"ok": True, "result": result}
    reply.iter_content.return_value = chunks or [json.dumps(payload).encode()]
    return reply


def client(reply):
    session = Mock()
    session.post.return_value = reply
    session.get.return_value = reply
    return BotAPI(TOKEN, session=session), session


def test_verified_identity_uses_fixed_origin_and_disables_redirects():
    api, session = client(response({"id": 12345678, "is_bot": True, "username": "brand_client_bot"}))
    assert api.get_me()["id"] == 12345678
    args, kwargs = session.post.call_args
    assert args[0].startswith("https://api.telegram.org/bot")
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"] == (5, 15)
    assert kwargs["stream"] is True


@pytest.mark.parametrize("identity", [{"id": 1}, {"id": True}, {"id": 12345678, "is_bot": False}, {}])
def test_wrong_bot_identity_is_never_accepted(identity):
    api, _ = client(response(identity))
    with pytest.raises(TelegramAPIError) as caught:
        api.get_me()
    assert caught.value.kind == "invalid_identity"


@pytest.mark.parametrize("method,ambiguous", [("getMe", False), ("sendMessage", True)])
@pytest.mark.parametrize("failure", [requests.ReadTimeout, requests.ConnectionError])
def test_transport_errors_redact_credentials_and_mark_uncertain_writes(method, ambiguous, failure):
    api, session = client(response())
    session.post.side_effect = failure(f"upstream leaked {TOKEN}")
    with pytest.raises(TelegramAPIError) as caught:
        api.call(method)
    assert TOKEN not in str(caught.value)
    assert caught.value.ambiguous is ambiguous
    assert caught.value.__suppress_context__ is True


def test_preconnect_timeout_is_safe_to_retry():
    api, session = client(response())
    session.post.side_effect = requests.ConnectTimeout(TOKEN)
    with pytest.raises(TelegramAPIError) as caught:
        api.call("sendMessage")
    assert caught.value.ambiguous is False


@pytest.mark.parametrize(
    "status,kind", [(401, "unauthorized"), (403, "forbidden"), (409, "conflict"), (302, "rejected")]
)
def test_protocol_errors_ignore_upstream_description(status, kind):
    reply = response(status=status, body={"ok": False, "error_code": status, "description": TOKEN})
    api, _ = client(reply)
    with pytest.raises(TelegramAPIError) as caught:
        api.call("sendMessage")
    assert caught.value.kind == kind
    assert TOKEN not in str(caught.value)
    reply.close.assert_called_once()


@pytest.mark.parametrize("retry,expected", [(-1, 1), (0, 60), (50000, 50000), (True, 60)])
def test_rate_limit_retry_honors_the_server_minimum(retry, expected):
    api, _ = client(response(status=429, body={"ok": False, "parameters": {"retry_after": retry}}))
    with pytest.raises(TelegramAPIError) as caught:
        api.call("sendMessage")
    assert caught.value.retry_after == expected
    assert caught.value.ambiguous is False


def test_lost_worker_session_blocks_transport_before_requests_are_started():
    from apps.common.background import WorkerLeaseLostError, worker_lease_checks

    api, session = client(response({"message_id": 7}))

    def lost_lease():
        raise RuntimeError("worker lease disappeared")

    with worker_lease_checks(lost_lease), pytest.raises(WorkerLeaseLostError):
        api.call("sendMessage", {"chat_id": -123, "text": "Do not send"})
    session.post.assert_not_called()


@pytest.mark.parametrize("method,ambiguous", [("getMe", False), ("sendMessage", True)])
def test_server_failure_cannot_claim_definite_write_failure(method, ambiguous):
    api, _ = client(response(status=503, body={"ok": False, "description": TOKEN}))
    with pytest.raises(TelegramAPIError) as caught:
        api.call(method)
    assert caught.value.ambiguous is ambiguous


def test_oversized_stream_is_closed_and_never_parsed():
    reply = response(chunks=[b"a" * (MAX_RESPONSE_BYTES + 1)])
    api, _ = client(reply)
    with pytest.raises(TelegramAPIError) as caught:
        api.call("sendMessage")
    assert caught.value.kind == "invalid_response"
    assert caught.value.ambiguous is True
    reply.close.assert_called_once()


@pytest.mark.parametrize(
    "path",
    ["../x", "photos/../x", "/photos/x", "photos//x", "https://evil.invalid/x", "photos/x?q=1", "photos/%2e%2e/x"],
)
def test_download_cannot_escape_fixed_file_origin(path):
    api, session = client(response())
    with pytest.raises(TelegramAPIError):
        api.download(path, 1024)
    session.get.assert_not_called()


def test_download_is_bounded_and_closes_response():
    reply = response(chunks=[b"1234", b"5678"])
    api, _ = client(reply)
    with pytest.raises(TelegramAPIError) as caught:
        api.download("photos/ref.jpg", 4)
    assert caught.value.kind == "file_too_large"
    reply.close.assert_called_once()


def test_group_migration_requires_new_identity_verification():
    api, _ = client(response(status=400, body={"ok": False, "parameters": {"migrate_to_chat_id": -10012345}}))
    with pytest.raises(TelegramAPIError) as caught:
        api.call("sendMessage")
    assert caught.value.kind == "chat_migrated"
    assert caught.value.migrate_to_chat_id == -10012345


def test_photo_upload_sanitizes_filename_and_keeps_controls_in_multipart():
    api, session = client(response({"message_id": 10}))
    api.send_photo(123, b"image", '../bad\r\n"name.jpg', reply_markup={"inline_keyboard": []})
    kwargs = session.post.call_args.kwargs
    assert kwargs["files"]["photo"][0] == "bad___name.jpg"
    assert json.loads(kwargs["data"]["reply_markup"]) == {"inline_keyboard": []}
    assert kwargs["allow_redirects"] is False


def test_photo_caption_limit_counts_telegram_utf16_units():
    api, session = client(response())
    with pytest.raises(TelegramAPIError) as caught:
        api.send_photo(123, b"image", "image.jpg", "🧠" * 513)
    assert caught.value.kind == "invalid_caption"
    session.post.assert_not_called()


def test_bool_cannot_impersonate_telegram_user_id():
    api, _ = client(response({"user": {"id": True}, "status": "administrator"}))
    with pytest.raises(TelegramAPIError):
        api.get_chat_member(-100, 1)


def test_unknown_method_has_no_network_effect():
    api, session = client(response())
    with pytest.raises(TelegramAPIError):
        api.call("logout")
    session.post.assert_not_called()


def test_http_debug_log_redacts_credential_before_handlers(caplog):
    with caplog.at_level(logging.DEBUG, logger="urllib3.connectionpool"):
        logging.getLogger("urllib3.connectionpool").debug("POST /bot%s/getMe HTTP/1.1", TOKEN)
    assert "[redacted-bot-token]" in caplog.text
    assert TOKEN not in caplog.text
    assert caplog.records[-1].args == ()


def test_managed_token_retrieval_uses_existing_child_identity_without_rotation():
    child_token = "7654321:" + "c" * 32
    api, session = client(response(child_token))
    assert api.get_managed_bot_token(7654321) == child_token
    assert session.post.call_args.args[0].endswith("/getManagedBotToken")
    assert session.post.call_args.kwargs["json"] == {"user_id": 7654321}


@pytest.mark.parametrize("bot_id", [True, 0, -1, "123456", 2**63])
def test_managed_token_rejects_invalid_child_id_before_network(bot_id):
    api, session = client(response())
    with pytest.raises(TelegramAPIError):
        api.get_managed_bot_token(bot_id)
    session.post.assert_not_called()


@pytest.mark.parametrize("token", [None, {}, "invalid", "7654321:" + "c" * 32])
def test_managed_token_response_must_belong_to_exact_requested_child(token):
    api, _ = client(response(token))
    with pytest.raises(TelegramAPIError, match="could not be verified"):
        api.get_managed_bot_token(654321)


def test_managed_token_read_timeout_is_safe_and_never_exposes_response_credentials():
    api, session = client(response())
    session.post.side_effect = requests.ReadTimeout(TOKEN)
    with pytest.raises(TelegramAPIError) as caught:
        api.get_managed_bot_token(7654321)
    assert caught.value.ambiguous is False and TOKEN not in str(caught.value)


def test_webhook_subscribes_to_authenticated_manager_events():
    api, session = client(response(True))
    api.set_webhook("https://smbean.example.com/webhook", "fake-secret")
    assert "managed_bot" in session.post.call_args.kwargs["json"]["allowed_updates"]
