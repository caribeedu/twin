"""Optional local encryption at rest (percept content + evidence quotes)."""

from twin import ids
from twin.store.crypto import build_codec
from twin.store.models import Evidence, MemoryItem
from twin.store.store.sqlite import SqliteStore
from twin.sense.sensory.percept import Percept


def test_encryption_at_rest_roundtrip(tmp_path):
    codec = build_codec("senha-super-secreta", tmp_path)
    store = SqliteStore(tmp_path / "enc.db", codec=codec)
    percept = Percept(percept_type="document", source_sensor="document",
                      content="conteúdo sigiloso do documento").seal()
    store.insert_percept(percept)

    # plaintext never touches disk
    raw = store.conn.execute("SELECT content FROM percepts").fetchone()[0]
    assert raw.startswith("enc1:")
    assert "sigiloso" not in raw
    # transparent decryption on read
    assert store.get_percept(percept.id).content == "conteúdo sigiloso do documento"

    mem = MemoryItem(id=ids.memory_id(), type="fact", title="t", summary="s")
    store.insert_memory(mem)
    store.insert_evidence(Evidence(id=ids.evidence_id(), memory_id=mem.id,
                                   percept_id=percept.id, quote="trecho sigiloso"))
    raw_quote = store.conn.execute("SELECT quote FROM evidence").fetchone()[0]
    assert raw_quote.startswith("enc1:")
    assert store.get_evidence(mem.id)[0].quote == "trecho sigiloso"
    store.close()


def test_plaintext_readthrough_after_enabling_encryption(tmp_path):
    plain = SqliteStore(tmp_path / "mix.db")
    percept = Percept(percept_type="document", source_sensor="document",
                      content="escrito antes da criptografia").seal()
    plain.insert_percept(percept)
    plain.close()

    codec = build_codec("senha", tmp_path)
    enc = SqliteStore(tmp_path / "mix.db", codec=codec)
    assert enc.get_percept(percept.id).content == "escrito antes da criptografia"
    enc.close()


def test_null_codec_when_no_key(tmp_path):
    codec = build_codec("", tmp_path)
    assert codec.encrypt("texto") == "texto"
    assert codec.decrypt("texto") == "texto"
