import pytest

from twin.config import Config
from twin.db import Database
from twin.embeddings import get_embedder


@pytest.fixture()
def cfg(tmp_path):
    c = Config(home=tmp_path / "twin-home")
    c.extractor = "heuristic"  # tests never call the network
    c.ensure_home()
    return c


@pytest.fixture()
def db(cfg):
    database = Database(cfg.db_path)
    yield database
    database.close()


@pytest.fixture()
def embedder(cfg):
    return get_embedder(cfg.embedder, cfg.embedding_dim)
