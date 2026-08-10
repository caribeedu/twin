"""project_id is stamped onto connector percepts so extracted memories inherit
the shared key that bridges cross-sense correlation."""
from __future__ import annotations

from twin.sense.connectors import runtime as rt
from twin.sense.connectors.models import (
    ConnectorInstance,
    ConnectorRecord,
    SourceAccount,
)


def _fixtures():
    acc = SourceAccount(connector_type="github", owner_principal_id="p1",
                        vault_id="vault_dogfood")
    inst = ConnectorInstance(connector_type="github", account_id=acc.id)
    rec = ConnectorRecord(
        connector_id=inst.id, source_account_id=acc.id,
        external_type="pull_request", external_id="caribeedu/dogwalker#14",
        content="Add role and preset management",
        source_metadata={"repo": "caribeedu/dogwalker"},
    )
    return acc, inst, rec


def test_build_percept_forwards_project_id():
    acc, inst, rec = _fixtures()
    p = rt.build_percept(acc, inst, rec, project_id="proj_abc")
    assert p.project_id == "proj_abc"


def test_build_percept_project_id_defaults_none():
    acc, inst, rec = _fixtures()
    p = rt.build_percept(acc, inst, rec)
    assert p.project_id is None


def test_resolve_record_project_delegates(monkeypatch):
    _, _, rec = _fixtures()

    import twin.cognize.services.correlation.projects as proj

    monkeypatch.setattr(
        proj, "resolve_project_for_record", lambda store, r: ("proj_xyz", None)
    )
    assert rt._resolve_record_project(object(), rec) == "proj_xyz"


def test_resolve_record_project_swallows_errors(monkeypatch):
    _, _, rec = _fixtures()

    import twin.cognize.services.correlation.projects as proj

    def boom(store, r):
        raise RuntimeError("no store")

    monkeypatch.setattr(proj, "resolve_project_for_record", boom)
    assert rt._resolve_record_project(object(), rec) is None
