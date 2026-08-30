"""Episode cognition pipeline — brain-named LLM stages over WorkEpisodes.

Correlation (the *sensory* scaffold) clusters connector records into episodes by
explicit anchors and exact identity/project matches. Everything *semantic* on
top of that is a chain of cognition stages, each named for the brain analogy it
plays (see ``docs/ARCHITECTURE.md`` → Brain analogies):

    sensory              structural scaffold (run_correlation_pass)
    amygdala             classify member roles + salience            (LLM)
    basal                manage: read episode lifecycle              (over roles)
    hippocampus_bind     bind: membership consolidation              (structural)
    cortex               understand: phases + narrative edges        (LLM)
    hippocampus_consolidate  reflect: trajectory review candidates   (LLM)
    prefrontal           conclude: draft JudgmentProposals           (from confirmed)

Like the interpreter, a missing model **defers** a stage — it never falls back
to lexical rules and never fabricates structure. ``extractor=heuristic`` is
detection-only and blocks the semantic stages with a clear message. Tests inject
deterministic stage overrides (``set_stage_override``) instead of a model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from twin.config import Config
from .correlation.edges import build_edges_from_llm, persist_edges
from .correlation.phases import (
    build_phases_from_roles,
    member_briefs,
    persist_phases,
)
from .correlation.service import CorrelationReport, run_correlation_pass


class BrainStage(str, Enum):
    sensory = "sensory"
    amygdala = "amygdala"
    basal = "basal"
    hippocampus_bind = "hippocampus_bind"
    cortex = "cortex"
    hippocampus_consolidate = "hippocampus_consolidate"
    prefrontal = "prefrontal"


STAGE_ORDER: list[BrainStage] = [
    BrainStage.sensory,
    BrainStage.amygdala,
    BrainStage.basal,
    BrainStage.hippocampus_bind,
    BrainStage.cortex,
    BrainStage.hippocampus_consolidate,
    BrainStage.prefrontal,
]

# One-line brain analogy per stage (for CLI / docs consistency).
BRAIN_ANALOGY: dict[BrainStage, str] = {
    BrainStage.sensory: "sensory encoding · structural scaffold",
    BrainStage.amygdala: "amygdala · salience & role",
    BrainStage.basal: "basal ganglia · lifecycle",
    BrainStage.hippocampus_bind: "hippocampus · binding",
    BrainStage.cortex: "cortex · understanding (phases + edges)",
    BrainStage.hippocampus_consolidate: "hippocampus · consolidation (reflect)",
    BrainStage.prefrontal: "prefrontal · executive (judgment drafts)",
}


class StageStatus(str, Enum):
    ok = "ok"
    deferred = "deferred"
    blocked = "blocked"
    skipped = "skipped"


def _stage_index(stage: Any) -> int:
    s = stage if isinstance(stage, BrainStage) else BrainStage(str(stage))
    return STAGE_ORDER.index(s)


# -- stage overrides (tests / CI; no model, no lexical rules) ----------------

# amygdala: fn(members: list[dict], cfg) -> dict[ref, {"kind","salience"}]
# cortex:   fn(phases: list[dict], quotes_by_ref: dict, cfg) -> list[edge dict]
_STAGE_OVERRIDES: dict[str, Callable[..., Any]] = {}


def set_stage_override(stage: Any, fn: Optional[Callable[..., Any]]) -> None:
    """Inject a deterministic engine for one stage (tests/CI). ``None`` clears."""
    key = stage.value if isinstance(stage, BrainStage) else str(stage)
    if fn is None:
        _STAGE_OVERRIDES.pop(key, None)
    else:
        _STAGE_OVERRIDES[key] = fn


def clear_stage_overrides() -> None:
    _STAGE_OVERRIDES.clear()


def _override(stage: BrainStage) -> Optional[Callable[..., Any]]:
    return _STAGE_OVERRIDES.get(stage.value)


# -- model gate --------------------------------------------------------------


@dataclass
class _Gate:
    chat: Any = None
    available: bool = False
    blocked_reason: Optional[str] = None


def _open_gate(cfg: Config) -> _Gate:
    ext = getattr(cfg, "extractor", "auto")
    if ext == "heuristic":
        return _Gate(
            blocked_reason=(
                "extractor=heuristic is detection-only; episode cognition needs "
                "an interpreting mode (auto / ollama / openai / anthropic / …)"
            ),
        )
    if ext == "echo":
        # No model, but not blocked — stages defer unless a test override exists.
        return _Gate()
    try:
        from twin.llm import get_chat_client

        chat = get_chat_client(cfg)
        return _Gate(chat=chat, available=bool(chat.available()))
    except Exception:
        return _Gate()


def _close_gate(gate: _Gate) -> None:
    closer = getattr(gate.chat, "close", None)
    if callable(closer):
        try:
            closer()
        except Exception:
            pass


# -- report ------------------------------------------------------------------


@dataclass
class StageOutcome:
    stage: BrainStage
    status: StageStatus = StageStatus.skipped
    detail: str = ""
    counts: dict[str, int] = field(default_factory=dict)

    def bump(self, key: str, n: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + n

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage.value,
            "analogy": BRAIN_ANALOGY[self.stage],
            "status": self.status.value,
            "detail": self.detail,
            "counts": dict(self.counts),
        }


@dataclass
class CognitionReport:
    mode: str = "full"
    until: str = BrainStage.cortex.value
    correlation: Optional[CorrelationReport] = None
    episode_ids: list[str] = field(default_factory=list)
    stages: dict[str, StageOutcome] = field(default_factory=dict)
    candidate_ids: list[str] = field(default_factory=list)
    proposal_ids: list[str] = field(default_factory=list)

    def stage(self, s: BrainStage) -> StageOutcome:
        out = self.stages.get(s.value)
        if out is None:
            out = StageOutcome(stage=s)
            self.stages[s.value] = out
        return out

    def deferred_stages(self) -> list[str]:
        return [
            k for k, v in self.stages.items()
            if v.status in (StageStatus.deferred, StageStatus.blocked)
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "until": self.until,
            "episode_ids": list(self.episode_ids),
            "stages": [
                self.stages[s.value].to_dict()
                for s in STAGE_ORDER if s.value in self.stages
            ],
            "candidate_ids": list(self.candidate_ids),
            "proposal_ids": list(self.proposal_ids),
            "records_scanned": (
                self.correlation.records_scanned if self.correlation else 0
            ),
        }


# -- stage engines -----------------------------------------------------------


def _classify(members: list[dict[str, Any]], cfg: Config, gate: _Gate):
    """Return (StageStatus, roles, detail)."""
    ov = _override(BrainStage.amygdala)
    if ov is not None:
        try:
            roles = dict(ov(members, cfg) or {})
        except Exception as exc:
            return StageStatus.deferred, {}, f"override error: {type(exc).__name__}"
        if members and not roles:
            return StageStatus.deferred, {}, "amygdala returned no roles"
        return StageStatus.ok, roles, "override"
    if gate.blocked_reason:
        return StageStatus.blocked, {}, gate.blocked_reason
    if not gate.available or gate.chat is None:
        return StageStatus.deferred, {}, "model unavailable"
    try:
        from .interpreter.classify_prompt import classify_members
        from twin.llm.usage import usage_context

        with usage_context(stage=BrainStage.amygdala.value, role="llm"):
            roles = classify_members(gate.chat, members)
    except Exception as exc:
        return StageStatus.deferred, {}, f"amygdala error: {type(exc).__name__}"
    if members and not roles:
        return StageStatus.deferred, {}, "amygdala returned no roles (bad JSON shape)"
    return StageStatus.ok, roles, "llm"


def _understand(phases: list[dict[str, Any]], quotes: dict[str, str],
                cfg: Config, gate: _Gate):
    """Return (StageStatus, edge_proposals, detail)."""
    ov = _override(BrainStage.cortex)
    if ov is not None:
        try:
            return StageStatus.ok, list(ov(phases, quotes, cfg) or []), "override"
        except Exception as exc:
            return StageStatus.deferred, [], f"override error: {type(exc).__name__}"
    if gate.blocked_reason:
        return StageStatus.blocked, [], gate.blocked_reason
    if not gate.available or gate.chat is None:
        return StageStatus.deferred, [], "model unavailable"
    try:
        from .interpreter.understand_prompt import understand_edges
        from twin.llm.usage import usage_context

        with usage_context(stage=BrainStage.cortex.value, role="llm"):
            return StageStatus.ok, understand_edges(gate.chat, phases, quotes), "llm"
    except Exception as exc:
        return StageStatus.deferred, [], f"cortex error: {type(exc).__name__}"


def _phase_dicts(phases) -> list[dict[str, Any]]:
    return [
        {
            "phase_key": p.phase_key,
            "kind": getattr(p.kind, "value", p.kind),
            "order": p.order,
            "started_at": p.started_at,
            "summary": p.summary,
            "members": list(p.member_external_refs or []),
        }
        for p in phases
    ]


def _quotes_for(members: list[dict[str, Any]]) -> dict[str, str]:
    return {m["ref"]: m.get("excerpt", "") for m in members if m.get("ref")}


# -- orchestrator ------------------------------------------------------------


def run_episode_cognition(
    store,
    cfg: Config,
    embedder=None,
    *,
    connector_ids: Optional[list[str]] = None,
    mode: str = "full",
    until: Any = BrainStage.cortex,
    episode_ids: Optional[list[str]] = None,
    detect_conflicts: bool = True,
    limit: int = 2000,
    reflect_limit: int = 50,
    dry_run: bool = False,
) -> CognitionReport:
    """Run the brain-staged cognition chain up to ``until``.

    ``sensory`` always runs (structural correlation). Semantic stages run only
    when a model (or a test override) is available; otherwise they defer. Never
    writes confirmed Memory or Judgment: ``hippocampus_consolidate`` emits
    candidates and ``prefrontal`` drafts proposals from *already-confirmed*
    trajectory review candidates.
    """
    until_stage = until if isinstance(until, BrainStage) else BrainStage(str(until))
    report = CognitionReport(mode=mode, until=until_stage.value)

    # -- sensory: structural scaffold ---------------------------------------
    sensory = run_correlation_pass(
        store, connector_ids=connector_ids, mode=mode,
        detect_conflicts=detect_conflicts, limit=limit,
    )
    report.correlation = sensory
    so = report.stage(BrainStage.sensory)
    so.status = StageStatus.ok
    so.detail = "structural correlation"
    so.counts = {
        "records": sensory.records_scanned,
        "episodes": len(sensory.episode_ids),
        "identity_links": sensory.identity_links_created,
        "project_links": sensory.project_links_created,
    }

    target = episode_ids or list(sensory.episode_ids)
    episodes = []
    for eid in target:
        ep = store.get_work_episode(eid)
        if ep is None:
            continue
        status = getattr(ep.status, "value", ep.status)
        if status in ("active", "candidate", "closed"):
            episodes.append(ep)
    report.episode_ids = [e.id for e in episodes]

    if _stage_index(until_stage) < _stage_index(BrainStage.amygdala):
        return report

    gate = _open_gate(cfg)
    try:
        _run_semantic_stages(
            store, cfg, embedder, episodes, gate, until_stage, report,
            reflect_limit=reflect_limit, dry_run=dry_run,
        )
    finally:
        _close_gate(gate)
    return report


def _run_semantic_stages(
    store, cfg, embedder, episodes, gate, until_stage, report, *,
    reflect_limit, dry_run,
):
    amy = report.stage(BrainStage.amygdala)
    bas = report.stage(BrainStage.basal)
    bind = report.stage(BrainStage.hippocampus_bind)
    cor = report.stage(BrainStage.cortex)

    want_cortex = _stage_index(until_stage) >= _stage_index(BrainStage.cortex)
    want_basal = _stage_index(until_stage) >= _stage_index(BrainStage.basal)
    want_bind = _stage_index(until_stage) >= _stage_index(BrainStage.hippocampus_bind)

    for ep in episodes:
        members = member_briefs(store, ep)
        if not members:
            amy.bump("skipped_empty")
            continue

        status, roles, detail = _classify(members, cfg, gate)
        _absorb(amy, status, detail)
        if status is not StageStatus.ok:
            # No roles → the rest of the arc defers for this episode.
            if want_basal:
                _absorb(bas, status, detail)
            if want_bind:
                _absorb(bind, status, detail)
            if want_cortex:
                _absorb(cor, status, detail)
            continue
        amy.bump("classified", len(roles))

        # basal: read lifecycle from roles (report-only; never mutates).
        if want_basal:
            kinds = {(roles.get(m["ref"]) or {}).get("kind") for m in members}
            bas.status = StageStatus.ok
            bas.detail = "lifecycle read from roles"
            bas.bump("concluded" if "outcome" in kinds else "ongoing")

        # hippocampus_bind: structural membership stands (soft LLM binding: later).
        if want_bind:
            bind.status = StageStatus.ok
            bind.detail = "structural membership"
            bind.bump("members", len(members))

        if not want_cortex:
            continue

        # cortex: phases (grouped from roles) + narrative edges (LLM).
        phases = build_phases_from_roles(store, ep, roles)
        persist_phases(store, ep, phases)
        cor.bump("phases", len(phases))
        pdicts = _phase_dicts(phases)
        quotes = _quotes_for(members)
        e_status, proposals, e_detail = _understand(pdicts, quotes, cfg, gate)
        _absorb(cor, e_status, e_detail)
        if e_status is StageStatus.ok:
            edges = build_edges_from_llm(ep, phases, proposals)
            persist_edges(store, ep, edges)
            cor.bump("edges", len(edges))

    # -- hippocampus_consolidate: reflect ----------------------------------
    if _stage_index(until_stage) >= _stage_index(BrainStage.hippocampus_consolidate):
        _run_consolidate(
            store, cfg, embedder, episodes, report,
            reflect_limit=reflect_limit, dry_run=dry_run,
        )
        # Collapse near-duplicate reflect paraphrases before prefrontal.
        if not dry_run and report.candidate_ids:
            try:
                from .condense import condense_near_duplicates
                cr = condense_near_duplicates(
                    store, embedder, claim_ids=list(report.candidate_ids),
                )
                con = report.stage(BrainStage.hippocampus_consolidate)
                if cr.merged:
                    con.bump("condensed", cr.merged)
                    # Replace absorbed ids with survivors in the report list.
                    absorbed = set(cr.absorbed_ids)
                    kept = [i for i in report.candidate_ids if i not in absorbed]
                    for sid in cr.survivor_ids:
                        if sid not in kept:
                            kept.append(sid)
                    report.candidate_ids = kept
            except Exception:
                pass

    # -- prefrontal: draft judgment proposals from confirmed trajectories --
    if _stage_index(until_stage) >= _stage_index(BrainStage.prefrontal):
        _run_prefrontal(store, episodes, report)


def _run_consolidate(store, cfg, embedder, episodes, report, *, reflect_limit, dry_run):
    from .episode_reflect import reflect_episode

    con = report.stage(BrainStage.hippocampus_consolidate)
    con.status = StageStatus.skipped
    reflected = 0
    for ep in episodes:
        if reflected >= reflect_limit:
            break
        try:
            result = reflect_episode(store, cfg, embedder, ep.id, dry_run=dry_run)
        except Exception as exc:
            _absorb(con, StageStatus.deferred, f"reflect error: {type(exc).__name__}")
            continue
        if result.claims:
            con.status = StageStatus.ok
            reflected += 1
            for c in result.claims:
                con.bump("candidates")
                if c.get("claim_id") and c.get("created"):
                    report.candidate_ids.append(c["claim_id"])
        elif result.skipped_reason:
            low = result.skipped_reason.lower()
            if "deferred" in low or "unavailable" in low or "model" in low:
                _absorb(con, StageStatus.deferred, result.skipped_reason)
            else:
                con.bump("no_arc")
                if con.status is StageStatus.skipped:
                    con.detail = result.skipped_reason


def _run_prefrontal(store, episodes, report):
    from twin.cognize.stance_engine.proposals import propose_from_episode

    pre = report.stage(BrainStage.prefrontal)
    pre.status = StageStatus.ok
    pre.detail = "drafts from confirmed trajectories"
    for ep in episodes:
        try:
            proposal = propose_from_episode(store, ep.id)
        except Exception:
            continue
        if proposal is not None:
            pre.bump("proposals")
            report.proposal_ids.append(proposal.id)
    if not report.proposal_ids and not pre.counts:
        pre.detail = "no confirmed trajectory to generalize yet"


def _absorb(outcome: StageOutcome, status: StageStatus, detail: str) -> None:
    """Fold a per-episode status into a stage outcome (ok wins; defer/block sticky)."""
    if status is StageStatus.ok:
        if outcome.status is not StageStatus.ok:
            outcome.status = StageStatus.ok
            outcome.detail = detail
        return
    # deferred / blocked / skipped — only downgrade an unset/skipped stage.
    if outcome.status in (StageStatus.skipped,):
        outcome.status = status
        outcome.detail = detail
    outcome.bump(status.value)
