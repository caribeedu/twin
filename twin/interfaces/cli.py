"""twin CLI.

    twin init                          create ~/.twin + guided Ollama/model setup
    twin ingest <paths...>             run sensors over docs/transcripts/meetings/slack exports
    twin extract [--auto-approve|-A]   interpret pending percepts (+ optional auto-confirm)
    twin review                        interactive review (single-key a/r/s/q)
    twin search "query" [--domain d]   hybrid search
    twin pack "task" [--domain d]      build a safe context pack (confirmed only;
                                       --include-candidates to loosen)
    twin observe "current text"        memory observer suggestion
    twin workspace tick "text"         parallel memory tick (recall + optional interpret)
    twin consolidate daily|weekly      scheduled consolidation cycle
    twin runtime start|status|enqueue  durable cognitive runtime (v1.0)
    twin promote <memory_id>           promote a memory into the judgment profile
    twin supersede <new_id> <old_id>   new memory replaces the old one
    twin contradict <id_a> <id_b>      flag two memories as contradictory
    twin stats                         memory + product quality metrics
    twin reindex                       regenerate embeddings with the current embedder
    twin session start "task"          open a cognitive session (context pack + tracking)
    twin session observe <id> ...      record artifacts produced during the work
    twin session complete <id>         close the loop: work → percepts → candidates
    twin session feedback <id> <v>     usefulness feedback (useful, irrelevant, ...)
    twin project add|list              first-class projects (repos, aliases, goals)
    twin watch <paths...>              continuous incremental ingestion
    twin doctor                        verify models, stores, configs, MCP clients
    twin setup ollama|postgres|mcp     bootstrap local infrastructure
    twin serve [--port 8765]           local API + review UI
    twin mcp                           MCP server over stdio
    twin native event|install|bindings host-native observation (Phase 8)
    twin export                        dump memories/entities/judgment as JSON
"""

from __future__ import annotations

import argparse
import json

from ..workspace import Workspace


