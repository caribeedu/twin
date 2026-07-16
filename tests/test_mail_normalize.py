"""Shared mail normalize / classification unit tests."""

from twin.connectors.mail.classification import (
    CLASS_CODE_REVIEW,
    CLASS_HUMAN,
    CLASS_NEWSLETTER,
    CLASS_NOTIFICATION,
    classify_message,
    is_memory_relevant,
)
from twin.connectors.mail.mime import split_authored, strip_html
from twin.connectors.mail.normalize import record_from_message, thread_key


def test_classify_noreply_and_newsletter():
    assert classify_message(from_addr="noreply@github.com",
                            subject="PR merged") == CLASS_CODE_REVIEW
    assert classify_message(from_addr="news@list.com",
                            body="Click unsubscribe below") == CLASS_NEWSLETTER
    assert classify_message(from_addr="bot@acme.com",
                            headers={"Auto-Submitted": "auto-generated"}
                            ) == CLASS_NOTIFICATION
    assert classify_message(from_addr="alice@acme.com",
                            subject="Decision: use Postgres",
                            body="We decided.") == CLASS_HUMAN


def test_split_authored_strips_quote_and_signature():
    body = "New decision.\n\nOn Mon, Alice wrote:\n> old stuff\n--\nSent from my iPhone"
    parts = split_authored(body)
    assert "New decision" in parts["authored"]
    assert "old stuff" in parts["quoted"] or parts["quoted"].startswith("On Mon")
    assert "Sent from my iPhone" in parts["signature"] or parts["signature"].startswith("--")


def test_strip_html_removes_tags():
    assert strip_html("<p>Hello <b>world</b></p>") == "Hello world"


def test_record_thread_key_and_derived_notification():
    rec = record_from_message(
        connector_id="conn_1", account_id="acct_1",
        provider="gmail", account_key="edu@acme.com",
        message={
            "id": "m1", "thread_id": "t1",
            "subject": "[GitHub] PR opened",
            "from": "notifications@github.com",
            "body_text": "opened a pull request",
            "classification": CLASS_CODE_REVIEW,
            "internalDate": "1",
        },
    )
    assert rec.thread_key == thread_key("gmail", "edu@acme.com", "t1")
    assert rec.source_metadata["derived"] == "likely_notification"
    assert not is_memory_relevant(CLASS_CODE_REVIEW)
    assert rec.confidentiality["source_trust"] == 0.40
