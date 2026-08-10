"""Task-aware pack profiles (twin.cognize.services.task_profiles + context_pack)."""

from twin import ids
from twin.inject.context_pack import build_context_pack
from twin.cognize.services.task_profiles import PROFILES, get_profile, infer_task_profile
from twin.store.models import StoreClaim
from twin.privacy.identity import ensure_local_identity, resolve_access
from twin.privacy.yaml_io import bootstrap_policy_set


def _cli_access(store):
    bootstrap_policy_set(store)
    ensure_local_identity(store)
    return resolve_access(store, surface="cli", persona="individual",
                          purpose="memory_retrieval", audience="self")



def test_every_profile_is_well_formed():
    for name, spec in PROFILES.items():
        assert spec.name == name
        assert spec.sections
        assert 0 < spec.judgment_share <= 0.5
        assert abs(sum(share for _, _, share in spec.sections) - 1.0) < 0.01


def test_get_profile_falls_back_to_general():
    assert get_profile("architecture").name == "architecture"
    assert get_profile("nonsense").name == "general"


def test_infer_task_profile():
    name, conf = infer_task_profile("write the RFC for the new architecture design")
    assert name == "architecture"
    assert conf > 0.5
    name, conf = infer_task_profile("investigate this bug, here is the stacktrace")
    assert name == "debugging"
    name, conf = infer_task_profile("bom dia")
    assert (name, conf) == ("general", 0.0)


def _seed(store, embedder):
    data = [
        ("decision", "Use RabbitMQ", "Decision: RabbitMQ for webhook delivery."),
        ("constraint", "No cloud LLMs", "All models must run locally."),
        ("task", "Write the RFC", "RFC for webhook retries is pending."),
        ("preference", "Direct answers", "Prefers direct, source-linked answers."),
        ("fact", "Webhooks ship v2", "Webhook v2 shipped in June."),
    ]
    for type_, title, summary in data:
        mem = StoreClaim(id=ids.claim_id(), type=type_, title=title, summary=summary,
                         domain="technical", confidence=0.9, status="confirmed")
        store.insert_claim(mem)
        store.store_embedding(mem.id, "claim", embedder.name,
                              embedder.embed(f"{title}\n{summary}"))


def test_profiles_reorder_sections(store, cfg, embedder):
    _seed(store, embedder)
    query = "webhook RFC RabbitMQ retries local models"
    arch = build_context_pack(store, cfg, embedder, query,
                              task_profile="architecture", max_tokens=2000, access=_cli_access(store))
    coding = build_context_pack(store, cfg, embedder, query,
                                task_profile="coding", max_tokens=2000, access=_cli_access(store))
    assert arch.task_profile == "architecture"
    # architecture leads with prior decisions; coding with project context
    assert arch.context_pack.index("## Prior decisions & rejected alternatives") \
        < arch.context_pack.index("## Constraints")
    assert "## Active project context" in coding.context_pack
    # same memories, different packaging — firewall guarantees unchanged
    assert {s["claim_id"] for s in arch.sources} == {s["claim_id"] for s in coding.sources}


def test_unknown_profile_uses_general_sections(store, cfg, embedder):
    _seed(store, embedder)
    pack = build_context_pack(store, cfg, embedder, "webhook RabbitMQ",
                              task_profile="nonsense", max_tokens=2000, access=_cli_access(store))
    assert pack.task_profile == "general"
    assert "## Decisions" in pack.context_pack
