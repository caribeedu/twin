import pytest

from twin.config import Config
from twin.memory.embeddings import get_embedder
from twin.memory.store.sqlite import SqliteStore


@pytest.fixture()
def cfg(tmp_path):
    c = Config(home=tmp_path / "twin-home")
    c.extractor = "echo"        # deterministic offline interpreter (no LLM)
    c.embedder = "hash"         # deterministic, no server required
    c.db_url = f"sqlite:///{tmp_path / 'twin-home' / 'twin.db'}"
    c.ensure_home()
    return c


@pytest.fixture(autouse=True)
def _reset_interpreter_override():
    """Guarantee no scripted interpreter override leaks between tests — a test
    that authors an interpretation (set_interpreter_override) is isolated."""
    from twin.cognition import (
        clear_stage_overrides,
        set_interpreter_override,
        set_reflect_override,
    )
    set_interpreter_override(None)
    set_reflect_override(None)
    clear_stage_overrides()
    yield
    set_interpreter_override(None)
    set_reflect_override(None)
    clear_stage_overrides()


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
    from twin.privacy.identity import ensure_local_identity, resolve_access
    from twin.privacy.yaml_io import bootstrap_policy_set
    bootstrap_policy_set(store)
    ensure_local_identity(store)
    return resolve_access(
        store, surface="cli", client="local-cli",
        persona="individual", purpose="memory_retrieval", audience="self",
    )
