"""Slack messages should expose human names, not bare U… ids."""
from __future__ import annotations

from twin.sense.connectors.slack import normalize as norm


def test_display_label_prefers_profile_display_name():
    label = norm.display_label_for_user({
        "name": "jdoe",
        "real_name": "Jane Doe",
        "profile": {"display_name": "Jane", "real_name": "Jane Doe"},
    })
    assert label == "Jane"


def test_record_from_message_uses_author_and_mention_labels():
    msg = {
        "ts": "1720000000.0001",
        "user": "U0BMAC6T5EW",
        "text": "<@U0BMAC2RKR8> please implement presets",
    }
    rec = norm.record_from_message(
        "conn_x", "acc_x", "C0BM8DT14S2", msg,
        team_id="T0BMCA2G1S5",
        author_label="PO Bot",
        channel_label="#dogwalker",
        user_labels={"U0BMAC6T5EW": "PO Bot", "U0BMAC2RKR8": "Dev Twin"},
    )
    assert "@PO Bot" in rec.content
    assert "@Dev Twin" in rec.content
    assert "U0BMAC6T5EW" not in rec.content
    assert "U0BMAC2RKR8" not in rec.content
    assert "#dogwalker" in rec.content
    assert rec.source_metadata.get("author_name") == "PO Bot"


def test_rewrite_mentions_keeps_unknown_ids():
    out = norm.rewrite_mentions("<@UUNKNOWN> hi", {})
    assert "<@UUNKNOWN>" in out
