import pytest
from pydantic import ValidationError

from app.schemas import EmailObject, EmailRequest, Sender, WebhookEvent


def sample_email(**overrides):
    data = {
        "attachments": [
            {
                "content_type": "application/pdf",
                "filename": "agenda.pdf",
                "grant_id": "grant-1",
                "id": "att-1",
                "size": 1234,
            }
        ],
        "body": "<p>Hello</p>",
        "date": 1731657600,
        "folders": ["INBOX"],
        "from": [{"email": "alice@example.com", "name": "Alice"}],
        "grant_id": "grant-1",
        "id": "msg-1",
        "object": "message",
        "snippet": "Hello",
        "starred": False,
        "subject": "Morning",
        "thread_id": "thread-1",
        "to": [{"email": "bob@example.com", "name": "Bob"}],
        "unread": True,
    }
    data.update(overrides)
    return data


def test_valid_sample_parses_with_defaults():
    email = EmailObject.model_validate(sample_email())
    assert email.from_[0].email == "alice@example.com"
    assert email.attachments[0].is_inline is False
    assert email.attachments[0].content_id is None
    assert email.bcc == [] and email.cc == [] and email.reply_to == []


def test_from_alias_input_both_ways():
    via_alias = EmailObject.model_validate(sample_email())
    data = sample_email()
    data["from_"] = data.pop("from")
    via_name = EmailObject.model_validate(data)
    assert via_alias.from_ == via_name.from_


def test_from_alias_output():
    dumped = EmailObject.model_validate(sample_email()).model_dump(by_alias=True)
    assert "from" in dumped and "from_" not in dumped


def test_sender_name_defaults_to_empty():
    assert Sender(email="noname@example.com").name == ""


@pytest.mark.parametrize("field", ["from", "to", "body", "id", "subject", "date"])
def test_missing_required_field_fails(field):
    data = sample_email()
    del data[field]
    with pytest.raises(ValidationError):
        EmailObject.model_validate(data)


def test_email_request_requires_all_fields():
    with pytest.raises(ValidationError):
        EmailRequest(subject="s", body="b")


def test_webhook_event_parses():
    event = WebhookEvent(
        specversion="1.0",
        type="message.created",
        source="/google/emails/realtime",
        id="evt-1",
        time=1731657600,
        webhook_delivery_attempt=1,
        data={"application_id": "app-1", "object": sample_email()},
    )
    assert event.data["object"]["id"] == "msg-1"
