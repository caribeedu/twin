from twin import ids
from twin.clock import now_iso
from twin.privacy.firewall import Firewall
from twin.store.models import MemoryItem


def _mem(**kw) -> MemoryItem:
    base = dict(
        id=ids.memory_id(), type="fact", title="t", summary="s",
        domain="technical", sensitivity="internal", confidence=0.9,
        status="confirmed", created_at=now_iso(), updated_at=now_iso(),
    )
    base.update(kw)
    return MemoryItem(**base)


def test_technical_memory_allowed_in_technical_context(cfg):
    fw = Firewall(cfg.policies_path)
    assert fw.evaluate(_mem(), "technical").allowed


def test_relationship_blocked_in_work(cfg):
    fw = Firewall(cfg.policies_path)
    verdict = fw.evaluate(_mem(domain="relationship"), "work")
    assert not verdict.allowed
    assert verdict.rule == "relationship_not_allowed_outside_own_domain"


def test_relationship_allowed_in_own_domain(cfg):
    fw = Firewall(cfg.policies_path)
    assert fw.evaluate(_mem(domain="relationship"), "relationship").allowed


def test_restricted_requires_permission(cfg):
    fw = Firewall(cfg.policies_path)
    verdict = fw.evaluate(_mem(sensitivity="restricted"), "technical")
    assert not verdict.allowed
    assert verdict.requires_permission


def test_work_blocked_in_family_context(cfg):
    fw = Firewall(cfg.policies_path)
    verdict = fw.evaluate(_mem(domain="work"), "family")
    assert not verdict.allowed


def test_rejected_memory_never_flows(cfg):
    fw = Firewall(cfg.policies_path)
    verdict = fw.evaluate(_mem(status="rejected"), "technical")
    assert not verdict.allowed
    assert verdict.rule == "status_gate"


def test_expired_memory_blocked(cfg):
    fw = Firewall(cfg.policies_path)
    verdict = fw.evaluate(_mem(valid_until="2020-01-01"), "technical", as_of=now_iso())
    assert not verdict.allowed
    assert verdict.rule == "temporal_gate"


def test_low_confidence_blocked(cfg):
    fw = Firewall(cfg.policies_path)
    verdict = fw.evaluate(_mem(confidence=0.1), "technical")
    assert not verdict.allowed
    assert verdict.rule == "confidence_gate"


def test_blocks_are_logged_to_store(cfg, store):
    fw = Firewall(cfg.policies_path, store)
    fw.evaluate(_mem(domain="relationship"), "work")
    rows = store.conn.execute("SELECT * FROM firewall_log").fetchall()
    assert len(rows) == 1
    assert rows[0]["target_domain"] == "work"


def test_unclassified_target_is_default_deny(cfg):
    """An unclassified target context is restricted mode: NOTHING crosses —
    not even public technical memories — until the domain is confirmed."""
    fw = Firewall(cfg.policies_path)
    for domain in ("technical", "work", "assistant_preferences", "relationship"):
        for sensitivity in ("public", "internal"):
            verdict = fw.evaluate(_mem(domain=domain, sensitivity=sensitivity),
                                  "unclassified")
            assert not verdict.allowed
            assert verdict.rule == "unclassified_target_default_deny"


def test_unclassified_blocks_are_audited(cfg, store):
    fw = Firewall(cfg.policies_path, store)
    fw.evaluate(_mem(), "unclassified")
    rows = store.conn.execute("SELECT * FROM firewall_log").fetchall()
    assert len(rows) == 1
    assert rows[0]["target_domain"] == "unclassified"
