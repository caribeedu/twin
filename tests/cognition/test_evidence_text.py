"""Session-summary fold labels and evidence quote hygiene."""

from twin.clock import now_iso
from twin.cognize.services.evidence_text import fold_summary_line, sanitize_evidence_quote
from twin.store.formation import propose_or_corroborate
from twin.store.models import StoreClaim, ClaimType
from twin.sense.sensory.percept import Percept


def test_fold_summary_line_uses_human_labels():
    assert fold_summary_line("user_message", "i like pineapple juice") == (
        "User: i like pineapple juice"
    )
    assert fold_summary_line("assistant_result", "You like pineapple juice.") == (
        "Assistant: You like pineapple juice."
    )
    assert fold_summary_line("note", "Decided on RabbitMQ") == (
        "Note: Decided on RabbitMQ"
    )


def test_sanitize_strips_legacy_kind_tags():
    raw = (
        "[user_message] what juice do I like? "
        "[assistant_result] You like pineapple juice."
    )
    assert sanitize_evidence_quote(raw) == (
        "what juice do I like? You like pineapple juice."
    )
    assert sanitize_evidence_quote("you know, i like pineapple juice") == (
        "you know, i like pineapple juice"
    )
    assert "[" not in sanitize_evidence_quote("[file_context] README.md")


def test_propose_stores_sanitized_evidence_quote(store):
    p = Percept(
        percept_type="session_summary",
        source_sensor="session",
        occurred_at=now_iso(),
        ingested_at=now_iso(),
        content="User: what juice do I like?\nAssistant: You like pineapple juice.",
        source_trust=0.6,
        source_scope="personal",
    )
    p.seal()
    store.insert_percept(p)
    mem = StoreClaim(
        id="mem_pineapple",
        type=ClaimType.preference,
        title="Pineapple Juice Preference",
        summary="The user likes pineapple juice.",
        domain="personal",
        confidence=0.65,
    )
    out, action = propose_or_corroborate(
        store, mem,
        percept_id=p.id,
        evidence_quote=(
            "[user_message] what juice do I like? "
            "[assistant_result] You like pineapple juice."
        ),
    )
    assert action == "created"
    ev = store.get_evidence(out.id)
    assert len(ev) == 1
    assert "[user_message]" not in ev[0].quote
    assert "[assistant_result]" not in ev[0].quote
    assert "pineapple juice" in ev[0].quote.lower()
