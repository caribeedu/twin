import pytest

from twin.config import Config
from twin.memory.embeddings import get_embedder
from twin.memory.store.sqlite import SqliteStore


@pytest.fixture()
def cfg(tmp_path):
    c = Config(home=tmp_path / "twin-home")
    c.extractor = "heuristic"   # tests never call an LLM by default
    c.embedder = "hash"         # deterministic, no server required
    c.db_url = f"sqlite:///{tmp_path / 'twin-home' / 'twin.db'}"
    c.ensure_home()
    return c


@pytest.fixture()
def store(cfg):
    s = SqliteStore(cfg.home / "twin.db")
    yield s
    s.close()


@pytest.fixture()
def embedder(cfg):
    return get_embedder(cfg.embedder, cfg.embedding_dim)


@pytest.fixture()
def local_access(store):
    """Authenticated local CLI access for pack/session tests (not restricted)."""
    from twin.privacy.identity import resolve_access
    return resolve_access(
        store, surface="cli", client="local-cli",
        persona="individual", purpose="memory_retrieval", audience="self",
    )
