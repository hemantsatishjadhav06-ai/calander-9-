import uuid

import pytest

from apps.inbox.forms import BulkActionForm


@pytest.mark.parametrize("message_ids", ["junk", " , ", f"{uuid.uuid4()},junk"])
def test_invalid_bulk_message_ids_are_form_errors(message_ids):
    form = BulkActionForm({"message_ids": message_ids, "action": "resolve"})
    assert not form.is_valid()
    assert "message_ids" in form.errors


def test_invalid_assignment_id_is_a_form_error():
    form = BulkActionForm({"message_ids": str(uuid.uuid4()), "action": "assign", "value": "junk"})
    assert not form.is_valid()
    assert "value" in form.errors


def test_valid_bulk_ids_are_resolved_as_uuids():
    message_id, assignee_id = uuid.uuid4(), uuid.uuid4()
    form = BulkActionForm({"message_ids": f" {message_id} ,", "action": "assign", "value": str(assignee_id)})
    assert form.is_valid(), form.errors
    assert form.cleaned_data["message_ids"] == [message_id]
    assert form.cleaned_data["value"] == assignee_id
