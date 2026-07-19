"""Sensory Layer: sensors emit normalized, sealed Percepts."""

import json
from pathlib import Path

from tests.paths import EXAMPLES

from twin.sensory import sense_paths
from twin.sensory.sensors.document import DocumentSensor
from twin.sensory.sensors.meeting import MeetingSensor
from twin.sensory.sensors.slack import SlackSensor

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


def _git_repo(tmp_path):
    import subprocess

    repo = tmp_path / "atlas-api"
    repo.mkdir(parents=True)
    env = {"GIT_AUTHOR_NAME": "Edu", "GIT_AUTHOR_EMAIL": "edu@example.com",
           "GIT_COMMITTER_NAME": "Edu", "GIT_COMMITTER_EMAIL": "edu@example.com",
           "HOME": str(tmp_path), "PATH": "/usr/bin:/bin:/usr/local/bin"}

    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args], check=True,
                       capture_output=True, env=env)

    git("init", "-b", "main")
    (repo / "app.py").write_text("print('hi')\n")
    git("add", "app.py")
    git("commit", "-m", "Add webhook endpoint")
    (repo / "queue.py").write_text("pass\n")
    git("add", "queue.py")
    git("commit", "-m", "Use RabbitMQ for delivery")
    return repo


def test_git_sensor_emits_one_percept_per_commit(tmp_path):
    from twin.sensory.sensors.git import GitSensor

    repo = _git_repo(tmp_path)
    sensor = GitSensor()
    assert sensor.can_handle(repo)
    assert not sensor.can_handle(tmp_path)  # no .git
    percepts = list(sensor.sense(repo))
    assert len(percepts) == 2
    newest = percepts[0]
    assert newest.percept_type == "git_commit"
    assert newest.actors == ["Edu"]
    assert newest.source_trust == 0.9
    assert "Use RabbitMQ for delivery" in newest.content
    assert "queue.py" in newest.content
    # the sensor never claims the commit was created on this branch — only
    # that it was observed from it
    assert newest.metadata["observed_from_branch"] == "main"
    assert "observed from branch main" in newest.content
    assert newest.content_refs[0]["kind"] == "git_commit"


def test_git_sensor_dedup_is_incremental(tmp_path, store):
    from twin.sensory.sensors.git import GitSensor

    repo = _git_repo(tmp_path)
    for p in GitSensor().sense(repo):
        assert store.insert_percept(p) is not None
    # re-sensing the same repo ingests nothing — dedup keys on the commit sha
    for p in GitSensor().sense(repo):
        assert store.insert_percept(p) is None


def test_git_sensor_identity_distinguishes_same_basename(tmp_path, store):
    """Two unrelated repositories named 'atlas-api' must not dedupe into one
    — repository identity comes from the remote/toplevel, never the name."""
    from twin.sensory.sensors.git import GitSensor, repository_identity

    repo_a = _git_repo(tmp_path / "work")
    repo_b = _git_repo(tmp_path / "personal")
    assert repo_a.name == repo_b.name
    assert repository_identity(repo_a) != repository_identity(repo_b)

    for p in GitSensor().sense(repo_a):
        assert store.insert_percept(p) is not None
    # same subjects/files, different repository → still ingested
    for p in GitSensor().sense(repo_b):
        assert store.insert_percept(p) is not None


def test_git_sensor_identity_prefers_remote(tmp_path):
    import subprocess

    from twin.sensory.sensors.git import repository_identity

    repo = _git_repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin",
                    "git@github.com:Edu/Atlas-API.git"], check=True,
                   capture_output=True)
    identity = repository_identity(repo)
    assert identity == "github.com/edu/atlas-api"
    # clones of the same remote share the identity regardless of URL form
    subprocess.run(["git", "-C", str(repo), "remote", "set-url", "origin",
                    "https://github.com/Edu/Atlas-API.git"], check=True,
                   capture_output=True)
    assert repository_identity(repo) == identity


def test_sense_paths_senses_git_directories(tmp_path):
    repo = _git_repo(tmp_path)
    (repo / "README.md").write_text("# atlas\n")
    percepts, _ = sense_paths([repo])
    types = [p.percept_type for p in percepts]
    assert types.count("git_commit") == 2
    assert "document" in types  # file walk still runs after the dir sensors


def test_source_qualification_fields_roundtrip(store):
    percepts, _ = sense_paths([EXAMPLES / "transcripts"])
    percept = percepts[0]
    assert percept.source_trust == 0.7  # meeting transcript sensor default
    store.insert_percept(percept)
    loaded = store.get_percept(percept.id)
    assert loaded.source_trust == 0.7
    assert loaded.source_scope == "work"
    assert loaded.source_confidentiality == "internal"
