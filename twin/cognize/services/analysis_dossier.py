"""Analysis Context Compiler (ACC).

A deterministic stage that compiles an :class:`AnalysisDossier` — a budgeted,
cross-sense, correlation-rich briefing — and hands *that* to the analysis LLMs
(reflect now, pattern pass next). The model only *judges*; it never has to
discover the corpus by itself.

Design goals (see the plan):
- feed the analyzer denser primary evidence than a 700-char excerpt;
- surface **cross-sense** neighbors via soft anchors (project / time / actor /
  lexical) so a Slack symptom can meet a GitHub fix without an explicit anchor;
- reuse the read-path retrieval (``retrieve()`` — graph expand + rejected +
  session artifacts) instead of a shallow ``search()``;
- attach per-sense **lenses** so "each sense is analyzed differently" lands in
  the analyzer's input;
- stay deterministic and testable — no LLM in the compile.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from twin.store.embeddings import Embedder
from twin.store.store.base import TwinStore
from . import sense_lenses
from .correlation.partition import vault_for_record
from .correlation.projects import resolve_project_for_record
from .correlation.text import normalize_for_compare, rich_excerpt

# -- budget / tiers -----------------------------------------------------------

DEFAULT_BUDGET_CHARS = 28_000
L0_CAP = 220              # abstract: one dense line
L1_CAP = 1_200           # overview: cross-sense neighbor
L2_CAP = 3_200           # full: dominant primary evidence (well past 700)

# soft-correlation tuning
SOFT_WINDOW_PAD_HOURS = 48
SOFT_MIN_SCORE = 0.40
LEX_MIN_OVERLAP = 0.12
MAX_CROSS_SENSE = 8
# Reserve slots so same-sense github commits cannot crowd Slack/meeting out.
CROSS_SENSE_RESERVED = 3
MAX_NEIGHBORS = 6
MAX_RELATED = 12
MAX_STANCE = 8
SCAN_RECORDS_LIMIT = 4_000
PER_CONNECTOR_LIMIT = 2_000

_STOPWORDS = frozenset(
    "the a an and or of to in on for with without from into is are was were be "
    "this that these those it its as at by we i you he she they them our your "
    "will would should could can may might not no do does did done have has had "
    "but if then than so about over under after before during out up down".split()
)


# -- structures ---------------------------------------------------------------


@dataclass
class DossierFocus:
    kind: str                       # episode | window | project
    id: str = ""
    vault_id: str = ""
    project_id: Optional[str] = None
    title: str = ""
    time_from: Optional[str] = None
    time_until: Optional[str] = None


@dataclass
class DossierBlob:
    sense: str
    ref: str
    text: str
    tier: str = "l2"                # l0 | l1 | l2
    occurred_at: Optional[str] = None
    role: str = "primary"           # primary | cross_sense
    score: float = 0.0
    anchors: list[str] = field(default_factory=list)
    record_id: Optional[str] = None


@dataclass
class DossierBudget:
    max_chars: int = DEFAULT_BUDGET_CHARS
    used_chars: int = 0
    dropped: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AnalysisDossier:
    focus: DossierFocus
    primary: list[DossierBlob] = field(default_factory=list)
    cross_sense: list[DossierBlob] = field(default_factory=list)
    neighbors: list[dict[str, Any]] = field(default_factory=list)
    related_claims: list[dict[str, Any]] = field(default_factory=list)
    lenses: list[dict[str, Any]] = field(default_factory=list)
    user_stance: list[dict[str, Any]] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    budget: DossierBudget = field(default_factory=DossierBudget)

    @property
    def related_memories(self) -> list[dict[str, Any]]:
        """Deprecated alias of ``related_claims``."""
        return self.related_claims

    @related_memories.setter
    def related_memories(self, value: list[dict[str, Any]]) -> None:
        self.related_claims = list(value) if value is not None else []

    def senses(self) -> list[str]:
        out: list[str] = []
        for b in list(self.primary) + list(self.cross_sense):
            if b.sense not in out:
                out.append(b.sense)
        return out

    def render(self) -> str:
        """A single text block for an analysis prompt (reflect / pattern)."""
        lines: list[str] = []
        f = self.focus
        span = f"{f.time_from or '?'} → {f.time_until or '?'}"
        lines.append(f"FOCUS ({f.kind}): {f.title or f.id} [{span}]")
        if f.project_id:
            lines.append(f"project: {f.project_id}")
        lines.append("")

        lines.append("PRIMARY EVIDENCE (the focus itself):")
        if self.primary:
            for b in self.primary:
                lines.append(f"  <{b.sense}> {b.ref} @ {b.occurred_at or '?'}")
                lines.append(f"    {b.text}")
        else:
            lines.append("  (none)")
        lines.append("")

        lines.append(
            "CROSS-SENSE (soft neighbors: same project/time/people/topic — "
            "NOT an explicit link; judge whether they relate):"
        )
        if self.cross_sense:
            for b in self.cross_sense:
                why = ", ".join(b.anchors) or "topical"
                lines.append(
                    f"  <{b.sense}> {b.ref} @ {b.occurred_at or '?'} [{why}]"
                )
                lines.append(f"    {b.text}")
        else:
            lines.append("  (none found)")
        lines.append("")

        if self.neighbors:
            lines.append("NEIGHBOR EPISODES (same project):")
            for n in self.neighbors:
                lines.append(
                    f"  {n.get('episode_id')}: {n.get('title')} — "
                    f"{n.get('phase_summary') or ''}"
                )
            lines.append("")

        lines.append(
            "RELATED CONTEXT (vault claims confirmed/candidate/rejected + "
            "open-session artifacts):"
        )
        if self.related_claims:
            for rm in self.related_claims:
                lines.append(
                    f"  [{rm.get('status')}] {rm.get('id')} "
                    f"type={rm.get('type')} domain={rm.get('domain')}: "
                    f"{rm.get('title')} — {rm.get('summary')}"
                )
        else:
            lines.append("  (none)")
        lines.append("")

        if self.user_stance:
            lines.append("ESTABLISHED USER STANCE (already confirmed — extend, do not restate):")
            for s in self.user_stance:
                lines.append(
                    f"  [{s.get('type')}] {s.get('title')} — {s.get('summary')}"
                )
            lines.append("")

        lines.append("LENSES (what to look for per sense present above):")
        for lens in self.lenses:
            joined = "; ".join(lens.get("look_for") or [])
            lines.append(f"  {lens.get('sense')}: {joined}")
        lines.append("")

        if self.gaps:
            lines.append("COMPILER HINTS (unlinked signals worth connecting):")
            for g in self.gaps:
                lines.append(f"  - {g}")
        return "\n".join(lines)


# -- time / lexical helpers ---------------------------------------------------


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _tokens(text: str) -> set[str]:
    norm = normalize_for_compare(text or "")
    return {t for t in norm.split() if len(t) > 2 and t not in _STOPWORDS}


def _lexical_overlap(a: set[str], b: set[str]) -> float:
    """Overlap coefficient (|A∩B| / min(|A|,|B|)) — robust to length gaps."""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if not inter:
        return 0.0
    return inter / min(len(a), len(b))


# -- record scanning ----------------------------------------------------------


def _iter_vault_records(
    store: TwinStore, vault_id: str,
) -> Iterable[Any]:
    """Live connector records in one vault, bounded, newest connectors first."""
    if not hasattr(store, "list_connector_instances"):
        return []
    seen = 0
    out: list[Any] = []
    for inst in store.list_connector_instances():
        recs = store.list_connector_records(inst.id)[:PER_CONNECTOR_LIMIT]
        for rec in recs:
            if getattr(rec, "deleted", False):
                continue
            if vault_for_record(store, rec) != vault_id:
                continue
            out.append(rec)
            seen += 1
            if seen >= SCAN_RECORDS_LIMIT:
                return out
    return out


def _member_record_ids(store: TwinStore, episode_id: str) -> tuple[list[Any], set[str]]:
    """Active connector records that are members of an episode."""
    from .correlation.models import EpisodeLinkStatus

    records: list[Any] = []
    ids: set[str] = set()
    if not hasattr(store, "list_episode_links"):
        return records, ids
    for lk in store.list_episode_links(episode_id):
        st = getattr(lk.status, "value", lk.status)
        if st != EpisodeLinkStatus.active.value:
            continue
        rid = lk.connector_record_id
        if not rid or rid in ids:
            continue
        rec = store.get_connector_record(rid) if hasattr(store, "get_connector_record") else None
        if rec is None:
            continue
        ids.add(rid)
        records.append(rec)
    return records, ids


# -- blob building / budget ---------------------------------------------------


def _record_ref(record: Any) -> str:
    et = getattr(record, "external_type", "") or "record"
    eid = getattr(record, "external_id", "") or getattr(record, "id", "") or "?"
    return f"{et}:{eid}"


def _fill_budget(
    primary_recs: list[Any],
    cross: list[tuple[Any, float, list[str]]],
    budget: DossierBudget,
    *,
    store=None,
) -> tuple[list[DossierBlob], list[DossierBlob]]:
    """Greedy progressive fill: dominant primary at L2, cross-sense at L1,
    downgrade to L0 (or drop) when the char budget is exhausted."""
    from .actor_labels import humanize_record_text

    primary_blobs: list[DossierBlob] = []
    cross_blobs: list[DossierBlob] = []

    def _content(rec: Any) -> str:
        raw = getattr(rec, "content", "") or ""
        if store is not None:
            try:
                return humanize_record_text(store, rec, raw)
            except Exception:
                return raw
        return raw

    # primary first (chronological), then cross-sense by score
    for rec in sorted(primary_recs, key=lambda r: getattr(r, "occurred_at", "") or ""):
        content = _content(rec)
        full = rich_excerpt(content, limit=L2_CAP)
        short = rich_excerpt(content, limit=L0_CAP)
        sense = sense_lenses.sense_for_record(rec)
        ref = _record_ref(rec)
        if budget.used_chars + len(full) <= budget.max_chars:
            budget.used_chars += len(full)
            primary_blobs.append(DossierBlob(
                sense=sense, ref=ref, text=full, tier="l2",
                occurred_at=getattr(rec, "occurred_at", None), role="primary",
                record_id=getattr(rec, "id", None),
            ))
        elif budget.used_chars + len(short) <= budget.max_chars:
            budget.used_chars += len(short)
            primary_blobs.append(DossierBlob(
                sense=sense, ref=ref, text=short, tier="l0",
                occurred_at=getattr(rec, "occurred_at", None), role="primary",
                record_id=getattr(rec, "id", None),
            ))
        else:
            budget.dropped.append({"ref": ref, "role": "primary", "reason": "budget"})

    for rec, score, anchors in sorted(cross, key=lambda t: t[1], reverse=True):
        content = _content(rec)
        over = rich_excerpt(content, limit=L1_CAP)
        short = rich_excerpt(content, limit=L0_CAP)
        sense = sense_lenses.sense_for_record(rec)
        ref = _record_ref(rec)
        if budget.used_chars + len(over) <= budget.max_chars:
            budget.used_chars += len(over)
            tier, text = "l1", over
        elif budget.used_chars + len(short) <= budget.max_chars:
            budget.used_chars += len(short)
            tier, text = "l0", short
        else:
            budget.dropped.append({"ref": ref, "role": "cross_sense", "reason": "budget"})
            continue
        cross_blobs.append(DossierBlob(
            sense=sense, ref=ref, text=text, tier=tier,
            occurred_at=getattr(rec, "occurred_at", None), role="cross_sense",
            score=round(score, 3), anchors=anchors,
            record_id=getattr(rec, "id", None),
        ))
    return primary_blobs, cross_blobs


# -- soft cross-sense correlation --------------------------------------------


def _score_cross_candidate(
    store: TwinStore,
    rec: Any,
    *,
    focus_tokens: set[str],
    focus_actors: set[str],
    focus_project: Optional[str],
    win_from: Optional[datetime],
    win_until: Optional[datetime],
    primary_senses: set[str],
) -> tuple[float, list[str]]:
    """Soft anchor score for a candidate cross-sense record. Never merges."""
    anchors: list[str] = []
    score = 0.0

    lex = _lexical_overlap(focus_tokens, _tokens(getattr(rec, "content", "") or ""))
    if lex >= LEX_MIN_OVERLAP:
        score += min(0.5, lex)
        anchors.append("topic")

    if focus_project:
        pid, _ = resolve_project_for_record(store, rec)
        if pid and pid == focus_project:
            score += 0.35
            anchors.append("project")

    occurred = _parse_iso(getattr(rec, "occurred_at", None))
    if occurred is not None and win_from is not None and win_until is not None:
        if win_from <= occurred <= win_until:
            score += 0.25
            anchors.append("time")

    rec_actors = set(getattr(rec, "actor_ids", None) or []) | set(
        getattr(rec, "participant_ids", None) or []
    )
    if focus_actors and rec_actors & focus_actors:
        score += 0.2
        anchors.append("people")

    # A different sense than the focus is exactly the cross-sense we want.
    if sense_lenses.sense_for_record(rec) not in primary_senses:
        score += 0.1
        anchors.append("cross-sense")

    # Require topical relevance: pure same-day/same-project without any lexical
    # or people signal is too noisy to include.
    if "topic" not in anchors and "people" not in anchors:
        return 0.0, []
    return score, anchors


def _diversify_cross_sense(
    scored: list[tuple[Any, float, list[str]]],
    *,
    primary_senses: set[str],
    limit: int = MAX_CROSS_SENSE,
    reserved: int = CROSS_SENSE_RESERVED,
) -> list[tuple[Any, float, list[str]]]:
    """Fill ``limit`` slots, reserving ``reserved`` for other-sense hits.

    Same-sense neighbors (e.g. more github commits next to a github PR) remain
    useful but must not monopolize the dossier when Slack/meeting signals also
    clear the soft threshold — that was the presets/roles failure mode.
    """
    if not scored:
        return []
    other = [
        item for item in scored
        if sense_lenses.sense_for_record(item[0]) not in primary_senses
    ]
    reserved_n = min(reserved, limit, len(other))
    # Prefer other-sense first (up to reserved), then fill from the global
    # ranking so high-scoring same-sense still appear when slots remain.
    picked: list[tuple[Any, float, list[str]]] = list(other[:reserved_n])
    picked_ids = {id(x[0]) for x in picked}
    for item in scored:
        if len(picked) >= limit:
            break
        if id(item[0]) in picked_ids:
            continue
        picked.append(item)
        picked_ids.add(id(item[0]))
    return picked[:limit]


def _gather_cross_sense(
    store: TwinStore,
    *,
    vault_id: str,
    focus_text: str,
    focus_actors: set[str],
    focus_project: Optional[str],
    time_from: Optional[str],
    time_until: Optional[str],
    exclude_ids: set[str],
    primary_senses: set[str],
) -> list[tuple[Any, float, list[str]]]:
    focus_tokens = _tokens(focus_text)
    if not focus_tokens:
        return []
    wf = _parse_iso(time_from)
    wu = _parse_iso(time_until)
    if wf is not None:
        wf = wf - timedelta(hours=SOFT_WINDOW_PAD_HOURS)
    if wu is not None:
        wu = wu + timedelta(hours=SOFT_WINDOW_PAD_HOURS)

    scored: list[tuple[Any, float, list[str]]] = []
    for rec in _iter_vault_records(store, vault_id):
        rid = getattr(rec, "id", None)
        if rid and rid in exclude_ids:
            continue
        if not (getattr(rec, "content", "") or "").strip():
            continue
        score, anchors = _score_cross_candidate(
            store, rec,
            focus_tokens=focus_tokens, focus_actors=focus_actors,
            focus_project=focus_project, win_from=wf, win_until=wu,
            primary_senses=primary_senses,
        )
        if score >= SOFT_MIN_SCORE:
            scored.append((rec, score, anchors))
    scored.sort(key=lambda t: t[1], reverse=True)
    return _diversify_cross_sense(scored, primary_senses=primary_senses)


# -- related / neighbors / stance --------------------------------------------


def _related_from_retrieve(
    store: TwinStore,
    embedder: Embedder,
    *,
    query: str,
    project_id: Optional[str],
    exclude_episode_id: Optional[str],
    limit: int,
) -> list[dict[str, Any]]:
    if not query.strip():
        return []
    from .retrieval import retrieve

    result = retrieve(
        store, embedder, query,
        target_domain="technical",
        firewall=None,
        project_id=project_id,
        include_candidates=True,
        include_rejected=True,
        limit=max(limit * 2, 20),
    )
    out: list[dict[str, Any]] = []
    for hit in result.hits:
        mem = hit.claim
        payload = mem.payload or {}
        if exclude_episode_id and payload.get("episode_id") == exclude_episode_id:
            continue
        out.append({
            "id": mem.id,
            "type": mem.type.value if hasattr(mem.type, "value") else str(mem.type),
            "domain": mem.domain,
            "status": mem.status.value if hasattr(mem.status, "value") else str(mem.status),
            "title": mem.title,
            "summary": (mem.summary or "")[:240],
            "score": hit.score,
            "why": hit.why,
        })
        if len(out) >= limit:
            break
    return out


def _gather_neighbors(
    store: TwinStore, *, vault_id: str, project_id: Optional[str],
    exclude_episode_id: Optional[str], limit: int,
) -> list[dict[str, Any]]:
    if not project_id or not hasattr(store, "list_work_episodes"):
        return []
    out: list[dict[str, Any]] = []
    for ep in store.list_work_episodes(project_id=project_id, vault_id=vault_id, limit=50):
        if ep.id == exclude_episode_id:
            continue
        summary = ""
        if hasattr(store, "list_episode_phases"):
            phases = store.list_episode_phases(ep.id)
            summary = "; ".join(
                p.summary for p in sorted(phases, key=lambda x: x.order) if p.summary
            )[:200]
        out.append({
            "episode_id": ep.id,
            "title": ep.title,
            "phase_summary": summary,
        })
        if len(out) >= limit:
            break
    return out


def _gather_user_stance(
    store: TwinStore, *, project_id: Optional[str], limit: int,
) -> list[dict[str, Any]]:
    stance_types = ("preference", "procedure", "constraint")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for t in stance_types:
        rows = store.list_claims(
            type_=t, status="confirmed", project_id=project_id, limit=limit,
        )
        if not rows and project_id:
            rows = store.list_claims(type_=t, status="confirmed", limit=limit)
        for mem in rows:
            if mem.id in seen:
                continue
            seen.add(mem.id)
            out.append({
                "id": mem.id,
                "type": mem.type.value if hasattr(mem.type, "value") else str(mem.type),
                "title": mem.title,
                "summary": (mem.summary or "")[:200],
            })
            if len(out) >= limit:
                return out
    return out


def _compiler_gaps(
    primary: list[DossierBlob], cross: list[DossierBlob],
    related: list[dict[str, Any]],
) -> list[str]:
    """Deterministic hints — unlinked signals worth an explicit connection.

    The flagship case (success criterion): a Slack/meeting symptom sitting in
    cross_sense next to primary work, with no memory yet linking them. That is
    a candidate 'PR X resolved the problem reported in <sense>'.
    """
    gaps: list[str] = []
    symptom_senses = {"slack", "meeting", "mail"}
    p_senses = {b.sense for b in primary}
    for b in cross:
        if b.sense in symptom_senses and p_senses - symptom_senses:
            other = ", ".join(sorted(p_senses - symptom_senses))
            gaps.append(
                f"{b.sense} signal {b.ref} overlaps the {other} work in time/"
                f"topic but no memory links them — consider whether the work "
                f"resolves what {b.sense} raised."
            )
    if not gaps:
        return gaps
    return gaps[:4]


# -- public compile entry points ---------------------------------------------


def compile_episode_dossier(
    store: TwinStore,
    embedder: Embedder,
    episode_id: str,
    *,
    session_id: Optional[str] = None,
    budget_chars: int = DEFAULT_BUDGET_CHARS,
) -> Optional[AnalysisDossier]:
    """Compile a dossier focused on one WorkEpisode."""
    if not hasattr(store, "get_work_episode"):
        return None
    ep = store.get_work_episode(episode_id)
    if ep is None:
        return None

    member_recs, member_ids = _member_record_ids(store, episode_id)
    focus = DossierFocus(
        kind="episode",
        id=ep.id,
        vault_id=ep.vault_id,
        project_id=ep.project_id,
        title=ep.title,
        time_from=ep.started_at,
        time_until=ep.ended_at,
    )
    return _compile(
        store, embedder,
        focus=focus,
        primary_recs=member_recs,
        exclude_ids=member_ids,
        exclude_episode_id=ep.id,
        session_id=session_id,
        budget_chars=budget_chars,
    )


def compile_window_dossier(
    store: TwinStore,
    embedder: Embedder,
    *,
    vault_id: str,
    project_id: Optional[str] = None,
    time_from: Optional[str] = None,
    time_until: Optional[str] = None,
    title: str = "",
    session_id: Optional[str] = None,
    budget_chars: int = DEFAULT_BUDGET_CHARS,
) -> AnalysisDossier:
    """Compile a dossier over a time window (+ optional project) — the input to
    the pattern pass (habits / preferences / procedures across a window)."""
    wf = _parse_iso(time_from)
    wu = _parse_iso(time_until)
    primary_recs: list[Any] = []
    for rec in _iter_vault_records(store, vault_id):
        occ = _parse_iso(getattr(rec, "occurred_at", None))
        if wf is not None and occ is not None and occ < wf:
            continue
        if wu is not None and occ is not None and occ > wu:
            continue
        if project_id:
            pid, _ = resolve_project_for_record(store, rec)
            if pid != project_id:
                continue
        primary_recs.append(rec)
    focus = DossierFocus(
        kind="window",
        id=f"{vault_id}:{time_from or '?'}:{time_until or '?'}",
        vault_id=vault_id,
        project_id=project_id,
        title=title or "Activity window",
        time_from=time_from,
        time_until=time_until,
    )
    exclude_ids = {getattr(r, "id", None) for r in primary_recs if getattr(r, "id", None)}
    return _compile(
        store, embedder,
        focus=focus,
        primary_recs=primary_recs,
        exclude_ids=exclude_ids,
        exclude_episode_id=None,
        session_id=session_id,
        budget_chars=budget_chars,
        scan_cross=project_id is None,  # window already gathered its project set
    )


def _compile(
    store: TwinStore,
    embedder: Embedder,
    *,
    focus: DossierFocus,
    primary_recs: list[Any],
    exclude_ids: set[str],
    exclude_episode_id: Optional[str],
    session_id: Optional[str],
    budget_chars: int,
    scan_cross: bool = True,
) -> AnalysisDossier:
    budget = DossierBudget(max_chars=budget_chars)

    focus_text_parts = [focus.title]
    focus_actors: set[str] = set()
    for rec in primary_recs:
        focus_text_parts.append((getattr(rec, "content", "") or "")[:1500])
        focus_actors |= set(getattr(rec, "actor_ids", None) or [])
        focus_actors |= set(getattr(rec, "participant_ids", None) or [])
    focus_text = "\n".join(p for p in focus_text_parts if p)
    primary_senses = {sense_lenses.sense_for_record(r) for r in primary_recs}

    cross: list[tuple[Any, float, list[str]]] = []
    if scan_cross and focus.vault_id:
        cross = _gather_cross_sense(
            store,
            vault_id=focus.vault_id,
            focus_text=focus_text,
            focus_actors=focus_actors,
            focus_project=focus.project_id,
            time_from=focus.time_from,
            time_until=focus.time_until,
            exclude_ids=exclude_ids,
            primary_senses=primary_senses,
        )

    primary_blobs, cross_blobs = _fill_budget(
        primary_recs, cross, budget, store=store,
    )

    # related: retrieve() (graph expand + rejected) + live session artifacts
    query = focus_text[:900]
    related = _related_from_retrieve(
        store, embedder,
        query=query,
        project_id=focus.project_id,
        exclude_episode_id=exclude_episode_id,
        limit=MAX_RELATED,
    )
    session_hits = _session_artifacts(store, focus.project_id, session_id)
    related = session_hits + [
        r for r in related if r["id"] not in {s["id"] for s in session_hits}
    ]
    related = related[: MAX_RELATED + len(session_hits)]

    neighbors = _gather_neighbors(
        store, vault_id=focus.vault_id, project_id=focus.project_id,
        exclude_episode_id=exclude_episode_id, limit=MAX_NEIGHBORS,
    )
    stance = _gather_user_stance(store, project_id=focus.project_id, limit=MAX_STANCE)

    senses = []
    for b in primary_blobs + cross_blobs:
        senses.append(b.sense)
    if session_hits:
        senses.append("session")
    lenses = sense_lenses.lenses_for(senses or ["generic"])
    gaps = _compiler_gaps(primary_blobs, cross_blobs, related)

    return AnalysisDossier(
        focus=focus,
        primary=primary_blobs,
        cross_sense=cross_blobs,
        neighbors=neighbors,
        related_claims=related,
        lenses=lenses,
        user_stance=stance,
        gaps=gaps,
        budget=budget,
    )


def _session_artifacts(
    store: TwinStore, project_id: Optional[str], session_id: Optional[str],
) -> list[dict[str, Any]]:
    """Reuse the reflect session-artifact gatherer with a lightweight brief."""
    from .episode_reflect import EpisodeBrief, gather_session_artifacts

    brief = EpisodeBrief(
        episode_id="", vault_id="", title="", project_id=project_id,
    )
    return gather_session_artifacts(store, brief, session_id=session_id)
