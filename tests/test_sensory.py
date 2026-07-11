"""Sensory Layer: sensors emit normalized, sealed Percepts."""

import json
from pathlib import Path

from twin.sensory import sense_paths
from twin.sensory.sensors.document import DocumentSensor
from twin.sensory.sensors.meeting import MeetingSensor
from twin.sensory.sensors.slack import SlackSensor

EXAMPLES = Path(__file__).parent.parent / "examples"

PERCEPT_CONTRACT_FIELDS = {
    "id", "percept_type", "source_sensor", "occurred_at", "ingested_at",
    "actors", "content", "content_refs", "attachments", "privacy_hints",
    "integrity", "metadata",
}


def test_percept_contract_fields():
    [percept] = list(DocumentSensor().sense(EXAMPLES / "docs" / "rfc-webhooks.md"))
    assert PERCEPT_CONTRACT_FIELDS <= set(percept.model_dump().keys())
    assert percept.integrity["content_hash"]
    assert percept.integrity["size_bytes"] > 0
    assert percept.content_refs[0]["kind"] == "file"


def test_document_sensor_front_matter():
    [percept] = list(DocumentSensor().sense(EXAMPLES / "docs" / "rfc-webhooks.md"))
    assert percept.percept_type == "document"
    assert percept.source_sensor == "document"
    assert percept.actors == ["Edu"]
    assert percept.occurred_at == "2026-06-20"
    assert "outbox" in percept.content


def test_meeting_sensor_transcript():
    [percept] = list(MeetingSensor().sense(EXAMPLES / "transcripts" / "standup-2026-07-08.txt"))
    assert percept.percept_type == "meeting_transcript"
    assert "Edu" in percept.actors and "Marina" in percept.actors


def test_meeting_sensor_json():
    [percept] = list(MeetingSensor().sense(EXAMPLES / "meetings" / "atlas-kickoff.json"))
    assert percept.percept_type == "meeting"
    assert percept.actors == ["Edu", "Marina", "Rafael"]
    assert "outbox" in percept.content


def test_slack_sensor(tmp_path):
    data = [
        {"user": "U1", "user_profile": {"real_name": "Edu"}, "ts": "1", "text": "vamos usar Qdrant"},
        {"user": "U2", "user_profile": {"real_name": "Marina"}, "ts": "2", "text": "fechado"},
    ]
    f = tmp_path / "channel.json"
    f.write_text(json.dumps(data))
    sensor = SlackSensor()
    assert sensor.can_handle(f)
    [percept] = list(sensor.sense(f))
    assert percept.percept_type == "slack_thread"
    assert percept.actors == ["Edu", "Marina"]
    assert "Qdrant" in percept.content


def test_sense_paths_routes_by_sensor():
    percepts, skipped = sense_paths([EXAMPLES])
    types = {p.percept_type for p in percepts}
    assert types == {"document", "meeting_transcript", "meeting"}


def test_store_dedupes_percepts_by_content(store):
    percepts, _ = sense_paths([EXAMPLES / "docs"])
    assert store.insert_percept(percepts[0]) is not None
    again, _ = sense_paths([EXAMPLES / "docs"])
    assert store.insert_percept(again[0]) is None


def test_source_qualification_fields_roundtrip(store):
    percepts, _ = sense_paths([EXAMPLES / "transcripts"])
    percept = percepts[0]
    assert percept.source_trust == 0.7  # meeting transcript sensor default
    store.insert_percept(percept)
    loaded = store.get_percept(percept.id)
    assert loaded.source_trust == 0.7
    assert loaded.source_scope == "work"
    assert loaded.source_confidentiality == "internal"
