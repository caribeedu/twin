import json
from pathlib import Path

from twin.ingest import ingest_paths, load_file

EXAMPLES = Path(__file__).parent.parent / "examples"


def test_load_markdown_front_matter():
    src = load_file(EXAMPLES / "docs" / "rfc-webhooks.md")
    assert src.source_type == "markdown"
    assert src.author == "Edu"
    assert src.created_at == "2026-06-20"
    assert "outbox" in src.raw_text


def test_load_transcript_participants():
    src = load_file(EXAMPLES / "transcripts" / "standup-2026-07-08.txt")
    assert src.source_type == "meeting_transcript"
    assert "Edu" in src.participants and "Marina" in src.participants


def test_load_meeting_json():
    src = load_file(EXAMPLES / "meetings" / "atlas-kickoff.json")
    assert src.source_type == "meeting_json"
    assert src.participants == ["Edu", "Marina", "Rafael"]
    assert "outbox" in src.raw_text


def test_load_slack_export(tmp_path):
    data = [
        {"user": "U1", "user_profile": {"real_name": "Edu"}, "ts": "1", "text": "vamos usar Qdrant"},
        {"user": "U2", "user_profile": {"real_name": "Marina"}, "ts": "2", "text": "fechado"},
    ]
    f = tmp_path / "channel.json"
    f.write_text(json.dumps(data))
    src = load_file(f)
    assert src.source_type == "slack"
    assert src.participants == ["Edu", "Marina"]
    assert "Qdrant" in src.raw_text


def test_ingest_dedupes_by_content(db):
    new1, _ = ingest_paths(db, [EXAMPLES / "docs"])
    assert len(new1) == 1
    new2, skipped = ingest_paths(db, [EXAMPLES / "docs"])
    assert new2 == []
    assert any("duplicate" in s for s in skipped)
