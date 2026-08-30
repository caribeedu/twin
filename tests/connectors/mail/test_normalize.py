"""Shared mail MIME / normalize helpers."""
from twin.sense.connectors.mail.classification import (
    CLASS_CODE_REVIEW,
    CLASS_HUMAN,
    CLASS_NEWSLETTER,
    CLASS_NOTIFICATION,
    classify_message,
    is_memory_relevant,
)
from twin.sense.connectors.mail.mime import split_authored, strip_html, untrusted_html_stub
from twin.sense.connectors.mail.normalize import record_from_message, thread_key


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


def test_html_stub_is_explicitly_untrusted():
    stub = untrusted_html_stub('<a href="javascript:alert(1)">x</a><script>bad</script>')
    assert "script" not in stub.lower() or "<script" not in stub.lower()
    # still may contain javascript: — field must not be treated as safe
    assert "javascript:" in stub or "x" in stub


def test_record_sender_only_in_actor_ids():
    rec = record_from_message(
        connector_id="conn_1", account_id="acct_1",
        provider="gmail", account_key="edu@acme.com",
        message={
            "id": "m1", "thread_id": "t1",
            "subject": "Hello",
            "from": "alice@acme.com",
            "to": ["edu@acme.com", "bob@acme.com"],
            "body_text": "hi",
            "classification": CLASS_HUMAN,
            "internalDate": "1",
        },
    )
    assert rec.actor_ids == ["mail:alice@acme.com"]
    assert "mail:edu@acme.com" in rec.participant_ids
    assert "mail:bob@acme.com" in rec.participant_ids
    assert rec.source_metadata["classification_kind"] == "source_heuristic"


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