def _print(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def cmd_init(args) -> None:
    from . import ux
    from .setup_wizard import run_setup_wizard

    ws = Workspace(args.home)
    interactive = not getattr(args, "skip_setup", False)
    run_setup_wizard(ws.cfg, interactive=interactive)
    ux.print_panel(
        f"db        {ws.cfg.resolved_db_url}\n"
        f"policies  {ws.cfg.policies_path}\n"
        f"judgment  {ws.cfg.judgment_path}\n"
        f"calib     {ws.cfg.calibration_path}\n"
        f"embedder  {ws.embedder.name}\n"
        f"ollama    {ws.cfg.ollama_url}\n"
        f"model     {ws.cfg.ollama_model}\n"
        f"embed     {ws.cfg.ollama_embed_model}",
        title="home ready",
    )
    ux.print_legend([
        ("1", "twin ingest <paths>  — sense docs / transcripts"),
        ("2", "twin extract         — interpret into memories"),
        ("3", "twin review          — approve / reject candidates"),
        ("4", "twin doctor          — verify local setup"),
        ("5", "twin setup mcp cursor — wire MCP client"),
    ], title="next steps")


def cmd_ingest(args) -> None:
    from . import ux

    ws = Workspace(args.home)
    paths = [str(p) for p in args.paths]
    ux.print_rule("ingest")
    ux.print_kv([
        ("paths", ", ".join(paths)),
        ("home", str(ws.cfg.home)),
        ("db", ws.cfg.resolved_db_url),
    ])
    ux.print_panel(
        "Sensors read files into percepts (raw observations).\n"
        "Duplicates are skipped. Run twin extract next to interpret.",
        title="what this does",
    )
    with ux.spinner(f"Sensing {len(paths)} path(s)…"):
        new_ids, skipped = ws.ingest(args.paths)

    if new_ids:
        preview = "\n".join(f"  {pid}" for pid in new_ids[:20])
        if len(new_ids) > 20:
            preview += f"\n  … +{len(new_ids) - 20} more"
        ux.print_panel(preview, title=f"new percepts ({len(new_ids)})")
        ux.print_ok(f"ingested {len(new_ids)} percept(s)")
    else:
        ux.print_warn("no new percepts")

    if skipped:
        skip_body = "\n".join(f"  {s}" for s in skipped[:30])
        if len(skipped) > 30:
            skip_body += f"\n  … +{len(skipped) - 30} more"
        ux.print_panel(skip_body, title=f"skipped ({len(skipped)})")
    else:
        ux.print_dim("skipped: 0")

    ux.print_legend([
        ("→", "twin extract   — interpret pending percepts"),
        ("→", "twin interpret status — see queue health"),
        ("→", "twin review    — after extract creates candidates"),
    ], title="next")


def cmd_interpret(args) -> None:
    from collections import Counter

    from ..cognition.interpreter import MAX_INTERPRETATION_ATTEMPTS

    ws = Workspace(args.home)
    if args.interpret_command == "deferred":
        # Include backoff / terminal errors — status alone is easy to miss.
        stuck = [
            i for i in ws.store.list_interpretations(limit=10000)
            if i.status in ("deferred", "error")
        ]
        if not stuck:
            print("no deferred/error percepts")
            return
        for st in stuck:
            flag = "terminal" if st.terminal else "retryable"
            print(
                f"{st.percept_id}  {st.status}/{st.failure_class or '-'}  "
                f"attempts={st.attempts}  {flag}  "
                f"next={st.next_attempt_at or 'now'}  {st.detail}"
            )
        return
    if args.interpret_command == "signals":
        signals = ws.store.list_detection_signals(limit=10000)
        if not signals:
            print("no detection signals (heuristic mode records hints, not memories)")
            return
        for s in signals:
            print(f"{s.percept_id}  {s.kind:20}  {s.span[:70]}")
        return
    # status
    counts = Counter(i.status for i in ws.store.list_interpretations(limit=10000))
    never = len([p for p in ws.store.percepts_pending_interpretation(
        max_attempts=MAX_INTERPRETATION_ATTEMPTS)
        if ws.store.get_interpretation(p.id) is None])
    print(f"never interpreted : {never}")
    for status in ("interpreted", "empty", "deferred", "error",
                   "heuristic_detection", "quarantined"):
        print(f"{status:20}: {counts.get(status, 0)}")
    signal_count = len(ws.store.list_detection_signals(limit=10000))
    print(f"{'detection_signals':20}: {signal_count} (routing hints, not memories)")


def cmd_extract(args) -> None:
    from ..cognition import extract_pending
    from ..cognition.interpreter import MAX_INTERPRETATION_ATTEMPTS
    from ..memory.models import MemoryStatus
    from . import ux

    ws = Workspace(args.home)
    pending = ws.store.percepts_pending_interpretation(
        max_attempts=MAX_INTERPRETATION_ATTEMPTS,
    )
    ux.print_rule("extract")
    if not pending:
        ux.print_warn("nothing to interpret (all percepts already interpreted or deferred)")
        return

    auto = bool(getattr(args, "auto_approve", False))
    ux.print_dim(
        f"{len(pending)} percept(s) · model={ws.cfg.ollama_model} · "
        f"url={ws.cfg.ollama_url}"
        + (" · auto-approve ON" if auto else "")
    )

    details: list[str] = []

    with ux.progress_bar(len(pending), description="Extracting") as advance:
        def on_progress(done, total, percept, report) -> None:
            short = percept.id[:10]
            if report.deferred:
                label = f"{short} deferred"
                st = ws.store.get_interpretation(report.percept_id)
                detail = (st.detail if st else "") or report.interpretation_status
                fclass = (st.failure_class if st else "") or "-"
                why = (
                    "model unreachable — start Ollama / check TWIN_OLLAMA_URL"
                    if report.interpretation_status == "deferred"
                    else "interpreter call failed (timeout/schema/HTTP)"
                )
                details.append(
                    f"{report.percept_id}: {report.interpretation_status.upper()} "
                    f"({fclass}) — {why}"
                )
                if detail:
                    details.append(f"  detail: {detail}")
            else:
                label = f"{short} +{len(report.inserted)}"
                details.append(
                    f"{report.percept_id}: {len(report.inserted)} memories via "
                    f"{report.extractor} ({report.flagged_for_review} to review, "
                    f"{report.duplicates} duplicates, "
                    f"{report.pii_findings} PII findings masked)"
                )
            advance(label)

        reports = extract_pending(
            ws.store, ws.cfg, ws.embedder, on_progress=on_progress,
        )

    for line in details:
        ux.print_dim(line) if line.startswith("  ") else print(line)

    total = sum(len(r.inserted) for r in reports)
    review = sum(r.flagged_for_review for r in reports)
    dups = sum(r.duplicates for r in reports)
    deferred = sum(1 for r in reports if r.deferred)
    ux.print_ok(
        f"total: {total} new, {review} queued for review, {dups} duplicates, "
        f"{deferred} deferred"
    )

    if auto:
        approved = 0
        for r in reports:
            for mid in r.inserted:
                mem = ws.store.get_memory(mid)
                if mem is None:
                    continue
                if mem.status.value in ("candidate", "confirmed"):
                    # confirm candidates; leave already-confirmed alone
                    if mem.status.value == "candidate":
                        ws.store.set_status(mid, MemoryStatus.confirmed)
                        approved += 1
        ux.print_ok(f"auto-approved {approved} memory(ies) — skipped review queue")
    elif review:
        ux.print_dim("next: twin review   (or re-run with --auto-approve / -A)")

    if deferred:
        ux.print_dim(
            "pending percepts stay eligible — inspect with "
            "'twin interpret deferred' then re-run 'twin extract'"
        )


def cmd_review(args) -> None:
    from ..cognition.quality import analyze_candidates, review_queue
    from ..memory.models import MemoryStatus
    from . import ux

    ws = Workspace(args.home)
    if getattr(args, "analyze", False):
        reports = analyze_candidates(ws.store, ws.embedder)
        ux.print_ok(f"analyzed {len(reports)} candidates")
        for r in reports[:20]:
            print(f"  {r.memory_id} prio={r.review_priority:.2f} "
                  f"action={r.suggested_action.value} flags={r.quality_flags}")
        return

    queue = review_queue(
        ws.store,
        project_id=None,
        conflicts_only=getattr(args, "conflicts", False),
        min_priority=0.7 if getattr(args, "priority", None) == "high" else 0.0,
        limit=200,
    )
    if getattr(args, "project", None):
        proj = ws.store.find_project(args.project) or ws.store.get_project(args.project)
        if proj:
            queue = [m for m in queue if m.project_id == proj.id]
    if not queue:
        ux.print_warn("review queue is empty")
        return

    ux.print_rule("review")
    ux.print_panel(
        f"{len(queue)} candidate(s) in priority order.\n"
        "Press a single key — no Enter needed.",
        title="queue",
    )
    ux.print_legend([
        ("a", "approve — confirm memory (enters retrieval / packs)"),
        ("r", "reject — discard memory (never retrieved)"),
        ("s", "skip — leave as candidate, move to next"),
        ("q", "quit — stop review, keep remaining candidates"),
    ], title="legend")
    approved = rejected = skipped = 0
    for idx, mem in enumerate(queue, start=1):
        body = (
            f"prio {mem.review_priority:.2f} · {mem.type.value} · {mem.domain} · "
            f"{mem.sensitivity.value} · conf {mem.confidence:.2f}\n"
            f"{mem.title}"
        )
        if mem.summary != mem.title:
            body += f"\n{mem.summary}"
        if mem.quality_flags:
            body += f"\nflags: {', '.join(mem.quality_flags)}"
        if mem.review_reason:
            body += f"\nreason: {mem.review_reason}"
        for ev in ws.store.get_evidence(mem.id)[:1]:
            body += f'\nevidence: "{ev.quote[:140]}"'
        ux.print_panel(body, title=f"{idx}/{len(queue)}")
        choice = ux.read_key("  [a]pprove [r]eject [s]kip [q]uit  ", allowed="arsq")
        if choice == "a":
            ws.store.set_status(mem.id, MemoryStatus.confirmed)
            approved += 1
            ux.print_ok("approved")
        elif choice == "r":
            ws.store.set_status(mem.id, MemoryStatus.rejected)
            rejected += 1
            ux.print_err("rejected")
        elif choice == "q":
            ux.print_dim("quit")
            break
        else:
            skipped += 1
            ux.print_dim("skipped")
    ux.print_ok(f"done — approved={approved} rejected={rejected} skipped={skipped}")


def cmd_review_batch(args) -> None:
    from ..memory.batches import create_batch, get_batch

    ws = Workspace(args.home)
    if args.batch_command == "create":
        query = {}
        if args.source:
            query["source_sensor"] = args.source
        if args.project:
            proj = ws.store.find_project(args.project)
            if proj:
                query["project_id"] = proj.id
        batch = create_batch(ws.store, args.name or "batch", query=query)
        print(f"{batch.id}  {batch.name}  {batch.progress_total} memories")
    elif args.batch_command == "resume":
        batch = get_batch(ws.store, args.batch_id)
        if batch is None:
            raise SystemExit(f"batch {args.batch_id} not found")
        print(f"{batch.id}  reviewed {batch.progress_reviewed}/{batch.progress_total}")
        for mid in batch.memory_ids[batch.progress_reviewed:batch.progress_reviewed + 5]:
            m = ws.store.get_memory(mid)
            if m:
                print(f"  {m.id}  {m.title}")


def cmd_memory(args) -> None:
    from ..memory.lifecycle import archive_memory, merge_memories, split_memory, undo_operation
    from ..memory.provenance import memory_provenance

    ws = Workspace(args.home)
    if args.memory_command == "diff":
        a, b = ws.store.get_memory(args.id_a), ws.store.get_memory(args.id_b)
        if not a or not b:
            raise SystemExit("memory not found")
        print(f"A: {a.title}\n   {a.summary}\n")
        print(f"B: {b.title}\n   {b.summary}")
    elif args.memory_command == "merge":
        result = merge_memories(ws.store, args.ids, embedder=ws.embedder)
        print(f"merged → {result.extras.get('merged_id')}  op={result.operation_id}")
    elif args.memory_command == "split":
        parts = [{"title": p, "summary": p} for p in args.parts]
        result = split_memory(ws.store, args.memory_id, parts, embedder=ws.embedder)
        print(f"split → {result.extras.get('children')}  op={result.operation_id}")
    elif args.memory_command == "provenance":
        print(json.dumps(memory_provenance(ws.store, args.memory_id), indent=2, default=str))
    elif args.memory_command == "archive":
        result = archive_memory(ws.store, args.memory_id)
        print(f"archived {args.memory_id}  op={result.operation_id}")
    elif args.memory_command == "unsupported":
        for m in ws.store.list_memories(status="unsupported", limit=200):
            print(f"{m.id}  {m.title}")
    elif args.memory_command == "undo":
        print(undo_operation(ws.store, args.operation_id))


def cmd_eval(args) -> None:
    from ..evals import compare_runs, default_eval_root, run_extraction_eval, run_retrieval_eval

    ws = Workspace(args.home)
    root = default_eval_root()
    if args.eval_command == "extraction":
        run = run_extraction_eval(ws.store, ws.cfg, ws.embedder, root / "extraction")
        print(json.dumps({"id": run.id, "summary": run.summary}, indent=2))
    elif args.eval_command == "retrieval":
        run = run_retrieval_eval(ws.store, ws.embedder, root / "retrieval", firewall=ws.firewall)
        print(json.dumps({"id": run.id, "summary": run.summary}, indent=2))
    elif args.eval_command == "golden":
        from ..evals.golden import run_golden_work_loop
        report = run_golden_work_loop(ws.store, ws.cfg, ws.embedder)
        print(json.dumps(report, indent=2, default=str))
        if not report.get("ok"):
            raise SystemExit(1)
    elif args.eval_command == "v1-completion":
        from ..evals.v1_completion import v1_completion_matrix
        matrix = v1_completion_matrix()
        print(json.dumps(matrix, indent=2, default=str))
        if not matrix.get("ok"):
            raise SystemExit(1)
    elif args.eval_command == "compare":
        print("compare requires two prior run payloads; use API /api/evals for now")


def cmd_source(args) -> None:
    from ..memory.calibration import load_calibration, source_report

    ws = Workspace(args.home)
    cal = load_calibration(ws.cfg.calibration_path)
    print(json.dumps(source_report(cal, args.source if args.source != "all" else None), indent=2))


def cmd_retention(args) -> None:
    from ..memory.retention import apply_retention_policies

    ws = Workspace(args.home)
    dry = not getattr(args, "apply", False)
    print(json.dumps(apply_retention_policies(ws.store, dry_run=dry), indent=2))


def cmd_delete_source(args) -> None:
    from ..memory.retention import delete_by_source_system

    ws = Workspace(args.home)
    dry = not getattr(args, "apply", False)
    print(json.dumps(
        delete_by_source_system(ws.store, args.source_system, dry_run=dry),
        indent=2, default=str,
    ))


def cmd_undo(args) -> None:
    from ..memory.lifecycle import undo_operation

    ws = Workspace(args.home)
    print(json.dumps(undo_operation(ws.store, args.operation_id), indent=2))


def cmd_search(args) -> None:
    from ..memory.search import search
    from . import ux

    ws = Workspace(args.home)
    domain = args.domain or "technical"
    ux.print_rule("search")
    ux.print_kv([
        ("query", args.query),
        ("domain", domain),
        ("limit", str(args.limit)),
        ("embedder", ws.embedder.name),
    ])
    with ux.spinner("Searching memories…"):
        result = search(
            ws.store, ws.embedder, args.query,
            target_domain=domain, firewall=ws.firewall, limit=args.limit,
        )
    if not result.hits:
        ux.print_warn("no hits")
    else:
        ux.print_ok(f"{len(result.hits)} hit(s)")
        for i, h in enumerate(result.hits, start=1):
            mem = h.memory
            body = (
                f"{ux.score_bar(h.score)}  {h.why}\n"
                f"[{mem.type.value}] {mem.domain} · {mem.status.value} · "
                f"conf {mem.confidence:.2f}\n"
                f"{mem.title}"
            )
            if mem.summary and mem.summary != mem.title:
                summary = mem.summary if len(mem.summary) <= 220 else mem.summary[:217] + "…"
                body += f"\n{summary}"
            ux.print_panel(body, title=f"{i}/{len(result.hits)} · {mem.id[:10]}")
    if result.blocked:
        ux.print_warn(f"{len(result.blocked)} blocked by firewall")
        for b in result.blocked[:12]:
            ux.print_dim(f"  {b.memory_id}: {b.rule} — {b.reason}")
        if len(result.blocked) > 12:
            ux.print_dim(f"  … +{len(result.blocked) - 12} more")


def cmd_pack(args) -> None:
    from ..cognition.context_pack import build_context_pack
    from ..privacy.identity import ensure_local_identity, resolve_access
    from ..privacy.yaml_io import bootstrap_policy_set
    from . import ux

    ws = Workspace(args.home)
    persona = getattr(args, "persona", None) or "individual"
    domain = args.domain or "technical"
    ux.print_rule("pack")
    ux.print_kv([
        ("query", args.query),
        ("domain", domain),
        ("persona", persona),
        ("max_tokens", str(args.max_tokens)),
        ("candidates", "yes" if args.include_candidates else "confirmed only"),
    ])
    bootstrap_policy_set(ws.store, policies_path=ws.cfg.policies_path)
    ensure_local_identity(ws.store)
    access = resolve_access(
        ws.store, surface="cli", client="local-cli",
        persona=persona,
        purpose=getattr(args, "purpose", None) or "memory_retrieval",
        audience=getattr(args, "audience", None) or "self",
        requested_domains=[args.domain] if getattr(args, "domain", None) else [],
    )
    with ux.spinner("Building context pack…"):
        pack = build_context_pack(
            ws.store, ws.cfg, ws.embedder, args.query,
            target_domain=domain, max_tokens=args.max_tokens,
            include_candidates=args.include_candidates,
            firewall=ws.firewall, access=access,
        )
    if args.json:
        _print(pack.__dict__)
        return

    budget = pack.token_budget or {}
    ux.print_kv([
        ("confidence", f"{pack.confidence:.2f}"),
        ("mode", pack.mode or "compact"),
        ("sources", str(len(pack.sources))),
        ("blocked", str(pack.blocked_count or len(pack.blocked))),
        ("evidence", "included" if pack.evidence_included else "omitted"),
        (
            "budget",
            f"{budget.get('used_chars', '?')} chars / "
            f"max_tokens={budget.get('max', args.max_tokens)}",
        ),
    ])
    body = pack.context_pack or "(empty pack — nothing passed firewall / retrieval)"
    ux.print_panel(body, title="context pack")
    if pack.sources:
        lines = []
        for src in pack.sources[:15]:
            mid = src.get("memory_id") or src.get("id") or "?"
            title = src.get("title") or ""
            conf = src.get("confidence")
            why = src.get("why_relevant") or src.get("label") or ""
            prefix = f"conf {conf:.2f}  " if isinstance(conf, (int, float)) else ""
            lines.append(f"{prefix}{mid}  {title}  {why}".rstrip())
        ux.print_panel("\n".join(lines), title=f"sources ({len(pack.sources)})")
    if pack.blocked:
        ux.print_warn(f"{len(pack.blocked)} memories withheld by firewall")
        for b in pack.blocked[:8]:
            if isinstance(b, dict):
                ux.print_dim(
                    f"  {b.get('memory_id', '?')}: {b.get('rule', b.get('reason', ''))}"
                )
            else:
                ux.print_dim(f"  {b}")
    ux.print_ok("pack ready — paste into your agent or pipe with --json")


def cmd_observe(args) -> None:
    from ..cognition.observer import observe

    ws = Workspace(args.home)
    s = observe(ws.store, ws.cfg, ws.embedder, args.text, args.domain)
    _print({
        "inferred_domain": s.inferred_domain,
        "suggested_context": s.suggested_context,
        "blocked_context": s.blocked_context,
    })


def cmd_workspace(args) -> None:
    from ..cognition.workspace import workspace_tick

    ws = Workspace(args.home)
    if args.workspace_command != "tick":
        raise SystemExit(f"unknown workspace command: {args.workspace_command}")
    result = workspace_tick(
        ws.store, ws.cfg, ws.embedder, args.text,
        session_id=getattr(args, "session_id", "") or "",
        target_domain=getattr(args, "domain", None),
        cwd=getattr(args, "cwd", None),
        interpret=bool(getattr(args, "interpret", False)),
        input_mode=getattr(args, "input_mode", "snapshot") or "snapshot",
        sequence=getattr(args, "sequence", None),
        idempotency_key=getattr(args, "idempotency_key", None),
        retry=bool(getattr(args, "retry", False)),
        firewall=ws.firewall,
    )
    _print(result.to_dict())


def cmd_consolidate(args) -> None:
    from ..cognition.consolidation_cycle import run_consolidation_cycle

    ws = Workspace(args.home)
    kind = args.consolidate_command
    result = run_consolidation_cycle(
        ws.store, ws.cfg, ws.embedder,
        kind=kind,
        dry_run=not getattr(args, "apply", False),
        analyze_limit=int(getattr(args, "limit", 200) or 200),
        retry=bool(getattr(args, "retry", False)),
    )
    _print(result.to_dict())


def cmd_runtime(args) -> None:
    from ..runtime.models import JobKind
    from ..runtime.queue import RuntimeQueue
    from ..runtime.scheduler import RuntimeScheduler
    from ..runtime.service import TwinRuntime

    ws = Workspace(args.home)
    cmd = args.runtime_command
    q = RuntimeQueue(ws.store)

    if cmd == "start":
        rt = TwinRuntime(
            ws.store, ws.cfg, ws.embedder,
            workers=int(getattr(args, "workers", 2) or 2),
            vault_id=getattr(args, "vault", None) or None,
            lease_seconds=int(getattr(args, "lease", 60) or 60),
            schedule_interval=float(getattr(args, "schedule_interval", 30) or 30),
            offline=bool(getattr(args, "offline", False)),
        )
        rt.run()
        return

    if cmd == "status":
        _print({
            "queue": ws.store.runtime_queue_depth(),
            "dead_letters": len(ws.store.list_runtime_dead_letters(limit=500)),
            "recent": [j.model_dump(mode="json") for j in ws.store.list_runtime_jobs(limit=20)],
        })
        return

    if cmd == "schedule":
        ids = RuntimeScheduler(
            q, vault_id=getattr(args, "vault", None) or "vault_general",
        ).tick()
        _print({"enqueued": ids})
        return

    if cmd == "enqueue":
        kind = JobKind(args.kind)
        payload = {}
        if getattr(args, "payload_json", None):
            payload = json.loads(args.payload_json)
        job = q.enqueue(
            kind,
            payload=payload,
            idempotency_key=getattr(args, "idempotency_key", "") or "",
            vault_id=getattr(args, "vault", None) or "vault_general",
            priority=int(getattr(args, "priority", 100) or 100),
        )
        _print(job.model_dump(mode="json"))
        return

    if cmd == "job":
        job = ws.store.get_runtime_job(args.job_id)
        if job is None:
            raise SystemExit(f"job {args.job_id} not found")
        _print(job.model_dump(mode="json"))
        return

    if cmd == "retry":
        job = q.retry(args.job_id)
        if job is None:
            raise SystemExit(f"job {args.job_id} not found")
        _print(job.model_dump(mode="json"))
        return

    if cmd == "cancel":
        ok = q.cancel(args.job_id)
        _print({"id": args.job_id, "cancelled": ok})
        return

    raise SystemExit(f"unknown runtime command: {cmd}")


def cmd_reindex(args) -> None:
    ws = Workspace(args.home)
    count = ws.reindex()
    print(f"re-embedded {count} memories with {ws.embedder.name}")


def cmd_promote(args) -> None:
    from ..judgment.profile import promote_memory

    ws = Workspace(args.home)
    mem = ws.store.get_memory(args.memory_id)
    if mem is None:
        raise SystemExit(f"memory {args.memory_id} not found")
    section = promote_memory(ws.cfg.judgment_path, mem, store=ws.store)
    ws.store.update_memory(mem.id, payload={**mem.payload, "promoted_to_judgment": True})
    print(f"promoted {mem.id} → {section} (pending human approval if proposal)")


def cmd_judgment(args) -> None:
    from ..judgment.conflicts import detect_behavior_conflicts, detect_judgment_conflicts, resolve_conflict
    from ..judgment.proposals import (
        approve_proposal, defer_proposal, preview_proposal, propose_from_memory,
        propose_from_pattern, reject_proposal,
    )
    from ..judgment.simulate import counterfactual, simulate
    from ..judgment.yaml_io import apply_yaml_import, export_judgment_yaml, preview_yaml_import
    from ..judgment.versions import active_items

    ws = Workspace(args.home)
    cmd = args.judgment_command
    if cmd == "list":
        for item in active_items(ws.store):
            print(f"{item.id}  {item.kind.value:12}  {item.statement[:80]}")
    elif cmd == "show":
        item = ws.store.get_judgment_item(args.judgment_id)
        if item is None:
            raise SystemExit("not found")
        print(item.model_dump_json(indent=2))
    elif cmd == "history":
        item = ws.store.get_judgment_item(args.judgment_id)
        if item is None:
            raise SystemExit("not found")
        print(f"supersedes: {item.supersedes}")
        for v in ws.store.list_judgment_versions():
            if args.judgment_id in v.item_ids:
                print(f"  v{v.version}  {v.id}  {v.reason}")
    elif cmd == "versions":
        for v in ws.store.list_judgment_versions():
            flag = "*" if v.active else " "
            print(f"{flag} v{v.version}  {v.id}  items={len(v.item_ids)}  {v.reason}")
    elif cmd == "import-preview":
        for c in preview_yaml_import(ws.cfg.judgment_path):
            print(f"{c['kind']:12} [{c['stability']:14}] {c['statement'][:70]}")
    elif cmd == "import":
        result = apply_yaml_import(ws.store, ws.cfg.judgment_path)
        print(f"imported {result['count']} items as version {result['version']}")
    elif cmd == "export":
        print(export_judgment_yaml(ws.store))
    elif cmd == "proposals":
        for p in ws.store.list_judgment_proposals(status=args.status or None):
            print(f"{p.id}  {p.status.value:10}  conf={p.confidence:.2f}  {p.reason[:60]}")
    elif cmd == "propose":
        if args.from_memory:
            p = propose_from_memory(ws.store, args.from_memory)
        else:
            props = propose_from_pattern(ws.store, domain=args.domain or "technical")
            if not props:
                raise SystemExit("no pattern proposals generated")
            p = props[0]
        print(p.id, p.reason)
    elif cmd == "preview":
        print(preview_proposal(ws.store, args.proposal_id))
    elif cmd == "approve":
        result = approve_proposal(
            ws.store, args.proposal_id, preview_token=args.token,
            confirm_constitutional=args.constitutional,
        )
        print(result)
    elif cmd == "reject":
        reject_proposal(ws.store, args.proposal_id, reason=args.reason or "")
        print("rejected")
    elif cmd == "defer":
        defer_proposal(ws.store, args.proposal_id)
        print("deferred")
    elif cmd == "simulate":
        result = simulate(
            ws.store, args.query, domain=args.domain or "technical",
            project_id=args.project, task_profile=args.profile or "architecture",
        )
        print(result["markdown"])
    elif cmd == "explain":
        tr = ws.store.get_judgment_trace(args.trace_id)
        if tr is None:
            raise SystemExit("trace not found")
        print(tr.model_dump_json(indent=2))
    elif cmd == "counterfactual":
        print(counterfactual(ws.store, args.query, args.judgment_id,
                             domain=args.domain or "technical"))
    elif cmd == "conflicts":
        if args.refresh:
            detect_judgment_conflicts(ws.store)
            detect_behavior_conflicts(ws.store)
        for c in ws.store.list_judgment_conflicts(status=args.status or "open"):
            print(f"{c.id}  {c.type.value:20}  {c.reason[:70]}")
    elif cmd == "resolve-conflict":
        resolve_conflict(
            ws.store, args.conflict_id,
            resolution=args.resolution or "dismiss",
            dismiss=True,
        )
        print("resolved")
    else:
        raise SystemExit(f"unknown judgment command: {cmd}")


def cmd_privacy(args) -> None:
    from ..privacy.deletion import preview_deletion
    from ..privacy.engine import evaluate_access, explain_decision
    from ..privacy.grants import create_grant, revoke_grant
    from ..privacy.models import AccessRequest
    from ..privacy.yaml_io import bootstrap_policy_set

    ws = Workspace(args.home)
    cmd = args.privacy_command
    if cmd == "bootstrap":
        v = bootstrap_policy_set(ws.store)
        print(f"policy set {v.id} v{v.version} ({len(v.policy_ids)} policies)")
    elif cmd == "simulate":
        bootstrap_policy_set(ws.store)
        memories = []
        for mid in args.memory or []:
            m = ws.store.get_memory(mid)
            if m:
                memories.append(m)
        if not memories:
            memories = ws.store.list_memories(status="confirmed", limit=20)
        req = AccessRequest(
            principal_id=f"tool_{args.tool}",
            persona=args.persona,
            purpose=args.purpose,
            audience=args.audience,
            tool_id=args.tool,
        )
        result = evaluate_access(ws.store, req, memories, persist=True)
        d = result["decision"]
        print(f"Decision: {d.effect.value.upper()}  id={d.id}")
        print(f"Allowed={d.metadata.get('resources_allowed')} "
              f"Redacted={d.metadata.get('resources_redacted')} "
              f"Denied={d.metadata.get('resources_denied')}")
        for rd in d.resource_decisions:
            print(f"  {rd.resource_id}  {rd.effect.value:18}  {rd.reason[:60]}")
    elif cmd == "explain":
        print(explain_decision(ws.store, args.decision_id))
    elif cmd == "grants":
        for g in ws.store.list_permission_grants(status=args.status):
            print(f"{g.id}  {g.status.value:10}  uses={g.uses}/{g.max_uses}  "
                  f"{g.purpose} → {g.principal_id}")
    elif cmd == "grant-create":
        g = create_grant(
            ws.store,
            principal_id=f"tool_{args.tool}",
            persona=args.persona,
            purpose=args.purpose,
            resource_scope={"domains": args.domain or []},
            ttl_seconds=args.ttl,
            max_uses=args.max_uses,
        )
        print(g.id, g.valid_until, f"max_uses={g.max_uses}")
    elif cmd == "grant-revoke":
        print(revoke_grant(ws.store, args.grant_id).status.value)
    elif cmd == "quarantine":
        for q in ws.store.list_quarantine(status=args.status):
            print(f"{q.id}  {q.severity:6}  {q.reason}  {q.detected_patterns}")
    elif cmd == "delete-preview":
        sel = {}
        if args.domain:
            sel["domain"] = args.domain
        if args.source_account:
            sel["source_account"] = args.source_account
        req = preview_deletion(ws.store, sel)
        print(req.id)
        print(f"token={req.preview_token}")
        print(req.preview)
    elif cmd == "delete-execute":
        from ..privacy.deletion import execute_deletion
        out = execute_deletion(
            ws.store, args.deletion_id,
            confirm=True, preview_token=args.token,
        )
        print(out.id, out.status.value, (out.preview or {}).get("deleted_count"))
    elif cmd == "quarantine-release":
        from ..privacy.quarantine import release_quarantine
        out = release_quarantine(
            ws.store, args.quarantine_id,
            actor=args.actor, reason=args.reason,
            mode=args.mode, confirm=True,
        )
        print(out.id, out.status.value)
    else:
        raise SystemExit(f"unknown privacy command: {cmd}")


def cmd_connector(args) -> None:
    import json as _json

    from ..connectors import (
        add_connector_instance,
        build_credential_store,
        connector_health,
        list_adapters,
        pause_connector,
        register_source_account,
        resume_connector,
        revoke_connector,
        sync_connector,
        validate_connector,
    )

    ws = Workspace(args.home)
    creds = build_credential_store(ws.cfg.home)
    cmd = args.connector_command

    if cmd == "adapters":
        for name in list_adapters():
            print(name)
    elif cmd == "list":
        for inst in ws.store.list_connector_instances():
            acc = ws.store.get_source_account(inst.account_id)
            owner = acc.source_owner if acc else "?"
            vault = acc.vault_id if acc else "?"
            print(f"{inst.id}  {inst.connector_type:8}  {inst.status:12}  "
                  f"owner={owner}  vault={vault}  account={inst.account_id}")
    elif cmd == "add":
        acc = register_source_account(
            ws.store,
            connector_type=args.connector_type,
            source_owner=args.source_owner,
            vault_id=args.vault_id,
            org_key=args.org_key,
            persona=args.persona,
            default_domain=args.domain,
            display_name=args.name or "",
            external_account_id=args.external_id or "",
            # the local CLI is the explicitly trusted admin surface; every
            # other surface must pass its resolved principal
            owner_principal_id="principal_local_cli",
        )
        inst = add_connector_instance(
            ws.store, creds, account_id=acc.id, secret=args.secret,
            configuration=_json.loads(args.config) if args.config else None,
        )
        print(f"account {acc.id}  vault={acc.vault_id}")
        print(f"connector {inst.id}  status={inst.status.value}")
    elif cmd == "configure":
        if args.config:
            ws.store.update_connector_instance(
                args.connector_id, configuration=_json.loads(args.config))
        if args.secret:
            from ..connectors import set_credential
            set_credential(ws.store, creds, args.connector_id, args.secret)
        if getattr(args, "webhook_secret", None):
            inst = ws.store.get_connector_instance(args.connector_id)
            if inst and inst.connector_type == "slack":
                from ..connectors.slack.webhook import set_webhook_secret
            else:
                from ..connectors.github.webhook import set_webhook_secret
            set_webhook_secret(ws.store, creds, args.connector_id,
                               args.webhook_secret)
        inst = ws.store.get_connector_instance(args.connector_id)
        print(f"{inst.id}  status={inst.status.value}  credential={'set' if inst.credential_ref else 'none'}")
    elif cmd in ("auth", "test"):
        health = validate_connector(ws.store, creds, args.connector_id)
        print(f"{args.connector_id}  {health.status.value}  {health.detail}")
    elif cmd == "sync":
        result = sync_connector(
            ws.store, creds, args.connector_id,
            streams=[args.stream] if args.stream else None,
            emit_percepts=not args.no_percepts,
        )
        print(f"health={result.health.value}  percepts={result.percepts}")
        for s in result.streams:
            state = "skipped:" + s.skipped if s.skipped else f"committed={s.committed}"
            print(f"  {s.stream:16}  {state}  raw={s.raw}  "
                  f"normalized={s.normalized}  dedup={s.deduplicated}  "
                  f"quarantined={s.quarantined}  percepts={s.percepts}  failed={s.failed}")
    elif cmd == "github":
        if args.github_command == "repositories":
            from ..connectors.registry import build_adapter
            inst = ws.store.get_connector_instance(args.connector_id)
            if inst is None:
                raise SystemExit(f"connector {args.connector_id} not found")
            acc = ws.store.get_source_account(inst.account_id)
            secret = creds.get(inst.credential_ref) if inst.credential_ref else None
            adapter = build_adapter(inst, acc, secret)
            for repo in adapter.list_repositories():
                print(f"{repo['full_name']:40}  "
                      f"{'private' if repo.get('private') else 'public ':7}  "
                      f"open_issues={repo.get('open_issues')}  "
                      f"pushed={repo.get('pushed_at')}")
        else:
            raise SystemExit(f"unknown github command: {args.github_command}")
    elif cmd == "slack":
        if args.slack_command == "channels":
            from ..connectors.registry import build_adapter
            inst = ws.store.get_connector_instance(args.connector_id)
            if inst is None:
                raise SystemExit(f"connector {args.connector_id} not found")
            acc = ws.store.get_source_account(inst.account_id)
            secret = creds.get(inst.credential_ref) if inst.credential_ref else None
            adapter = build_adapter(inst, acc, secret)
            for ch in adapter.list_channels():
                kind = ("private" if ch.get("is_private")
                        else "im" if ch.get("is_im") else "public")
                print(f"{ch['id']:16}  #{ch.get('name') or '?':32}  "
                      f"{kind:8}  members={ch.get('num_members')}")
        else:
            raise SystemExit(f"unknown slack command: {args.slack_command}")
    elif cmd == "gmail":
        if args.gmail_command == "labels":
            from ..connectors.registry import build_adapter
            inst = ws.store.get_connector_instance(args.connector_id)
            if inst is None:
                raise SystemExit(f"connector {args.connector_id} not found")
            acc = ws.store.get_source_account(inst.account_id)
            secret = creds.get(inst.credential_ref) if inst.credential_ref else None
            adapter = build_adapter(inst, acc, secret)
            for lab in adapter.list_labels():
                print(f"{lab['id']:24}  {lab.get('name') or '?':32}  "
                      f"type={lab.get('type')}  "
                      f"messages={lab.get('messages_total')}")
        else:
            raise SystemExit(f"unknown gmail command: {args.gmail_command}")
    elif cmd == "outlook":
        if args.outlook_command == "folders":
            from ..connectors.registry import build_adapter
            inst = ws.store.get_connector_instance(args.connector_id)
            if inst is None:
                raise SystemExit(f"connector {args.connector_id} not found")
            acc = ws.store.get_source_account(inst.account_id)
            secret = creds.get(inst.credential_ref) if inst.credential_ref else None
            adapter = build_adapter(inst, acc, secret)
            for folder in adapter.list_folders():
                print(f"{folder['id']:36}  {folder.get('name') or '?':32}  "
                      f"items={folder.get('total_item_count')}")
        else:
            raise SystemExit(f"unknown outlook command: {args.outlook_command}")
    elif cmd == "calendar":
        if args.calendar_command == "calendars":
            from ..connectors.registry import build_adapter
            inst = ws.store.get_connector_instance(args.connector_id)
            if inst is None:
                raise SystemExit(f"connector {args.connector_id} not found")
            acc = ws.store.get_source_account(inst.account_id)
            secret = creds.get(inst.credential_ref) if inst.credential_ref else None
            adapter = build_adapter(inst, acc, secret)
            for cal in adapter.list_calendars():
                primary = " primary" if cal.get("primary") else ""
                print(f"{cal['id']:40}  {cal.get('summary') or '?':32}  "
                      f"role={cal.get('access_role')}{primary}")
        else:
            raise SystemExit(f"unknown calendar command: {args.calendar_command}")
    elif cmd == "fireflies":
        if args.fireflies_command == "meetings":
            from ..connectors.registry import build_adapter
            inst = ws.store.get_connector_instance(args.connector_id)
            if inst is None:
                raise SystemExit(f"connector {args.connector_id} not found")
            acc = ws.store.get_source_account(inst.account_id)
            secret = creds.get(inst.credential_ref) if inst.credential_ref else None
            adapter = build_adapter(inst, acc, secret)
            for m in adapter.list_meetings():
                print(f"{m.get('id') or '?':24}  {m.get('title') or '?':40}  "
                      f"{m.get('date') or ''}")
        else:
            raise SystemExit(
                f"unknown fireflies command: {args.fireflies_command}")
    elif cmd == "folder":
        if args.folder_command == "roots":
            from ..connectors.registry import build_adapter
            inst = ws.store.get_connector_instance(args.connector_id)
            if inst is None:
                raise SystemExit(f"connector {args.connector_id} not found")
            acc = ws.store.get_source_account(inst.account_id)
            secret = creds.get(inst.credential_ref) if inst.credential_ref else None
            adapter = build_adapter(inst, acc, secret)
            for root in adapter.list_roots():
                flag = "ok" if root.get("readable") else (
                    "missing" if not root.get("exists") else "unreadable"
                )
                print(f"{root.get('id') or '?':24}  {root.get('path') or '?':48}  "
                      f"{flag}")
        else:
            raise SystemExit(f"unknown folder command: {args.folder_command}")
    elif cmd == "backfill":
        if getattr(args, "run_partition", False):
            if not args.job_id:
                raise SystemExit("--run-partition requires --job-id")
            from ..connectors import run_backfill_partition
            out = run_backfill_partition(
                ws.store, creds, args.job_id,
                emit_percepts=not getattr(args, "no_percepts", False),
            )
            print(_json.dumps(out, indent=2, default=str))
            return
        if not args.connector_id:
            raise SystemExit("connector_id required")
        if getattr(args, "create", False):
            from ..connectors import create_backfill_job
            job = create_backfill_job(ws.store, creds, args.connector_id)
            print(f"job {job.id}  status={job.status.value}  "
                  f"partitions={(job.progress or {}).get('total_partitions')}")
            return
        if getattr(args, "jobs", False):
            for job in ws.store.list_backfill_jobs(args.connector_id):
                prog = job.progress or {}
                print(f"{job.id}  {job.status.value:10}  "
                      f"{prog.get('completed_partitions', 0)}/"
                      f"{prog.get('total_partitions', 0)} partitions")
            return
        if not args.preview:
            raise SystemExit(
                "use --preview to inspect scope, --create to open a "
                "BackfillJob, --jobs to list, or --run-partition --job-id ID "
                "to advance one month (previewing never ingests)")
        from ..connectors import backfill_preview
        preview = backfill_preview(ws.store, creds, args.connector_id,
                                   principal_id="principal_local_cli")
        print(_json.dumps(preview, indent=2, ensure_ascii=False))
    elif cmd == "pause":
        print(pause_connector(ws.store, args.connector_id).status.value)
    elif cmd == "resume":
        print(resume_connector(ws.store, args.connector_id).status.value)
    elif cmd == "revoke":
        print(revoke_connector(ws.store, creds, args.connector_id).status.value)
    elif cmd == "status":
        print(_json.dumps(connector_health(ws.store, args.connector_id), indent=2))
    elif cmd == "checkpoint":
        for c in ws.store.list_connector_checkpoints(args.connector_id):
            print(f"{c.stream:16}  v{c.version}  cursor={c.cursor}  batch={c.committed_batch_id}")
    elif cmd == "dead-letters":
        for d in ws.store.list_connector_dead_letters(args.connector_id):
            print(f"{d.id}  {d.failure_class.value:18}  {d.status.value:10}  "
                  f"attempts={d.attempts}  {d.external_type}:{d.external_id}  "
                  f"{d.last_error[:60]}")
    elif cmd == "replay":
        from ..connectors import retry_dead_letter
        dlq = retry_dead_letter(ws.store, creds, args.dead_letter_id)
        print(f"{dlq.id}  status={dlq.status.value}  attempts={dlq.attempts}"
              + (f"  error={dlq.last_error}" if dlq.last_error else ""))
    elif cmd == "deletion-events":
        for e in ws.store.list_connector_deletion_events(args.connector_id):
            print(f"{e.id}  {e.status.value:9}  {e.external_type}:{e.external_id}  "
                  f"prior={len(e.prior_record_ids)}  percepts={len(e.affected_percept_ids)}")
    elif cmd == "setup":
        from ..connectors import plan_connector_setup
        plan = plan_connector_setup(
            ws.store,
            connector_type=args.connector_type,
            source_owner=args.source_owner,
            vault_id=args.vault_id,
            org_key=args.org_key,
            display_name=args.name or "",
            configuration=_json.loads(args.config) if args.config else None,
            home=ws.cfg.home,
        )
        print(_json.dumps(plan, indent=2, ensure_ascii=False))
        if not plan.get("ok"):
            raise SystemExit(1)
    elif cmd == "due":
        from ..connectors import list_due_connectors
        print(_json.dumps(list_due_connectors(ws.store, ws.cfg.home),
                          indent=2, default=str))
    elif cmd == "sync-due":
        from ..connectors import run_sync_due
        rows = run_sync_due(
            ws.store, creds, ws.cfg.home,
            emit_percepts=not getattr(args, "no_percepts", False),
        )
        print(_json.dumps({"results": rows, "count": len(rows)}, indent=2))
    elif cmd == "contract":
        from ..connectors import contract_matrix
        print(_json.dumps(contract_matrix(), indent=2, default=str))
    elif cmd == "production-ready":
        from ..connectors import production_ready_adapters
        report = production_ready_adapters()
        print(_json.dumps(report, indent=2, default=str))
        if not report.get("ok"):
            raise SystemExit(1)
    elif cmd == "completion":
        from ..connectors import completion_matrix
        matrix = completion_matrix()
        print(_json.dumps(matrix, indent=2, default=str))
        if not matrix.get("ok"):
            raise SystemExit(1)
    else:
        raise SystemExit(f"unknown connector command: {cmd}")


def cmd_supersede(args) -> None:
    from ..memory.lifecycle import supersede

    ws = Workspace(args.home)
    result = supersede(ws.store, args.new_id, args.old_id)
    print(f"{result.subject_id} supersedes {result.object_id};"
          f" old memory deprecated (relation {result.relation_id})")


def cmd_contradict(args) -> None:
    from ..memory.lifecycle import contradict

    ws = Workspace(args.home)
    result = contradict(ws.store, args.id_a, args.id_b)
    print(f"{result.subject_id} contradicts {result.object_id};"
          f" both queued for review (relation {result.relation_id})")


def cmd_stats(args) -> None:
    from ..memory.metrics import compute_metrics

    ws = Workspace(args.home)
    _print(compute_metrics(ws.store))


def cmd_serve(args) -> None:
    from .api import main as serve_main

    serve_main(args.home, host=args.host, port=args.port)


def cmd_mcp(args) -> None:
    from .mcp_server import main as mcp_main

    mcp_main(args.home)


def cmd_backup(args) -> None:
    from pathlib import Path

    from ..sovereignty.backup import create_backup, restore_sqlite_backup, validate_backup

    ws = Workspace(args.home)
    cmd = args.backup_command
    if cmd == "create":
        dest = Path(args.dest)
        db_path = None
        if hasattr(ws.store, "path"):
            db_path = Path(ws.store.path)
        manifest = create_backup(ws.store, dest, copy_sqlite_db=db_path)
        _print(manifest.model_dump(mode="json"))
        return
    if cmd == "validate":
        _print(validate_backup(args.bundle))
        return
    if cmd == "restore":
        _print(restore_sqlite_backup(args.bundle, args.target_db))
        return
    raise SystemExit(f"unknown backup command: {cmd}")


def cmd_export(args) -> None:
    from ..judgment.profile import load_profile

    ws = Workspace(args.home)
    memories = ws.store.list_memories(limit=100000)
    _print({
        "memories": [
            {
                **m.model_dump(),
                "type": m.type.value, "sensitivity": m.sensitivity.value,
                "status": m.status.value,
                "evidence": [e.model_dump() for e in ws.store.get_evidence(m.id)],
            }
            for m in memories
        ],
        "entities": [e.model_dump() for e in ws.store.list_entities()],
        "judgment": load_profile(ws.cfg.judgment_path),
    })


def cmd_session_start(args) -> None:
    from ..cognition.sessions import start_session

    ws = Workspace(args.home)
    started = start_session(
        ws.store, ws.cfg, ws.embedder, args.query,
        client=args.client, cwd=args.cwd, domain=args.domain,
        project=args.project, task_profile=args.profile,
        max_tokens=args.max_tokens,
    )
    ses = started.session
    print(f"session {ses.id} started")
    print(f"  domain: {ses.domain} · profile: {ses.task_profile}"
          f" · project: {ses.project_id or '—'}"
          f" · observer: {started.observer_mode} {started.reading_confidences}")
    if started.needs_domain_confirmation:
        print("  ⚠ domain unclassified — no context supplied (default-deny)."
              " Re-run with --domain work|technical|personal_preferences|"
              "assistant_preferences")
    print(f"  supplied {len(ses.supplied_memory_ids)} memories"
          f" ({ses.pack_chars // 4} tokens approx)\n")
    print(started.pack.context_pack or "(empty pack)")


def cmd_session_observe(args) -> None:
    from ..cognition.sessions import observe_session

    ws = Workspace(args.home)
    artifact = {"kind": args.kind}
    if args.ref:
        artifact["ref"] = args.ref
    if args.note:
        artifact["note"] = args.note
    ses = observe_session(ws.store, args.session_id, artifact)
    print(f"session {ses.id}: {len(ses.artifacts)} artifact(s) recorded")


def cmd_session_complete(args) -> None:
    from ..cognition.sessions import complete_session

    ws = Workspace(args.home)
    # a summary typed at the CLI comes from the human: origin "user"
    ses = complete_session(ws.store, ws.cfg, ws.embedder, args.session_id,
                           summary=args.summary or "", abandoned=args.abandon,
                           summary_origin="user", user_confirmed=bool(args.summary))
    print(f"session {ses.id} {ses.status.value}"
          f" (consolidation: {ses.consolidation_status.value})")
    if ses.consolidation_error:
        print(f"  ⚠ consolidation failed: {ses.consolidation_error}")
        print("  retry with: twin session complete " + ses.id)
    if ses.created_memory_ids:
        print(f"  {len(ses.created_memory_ids)} candidate memories created"
              f" — review with: twin review")


def cmd_session_feedback(args) -> None:
    from ..cognition.sessions import record_feedback

    ws = Workspace(args.home)
    ses = record_feedback(ws.store, args.session_id, args.verdict,
                          memory_id=args.memory, note=args.note or "",
                          scope=args.scope)
    print(f"session {ses.id}: feedback '{args.verdict}' recorded")


def cmd_session_cleanup(args) -> None:
    from ..cognition.sessions import abandon_stale_sessions

    ws = Workspace(args.home)
    abandoned = abandon_stale_sessions(ws.store, args.max_idle_hours)
    if abandoned:
        print(f"abandoned {len(abandoned)} stale session(s): {', '.join(abandoned)}")
    else:
        print("no stale sessions")


def cmd_project(args) -> None:
    ws = Workspace(args.home)
    if args.project_command == "add":
        from ..cognition.sessions import ensure_project

        # idempotent: repos/aliases merge into an existing project
        project = ensure_project(ws.store, args.name,
                                 repos=args.repo or [], aliases=args.alias or [])
        if args.goal:
            project.goals = sorted(set(project.goals) | set(args.goal))
            ws.store.update_project(project)
        print(f"{project.id}: {project.name} (repos: {', '.join(project.repos) or '—'})")
    elif args.project_command == "link":
        from ..cognition.correlation.projects import link_project
        from ..cognition.sessions import ensure_project

        project = ensure_project(ws.store, args.name)
        link = link_project(
            ws.store,
            project_id=project.id,
            external_type=args.external_type,
            external_id=args.external_id,
            confirmed=not args.candidate,
            confidence=1.0 if not args.candidate else 0.7,
        )
        status = getattr(link.status, "value", link.status)
        print(
            f"{link.id}: {project.name} ← {link.external_type}:{link.external_id} "
            f"(status={status})"
        )
    elif args.project_command in ("reject", "historical", "confirm"):
        from ..cognition.correlation.projects import set_project_link_status
        from ..cognition.correlation.models import ProjectLinkStatus

        mapping = {
            "reject": ProjectLinkStatus.rejected,
            "historical": ProjectLinkStatus.historical,
            "confirm": ProjectLinkStatus.confirmed,
        }
        link = set_project_link_status(
            ws.store, args.link_id, mapping[args.project_command],
        )
        print(f"{link.id} status={link.status.value}")
    elif args.project_command == "explain":
        import json as _json
        from ..cognition.correlation.explain import explain_project_link
        print(_json.dumps(explain_project_link(ws.store, args.link_id),
                          indent=2, default=str))
    elif args.project_command == "links":
        for link in ws.store.list_project_links():
            status = getattr(link.status, "value", None) or (
                "confirmed" if link.confirmed else "candidate"
            )
            print(
                f"{link.id}  project={link.project_id}  "
                f"{link.external_type}:{link.external_id}  "
                f"conf={link.confidence:.2f} status={status}"
            )
    else:
        for p in ws.store.list_projects():
            sessions = len(ws.store.list_sessions(project_id=p.id))
            memories = len(ws.store.list_memories(project_id=p.id, limit=100000))
            print(f"{p.id}  {p.name} [{p.status}]"
                  f" — {memories} memories, {sessions} sessions,"
                  f" repos: {', '.join(p.repos) or '—'}")


def cmd_native(args) -> None:
    """Phase 8 — host-native observation (Claude Code hooks proof).

    Protocol:
    - stdout: JSON ``NativeEventResult`` (context_pack only for SessionStart /
      pack_request);
    - stderr: diagnostics;
    - ``--fail-open`` (hooks default): Twin failures exit 0 so the host is not blocked;
    - ``--strict`` / admin commands: non-zero exit on failure.
    """
    import sys
    from pathlib import Path

    from .native.claude_code import (
        MissingExternalSessionId,
        normalize_claude_code_hook,
        write_hooks_config,
    )
    from .native.events import HostEvent
    from .native.service import NativeHostService, should_emit_pack

    ws = Workspace(args.home)
    if args.native_command == "install":
        target = args.dir or str(ws.home / "native" / "claude-code")
        path = write_hooks_config(
            Path(target),
            twin_bin=args.twin_bin or "twin",
            home=str(ws.home),
        )
        print(f"wrote {path}")
        print("Merge the `hooks` object into Claude Code settings, then restart.")
        return

    if args.native_command == "bindings":
        host = args.host
        for b in ws.store.list_host_session_bindings(host_type=host, limit=args.limit):
            print(
                f"{b.id}  {b.host_type}:{b.external_session_id}"
                f"#occ={b.occurrence}  "
                f"ses={b.cognitive_session_id}  "
                f"domain={b.domain or '—'}  "
                f"{'ended' if b.ended_at else 'active'}"
            )
        return

    # event
    fail_open = bool(getattr(args, "fail_open", False)) and not getattr(args, "strict", False)
    raw = args.payload
    if args.stdin or raw in (None, "-", ""):
        raw = sys.stdin.read()
    host = (args.host or "claude-code").lower()
    try:
        if host == "claude-code":
            try:
                data = json.loads(raw) if isinstance(raw, str) and raw.strip().startswith("{") else {}
            except json.JSONDecodeError:
                data = {"text": raw}
            if isinstance(raw, str) and raw.strip() and not data:
                data = {"prompt": raw}
            if args.external_session and isinstance(data, dict):
                data = {**data, "session_id": args.external_session}
            event = normalize_claude_code_hook(
                data if data else raw,
                hook_name=args.hook,
                default_cwd=args.cwd,
            )
            if args.kind:
                event.kind = args.kind
        else:
            if not args.external_session:
                raise MissingExternalSessionId(
                    "external_session_id required — cwd/project must not identify conversations"
                )
            event = HostEvent(
                kind=args.kind or "user_message",
                host_type=host,
                external_session_id=args.external_session,
                text=raw if isinstance(raw, str) else "",
                cwd=args.cwd,
                project=args.project,
                domain=args.domain,
            )
        result = NativeHostService(ws.store, ws.cfg, ws.embedder).handle(event)
    except MissingExternalSessionId as exc:
        from .native.service import NativeEventResult

        result = NativeEventResult(ok=False, error=str(exc))
        event = None

    emit_pack = should_emit_pack(getattr(event, "kind", "") or "")
    payload = result.to_dict(include_pack=emit_pack)
    if not result.ok:
        print(
            f"twin native: {result.error}"
            + (f" error_id={result.error_id}" if result.error_id else ""),
            file=sys.stderr,
        )
    print(json.dumps(payload, ensure_ascii=False, default=str))
    if not result.ok and not fail_open:
        raise SystemExit(1)


def cmd_correlate(args) -> None:
    from ..cognition.correlation import run_correlation_pass

    ws = Workspace(args.home)
    report = run_correlation_pass(
        ws.store,
        connector_ids=args.connector or None,
        detect_conflicts=not args.no_conflicts,
    )
    print(
        f"scanned={report.records_scanned} "
        f"identities=+{report.identities_created}/~{report.identities_updated} "
        f"id_links=+{report.identity_links_created} "
        f"proj_links=+{report.project_links_created}/~{report.project_links_reused} "
        f"episodes=+{report.episodes_created}/~{report.episodes_updated}/"
        f"x{report.episodes_closed} "
        f"conflicts=+{report.conflicts_created}/~{report.conflicts_reused}/"
        f"x{report.conflicts_resolved}"
    )
    for eid in report.episode_ids:
        ep = ws.store.get_work_episode(eid)
        vault = ep.vault_id if ep else "?"
        print(f"  episode {eid} vault={vault}")


def cmd_episode(args) -> None:
    ws = Workspace(args.home)
    if args.episode_command == "show":
        ep = ws.store.get_work_episode(args.episode_id)
        if ep is None:
            raise SystemExit(f"episode {args.episode_id} not found")
        print(f"{ep.id}  {ep.title}  [{ep.status.value}] conf={ep.confidence:.2f}")
        print(f"  project={ep.project_id or '—'}  indep={ep.independence_group or '—'}")
        print(f"  participants={', '.join(ep.participant_actor_ids) or '—'}")
        for ref in ep.source_refs:
            print(
                f"  - {ref.get('external_type')}:{ref.get('external_id')} "
                f"({ref.get('occurred_at') or '?'})"
            )
        for link in ws.store.list_episode_links(ep.id):
            print(
                f"  link {link.kind.value} conf={link.confidence:.2f} "
                f"{link.external_type}:{link.external_id}"
            )
    elif args.episode_command == "explain":
        import json as _json
        from ..cognition.correlation.explain import explain_episode
        print(_json.dumps(explain_episode(ws.store, args.episode_id),
                          indent=2, default=str))
    else:
        for ep in ws.store.list_work_episodes(limit=args.limit):
            print(
                f"{ep.id}  [{ep.status.value}] conf={ep.confidence:.2f}  "
                f"{ep.title[:60]}  refs={len(ep.source_refs)}"
            )


def cmd_identity(args) -> None:
    ws = Workspace(args.home)
    if args.identity_command == "links":
        for link in ws.store.list_identity_links():
            print(
                f"{link.id}  {link.left_identity_id}↔{link.right_identity_id} "
                f"[{link.status.value}] conf={link.confidence:.2f} "
                f"signals={','.join(link.signals)}"
            )
    elif args.identity_command == "confirm":
        from ..cognition.correlation.identity import confirm_identity_link

        link = confirm_identity_link(
            ws.store, args.link_id, entity_id=args.entity,
        )
        print(f"confirmed {link.id} status={link.status.value}")
    elif args.identity_command == "unconfirm":
        from ..cognition.correlation.identity import unconfirm_identity_link
        link = unconfirm_identity_link(ws.store, args.link_id)
        print(f"unconfirmed {link.id} status={link.status.value}")
    elif args.identity_command == "reject":
        from ..cognition.correlation.identity import reject_identity_link
        link = reject_identity_link(ws.store, args.link_id)
        print(f"rejected {link.id} status={link.status.value}")
    elif args.identity_command == "why":
        import json as _json
        from ..cognition.correlation.explain import explain_identity_link
        print(_json.dumps(explain_identity_link(ws.store, args.link_id),
                          indent=2, default=str))
    else:
        for ident in ws.store.list_external_identities(provider=args.provider):
            print(
                f"{ident.id}  {ident.actor_id}  email={ident.email or '—'} "
                f"conf={ident.confidence:.2f} confirmed={ident.confirmed}"
            )


def cmd_watch(args) -> None:
    import time

    from ..cognition import extract_pending

    ws = Workspace(args.home)
    print(f"watching {', '.join(args.paths)} every {args.interval}s (Ctrl+C to stop)")
    try:
        while True:
            new_ids, _ = ws.ingest(args.paths)
            if new_ids:
                reports = extract_pending(ws.store, ws.cfg, ws.embedder)
                total = sum(len(r.inserted) for r in reports)
                print(f"[{__import__('twin.clock', fromlist=['now_iso']).now_iso()}]"
                      f" {len(new_ids)} new percepts → {total} candidate memories")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("stopped")


def cmd_doctor(args) -> None:
    from . import ux
    from .ops import doctor

    ws = Workspace(args.home)
    ux.print_rule("doctor")
    ux.print_kv([
        ("home", str(ws.cfg.home)),
        ("db", ws.cfg.resolved_db_url),
        ("llm", f"{ws.cfg.normalized_llm_provider} @ {ws.cfg.resolved_llm_base_url}"),
        ("model", ws.cfg.resolved_llm_model),
    ])
    ux.print_legend([
        ("✓", "ok — healthy"),
        ("!", "warn — usable but incomplete / optional missing"),
        ("✗", "fail — broken; fix before relying on this path"),
    ], title="status legend")
    with ux.spinner("Running checks…"):
        checks = doctor(ws.cfg)

    n_ok = n_warn = n_fail = 0
    worst = "ok"
    for c in checks:
        if c.status == "ok":
            n_ok += 1
            ux.print_ok(f"{c.name:24} {c.detail}")
        elif c.status == "warn":
            n_warn += 1
            ux.print_warn(f"{c.name:24} {c.detail}")
            if worst == "ok":
                worst = "warn"
        else:
            n_fail += 1
            ux.print_err(f"{c.name:24} {c.detail}")
            worst = "fail"

    verdict = {
        "ok": "all clear",
        "warn": "usable with warnings — review items above",
        "fail": "failures found — fix ✗ items before production use",
    }[worst]
    ux.print_panel(
        f"ok={n_ok}  warn={n_warn}  fail={n_fail}\n{verdict}",
        title="verdict",
    )
    if worst == "fail":
        ux.print_legend([
            ("→", "twin init              — recreate home defaults"),
            ("→", "twin setup ollama      — pull models / check server"),
            ("→", "twin setup mcp cursor  — wire MCP"),
        ], title="fix hints")
        raise SystemExit(1)


def cmd_setup(args) -> None:
    from . import ux
    from .ops import setup_mcp, setup_ollama, setup_postgres

    ws = Workspace(args.home)
    ux.print_rule(f"setup {args.target}")
    if args.target == "ollama":
        with ux.spinner("Talking to Ollama…"):
            lines = setup_ollama(ws.cfg)
    elif args.target == "postgres":
        with ux.spinner("Checking Postgres…"):
            lines = setup_postgres(ws.cfg)
    else:
        if not args.client:
            raise SystemExit("usage: twin setup mcp <claude-code|claude-desktop|cursor>")
        lines = setup_mcp(ws.cfg, args.client)
    for line in lines:
        ux.print_dim(line)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="twin", description="Personal Cognitive OS")
    parser.add_argument("--home", default=None, help="twin home dir (default ~/.twin or $TWIN_HOME)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="initialize home + guided Ollama setup")
    p.add_argument(
        "--skip-setup",
        action="store_true",
        help="only create home defaults (no interactive wizard)",
    )
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("ingest", help="run sensors over files or directories")
    p.add_argument("paths", nargs="+")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser(
        "extract",
        help="interpret pending percepts into memories",
    )
    p.add_argument(
        "--auto-approve", "-A",
        action="store_true",
        help="confirm newly extracted memories immediately (skip review queue)",
    )
    p.set_defaults(func=cmd_extract)

    pi = sub.add_parser("interpret", help="cognitive interpretation status (v0.7)")
    pis = pi.add_subparsers(dest="interpret_command", required=True)
    pistatus = pis.add_parser("status", help="counts by interpretation status")
    pistatus.set_defaults(func=cmd_interpret)
    pisd = pis.add_parser("deferred", help="percepts awaiting a cognitive interpreter")
    pisd.set_defaults(func=cmd_interpret)
    pisig = pis.add_parser("signals", help="heuristic detection hints (never memories)")
    pisig.set_defaults(func=cmd_interpret)

    p = sub.add_parser("review", help="interactive priority review queue")
    p.add_argument("--priority", choices=["high"], default=None)
    p.add_argument("--project", default=None)
    p.add_argument("--conflicts", action="store_true")
    p.add_argument("--analyze", action="store_true", help="run quality analyzer on candidates")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("review-batch", help="create or resume a review batch")
    rb = p.add_subparsers(dest="batch_command", required=True)
    pbc = rb.add_parser("create")
    pbc.add_argument("--name", default="batch")
    pbc.add_argument("--source", default=None)
    pbc.add_argument("--project", default=None)
    pbc.set_defaults(func=cmd_review_batch)
    pbr = rb.add_parser("resume")
    pbr.add_argument("batch_id")
    pbr.set_defaults(func=cmd_review_batch)

    p = sub.add_parser("memory", help="memory consolidation ops")
    ms = p.add_subparsers(dest="memory_command", required=True)
    pd = ms.add_parser("diff")
    pd.add_argument("id_a")
    pd.add_argument("id_b")
    pd.set_defaults(func=cmd_memory)
    pm = ms.add_parser("merge")
    pm.add_argument("ids", nargs="+")
    pm.set_defaults(func=cmd_memory)
    psp = ms.add_parser("split")
    psp.add_argument("memory_id")
    psp.add_argument("parts", nargs="+")
    psp.set_defaults(func=cmd_memory)
    ppv = ms.add_parser("provenance")
    ppv.add_argument("memory_id")
    ppv.set_defaults(func=cmd_memory)
    pa = ms.add_parser("archive")
    pa.add_argument("memory_id")
    pa.set_defaults(func=cmd_memory)
    ms.add_parser("unsupported").set_defaults(func=cmd_memory, memory_command="unsupported")
    pu = ms.add_parser("undo")
    pu.add_argument("operation_id")
    pu.set_defaults(func=cmd_memory)

    p = sub.add_parser("eval", help="run extraction/retrieval benchmarks")
    es = p.add_subparsers(dest="eval_command", required=True)
    es.add_parser("extraction").set_defaults(func=cmd_eval)
    es.add_parser("retrieval").set_defaults(func=cmd_eval)
    es.add_parser("golden", help="run golden cognitive work-loop scenario"
                  ).set_defaults(func=cmd_eval)
    es.add_parser(
        "v1-completion",
        help="fail-closed v1.0 cognitive OS completion matrix",
    ).set_defaults(func=cmd_eval)
    es.add_parser("compare").set_defaults(func=cmd_eval)

    p = sub.add_parser("source", help="show source calibration")
    p.add_argument("source", nargs="?", default="all")
    p.set_defaults(func=cmd_source)

    p = sub.add_parser("retention", help="apply retention policies")
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--apply", action="store_true")
    p.set_defaults(func=cmd_retention)

    p = sub.add_parser("delete-source", help="propagate deletion from a source system")
    p.add_argument("source_system")
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--apply", action="store_true")
    p.set_defaults(func=cmd_delete_source)

    p = sub.add_parser("undo", help="undo a recorded memory operation")
    p.add_argument("operation_id")
    p.set_defaults(func=cmd_undo)

    p = sub.add_parser("search", help="hybrid search")
    p.add_argument("query")
    p.add_argument("--domain", default="technical")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("pack", help="build a safe context pack")
    p.add_argument("query")
    p.add_argument("--domain", default="technical")
    p.add_argument("--max-tokens", type=int, default=1200)
    p.add_argument("--include-candidates", action="store_true",
                   help="also pack unreviewed candidate memories (off by default)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_pack)

    p = sub.add_parser("observe", help="memory observer suggestion")
    p.add_argument("text")
    p.add_argument("--domain", default=None)
    p.set_defaults(func=cmd_observe)

    p = sub.add_parser("workspace", help="parallel memory workspace (v0.8)")
    wss = p.add_subparsers(dest="workspace_command", required=True)
    wt = wss.add_parser("tick", help="one observation/recall tick")
    wt.add_argument("text")
    wt.add_argument("--domain", default=None)
    wt.add_argument("--session-id", default="")
    wt.add_argument("--cwd", default=None)
    wt.add_argument(
        "--interpret", action="store_true",
        help="also run parallel interpretation (requires --input-mode delta)",
    )
    wt.add_argument(
        "--input-mode", choices=["snapshot", "delta"], default="snapshot",
        help="snapshot=observe/recall only; delta=may interpret as session_delta",
    )
    wt.add_argument("--sequence", type=int, default=None,
                    help="monotonic session sequence for idempotent ticks")
    wt.add_argument("--idempotency-key", default=None,
                    help="explicit idempotency key for retries")
    wt.add_argument("--retry", action="store_true",
                    help="reclaim a prior failed (error) tick with the same identity")
    wt.set_defaults(func=cmd_workspace)

    p = sub.add_parser("consolidate", help="daily/weekly consolidation cycle (v0.8)")
    cs = p.add_subparsers(dest="consolidate_command", required=True)
    for kind, help_text in (
        ("daily", "daily quality + safe automation + temporal refresh"),
        ("weekly", "weekly cycle + optional judgment proposals"),
    ):
        pc = cs.add_parser(kind, help=help_text)
        pc.add_argument("--apply", action="store_true",
                        help="write changes (default is dry-run)")
        pc.add_argument("--limit", type=int, default=200,
                        help="max candidates to analyze")
        pc.add_argument("--retry", action="store_true",
                        help="reclaim a prior failed (error) apply run for this window")
        pc.set_defaults(func=cmd_consolidate)

    p = sub.add_parser("runtime", help="durable cognitive runtime (v1.0)")
    rs = p.add_subparsers(dest="runtime_command", required=True)
    rst = rs.add_parser("start", help="run scheduler + workers (twin-runtime)")
    rst.add_argument("--workers", type=int, default=2)
    rst.add_argument("--vault", default=None, help="isolate worker to one vault")
    rst.add_argument("--lease", type=int, default=60, help="lease seconds")
    rst.add_argument("--schedule-interval", type=float, default=30.0)
    rst.add_argument("--offline", action="store_true",
                     help="scheduler only; do not claim jobs")
    rst.set_defaults(func=cmd_runtime)
    rs.add_parser("status", help="queue depth + recent jobs").set_defaults(func=cmd_runtime)
    rs.add_parser("schedule", help="enqueue due temporal jobs once").set_defaults(
        func=cmd_runtime,
    )
    re = rs.add_parser("enqueue", help="enqueue a job")
    re.add_argument("kind", choices=[
        "interpret_percept", "workspace_tick", "attention_evaluate",
        "consolidate_daily", "consolidate_weekly", "reembed_memory",
        "integrity_check", "connector_reconcile",
    ])
    re.add_argument("--payload-json", default=None)
    re.add_argument("--idempotency-key", default="")
    re.add_argument("--vault", default="vault_general")
    re.add_argument("--priority", type=int, default=100)
    re.set_defaults(func=cmd_runtime)
    rj = rs.add_parser("job", help="show one job")
    rj.add_argument("job_id")
    rj.set_defaults(func=cmd_runtime)
    rr = rs.add_parser("retry", help="requeue failed/dead-letter job")
    rr.add_argument("job_id")
    rr.set_defaults(func=cmd_runtime)
    rc = rs.add_parser("cancel", help="cancel pending/failed job")
    rc.add_argument("job_id")
    rc.set_defaults(func=cmd_runtime)

    sub.add_parser("reindex", help="regenerate embeddings").set_defaults(func=cmd_reindex)

    p = sub.add_parser("promote", help="propose promoting a memory into judgment")
    p.add_argument("memory_id")
    p.set_defaults(func=cmd_promote)

    p = sub.add_parser("judgment", help="evolving judgment model")
    js = p.add_subparsers(dest="judgment_command", required=True)
    js.add_parser("list").set_defaults(func=cmd_judgment)
    pshow = js.add_parser("show"); pshow.add_argument("judgment_id"); pshow.set_defaults(func=cmd_judgment)
    phist = js.add_parser("history"); phist.add_argument("judgment_id"); phist.set_defaults(func=cmd_judgment)
    js.add_parser("versions").set_defaults(func=cmd_judgment)
    js.add_parser("import-preview").set_defaults(func=cmd_judgment)
    js.add_parser("import").set_defaults(func=cmd_judgment)
    js.add_parser("export").set_defaults(func=cmd_judgment)
    pprop = js.add_parser("proposals"); pprop.add_argument("--status"); pprop.set_defaults(func=cmd_judgment)
    ppr = js.add_parser("propose")
    ppr.add_argument("--from-memory"); ppr.add_argument("--domain", default="technical")
    ppr.set_defaults(func=cmd_judgment)
    ppv = js.add_parser("preview"); ppv.add_argument("proposal_id"); ppv.set_defaults(func=cmd_judgment)
    pap = js.add_parser("approve")
    pap.add_argument("proposal_id"); pap.add_argument("--token", required=True)
    pap.add_argument("--constitutional", action="store_true")
    pap.set_defaults(func=cmd_judgment)
    prej = js.add_parser("reject"); prej.add_argument("proposal_id"); prej.add_argument("--reason")
    prej.set_defaults(func=cmd_judgment)
    pdf = js.add_parser("defer"); pdf.add_argument("proposal_id"); pdf.set_defaults(func=cmd_judgment)
    psim = js.add_parser("simulate")
    psim.add_argument("query"); psim.add_argument("--domain", default="technical")
    psim.add_argument("--project"); psim.add_argument("--profile", default="architecture")
    psim.set_defaults(func=cmd_judgment)
    pex = js.add_parser("explain"); pex.add_argument("trace_id"); pex.set_defaults(func=cmd_judgment)
    pcf = js.add_parser("counterfactual")
    pcf.add_argument("query"); pcf.add_argument("judgment_id"); pcf.add_argument("--domain", default="technical")
    pcf.set_defaults(func=cmd_judgment)
    pco = js.add_parser("conflicts"); pco.add_argument("--status"); pco.add_argument("--refresh", action="store_true")
    pco.set_defaults(func=cmd_judgment)
    prc = js.add_parser("resolve-conflict")
    prc.add_argument("conflict_id"); prc.add_argument("--resolution")
    prc.set_defaults(func=cmd_judgment)

    p = sub.add_parser("privacy", help="persona-aware privacy & governance")
    ps = p.add_subparsers(dest="privacy_command", required=True)
    psim = ps.add_parser("simulate")
    psim.add_argument("--persona", default="individual")
    psim.add_argument("--purpose", default="memory_retrieval")
    psim.add_argument("--audience", default="self")
    psim.add_argument("--tool", default="local-cli")
    psim.add_argument("--memory", action="append", default=[])
    psim.set_defaults(func=cmd_privacy)
    pex = ps.add_parser("explain"); pex.add_argument("decision_id"); pex.set_defaults(func=cmd_privacy)
    ppol = ps.add_parser("bootstrap"); ppol.set_defaults(func=cmd_privacy)
    pgl = ps.add_parser("grants"); pgl.add_argument("--status", default="active"); pgl.set_defaults(func=cmd_privacy)
    pgc = ps.add_parser("grant-create")
    pgc.add_argument("--tool", required=True); pgc.add_argument("--purpose", required=True)
    pgc.add_argument("--persona", default="individual"); pgc.add_argument("--domain", action="append", default=[])
    pgc.add_argument("--ttl", type=int, default=900); pgc.add_argument("--max-uses", type=int, default=1)
    pgc.set_defaults(func=cmd_privacy)
    pgr = ps.add_parser("grant-revoke"); pgr.add_argument("grant_id"); pgr.set_defaults(func=cmd_privacy)
    pql = ps.add_parser("quarantine"); pql.add_argument("--status", default="quarantined"); pql.set_defaults(func=cmd_privacy)
    pqr = ps.add_parser("quarantine-release")
    pqr.add_argument("quarantine_id")
    pqr.add_argument("--actor", required=True)
    pqr.add_argument("--reason", required=True)
    pqr.add_argument("--mode", default="release_as_safe",
                     choices=["release_as_safe", "release_sanitized", "reject"])
    pqr.set_defaults(func=cmd_privacy)
    pdp = ps.add_parser("delete-preview"); pdp.add_argument("--domain"); pdp.add_argument("--source-account")
    pdp.set_defaults(func=cmd_privacy)
    pde = ps.add_parser("delete-execute")
    pde.add_argument("deletion_id"); pde.add_argument("--token", required=True)
    pde.set_defaults(func=cmd_privacy)

    p = sub.add_parser("connector", help="professional connectors (v0.6)")
    cs = p.add_subparsers(dest="connector_command", required=True)
    cs.add_parser("adapters", help="list registered adapter types").set_defaults(func=cmd_connector)
    cs.add_parser("list", help="list connector instances").set_defaults(func=cmd_connector)
    cadd = cs.add_parser("add", help="register an account + connector instance")
    cadd.add_argument("connector_type")
    cadd.add_argument("--source-owner", required=True,
                      choices=["personal", "employer", "client", "opensource", "shared", "unknown"])
    cadd.add_argument("--vault-id", default=None)
    cadd.add_argument("--org-key", default=None)
    cadd.add_argument("--persona", default="individual")
    cadd.add_argument("--domain", default="work")
    cadd.add_argument("--name", default=None)
    cadd.add_argument("--external-id", default=None)
    cadd.add_argument("--secret", default=None)
    cadd.add_argument("--config", default=None, help="JSON instance configuration")
    cadd.set_defaults(func=cmd_connector)
    ccfg = cs.add_parser("configure", help="rotate credential / set configuration")
    ccfg.add_argument("connector_id")
    ccfg.add_argument("--secret", default=None)
    ccfg.add_argument("--config", default=None, help="JSON instance configuration")
    ccfg.add_argument("--webhook-secret", default=None,
                      help="dedicated webhook HMAC secret (github/slack)")
    ccfg.set_defaults(func=cmd_connector)
    cgh = cs.add_parser("github", help="github-specific helpers")
    cghs = cgh.add_subparsers(dest="github_command", required=True)
    cghr = cghs.add_parser("repositories",
                           help="repositories the token can reach")
    cghr.add_argument("connector_id")
    cghr.set_defaults(func=cmd_connector)
    csl = cs.add_parser("slack", help="slack-specific helpers")
    csls = csl.add_subparsers(dest="slack_command", required=True)
    cslc = csls.add_parser("channels",
                           help="channels the token can see")
    cslc.add_argument("connector_id")
    cslc.set_defaults(func=cmd_connector)
    cgm = cs.add_parser("gmail", help="gmail-specific helpers")
    cgms = cgm.add_subparsers(dest="gmail_command", required=True)
    cgml = cgms.add_parser("labels", help="labels the token can see")
    cgml.add_argument("connector_id")
    cgml.set_defaults(func=cmd_connector)
    cout = cs.add_parser("outlook", help="outlook-specific helpers")
    couts = cout.add_subparsers(dest="outlook_command", required=True)
    coutf = couts.add_parser("folders", help="mail folders the token can see")
    coutf.add_argument("connector_id")
    coutf.set_defaults(func=cmd_connector)
    ccal = cs.add_parser("calendar", help="calendar-specific helpers")
    ccals = ccal.add_subparsers(dest="calendar_command", required=True)
    ccalc = ccals.add_parser("calendars", help="calendars the token can see")
    ccalc.add_argument("connector_id")
    ccalc.set_defaults(func=cmd_connector)
    cff = cs.add_parser("fireflies", help="fireflies-specific helpers")
    cffs = cff.add_subparsers(dest="fireflies_command", required=True)
    cffm = cffs.add_parser("meetings", help="recent transcripts the token can see")
    cffm.add_argument("connector_id")
    cffm.set_defaults(func=cmd_connector)
    cfol = cs.add_parser("folder", help="local folder connector helpers")
    cfols = cfol.add_subparsers(dest="folder_command", required=True)
    cfolr = cfols.add_parser("roots", help="configured watch roots and readability")
    cfolr.add_argument("connector_id")
    cfolr.set_defaults(func=cmd_connector)
    cbf = cs.add_parser("backfill",
                        help="preview / create / advance partitionable BackfillJob")
    cbf.add_argument("connector_id", nargs="?", default=None)
    cbf.add_argument("--preview", action="store_true")
    cbf.add_argument("--create", action="store_true",
                     help="create a year-month BackfillJob (no ingest)")
    cbf.add_argument("--jobs", action="store_true",
                     help="list BackfillJobs for the connector")
    cbf.add_argument("--run-partition", dest="run_partition",
                     action="store_true",
                     help="advance one partition; requires --job-id")
    cbf.add_argument("--job-id", dest="job_id", default=None)
    cbf.add_argument("--no-percepts", action="store_true")
    cbf.set_defaults(func=cmd_connector)
    for name in ("auth", "test"):
        cx = cs.add_parser(name, help="validate stored credentials")
        cx.add_argument("connector_id")
        cx.set_defaults(func=cmd_connector)
    csync = cs.add_parser("sync", help="run one sync pass")
    csync.add_argument("connector_id")
    csync.add_argument("--stream", default=None)
    csync.add_argument("--no-percepts", action="store_true")
    csync.set_defaults(func=cmd_connector)
    for name in ("pause", "resume", "revoke", "status", "checkpoint",
                 "dead-letters", "deletion-events"):
        cx = cs.add_parser(name)
        cx.add_argument("connector_id")
        cx.set_defaults(func=cmd_connector)
    creplay = cs.add_parser("replay", help="retry one dead letter from its raw item")
    creplay.add_argument("dead_letter_id")
    creplay.set_defaults(func=cmd_connector)
    csetup = cs.add_parser(
        "setup",
        help="guided setup plan (no ingest) — ownership → auth → scope → preview",
    )
    csetup.add_argument("connector_type")
    csetup.add_argument("--source-owner", required=True,
                        choices=["personal", "employer", "client",
                                 "opensource", "shared", "unknown"])
    csetup.add_argument("--vault-id", default=None)
    csetup.add_argument("--org-key", default=None)
    csetup.add_argument("--name", default=None)
    csetup.add_argument("--config", default=None, help="JSON instance configuration")
    csetup.set_defaults(func=cmd_connector)
    cs.add_parser("due", help="list connectors the local scheduler would run now"
                  ).set_defaults(func=cmd_connector)
    csyncdue = cs.add_parser("sync-due", help="run one scheduler pass over due connectors")
    csyncdue.add_argument("--no-percepts", action="store_true")
    csyncdue.set_defaults(func=cmd_connector)
    cs.add_parser("contract", help="print §88 adapter contract matrix"
                  ).set_defaults(func=cmd_connector)
    cs.add_parser(
        "production-ready",
        help="attest ≥2 real adapters closed for daily production use",
    ).set_defaults(func=cmd_connector)
    cs.add_parser(
        "completion",
        help="print connector completion criteria matrix (§93)",
    ).set_defaults(func=cmd_connector)

    p = sub.add_parser("supersede", help="mark a memory as superseding another")
    p.add_argument("new_id")
    p.add_argument("old_id")
    p.set_defaults(func=cmd_supersede)

    p = sub.add_parser("contradict", help="flag two memories as contradictory")
    p.add_argument("id_a")
    p.add_argument("id_b")
    p.set_defaults(func=cmd_contradict)

    sub.add_parser("stats", help="memory quality metrics").set_defaults(func=cmd_stats)

    p = sub.add_parser("serve", help="run local API + review UI")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("session", help="cognitive session lifecycle")
    session_sub = p.add_subparsers(dest="session_command", required=True)

    ps = session_sub.add_parser("start", help="open a session and get a task-aware pack")
    ps.add_argument("query")
    ps.add_argument("--client", default="cli")
    ps.add_argument("--cwd", default=None, help="repository/directory signal for project inference")
    ps.add_argument("--domain", default=None)
    ps.add_argument("--project", default=None)
    ps.add_argument("--profile", default=None,
                    help="coding | architecture | debugging | writing | planning | review | meeting_prep")
    ps.add_argument("--max-tokens", type=int, default=1200)
    ps.set_defaults(func=cmd_session_start)

    ps = session_sub.add_parser("observe", help="record an artifact produced during the session")
    ps.add_argument("session_id")
    ps.add_argument("--kind", default="note")
    ps.add_argument("--ref", default=None, help="file path, commit sha, PR url, ...")
    ps.add_argument("--note", default=None)
    ps.set_defaults(func=cmd_session_observe)

    ps = session_sub.add_parser("complete", help="close the session and extract what changed")
    ps.add_argument("session_id")
    ps.add_argument("--summary", default=None,
                    help="what was decided/changed during the work")
    ps.add_argument("--abandon", action="store_true")
    ps.set_defaults(func=cmd_session_complete)

    ps = session_sub.add_parser("feedback", help="record usefulness feedback")
    ps.add_argument("session_id")
    ps.add_argument("verdict", choices=["useful", "partially_useful", "irrelevant",
                                        "incorrect", "missing_context",
                                        "privacy_overblock", "privacy_underblock"])
    ps.add_argument("--memory", default=None,
                    help="a memory this session supplied or created")
    ps.add_argument("--note", default=None)
    ps.add_argument("--scope", default=None, choices=["session", "pack", "memory"])
    ps.set_defaults(func=cmd_session_feedback)

    ps = session_sub.add_parser("cleanup", help="abandon stale active sessions")
    ps.add_argument("--max-idle-hours", type=float, default=24.0)
    ps.set_defaults(func=cmd_session_cleanup)

    p = sub.add_parser("project", help="first-class projects")
    project_sub = p.add_subparsers(dest="project_command", required=True)
    pp = project_sub.add_parser("add", help="create or update a project")
    pp.add_argument("name")
    pp.add_argument("--repo", action="append")
    pp.add_argument("--alias", action="append")
    pp.add_argument("--goal", action="append")
    pp.set_defaults(func=cmd_project)
    pp = project_sub.add_parser("list")
    pp.set_defaults(func=cmd_project)
    pp = project_sub.add_parser("link", help="map external container → project")
    pp.add_argument("name", help="project name or id")
    pp.add_argument("external_type", help="github_repository | slack_channel | …")
    pp.add_argument("external_id")
    pp.add_argument("--candidate", action="store_true",
                    help="store as unconfirmed candidate link")
    pp.set_defaults(func=cmd_project)
    pp = project_sub.add_parser("links", help="list project links")
    pp.set_defaults(func=cmd_project)
    for name, help_ in (
        ("confirm", "mark project link confirmed"),
        ("reject", "reject a project link"),
        ("historical", "archive link as historical (closed project provenance)"),
    ):
        pp = project_sub.add_parser(name, help=help_)
        pp.add_argument("link_id")
        pp.set_defaults(func=cmd_project)
    pp = project_sub.add_parser("explain", help="why a project link exists")
    pp.add_argument("link_id")
    pp.set_defaults(func=cmd_project)

    p = sub.add_parser(
        "correlate",
        help="cross-source pass: identities, project maps, WorkEpisodes, conflicts",
    )
    p.add_argument("--connector", action="append",
                   help="limit to connector instance id (repeatable)")
    p.add_argument("--no-conflicts", action="store_true")
    p.set_defaults(func=cmd_correlate)

    p = sub.add_parser("episode", help="WorkEpisode inspection")
    ep_sub = p.add_subparsers(dest="episode_command", required=True)
    ep = ep_sub.add_parser("list")
    ep.add_argument("--limit", type=int, default=50)
    ep.set_defaults(func=cmd_episode)
    ep = ep_sub.add_parser("show")
    ep.add_argument("episode_id")
    ep.set_defaults(func=cmd_episode)
    ep = ep_sub.add_parser("explain", help="why this episode exists (anchors/links)")
    ep.add_argument("episode_id")
    ep.set_defaults(func=cmd_episode)

    p = sub.add_parser("identity", help="external identity resolution")
    id_sub = p.add_subparsers(dest="identity_command", required=True)
    ii = id_sub.add_parser("list")
    ii.add_argument("--provider", default=None)
    ii.set_defaults(func=cmd_identity)
    ii = id_sub.add_parser("links")
    ii.set_defaults(func=cmd_identity)
    ii = id_sub.add_parser("confirm")
    ii.add_argument("link_id")
    ii.add_argument("--entity", default=None, help="canonical entity id")
    ii.set_defaults(func=cmd_identity)
    ii = id_sub.add_parser("unconfirm", help="undo confirmation → candidate")
    ii.add_argument("link_id")
    ii.set_defaults(func=cmd_identity)
    ii = id_sub.add_parser("reject", help="reject an identity link")
    ii.add_argument("link_id")
    ii.set_defaults(func=cmd_identity)
    ii = id_sub.add_parser("why", help="explain an identity link")
    ii.add_argument("link_id")
    ii.set_defaults(func=cmd_identity)

    p = sub.add_parser("watch", help="continuous incremental ingestion")
    p.add_argument("paths", nargs="+")
    p.add_argument("--interval", type=int, default=30)
    p.set_defaults(func=cmd_watch)

    sub.add_parser("doctor", help="verify the installation").set_defaults(func=cmd_doctor)

    p = sub.add_parser("setup", help="bootstrap local infrastructure")
    p.add_argument("target", choices=["ollama", "postgres", "mcp"])
    p.add_argument("client", nargs="?", default=None)
    p.set_defaults(func=cmd_setup)

    sub.add_parser("mcp", help="run MCP server (stdio)").set_defaults(func=cmd_mcp)

    p = sub.add_parser(
        "native",
        help="host-native observation (Claude Code hooks — Phase 8)",
    )
    nat = p.add_subparsers(dest="native_command", required=True)
    ni = nat.add_parser("install", help="write Claude Code hooks snippet")
    ni.add_argument("--dir", default=None, help="output directory")
    ni.add_argument("--twin-bin", default="twin")
    ni.set_defaults(func=cmd_native)
    ni = nat.add_parser("bindings", help="list HostSessionBindings")
    ni.add_argument("--host", default=None)
    ni.add_argument("--limit", type=int, default=50)
    ni.set_defaults(func=cmd_native)
    ni = nat.add_parser("event", help="ingest a host event (JSON or --stdin)")
    ni.add_argument("payload", nargs="?", default=None)
    ni.add_argument("--stdin", action="store_true")
    ni.add_argument("--host", default="claude-code")
    ni.add_argument("--hook", default=None, help="Claude Code hook name")
    ni.add_argument("--kind", default=None, help="override HostEvent.kind")
    ni.add_argument("--external-session", default=None,
                    help="required conversation id (never inferred from cwd)")
    ni.add_argument("--cwd", default=None)
    ni.add_argument("--project", default=None)
    ni.add_argument("--domain", default=None)
    ni.add_argument(
        "--fail-open", action="store_true",
        help="exit 0 on Twin errors so host hooks are never blocked (hooks default)",
    )
    ni.add_argument(
        "--strict", action="store_true",
        help="non-zero exit on Twin errors (admin / CI)",
    )
    ni.set_defaults(func=cmd_native)

    p = sub.add_parser("backup", help="sovereignty backup create/validate/restore (v0.9.8)")
    bs = p.add_subparsers(dest="backup_command", required=True)
    bc = bs.add_parser("create", help="write NDJSON + optional sqlite copy")
    bc.add_argument("dest", help="destination directory")
    bc.set_defaults(func=cmd_backup)
    bv = bs.add_parser("validate", help="verify manifest checksums")
    bv.add_argument("bundle", help="backup bundle directory")
    bv.set_defaults(func=cmd_backup)
    br = bs.add_parser("restore", help="restore store.sqlite to isolated path")
    br.add_argument("bundle")
    br.add_argument("target_db")
    br.set_defaults(func=cmd_backup)

    sub.add_parser("export", help="export everything as JSON").set_defaults(func=cmd_export)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
