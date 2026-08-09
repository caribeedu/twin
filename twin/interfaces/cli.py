"""Twin CLI.

 twin init create ~/.twin + guided Ollama/model setup
 twin ingest <paths...> run sensors over docs/transcripts/meetings/slack exports
 twin extract [--auto-approve|-A] interpret pending percepts (+ optional auto-confirm)
 twin review interactive review (single-key a/r/s/q)
 twin search "query" [--domain d] hybrid search
 twin pack "task" [--domain d] build a safe context pack (confirmed only;
 --include-candidates to loosen)
 twin observe "current text" memory observer suggestion
 twin workspace tick "text" parallel memory tick (recall + optional interpret)
 twin consolidate daily|weekly scheduled consolidation cycle
 twin runtime start|status|enqueue|job|retry|cancel durable cognitive runtime
 (live processing panel on start; session_domain_resolve / session_complete)
 twin promote <memory_id> promote a memory into the judgment profile
 twin supersede <new_id> <old_id> new memory replaces the old one
 twin contradict <id_a> <id_b> flag two memories as contradictory
 twin stats memory + product quality metrics
 twin reindex regenerate embeddings with the current embedder
 twin session start "task" open a cognitive session (context pack + tracking)
 twin session observe <id> ... record artifacts produced during the work
 twin session complete <id> close the loop: work → percepts → candidates
 twin session feedback <id> <v> usefulness feedback (useful, irrelevant, ...)
 twin project add|list first-class projects (repos, aliases, goals)
 twin watch <paths...> continuous incremental ingestion
 twin doctor verify models, stores, configs, MCP clients
 twin setup ollama|postgres|mcp bootstrap local infrastructure
 twin serve [--port 8765] local API + review UI
 twin mcp MCP server over stdio
 twin native event|install|bindings host-native observation
 twin export dump memories/entities/judgment as JSON
"""

from __future__ import annotations

import argparse
import json

from ..workspace import Workspace


def _print(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _want_json(args) -> bool:
    return bool(getattr(args, "json", False))


def _emit(args, data, pretty) -> None:
    """Machine path when ``--json`` is set, else the human ``pretty`` callable.

    ``data`` is JSON-serialised (``_print``) for scripts; ``pretty`` renders the
    branded human view. Keeps every ported command's ``--json`` branch uniform.
    """
    if _want_json(args):
        _print(data)
        return
    pretty()


def _add_json_flag(parser) -> None:
    """Attach a uniform ``--json`` escape hatch for scripting/machine output."""
    parser.add_argument(
        "--json", action="store_true",
        help="emit machine-readable JSON instead of the human view",
    )


def _summary_kv(data: dict) -> list[tuple[str, str]]:
    """Flatten a result dict to KV rows: scalars verbatim, containers summarised."""
    rows: list[tuple[str, str]] = []
    for key, value in data.items():
        if isinstance(value, dict):
            rows.append((str(key), f"{{{len(value)} field(s)}}"))
        elif isinstance(value, list):
            rows.append((str(key), f"[{len(value)} item(s)]"))
        elif isinstance(value, bool):
            rows.append((str(key), "yes" if value else "no"))
        else:
            rows.append((str(key), str(value)))
    return rows


def _work_spinner(args, message: str):
    """Spinner while working, unless ``--json`` (keeps stdout pure JSON)."""
    from contextlib import nullcontext

    from . import ux

    if _want_json(args):
        return nullcontext()
    return ux.spinner(message)


def _add_json_flag_tree(parser) -> None:
    """Add ``--json`` to every leaf subparser under ``parser`` (recursively)."""
    subs = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    if not subs:
        _add_json_flag(parser)
        return
    for sub in subs:
        for child in sub.choices.values():
            _add_json_flag_tree(child)


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

    from . import ux
    from ..cognition.interpreter import MAX_INTERPRETATION_ATTEMPTS

    ws = Workspace(args.home)
    if args.interpret_command == "deferred":
        # Include backoff / terminal errors — status alone is easy to miss.
        stuck = [
            i for i in ws.store.list_interpretations(limit=10000)
            if i.status in ("deferred", "error")
        ]
        rows = [
            {
                "percept_id": st.percept_id,
                "status": f"{st.status}/{st.failure_class or '-'}",
                "attempts": st.attempts,
                "kind": "terminal" if st.terminal else "retryable",
                "next": st.next_attempt_at or "now",
                "detail": st.detail,
            }
            for st in stuck
        ]

        def pretty():
            ux.print_rule("interpret · deferred")
            if not rows:
                ux.print_ok("no deferred/error percepts")
                return
            ux.print_table(
                ["percept", "status", "attempts", "kind", "next", "detail"],
                [[r["percept_id"], r["status"], r["attempts"], r["kind"],
                  r["next"], (r["detail"] or "")[:50]] for r in rows],
            )
            ux.print_warn(f"{len(rows)} percept(s) awaiting retry")

        _emit(args, {"deferred": rows, "count": len(rows)}, pretty)
        return
    if args.interpret_command == "signals":
        signals = ws.store.list_detection_signals(limit=10000)
        rows = [{"percept_id": s.percept_id, "kind": s.kind, "span": s.span}
                for s in signals]

        def pretty():
            ux.print_rule("interpret · signals")
            if not rows:
                ux.print_warn("no detection signals (heuristic mode records hints, not memories)")
                return
            ux.print_table(
                ["percept", "kind", "span"],
                [[r["percept_id"], r["kind"], (r["span"] or "")[:70]] for r in rows],
            )
            ux.print_ok(f"{len(rows)} routing hint(s)")

        _emit(args, {"signals": rows, "count": len(rows)}, pretty)
        return
    # status
    counts = Counter(i.status for i in ws.store.list_interpretations(limit=10000))
    never = len([p for p in ws.store.percepts_pending_interpretation(
        max_attempts=MAX_INTERPRETATION_ATTEMPTS)
        if ws.store.get_interpretation(p.id) is None])
    statuses = ("interpreted", "empty", "deferred", "error",
                "heuristic_detection", "quarantined")
    signal_count = len(ws.store.list_detection_signals(limit=10000))
    data = {
        "never_interpreted": never,
        **{s: counts.get(s, 0) for s in statuses},
        "detection_signals": signal_count,
    }

    def pretty():
        ux.print_rule("interpret · status")
        ux.print_kv([
            ("never interpreted", str(never)),
            *[(s, str(counts.get(s, 0))) for s in statuses],
            ("detection_signals", f"{signal_count} (routing hints, not memories)"),
        ])
        pending = never + counts.get("deferred", 0) + counts.get("error", 0)
        if pending:
            ux.print_next([("→", "twin extract   — interpret pending percepts")])
        else:
            ux.print_ok("nothing pending interpretation")

    _emit(args, data, pretty)


def cmd_extract(args) -> None:
    from ..cognition import extract_pending
    from ..cognition.interpreter import MAX_INTERPRETATION_ATTEMPTS
    from ..cognize.gate import require_chat_llm
    from ..memory.models import MemoryStatus
    from . import ux
    import os

    ws = Workspace(args.home)
    gate = require_chat_llm(
        extractor=ws.cfg.extractor,
        chat_provider=ws.cfg.normalized_llm_provider,
        allow_echo_cognition=os.environ.get("TWIN_ALLOW_ECHO_COGNITION", "") == "1",
    )
    if gate.halted:
        ux.print_rule("extract")
        ux.print_warn(
            f"Cognize halted: {gate.halt_reason.value if gate.halt_reason else 'unknown'}"
            f" — {gate.detail}"
        )
        ux.print_dim("Sense may still ingest; no cognitive writes without a chat LLM.")
        if getattr(args, "json", False):
            _emit(args, {
                "ok": False,
                "halted": True,
                "halt_reason": gate.halt_reason.value if gate.halt_reason else None,
                "detail": gate.detail,
            }, None)
        return

    pending = ws.store.percepts_pending_interpretation(
        max_attempts=MAX_INTERPRETATION_ATTEMPTS,
    )
    ux.print_rule("extract")
    if not pending:
        ux.print_warn("nothing to interpret (all percepts already interpreted or deferred)")
        return

    auto = bool(getattr(args, "auto_approve", False))
    ux.print_dim(
        f"{len(pending)} percept(s) · model={ws.cfg.resolved_llm_model} · "
        f"provider={ws.cfg.normalized_llm_provider}"
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
        rows = [
            {
                "memory_id": r.memory_id,
                "priority": round(r.review_priority, 2),
                "action": r.suggested_action.value,
                "flags": list(r.quality_flags),
            }
            for r in reports
        ]

        def pretty():
            ux.print_rule("review · analyze")
            if not rows:
                ux.print_ok("no candidates to analyze")
                return
            ux.print_table(
                ["memory", "priority", "action", "flags"],
                [[r["memory_id"], f"{r['priority']:.2f}", r["action"],
                  ", ".join(r["flags"]) or "—"] for r in rows[:20]],
            )
            ux.print_ok(f"analyzed {len(rows)} candidate(s)")
            ux.print_next([("→", "twin review   — step through the queue interactively")])

        _emit(args, {"reports": rows, "count": len(rows)}, pretty)
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
    from . import ux
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
        data = {"id": batch.id, "name": batch.name, "total": batch.progress_total}

        def pretty():
            ux.print_rule("review-batch · create")
            ux.print_kv([
                ("batch", batch.id), ("name", batch.name),
                ("memories", str(batch.progress_total)),
            ])
            ux.print_ok("batch created")
            ux.print_next([("→", f"twin review-batch resume {batch.id}")])

        _emit(args, data, pretty)
    elif args.batch_command == "resume":
        batch = get_batch(ws.store, args.batch_id)
        if batch is None:
            raise SystemExit(f"batch {args.batch_id} not found")
        upcoming = []
        for mid in batch.memory_ids[batch.progress_reviewed:batch.progress_reviewed + 5]:
            m = ws.store.get_memory(mid)
            if m:
                upcoming.append({"id": m.id, "title": m.title})
        data = {
            "id": batch.id, "reviewed": batch.progress_reviewed,
            "total": batch.progress_total, "upcoming": upcoming,
        }

        def pretty():
            ux.print_rule("review-batch · resume")
            ux.print_kv([
                ("batch", batch.id),
                ("progress", f"{batch.progress_reviewed}/{batch.progress_total}"),
            ])
            if upcoming:
                ux.print_table(
                    ["memory", "title"],
                    [[u["id"], u["title"]] for u in upcoming],
                )
            ux.print_next([("→", "twin review   — review candidates interactively")])

        _emit(args, data, pretty)


def cmd_memory(args) -> None:
    from . import ux
    from ..memory.lifecycle import archive_memory, merge_memories, split_memory, undo_operation
    from ..memory.provenance import memory_provenance

    ws = Workspace(args.home)
    if args.memory_command == "diff":
        a, b = ws.store.get_memory(args.id_a), ws.store.get_memory(args.id_b)
        if not a or not b:
            raise SystemExit("memory not found")

        def pretty():
            ux.print_rule("memory diff")
            ux.print_panel(f"{a.title}\n\n{a.summary}", title=f"A · {a.id}")
            ux.print_panel(f"{b.title}\n\n{b.summary}", title=f"B · {b.id}")

        _emit(args, {
            "a": {"id": a.id, "title": a.title, "summary": a.summary},
            "b": {"id": b.id, "title": b.title, "summary": b.summary},
        }, pretty)
    elif args.memory_command == "merge":
        result = merge_memories(ws.store, args.ids, embedder=ws.embedder)
        merged = result.extras.get("merged_id")

        def pretty():
            ux.print_rule("memory merge")
            ux.print_ok(f"merged {len(args.ids)} → {merged}")
            ux.print_dim(f"operation {result.operation_id} (undo with: twin undo {result.operation_id})")

        _emit(args, {"merged_id": merged, "operation_id": result.operation_id}, pretty)
    elif args.memory_command == "split":
        parts = [{"title": p, "summary": p} for p in args.parts]
        result = split_memory(ws.store, args.memory_id, parts, embedder=ws.embedder)
        children = result.extras.get("children")

        def pretty():
            ux.print_rule("memory split")
            ux.print_ok(f"split {args.memory_id} → {children}")
            ux.print_dim(f"operation {result.operation_id} (undo with: twin undo {result.operation_id})")

        _emit(args, {"children": children, "operation_id": result.operation_id}, pretty)
    elif args.memory_command == "provenance":
        prov = memory_provenance(ws.store, args.memory_id)

        def pretty():
            ux.print_rule(f"provenance · {args.memory_id}")
            ux.print_panel(json.dumps(prov, indent=2, default=str), title="lineage")

        _emit(args, prov, pretty)
    elif args.memory_command == "archive":
        result = archive_memory(ws.store, args.memory_id)

        def pretty():
            ux.print_rule("memory archive")
            ux.print_ok(f"archived {args.memory_id}")
            ux.print_dim(f"operation {result.operation_id} (undo with: twin undo {result.operation_id})")

        _emit(args, {"archived": args.memory_id, "operation_id": result.operation_id}, pretty)
    elif args.memory_command == "unsupported":
        rows = [{"id": m.id, "title": m.title}
                for m in ws.store.list_memories(status="unsupported", limit=200)]

        def pretty():
            ux.print_rule("memory · unsupported")
            if not rows:
                ux.print_ok("no unsupported memories")
                return
            ux.print_table(["memory", "title"], [[r["id"], r["title"]] for r in rows])

        _emit(args, {"unsupported": rows, "count": len(rows)}, pretty)
    elif args.memory_command == "undo":
        out = undo_operation(ws.store, args.operation_id)

        def pretty():
            ux.print_rule("memory undo")
            ux.print_ok(f"reverted operation {args.operation_id}")
            ux.print_panel(json.dumps(out, indent=2, default=str), title="result")

        _emit(args, out, pretty)


def cmd_eval(args) -> None:
    from . import ux
    from ..evals import compare_runs, default_eval_root, run_extraction_eval, run_retrieval_eval

    ws = Workspace(args.home)
    root = default_eval_root()
    if args.eval_command == "extraction":
        with _work_spinner(args, "Running extraction eval…"):
            run = run_extraction_eval(ws.store, ws.cfg, ws.embedder, root / "extraction")
        data = {"id": run.id, "summary": run.summary}

        def pretty():
            ux.print_rule("eval · extraction")
            ux.print_kv([("run", run.id)])
            ux.print_panel(json.dumps(run.summary, indent=2, default=str), title="summary")

        _emit(args, data, pretty)
    elif args.eval_command == "retrieval":
        with _work_spinner(args, "Running retrieval eval…"):
            run = run_retrieval_eval(ws.store, ws.embedder, root / "retrieval", firewall=ws.firewall)
        data = {"id": run.id, "summary": run.summary}

        def pretty():
            ux.print_rule("eval · retrieval")
            ux.print_kv([("run", run.id)])
            ux.print_panel(json.dumps(run.summary, indent=2, default=str), title="summary")

        _emit(args, data, pretty)
    elif args.eval_command == "golden":
        from ..evals.golden import run_golden_work_loop
        with _work_spinner(args, "Running golden work-loop…"):
            report = run_golden_work_loop(ws.store, ws.cfg, ws.embedder)

        def pretty():
            ux.print_rule("eval · golden")
            ux.print_kv(_summary_kv(report))
            if report.get("ok"):
                ux.print_ok("golden scenario passed")
            else:
                ux.print_err("golden scenario failed — inspect with --json")

        _emit(args, report, pretty)
        if not report.get("ok"):
            raise SystemExit(1)
    elif args.eval_command == "compare":
        msg = "compare requires two prior run payloads; use API /api/evals for now"

        def pretty():
            ux.print_rule("eval · compare")
            ux.print_warn(msg)

        _emit(args, {"error": msg}, pretty)


def cmd_source(args) -> None:
    from . import ux
    from ..memory.calibration import load_calibration, source_report

    ws = Workspace(args.home)
    cal = load_calibration(ws.cfg.calibration_path)
    report = source_report(cal, args.source if args.source != "all" else None)

    def pretty():
        ux.print_rule("source calibration")
        ux.print_panel(json.dumps(report, indent=2, default=str),
                       title=args.source)

    _emit(args, report, pretty)


def cmd_retention(args) -> None:
    from . import ux
    from ..memory.retention import apply_retention_policies

    ws = Workspace(args.home)
    dry = not getattr(args, "apply", False)
    result = apply_retention_policies(ws.store, dry_run=dry)

    def pretty():
        ux.print_rule("retention")
        ux.print_kv([("mode", "dry-run" if dry else "apply")])
        ux.print_panel(json.dumps(result, indent=2, default=str), title="policies")
        if dry:
            ux.print_warn("dry-run — re-run with --apply to enforce")
        else:
            ux.print_ok("retention policies applied")

    _emit(args, result, pretty)


def cmd_delete_source(args) -> None:
    from . import ux
    from ..memory.retention import delete_by_source_system

    ws = Workspace(args.home)
    dry = not getattr(args, "apply", False)
    result = delete_by_source_system(ws.store, args.source_system, dry_run=dry)

    def pretty():
        ux.print_rule(f"delete-source · {args.source_system}")
        ux.print_kv([("mode", "dry-run" if dry else "apply")])
        ux.print_panel(json.dumps(result, indent=2, default=str), title="deletion")
        if dry:
            ux.print_warn("dry-run — re-run with --apply to delete")
        else:
            ux.print_ok("source deletion propagated")

    _emit(args, result, pretty)


def cmd_undo(args) -> None:
    from . import ux
    from ..memory.lifecycle import undo_operation

    ws = Workspace(args.home)
    out = undo_operation(ws.store, args.operation_id)

    def pretty():
        ux.print_rule("undo")
        ux.print_ok(f"reverted operation {args.operation_id}")
        ux.print_panel(json.dumps(out, indent=2, default=str), title="result")

    _emit(args, out, pretty)


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
    from . import ux
    from ..cognition.observer import observe

    ws = Workspace(args.home)
    ux_domain = args.domain or "(inferred)"
    with _work_spinner(args, "Observing current text…"):
        s = observe(ws.store, ws.cfg, ws.embedder, args.text, args.domain)
    data = {
        "inferred_domain": s.inferred_domain,
        "suggested_context": s.suggested_context,
        "blocked_context": s.blocked_context,
    }

    def pretty():
        ux.print_rule("observe")
        ux.print_kv([
            ("requested domain", ux_domain),
            ("inferred domain", s.inferred_domain or "—"),
        ])
        if s.suggested_context:
            ux.print_panel(s.suggested_context, title="suggested context")
        else:
            ux.print_warn("no context suggested (nothing passed retrieval / firewall)")
        if s.blocked_context:
            ux.print_warn("some context withheld by firewall")

    _emit(args, data, pretty)


def cmd_workspace(args) -> None:
    from . import ux
    from ..cognition.workspace import workspace_tick

    ws = Workspace(args.home)
    if args.workspace_command != "tick":
        raise SystemExit(f"unknown workspace command: {args.workspace_command}")
    with _work_spinner(args, "Running workspace tick…"):
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
    data = result.to_dict()

    def pretty():
        ux.print_rule("workspace · tick")
        ux.print_kv(_summary_kv(data))
        ux.print_ok("tick complete — full payload with --json")

    _emit(args, data, pretty)


def cmd_consolidate(args) -> None:
    from . import ux
    from ..cognition.consolidation_cycle import run_consolidation_cycle

    ws = Workspace(args.home)
    kind = args.consolidate_command
    dry = not getattr(args, "apply", False)
    with _work_spinner(args, f"Running {kind} consolidation…"):
        result = run_consolidation_cycle(
            ws.store, ws.cfg, ws.embedder,
            kind=kind,
            dry_run=dry,
            analyze_limit=int(getattr(args, "limit", 200) or 200),
            retry=bool(getattr(args, "retry", False)),
        )
    data = result.to_dict()

    def pretty():
        ux.print_rule(f"consolidate · {kind}")
        ux.print_kv([("mode", "dry-run" if dry else "apply"), *_summary_kv(data)])
        if dry:
            ux.print_warn("dry-run — re-run with --apply to write changes")
        else:
            ux.print_ok("consolidation applied")

    _emit(args, data, pretty)


def cmd_runtime(args) -> None:
    from . import ux
    from ..runtime.models import JobKind
    from ..runtime.queue import RuntimeQueue
    from ..runtime.scheduler import RuntimeScheduler
    from ..runtime.service import TwinRuntime

    ws = Workspace(args.home)
    cmd = args.runtime_command
    q = RuntimeQueue(ws.store)

    if cmd == "start":
        # long-running foreground service — not a JSON dump
        rt = TwinRuntime(
            ws.store, ws.cfg, ws.embedder,
            workers=int(getattr(args, "workers", 2) or 2),
            vault_id=getattr(args, "vault", None) or None,
            lease_seconds=int(getattr(args, "lease", 60) or 60),
            schedule_interval=float(getattr(args, "schedule_interval", 30) or 30),
            offline=bool(getattr(args, "offline", False)),
        )
        want_live = (
            not _want_json(args)
            and not bool(getattr(args, "no_live", False))
        )
        if not _want_json(args) and not want_live:
            ux.print_rule("runtime · start")
            ux.print_ok("runtime started — Ctrl+C to stop")
        elif not _want_json(args):
            ux.print_rule("runtime · start")
            ux.print_dim("live panel — Ctrl+C to stop  (--no-live for logs only)")
        ux.run_runtime_with_live(rt, live=want_live)
        return

    if cmd == "status":
        limit = int(getattr(args, "limit", 20) or 20)
        recent = [j.model_dump(mode="json") for j in ws.store.list_runtime_jobs(limit=limit)]
        failed = [
            j.model_dump(mode="json")
            for j in ws.store.list_runtime_jobs(status="failed", limit=limit)
        ]
        dlq = [d.model_dump(mode="json") for d in ws.store.list_runtime_dead_letters(limit=limit)]

        def _clip(s, n=60):
            s = str(s or "")
            return s if len(s) <= n else s[: n - 1] + "…"

        data = {
            "queue": ws.store.runtime_queue_depth(),
            "dead_letters": len(dlq),
            "failed": failed,
            "dead_letter_items": dlq,
            "recent": recent,
        }

        def pretty():
            ux.print_rule("runtime · status")
            ux.print_kv([
                ("queue depth", str(data["queue"])),
                ("failed jobs", str(len(failed))),
                ("dead letters", str(len(dlq))),
                ("recent jobs", str(len(recent))),
            ])
            if failed:
                ux.print_warn(f"{len(failed)} failed job(s) — retry with `twin runtime retry <job_id>`")
                ux.print_table(
                    ["job", "kind", "attempts", "stage", "error"],
                    [[
                        j.get("id"), j.get("kind"),
                        f"{j.get('attempts')}/{j.get('max_attempts')}",
                        _clip(j.get("stage"), 24), _clip(j.get("error")),
                    ] for j in failed],
                    title="failed",
                )
            if dlq:
                ux.print_warn(f"{len(dlq)} dead-letter job(s) — inspect with `twin runtime job <job_id>`")
                ux.print_table(
                    ["dlq", "job", "kind", "attempts", "error_class", "error"],
                    [[
                        d.get("id"), d.get("job_id"), d.get("kind"),
                        d.get("attempts"), _clip(d.get("error_class"), 20),
                        _clip(d.get("error")),
                    ] for d in dlq],
                    title="dead letters",
                )
            if recent:
                ux.print_table(
                    ["job", "kind", "status"],
                    [[j.get("id"), j.get("kind"), j.get("status")] for j in recent],
                    title="recent",
                )

        _emit(args, data, pretty)
        return

    if cmd == "schedule":
        ids = RuntimeScheduler(
            q, vault_id=getattr(args, "vault", None) or "vault_general",
        ).tick()

        def pretty():
            ux.print_rule("runtime · schedule")
            ux.print_ok(f"enqueued {len(ids)} due job(s)")

        _emit(args, {"enqueued": ids}, pretty)
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
        data = job.model_dump(mode="json")

        def pretty():
            ux.print_rule("runtime · enqueue")
            ux.print_kv([("job", data.get("id")), ("kind", data.get("kind")),
                         ("status", data.get("status"))])
            ux.print_ok("job enqueued")

        _emit(args, data, pretty)
        return

    if cmd == "job":
        job = ws.store.get_runtime_job(args.job_id)
        if job is None:
            raise SystemExit(f"job {args.job_id} not found")
        data = job.model_dump(mode="json")

        def pretty():
            ux.print_rule(f"runtime job · {args.job_id}")
            ux.print_panel(json.dumps(data, indent=2, default=str), title="job")

        _emit(args, data, pretty)
        return

    if cmd == "retry":
        job = q.retry(args.job_id)
        if job is None:
            raise SystemExit(f"job {args.job_id} not found")
        data = job.model_dump(mode="json")

        def pretty():
            ux.print_rule("runtime · retry")
            ux.print_ok(f"requeued {args.job_id} → {data.get('status')}")

        _emit(args, data, pretty)
        return

    if cmd == "cancel":
        ok = q.cancel(args.job_id)

        def pretty():
            ux.print_rule("runtime · cancel")
            if ok:
                ux.print_ok(f"cancelled {args.job_id}")
            else:
                ux.print_warn(f"{args.job_id} not cancellable")

        _emit(args, {"id": args.job_id, "cancelled": ok}, pretty)
        return

    raise SystemExit(f"unknown runtime command: {cmd}")


def cmd_reindex(args) -> None:
    from . import ux

    ws = Workspace(args.home)
    with _work_spinner(args, f"Re-embedding with {ws.embedder.name}…"):
        count = ws.reindex()

    def pretty():
        ux.print_rule("reindex")
        ux.print_ok(f"re-embedded {count} memory(ies) with {ws.embedder.name}")

    _emit(args, {"reembedded": count, "embedder": ws.embedder.name}, pretty)


def cmd_promote(args) -> None:
    from . import ux
    from ..judgment.profile import promote_memory

    ws = Workspace(args.home)
    mem = ws.store.get_memory(args.memory_id)
    if mem is None:
        raise SystemExit(f"memory {args.memory_id} not found")
    section = promote_memory(ws.cfg.judgment_path, mem, store=ws.store)
    ws.store.update_memory(mem.id, payload={**mem.payload, "promoted_to_judgment": True})

    def pretty():
        ux.print_rule("promote")
        ux.print_ok(f"promoted {mem.id} → {section}")
        ux.print_dim("pending human approval if a proposal was created")

    _emit(args, {"memory_id": mem.id, "section": section}, pretty)


def _render_judgment_preview(preview: dict, proposal_id: str) -> None:
    """Human-readable judgment-proposal preview (replaces the raw JSON dump).

    Surfaces the proposed judgment as a headline statement + calibrated
    strength/confidence bars, its scope/exceptions, the evidence balance, and
    the exact approve/reject/defer commands (with the preview token wired in).
    """
    from . import ux

    item = preview.get("final_item") or {}
    proposal = preview.get("proposal") or {}
    action = str(proposal.get("action") or "create")
    kind = str(item.get("kind") or "?")
    stability = str(item.get("stability") or "evolving")
    durable = bool(preview.get("durable"))

    ux.print_rule(f"judgment preview · {proposal_id}")

    badges = f"[bold magenta]{action}[/] · [bold]{kind}[/]"
    if durable:
        badges += "  ·  [yellow]DURABLE — needs constitutional confirm[/]"
    ux.print_dim(badges)
    ux.print_panel(item.get("statement") or "(no statement)", title="statement")
    if item.get("description"):
        ux.print_dim(item["description"])

    def _f(v) -> float:
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    meta = [
        ("kind", kind),
        ("domain", str(item.get("domain") or "—")),
        ("persona", str(item.get("persona") or "—")),
        ("stability", stability),
        ("strength", ux.score_bar(_f(item.get("strength")))),
        ("confidence", ux.score_bar(_f(item.get("confidence")))),
    ]
    if item.get("lean") is not None:
        lean = _f(item.get("lean"))
        side = "→ B" if lean > 0 else ("A ←" if lean < 0 else "balanced")
        meta.append(("lean", f"{lean:+.2f} ({side})"))
    if item.get("valid_until"):
        meta.append(("valid_until", str(item.get("valid_until"))))
    ux.print_kv(meta)

    scope = item.get("scope") or {}
    scope_rows = [
        (k, ", ".join(str(x) for x in v))
        for k, v in scope.items() if v
    ]
    if item.get("tradeoff"):
        scope_rows.append(("tradeoff", str(item["tradeoff"])))
    if scope_rows:
        ux.print_rule("context & scope")
        ux.print_kv(scope_rows)

    exceptions = item.get("exceptions") or []
    if exceptions:
        ux.print_rule("exceptions")
        ux.print_table(
            ["condition", "effect", "value", "reason"],
            [[
                e.get("condition") or e.get("id") or "—",
                str(e.get("effect") or ""),
                f"{_f(e.get('value')):.2f}",
                (e.get("reason") or "")[:48],
            ] for e in exceptions],
        )

    ux.print_rule("evidence")
    signed = preview.get("signed_payload") or {}
    metadata = proposal.get("metadata") or {}
    mem_count = (
        signed.get("memory_count")
        if signed.get("memory_count") is not None
        else len(proposal.get("supporting_memory_ids") or [])
    )
    independent = (
        signed.get("independent_sources")
        if signed.get("independent_sources") is not None
        else metadata.get("independent_sources")
    )
    # support_count now *is* the independent-source count; keep both visible so
    # "2 memories · 1 independent source" reads honestly.
    support = proposal.get("support_count")
    if support is None:
        support = independent if independent is not None else mem_count
    contra = proposal.get("contradiction_count") or len(
        proposal.get("contradicting_memory_ids") or []
    )
    if independent is not None:
        support_line = f"{independent} independent source(s) · {mem_count} memories"
    else:
        support_line = str(support)
    ev = [
        ("supporting", support_line),
        ("contradicting", str(contra)),
        ("proposal conf", f"{_f(proposal.get('confidence')):.2f}"),
    ]
    prov = item.get("provenance") or {}
    if prov.get("source"):
        ev.append(("source", str(prov.get("source"))))
    if prov.get("twin_influenced"):
        ev.append(("twin_influenced", "yes (discounted)"))
    if metadata.get("detector"):
        ev.append(("detector", str(metadata.get("detector"))))
    ux.print_kv(ev)
    if independent is not None and independent <= 1 and mem_count > 1:
        ux.print_warn(
            "all supporting memories trace to a single source — confidence is "
            "discounted; corroboration from another sense would strengthen it"
        )
    # Prefer titled rows over opaque ids; show which independent source each came from.
    supporting = signed.get("supporting") or []
    if supporting:
        ux.print_table(
            ["memory", "title", "sources"],
            [[
                str(s.get("id") or "—"),
                (str(s.get("title") or "")[:56]),
                ", ".join(s.get("independent_sources") or [])[:40] or "—",
            ] for s in supporting[:8]],
        )
    else:
        mem_ids = list(prov.get("memory_ids") or proposal.get("supporting_memory_ids") or [])
        if mem_ids:
            ux.print_dim("from memories: " + ", ".join(mem_ids[:8])
                         + (" …" if len(mem_ids) > 8 else ""))
    if proposal.get("reason"):
        ux.print_panel(str(proposal["reason"]), title="why this proposal")

    token = preview.get("preview_token") or ""
    approve = f"twin judgment approve {proposal_id} --token {token}"
    if durable or stability == "constitutional":
        approve += " --constitutional"
    ux.print_next([
        ("→", approve),
        ("→", f'twin judgment reject {proposal_id} --reason "…"'),
        ("→", f"twin judgment defer {proposal_id}"),
    ])


def cmd_judgment(args) -> None:
    from . import ux
    from ..judgment.conflicts import detect_behavior_conflicts, detect_judgment_conflicts, resolve_conflict
    from ..judgment.proposals import (
        approve_proposal, defer_proposal, preview_proposal, propose_from_episode,
        propose_from_memory, propose_from_pattern, reject_proposal,
    )
    from ..judgment.simulate import counterfactual, simulate
    from ..judgment.yaml_io import apply_yaml_import, export_judgment_yaml, preview_yaml_import
    from ..judgment.versions import active_items

    ws = Workspace(args.home)
    cmd = args.judgment_command
    if cmd == "list":
        items = active_items(ws.store)
        rows = [{"id": i.id, "kind": i.kind.value, "statement": i.statement} for i in items]

        def pretty():
            ux.print_rule("judgment · items")
            if not rows:
                ux.print_warn("no active judgment items")
                return
            ux.print_table(
                ["id", "kind", "statement"],
                [[r["id"], r["kind"], (r["statement"] or "")[:80]] for r in rows],
            )

        _emit(args, {"items": rows, "count": len(rows)}, pretty)
    elif cmd == "show":
        item = ws.store.get_judgment_item(args.judgment_id)
        if item is None:
            raise SystemExit("not found")

        def pretty():
            ux.print_rule(f"judgment · {item.id}")
            ux.print_panel(item.model_dump_json(indent=2), title=item.kind.value)

        _emit(args, item.model_dump(mode="json"), pretty)
    elif cmd == "history":
        item = ws.store.get_judgment_item(args.judgment_id)
        if item is None:
            raise SystemExit("not found")
        versions = [
            {"version": v.version, "id": v.id, "reason": v.reason}
            for v in ws.store.list_judgment_versions() if args.judgment_id in v.item_ids
        ]

        def pretty():
            ux.print_rule(f"judgment history · {args.judgment_id}")
            ux.print_kv([("supersedes", str(item.supersedes or "—"))])
            if versions:
                ux.print_table(
                    ["version", "id", "reason"],
                    [[f"v{v['version']}", v["id"], v["reason"]] for v in versions],
                )

        _emit(args, {"supersedes": item.supersedes, "versions": versions}, pretty)
    elif cmd == "versions":
        rows = [
            {"version": v.version, "id": v.id, "active": v.active,
             "items": len(v.item_ids), "reason": v.reason}
            for v in ws.store.list_judgment_versions()
        ]

        def pretty():
            ux.print_rule("judgment · versions")
            if not rows:
                ux.print_warn("no versions")
                return
            ux.print_table(
                ["", "version", "id", "items", "reason"],
                [["*" if r["active"] else "", f"v{r['version']}", r["id"],
                  r["items"], r["reason"]] for r in rows],
            )

        _emit(args, {"versions": rows}, pretty)
    elif cmd == "import-preview":
        cands = list(preview_yaml_import(ws.cfg.judgment_path))

        def pretty():
            ux.print_rule("judgment · import-preview")
            if not cands:
                ux.print_warn("nothing to import")
                return
            ux.print_table(
                ["kind", "stability", "statement"],
                [[c["kind"], c["stability"], (c["statement"] or "")[:70]] for c in cands],
            )

        _emit(args, {"candidates": cands, "count": len(cands)}, pretty)
    elif cmd == "import":
        result = apply_yaml_import(ws.store, ws.cfg.judgment_path)

        def pretty():
            ux.print_rule("judgment · import")
            ux.print_ok(f"imported {result['count']} item(s) as version {result['version']}")

        _emit(args, result, pretty)
    elif cmd == "export":
        yaml_text = export_judgment_yaml(ws.store)
        if _want_json(args):
            _print({"yaml": yaml_text})
        else:
            print(yaml_text)
    elif cmd == "proposals":
        rows = [
            {"id": p.id, "status": p.status.value, "confidence": round(p.confidence, 2),
             "reason": p.reason}
            for p in ws.store.list_judgment_proposals(status=args.status or None)
        ]

        def pretty():
            ux.print_rule("judgment · proposals")
            if not rows:
                ux.print_ok("no proposals")
                return
            ux.print_table(
                ["id", "status", "conf", "reason"],
                [[r["id"], r["status"], f"{r['confidence']:.2f}", (r["reason"] or "")[:60]]
                 for r in rows],
            )

        _emit(args, {"proposals": rows, "count": len(rows)}, pretty)
    elif cmd == "propose":
        if args.from_memory:
            p = propose_from_memory(ws.store, args.from_memory)
        else:
            props = propose_from_pattern(ws.store, domain=args.domain or "technical")
            if not props:
                raise SystemExit("no pattern proposals generated")
            p = props[0]

        def pretty():
            ux.print_rule("judgment · propose")
            ux.print_ok(f"proposal {p.id}")
            ux.print_dim(p.reason)
            ux.print_next([("→", f"twin judgment preview {p.id}")])

        _emit(args, {"id": p.id, "reason": p.reason}, pretty)
    elif cmd == "propose-episode":
        p = propose_from_episode(ws.store, args.episode_id, domain=args.domain)
        if p is None:
            def pretty_none():
                ux.print_rule("judgment · propose-episode")
                ux.print_warn(
                    f"episode {args.episode_id} has no confirmed trajectory "
                    "memories to generalize"
                )
                ux.print_next([
                    ("→", f"twin episode reflect {args.episode_id}"),
                    ("→", "twin review   # confirm reflected candidates first"),
                ])
            if _want_json(args):
                raise SystemExit(
                    f"episode {args.episode_id} has no confirmed memories to "
                    "generalize (confirm reflected candidates first)"
                )
            pretty_none()
            raise SystemExit(1)

        def pretty():
            ux.print_rule("judgment · propose-episode")
            ux.print_ok(f"proposal {p.id}")
            ux.print_dim(p.reason)
            ux.print_next([("→", f"twin judgment preview {p.id}")])

        _emit(args, {"id": p.id, "reason": p.reason, "episode_id": args.episode_id},
              pretty)
    elif cmd == "preview":
        preview = preview_proposal(ws.store, args.proposal_id)

        def pretty():
            _render_judgment_preview(preview, args.proposal_id)

        _emit(args, {"preview": preview}, pretty)
    elif cmd == "approve":
        result = approve_proposal(
            ws.store, args.proposal_id, preview_token=args.token,
            confirm_constitutional=args.constitutional,
        )

        def pretty():
            ux.print_rule("judgment · approve")
            ux.print_ok(f"approved {args.proposal_id}")
            ux.print_dim(str(result))

        _emit(args, {"proposal_id": args.proposal_id, "result": result}, pretty)
    elif cmd == "reject":
        reject_proposal(ws.store, args.proposal_id, reason=args.reason or "")

        def pretty():
            ux.print_rule("judgment · reject")
            ux.print_ok(f"rejected {args.proposal_id}")

        _emit(args, {"proposal_id": args.proposal_id, "status": "rejected"}, pretty)
    elif cmd == "defer":
        defer_proposal(ws.store, args.proposal_id)

        def pretty():
            ux.print_rule("judgment · defer")
            ux.print_ok(f"deferred {args.proposal_id}")

        _emit(args, {"proposal_id": args.proposal_id, "status": "deferred"}, pretty)
    elif cmd == "simulate":
        result = simulate(
            ws.store, args.query, domain=args.domain or "technical",
            project_id=args.project, task_profile=args.profile or "architecture",
        )

        def pretty():
            ux.print_rule("judgment · simulate")
            ux.print_panel(result["markdown"], title="simulation")

        _emit(args, result, pretty)
    elif cmd == "explain":
        tr = ws.store.get_judgment_trace(args.trace_id)
        if tr is None:
            raise SystemExit("trace not found")

        def pretty():
            ux.print_rule(f"judgment explain · {args.trace_id}")
            ux.print_panel(tr.model_dump_json(indent=2), title="trace")

        _emit(args, tr.model_dump(mode="json"), pretty)
    elif cmd == "counterfactual":
        text = counterfactual(ws.store, args.query, args.judgment_id,
                              domain=args.domain or "technical")

        def pretty():
            ux.print_rule("judgment · counterfactual")
            ux.print_panel(str(text), title="counterfactual")

        _emit(args, {"counterfactual": text}, pretty)
    elif cmd == "conflicts":
        if args.refresh:
            detect_judgment_conflicts(ws.store)
            detect_behavior_conflicts(ws.store)
        rows = [
            {"id": c.id, "type": c.type.value, "reason": c.reason}
            for c in ws.store.list_judgment_conflicts(status=args.status or "open")
        ]

        def pretty():
            ux.print_rule("judgment · conflicts")
            if not rows:
                ux.print_ok("no conflicts")
                return
            ux.print_table(
                ["id", "type", "reason"],
                [[r["id"], r["type"], (r["reason"] or "")[:70]] for r in rows],
            )
            ux.print_warn(f"{len(rows)} open conflict(s)")

        _emit(args, {"conflicts": rows, "count": len(rows)}, pretty)
    elif cmd == "resolve-conflict":
        resolve_conflict(
            ws.store, args.conflict_id,
            resolution=args.resolution or "dismiss",
            dismiss=True,
        )

        def pretty():
            ux.print_rule("judgment · resolve-conflict")
            ux.print_ok(f"resolved {args.conflict_id}")

        _emit(args, {"conflict_id": args.conflict_id, "status": "resolved"}, pretty)
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


def _connector_adapter(ws, creds, connector_id: str):
    """Build a live adapter for discovery helpers (raises if not found)."""
    from ..connectors.registry import build_adapter

    inst = ws.store.get_connector_instance(connector_id)
    if inst is None:
        raise SystemExit(f"connector {connector_id} not found")
    acc = ws.store.get_source_account(inst.account_id)
    secret = creds.get(inst.credential_ref) if inst.credential_ref else None
    return build_adapter(inst, acc, secret)


def _connector_discovery(args, ws, creds, *, method, headers, row,
                         scope_key=None, id_of=None):
    """Shared render for github/slack/gmail/... scope-discovery helpers.

    Lists what the credential can reach. With ``--select`` (when the connector
    has a ``scope_key``) it also WRITES the selection into that configuration
    key — merging safely, so other configuration is preserved — turning the
    discovery command into the way you actually pick your scope."""
    from . import ux

    adapter = _connector_adapter(ws, creds, args.connector_id)
    items = list(getattr(adapter, method)())

    select = list(getattr(args, "select", None) or [])
    if select and scope_key:
        visible = {id_of(it) for it in items} if id_of else set()
        unknown = [s for s in select if visible and s not in visible]
        # replace the scope selection (dedup, keep order); preserve other config
        seen: set = set()
        chosen = [s for s in select if not (s in seen or seen.add(s))]
        inst = ws.store.get_connector_instance(args.connector_id)
        config = dict(inst.configuration or {})
        config[scope_key] = chosen
        ws.store.update_connector_instance(args.connector_id, configuration=config)
        data = {"connector_id": args.connector_id, "scope_key": scope_key,
                "selected": chosen, "unknown_to_credential": unknown,
                "count": len(items)}

        def pretty_select():
            ux.print_rule(f"connector · {args.connector_command} · select")
            for u in unknown:
                ux.print_warn(f"{u!r} is not visible to this credential — "
                              "kept anyway; sync will skip what it cannot read")
            ux.print_kv([("connector", args.connector_id),
                         (scope_key, ", ".join(chosen) or "(none)")])
            ux.print_ok(f"{scope_key} set to {len(chosen)} item(s)")
            ux.print_next([("→", f"twin connector backfill {args.connector_id} --preview"),
                           ("→", f"twin connector sync {args.connector_id}")])

        _emit(args, data, pretty_select)
        return

    def pretty():
        ux.print_rule(f"connector · {args.connector_command}")
        if not items:
            ux.print_warn("nothing visible to this credential")
            return
        ux.print_table(headers, [row(it) for it in items])
        ux.print_ok(f"{len(items)} item(s) visible")
        if scope_key:
            ux.print_next([("→",
                f"twin connector {args.connector_command} … {args.connector_id} "
                f"--select <id> [<id> …]   # pick your {scope_key}")])

    _emit(args, {"items": items, "count": len(items)}, pretty)


def cmd_connector(args) -> None:
    import json as _json

    from . import ux
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
        names = list(list_adapters())

        def pretty():
            ux.print_rule("connector adapters")
            ux.print_table(["adapter"], [[n] for n in names])
            ux.print_ok(f"{len(names)} adapter type(s) registered")

        _emit(args, {"adapters": names}, pretty)
    elif cmd == "list":
        rows = []
        for inst in ws.store.list_connector_instances():
            acc = ws.store.get_source_account(inst.account_id)
            rows.append({
                "id": inst.id,
                "type": inst.connector_type,
                "status": getattr(inst.status, "value", inst.status),
                "owner": acc.source_owner if acc else "?",
                "vault": acc.vault_id if acc else "?",
                "account": inst.account_id,
            })

        def pretty():
            ux.print_rule("connectors")
            if not rows:
                ux.print_warn("no connectors yet")
                ux.print_next([("→", "twin connector setup <type> --source-owner personal")])
                return
            ux.print_table(
                ["id", "type", "status", "owner", "vault", "account"],
                [[r["id"], r["type"], r["status"], r["owner"], r["vault"], r["account"]]
                 for r in rows],
            )
            ux.print_ok(f"{len(rows)} connector(s)")

        _emit(args, {"connectors": rows, "count": len(rows)}, pretty)
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
        data = {
            "account": acc.id, "vault": acc.vault_id,
            "connector": inst.id, "status": inst.status.value,
        }

        def pretty():
            ux.print_rule(f"connector add · {args.connector_type}")
            ux.print_kv([
                ("account", acc.id),
                ("vault", acc.vault_id),
                ("connector", inst.id),
                ("status", inst.status.value),
                ("credential", "set" if args.secret else "none"),
            ])
            ux.print_ok("connector registered")
            ux.print_next([
                ("→", f"twin connector auth {inst.id}      — verify credential"),
                ("→", f"twin connector sync {inst.id}      — first sync pass"),
                ("→", "twin extract                        — interpret percepts"),
                ("→", "twin review                         — approve candidates"),
            ])

        _emit(args, data, pretty)
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
        cred = "set" if inst.credential_ref else "none"
        data = {"id": inst.id, "status": inst.status.value, "credential": cred}

        def pretty():
            ux.print_rule("connector configure")
            ux.print_kv([
                ("connector", inst.id),
                ("status", inst.status.value),
                ("credential", cred),
            ])
            ux.print_ok("configuration updated")

        _emit(args, data, pretty)
    elif cmd in ("auth", "test"):
        health = validate_connector(ws.store, creds, args.connector_id)
        status = health.status.value
        data = {"connector": args.connector_id, "status": status, "detail": health.detail}

        def pretty():
            ux.print_rule(f"connector {cmd}")
            ux.print_kv([("connector", args.connector_id), ("status", status)])
            msg = f"{args.connector_id}: {health.detail}"
            if status in ("healthy", "ok"):
                ux.print_ok(msg)
            elif status in ("unknown", "paused", "degraded"):
                ux.print_warn(msg)
            else:
                ux.print_err(msg)

        _emit(args, data, pretty)
        if status not in ("healthy", "ok", "unknown", "paused"):
            raise SystemExit(1)
    elif cmd == "sync":
        result = sync_connector(
            ws.store, creds, args.connector_id,
            streams=[args.stream] if args.stream else None,
            emit_percepts=not args.no_percepts,
        )
        streams = [
            {
                "stream": s.stream,
                "state": ("skipped:" + s.skipped) if s.skipped else "committed",
                "raw": s.raw, "normalized": s.normalized, "dedup": s.deduplicated,
                "quarantined": s.quarantined, "percepts": s.percepts, "failed": s.failed,
            }
            for s in result.streams
        ]
        data = {
            "connector": args.connector_id,
            "health": result.health.value,
            "percepts": result.percepts,
            "streams": streams,
        }

        def pretty():
            ux.print_rule(f"connector sync · {args.connector_id}")
            ux.print_kv([
                ("health", result.health.value),
                ("percepts", str(result.percepts)),
                ("streams", str(len(streams))),
            ])
            if streams:
                ux.print_table(
                    ["stream", "state", "raw", "norm", "dedup", "quar", "percepts", "failed"],
                    [[s["stream"], s["state"], s["raw"], s["normalized"], s["dedup"],
                      s["quarantined"], s["percepts"], s["failed"]] for s in streams],
                )
            if result.health.value in ("healthy", "ok"):
                ux.print_ok("sync complete")
            else:
                ux.print_warn(f"sync finished with health={result.health.value}")
            if result.percepts:
                ux.print_next([("→", "twin extract   — interpret the new percepts")])

        _emit(args, data, pretty)
    elif cmd == "github":
        if args.github_command != "repositories":
            raise SystemExit(f"unknown github command: {args.github_command}")
        _connector_discovery(
            args, ws, creds, method="list_repositories",
            headers=["repository", "visibility", "open_issues", "pushed"],
            row=lambda r: [
                r["full_name"], "private" if r.get("private") else "public",
                r.get("open_issues"), r.get("pushed_at"),
            ],
            scope_key="repositories", id_of=lambda r: r.get("full_name"),
        )
    elif cmd == "slack":
        if args.slack_command != "channels":
            raise SystemExit(f"unknown slack command: {args.slack_command}")
        _connector_discovery(
            args, ws, creds, method="list_channels",
            headers=["id", "channel", "kind", "members"],
            row=lambda ch: [
                ch["id"], f"#{ch.get('name') or '?'}",
                "private" if ch.get("is_private") else "im" if ch.get("is_im") else "public",
                ch.get("num_members"),
            ],
            scope_key="channels", id_of=lambda ch: ch.get("id"),
        )
    elif cmd == "gmail":
        if args.gmail_command != "labels":
            raise SystemExit(f"unknown gmail command: {args.gmail_command}")
        _connector_discovery(
            args, ws, creds, method="list_labels",
            headers=["id", "label", "type", "messages"],
            row=lambda lab: [
                lab["id"], lab.get("name") or "?", lab.get("type"),
                lab.get("messages_total"),
            ],
            scope_key="labels", id_of=lambda lab: lab.get("id"),
        )
    elif cmd == "outlook":
        if args.outlook_command != "folders":
            raise SystemExit(f"unknown outlook command: {args.outlook_command}")
        _connector_discovery(
            args, ws, creds, method="list_folders",
            headers=["id", "folder", "items"],
            row=lambda f: [f["id"], f.get("name") or "?", f.get("total_item_count")],
        )
    elif cmd == "calendar":
        if args.calendar_command != "calendars":
            raise SystemExit(f"unknown calendar command: {args.calendar_command}")
        _connector_discovery(
            args, ws, creds, method="list_calendars",
            headers=["id", "calendar", "role", "primary"],
            row=lambda c: [
                c["id"], c.get("summary") or "?", c.get("access_role"),
                "yes" if c.get("primary") else "",
            ],
        )
    elif cmd == "fireflies":
        if args.fireflies_command != "meetings":
            raise SystemExit(f"unknown fireflies command: {args.fireflies_command}")
        _connector_discovery(
            args, ws, creds, method="list_meetings",
            headers=["id", "title", "date"],
            row=lambda m: [m.get("id") or "?", m.get("title") or "?", m.get("date") or ""],
        )
    elif cmd == "folder":
        if args.folder_command != "roots":
            raise SystemExit(f"unknown folder command: {args.folder_command}")
        _connector_discovery(
            args, ws, creds, method="list_roots",
            headers=["id", "path", "status"],
            row=lambda r: [
                r.get("id") or "?", r.get("path") or "?",
                "ok" if r.get("readable") else "missing" if not r.get("exists") else "unreadable",
            ],
        )
    elif cmd == "backfill":
        if getattr(args, "run_partition", False):
            if not args.job_id:
                raise SystemExit("--run-partition requires --job-id")
            from ..connectors import run_backfill_partition
            out = run_backfill_partition(
                ws.store, creds, args.job_id,
                emit_percepts=not getattr(args, "no_percepts", False),
            )

            def pretty():
                ux.print_rule("backfill · run-partition")
                ux.print_kv([
                    ("job", str(out.get("job_id") or args.job_id)),
                    ("partition", str(out.get("partition_key") or "—")),
                    ("partition_status", str(out.get("partition_status") or "—")),
                    ("job_status", str(out.get("job_status") or out.get("status") or "—")),
                    ("done", "yes" if out.get("done") else "no"),
                ])
                if out.get("done"):
                    ux.print_ok("backfill job complete")
                else:
                    ux.print_dim("one partition advanced · prefer --run under twin runtime start")
                    ux.print_next([
                        ("→", "twin runtime start"),
                        ("→", f"twin connector backfill --run --job-id {args.job_id}"),
                    ])

            _emit(args, out, pretty)
            return
        if getattr(args, "run", False):
            from ..runtime.backfill_sched import enqueue_backfill_partition_jobs
            from ..runtime.queue import RuntimeQueue

            job_id = getattr(args, "job_id", None)
            if not job_id:
                if not args.connector_id:
                    raise SystemExit("--run requires connector_id or --job-id")
                candidates = [
                    j for j in ws.store.list_backfill_jobs(args.connector_id)
                    if j.status.value in ("planned", "running", "failed")
                ]
                if not candidates:
                    raise SystemExit(
                        "no active backfill job — create one with "
                        f"`twin connector backfill {args.connector_id} --create`"
                    )
                job_id = candidates[0].id
            job = ws.store.get_backfill_job(job_id)
            if job is None:
                raise SystemExit(f"backfill job {job_id} not found")
            q = RuntimeQueue(ws.store)
            enqueued = enqueue_backfill_partition_jobs(
                q, ws.store,
                vault_id=(job.metadata or {}).get("vault_id") or "vault_general",
                backfill_job_id=job_id,
            )
            if _want_json(args):
                # JSON path: enqueue only (no live watch loop).
                prog = job.progress or {}
                _print({
                    "job_id": job_id,
                    "status": job.status.value,
                    "enqueued": enqueued,
                    "completed_partitions": prog.get("completed_partitions", 0),
                    "total_partitions": prog.get("total_partitions", 0),
                    "mode": "watch",
                    "note": "partitions execute via twin runtime start",
                })
                return
            if enqueued:
                ux.print_ok(f"enqueued {len(enqueued)} backfill_partition job(s)")
            else:
                ux.print_dim("no new runtime job needed (claim live or already queued)")
            ux.print_next([
                ("→", "twin runtime start   # drains backfill_partition jobs"),
            ])
            out = ux.watch_backfill_job(ws.store, job_id)
            if not out.get("done"):
                ux.print_next([
                    ("→", "twin runtime start"),
                    ("→", f"twin connector backfill --run --job-id {job_id}"),
                ])
            return
        if not args.connector_id:
            raise SystemExit("connector_id required")
        if getattr(args, "cancel", False):
            if not args.job_id:
                raise SystemExit("--cancel requires --job-id")
            from ..connectors import cancel_backfill_job
            job = cancel_backfill_job(ws.store, args.job_id)
            data = {"job": job.id, "status": job.status.value}

            def pretty():
                ux.print_rule("backfill · cancel")
                ux.print_kv([("job", job.id), ("status", job.status.value)])
                ux.print_ok("backfill job cancelled")
                ux.print_next([
                    ("→", f"twin connector backfill {args.connector_id} --preview"),
                    ("→", f"twin connector backfill {args.connector_id} --create"),
                ])

            _emit(args, data, pretty)
            return
        if getattr(args, "create", False):
            from ..connectors import create_backfill_job
            job = create_backfill_job(ws.store, creds, args.connector_id)
            total = (job.progress or {}).get("total_partitions")
            data = {"job": job.id, "status": job.status.value, "partitions": total}

            def pretty():
                ux.print_rule("backfill · create")
                ux.print_kv([
                    ("job", job.id), ("status", job.status.value),
                    ("partitions", str(total)),
                ])
                ux.print_ok("backfill job created (no ingest yet)")
                ux.print_next([
                    ("→", "twin runtime start"),
                    ("→", f"twin connector backfill {args.connector_id} --run --job-id {job.id}"),
                ])

            _emit(args, data, pretty)
            return
        if getattr(args, "jobs", False):
            jobs = []
            for job in ws.store.list_backfill_jobs(args.connector_id):
                prog = job.progress or {}
                jobs.append({
                    "id": job.id, "status": job.status.value,
                    "completed": prog.get("completed_partitions", 0),
                    "total": prog.get("total_partitions", 0),
                })

            def pretty():
                ux.print_rule("backfill · jobs")
                if not jobs:
                    ux.print_warn("no backfill jobs")
                    return
                ux.print_table(
                    ["id", "status", "partitions"],
                    [[j["id"], j["status"], f"{j['completed']}/{j['total']}"] for j in jobs],
                )
                active = next(
                    (j for j in jobs if j["status"] in ("planned", "running", "failed")),
                    None,
                )
                if active:
                    ux.print_next([
                        ("→", "twin runtime start"),
                        ("→", f"twin connector backfill {args.connector_id} --run --job-id {active['id']}"),
                    ])

            _emit(args, {"jobs": jobs, "count": len(jobs)}, pretty)
            return
        if not args.preview:
            raise SystemExit(
                "use --preview to inspect scope, --create to open a "
                "BackfillJob, --jobs to list, --run to watch runtime drain, "
                "or --run-partition --job-id ID for one-shot debug "
                "(previewing never ingests)")
        from ..connectors import backfill_preview
        preview = backfill_preview(ws.store, creds, args.connector_id,
                                   principal_id="principal_local_cli")

        def pretty():
            ux.print_rule(f"backfill preview · {args.connector_id}")
            ux.print_panel(_json.dumps(preview, indent=2, ensure_ascii=False),
                           title="scope (no ingest)")
            ux.print_ok("preview only — nothing was imported")

        _emit(args, preview, pretty)
    elif cmd in ("pause", "resume", "revoke"):
        if cmd == "pause":
            inst = pause_connector(ws.store, args.connector_id)
        elif cmd == "resume":
            inst = resume_connector(ws.store, args.connector_id)
        else:
            inst = revoke_connector(ws.store, creds, args.connector_id)
        status = inst.status.value
        data = {"connector": args.connector_id, "status": status}

        def pretty():
            ux.print_rule(f"connector {cmd}")
            ux.print_ok(f"{args.connector_id} → {status}")

        _emit(args, data, pretty)
    elif cmd == "status":
        health = connector_health(ws.store, args.connector_id)

        def pretty():
            ux.print_rule(f"connector status · {args.connector_id}")
            if health.get("error"):
                ux.print_err(health["error"])
                return
            ux.print_kv([
                ("type", str(health.get("connector_type"))),
                ("health", str(health.get("health"))),
                ("instance", str(health.get("instance_status"))),
                ("pending", str(health.get("pending_items"))),
                ("dead_letters", str(health.get("dead_letters"))),
                ("last_success", str(health.get("last_success_at") or "—")),
                ("next_run", str(health.get("next_run_at") or "—")),
            ])
            hv = str(health.get("health"))
            if hv in ("healthy", "ok"):
                ux.print_ok("connector healthy")
            elif hv in ("failed", "error"):
                ux.print_err(f"health={hv}")
            else:
                ux.print_warn(f"health={hv}")

        _emit(args, health, pretty)
    elif cmd == "checkpoint":
        rows = [
            {"stream": c.stream, "version": c.version, "cursor": c.cursor,
             "batch": c.committed_batch_id}
            for c in ws.store.list_connector_checkpoints(args.connector_id)
        ]

        def pretty():
            ux.print_rule(f"checkpoints · {args.connector_id}")
            if not rows:
                ux.print_warn("no checkpoints")
                return
            ux.print_table(
                ["stream", "version", "cursor", "batch"],
                [[r["stream"], f"v{r['version']}", r["cursor"], r["batch"]] for r in rows],
            )

        _emit(args, {"checkpoints": rows}, pretty)
    elif cmd == "dead-letters":
        rows = [
            {"id": d.id, "failure_class": d.failure_class.value, "status": d.status.value,
             "attempts": d.attempts, "external": f"{d.external_type}:{d.external_id}",
             "last_error": d.last_error}
            for d in ws.store.list_connector_dead_letters(args.connector_id)
        ]

        def pretty():
            ux.print_rule(f"dead letters · {args.connector_id}")
            if not rows:
                ux.print_ok("no dead letters")
                return
            ux.print_table(
                ["id", "failure", "status", "attempts", "external", "error"],
                [[r["id"], r["failure_class"], r["status"], r["attempts"],
                  r["external"], (r["last_error"] or "")[:60]] for r in rows],
            )
            ux.print_warn(f"{len(rows)} dead letter(s) — retry with: twin connector replay <id>")

        _emit(args, {"dead_letters": rows}, pretty)
    elif cmd == "replay":
        from ..connectors import retry_dead_letter
        dlq = retry_dead_letter(ws.store, creds, args.dead_letter_id)
        data = {"id": dlq.id, "status": dlq.status.value, "attempts": dlq.attempts,
                "last_error": dlq.last_error}

        def pretty():
            ux.print_rule("connector replay")
            ux.print_kv([("id", dlq.id), ("status", dlq.status.value),
                         ("attempts", str(dlq.attempts))])
            if dlq.last_error:
                ux.print_warn(dlq.last_error)
            else:
                ux.print_ok("replayed")

        _emit(args, data, pretty)
    elif cmd == "deletion-events":
        rows = [
            {"id": e.id, "status": e.status.value,
             "external": f"{e.external_type}:{e.external_id}",
             "prior": len(e.prior_record_ids), "percepts": len(e.affected_percept_ids)}
            for e in ws.store.list_connector_deletion_events(args.connector_id)
        ]

        def pretty():
            ux.print_rule(f"deletion events · {args.connector_id}")
            if not rows:
                ux.print_ok("no deletion events")
                return
            ux.print_table(
                ["id", "status", "external", "prior", "percepts"],
                [[r["id"], r["status"], r["external"], r["prior"], r["percepts"]]
                 for r in rows],
            )

        _emit(args, {"deletion_events": rows}, pretty)
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
            connector_id=getattr(args, "connector_id", None),
        )

        def pretty():
            ux.print_rule(f"connector setup · {args.connector_type}")
            if not plan.get("ok"):
                ux.print_err(plan.get("error", "setup plan failed"))
                for key in ("known", "allowed"):
                    if plan.get(key):
                        ux.print_dim(f"  {key}: {', '.join(map(str, plan[key]))}")
                return
            ux.print_kv([
                ("connector_type", plan.get("connector_type")),
                ("connector_id", str(plan.get("connector_id") or "(not registered yet)")),
                ("source_owner", plan.get("source_owner")),
                ("vault_id", str(plan.get("vault_id") or "(auto)")),
                ("status", str(plan.get("status") or "—")),
                ("auth_mode", str(plan.get("auth_mode") or "—")),
                ("ingests", "no — plan only"),
            ])
            for w in plan.get("warnings", []):
                ux.print_warn(w)
            next_id = plan.get("next_step")
            for i, step in enumerate(plan.get("steps", []), start=1):
                marker = {"done": "✓", "ready": "→", "blocked": "✗"}.get(
                    step.get("status"), "·")
                body = f"{step.get('detail', '')}\n\n$ {step.get('command', '')}"
                ux.print_panel(
                    body,
                    title=f"{marker} {i}. {step.get('title')} · {step.get('status')}"
                    + ("   ← you are here" if step.get("id") == next_id else ""),
                )
            if plan.get("complete"):
                ux.print_ok("setup complete — this connector is authenticated, "
                            "scoped and has synced at least once")
            else:
                nxt = next((s for s in plan.get("steps", [])
                            if s.get("id") == next_id), None)
                if nxt:
                    ux.print_next([("→", nxt.get("command", ""))])
                ux.print_ok("plan reflects the connector's real state — nothing "
                            "fetched until you run the command above")

        _emit(args, plan, pretty)
        if not plan.get("ok"):
            raise SystemExit(1)
    elif cmd == "due":
        from ..connectors import list_due_connectors
        due = list_due_connectors(ws.store, ws.cfg.home)

        def pretty():
            ux.print_rule("connectors due")
            rows = due.get("due", [])
            if not rows:
                ux.print_ok("nothing due right now")
                return
            ux.print_table(
                ["connector", "type", "status", "lag(s)", "next_run"],
                [[r.get("connector_id"), r.get("connector_type"), r.get("status"),
                  r.get("schedule_lag_seconds"), r.get("next_run_at") or "—"]
                 for r in rows],
            )
            ux.print_warn(f"{due.get('count')} connector(s) due")
            ux.print_next([("→", "twin connector sync-due   — run one scheduler pass")])

        _emit(args, due, pretty)
    elif cmd == "sync-due":
        from ..connectors import run_sync_due
        rows = run_sync_due(
            ws.store, creds, ws.cfg.home,
            emit_percepts=not getattr(args, "no_percepts", False),
        )

        def pretty():
            ux.print_rule("connector sync-due")
            if not rows:
                ux.print_ok("nothing was due")
                return
            ux.print_table(
                ["connector", "ok", "health", "percepts", "streams"],
                [[r.get("connector_id"), "yes" if r.get("ok") else "no",
                  r.get("health"), r.get("percepts"), r.get("streams")] for r in rows],
            )
            total = sum(r.get("percepts", 0) for r in rows)
            ux.print_ok(f"{len(rows)} connector(s) synced · {total} percepts")

        _emit(args, {"results": rows, "count": len(rows)}, pretty)
    elif cmd == "contract":
        from ..connectors import contract_matrix
        matrix = contract_matrix()

        def pretty():
            ux.print_rule("adapter contract matrix")
            ux.print_kv([
                ("adapters", str(matrix.get("adapters"))),
                ("ok", "yes" if matrix.get("ok") else "no"),
            ])
            ux.print_table(
                ["adapter", "ok", "missing_required", "partial"],
                [[r.get("connector_type") or r.get("adapter") or r.get("name"),
                  "yes" if r.get("ok") else "no",
                  len(r.get("missing_required", []) or []),
                  len(r.get("partial_items", []) or [])]
                 for r in matrix.get("rows", [])],
            )
            if matrix.get("ok"):
                ux.print_ok("all adapter rows meet the contract")
            else:
                ux.print_warn(matrix.get("note", "some rows incomplete"))

        _emit(args, matrix, pretty)
    elif cmd == "production-ready":
        from ..connectors import production_ready_adapters
        report = production_ready_adapters()

        def pretty():
            ux.print_rule("production-ready adapters")
            ready = report.get("ready", [])
            not_ready = report.get("not_ready", [])
            if ready:
                ux.print_table(
                    ["adapter", "status"],
                    [[r.get("connector_type"), "ready"] for r in ready],
                )
            for r in not_ready:
                ux.print_warn(
                    f"{r.get('connector_type')}: missing "
                    f"{', '.join(r.get('missing_required', []) or []) or '—'}"
                )
            if report.get("ok"):
                ux.print_ok(f"{len(ready)} adapter(s) production-ready")
            else:
                ux.print_warn(f"{len(not_ready)} adapter(s) not production-ready")

        _emit(args, report, pretty)
        if not report.get("ok"):
            raise SystemExit(1)
    else:
        raise SystemExit(f"unknown connector command: {cmd}")


def cmd_supersede(args) -> None:
    from . import ux
    from ..memory.lifecycle import supersede

    ws = Workspace(args.home)
    result = supersede(ws.store, args.new_id, args.old_id)

    def pretty():
        ux.print_rule("supersede")
        ux.print_ok(f"{result.subject_id} supersedes {result.object_id}")
        ux.print_dim(f"old memory deprecated (relation {result.relation_id})")

    _emit(args, {
        "subject_id": result.subject_id, "object_id": result.object_id,
        "relation_id": result.relation_id,
    }, pretty)


def cmd_contradict(args) -> None:
    from . import ux
    from ..memory.lifecycle import contradict

    ws = Workspace(args.home)
    result = contradict(ws.store, args.id_a, args.id_b)

    def pretty():
        ux.print_rule("contradict")
        ux.print_warn(f"{result.subject_id} contradicts {result.object_id}")
        ux.print_dim(f"both queued for review (relation {result.relation_id})")

    _emit(args, {
        "subject_id": result.subject_id, "object_id": result.object_id,
        "relation_id": result.relation_id,
    }, pretty)


def cmd_stats(args) -> None:
    from . import ux
    from ..memory.metrics import compute_metrics

    ws = Workspace(args.home)
    metrics = compute_metrics(ws.store)

    def pretty():
        ux.print_rule("stats")
        flat = [(k, v) for k, v in metrics.items() if not isinstance(v, (dict, list))]
        if flat:
            ux.print_kv([(str(k), str(v)) for k, v in flat])
        for k, v in metrics.items():
            if isinstance(v, dict) and v:
                ux.print_table(
                    [k, "value"],
                    [[str(kk), str(vv)] for kk, vv in v.items()],
                )

    _emit(args, metrics, pretty)


def cmd_serve(args) -> None:
    from .api import main as serve_main

    serve_main(args.home, host=args.host, port=args.port)


def cmd_mcp(args) -> None:
    from .mcp_server import main as mcp_main

    mcp_main(args.home)


def cmd_backup(args) -> None:
    from pathlib import Path

    from . import ux
    from ..sovereignty.backup import create_backup, restore_sqlite_backup, validate_backup

    ws = Workspace(args.home)
    cmd = args.backup_command
    if cmd == "create":
        dest = Path(args.dest)
        db_path = None
        if hasattr(ws.store, "path"):
            db_path = Path(ws.store.path)
        with _work_spinner(args, "Creating backup…"):
            manifest = create_backup(ws.store, dest, copy_sqlite_db=db_path)
        data = manifest.model_dump(mode="json")

        def pretty():
            ux.print_rule("backup · create")
            ux.print_kv([("destination", str(dest)), *_summary_kv(data)])
            ux.print_ok(f"backup written to {dest}")

        _emit(args, data, pretty)
        return
    if cmd == "validate":
        result = validate_backup(args.bundle)

        def pretty():
            ux.print_rule("backup · validate")
            ux.print_panel(json.dumps(result, indent=2, default=str), title=str(args.bundle))
            if isinstance(result, dict) and result.get("ok", True):
                ux.print_ok("bundle looks valid")

        _emit(args, result, pretty)
        return
    if cmd == "restore":
        result = restore_sqlite_backup(args.bundle, args.target_db)

        def pretty():
            ux.print_rule("backup · restore")
            ux.print_panel(json.dumps(result, indent=2, default=str), title="restore")
            ux.print_ok(f"restored into {args.target_db}")

        _emit(args, result, pretty)
        return
    raise SystemExit(f"unknown backup command: {cmd}")


def cmd_export(args) -> None:
    from . import ux
    from ..judgment.profile import load_profile

    ws = Workspace(args.home)
    memories = ws.store.list_memories(limit=100000)
    data = {
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
    }

    def pretty():
        ux.print_rule("export")
        ux.print_kv([
            ("memories", str(len(data["memories"]))),
            ("entities", str(len(data["entities"]))),
        ])
        ux.print_warn("summary only — pipe with --json to capture the full dump")

    _emit(args, data, pretty)


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
    """host-native observation (Claude Code hooks proof).

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
        claude_hooks_stdout,
        install_claude_code_hooks,
        normalize_claude_code_hook,
        uninstall_claude_code_hooks,
    )
    from .native.events import HostEvent
    from .native.service import NativeHostService, should_emit_pack

    ws = Workspace(args.home)
    if args.native_command == "install":
        from . import ux

        target = args.dir or str(ws.cfg.home / "native" / "claude-code")
        merge = not bool(getattr(args, "no_merge", False))
        settings_path = getattr(args, "settings", None)
        try:
            result = install_claude_code_hooks(
                twin_bin=args.twin_bin or "twin",
                home=str(ws.cfg.home),
                snippet_dir=Path(target),
                settings_path=Path(settings_path) if settings_path else None,
                merge=merge,
                profile=getattr(args, "profile", None) or "standard",
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        ux.print_rule("native install")
        ux.print_ok(f"snippet {result['snippet']}")
        ux.print_dim(f"observation profile: {result.get('profile', 'standard')}")
        if result.get("merged"):
            ux.print_ok(f"merged into {result['settings']}")
            if result.get("backup"):
                ux.print_dim(f"backup {result['backup']}")
            ux.print_next([
                ("→", "restart Claude Code (or start a new session)"),
                ("→", "type /hooks — SessionStart / UserPromptSubmit / SessionEnd / … should list Twin"),
            ])
        else:
            ux.print_warn("snippet only — did not patch Claude settings (--no-merge)")
            ux.print_next([
                ("→", "merge hooks from the snippet into ~/.claude/settings.json"),
                ("→", "restart Claude Code to activate host-native observation"),
            ])
        return

    if args.native_command == "uninstall":
        from . import ux

        settings_path = getattr(args, "settings", None)
        try:
            result = uninstall_claude_code_hooks(
                settings_path=Path(settings_path) if settings_path else None,
                restore_backup=bool(getattr(args, "restore_backup", False)),
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        ux.print_rule("native uninstall")
        if result.get("restored"):
            ux.print_ok(f"restored {result['settings']} from {result['backup']}")
        elif result.get("removed"):
            ux.print_ok(f"removed Twin hooks from {result['settings']}")
            if result.get("backup"):
                ux.print_dim(f"backup {result['backup']}")
        else:
            ux.print_dim(f"no Twin hooks found in {result['settings']} — nothing to remove")
        ux.print_next([
            ("→", "restart Claude Code (or start a new session) to drop the hooks"),
        ])
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

    emit_pack = (
        should_emit_pack(getattr(event, "kind", "") or "")
        or bool((result.extras or {}).get("emit_pack"))
        or bool(result.context_pack)
    )
    payload = result.to_dict(include_pack=emit_pack)
    if not result.ok:
        print(
            f"twin native: {result.error}"
            + (f" error_id={result.error_id}" if result.error_id else ""),
            file=sys.stderr,
        )
    # Hooks (--fail-open + claude-code): speak Claude's hook stdout schema so
    # SessionStart injects context_pack as additionalContext, and observation
    # hooks stay silent (no Twin JSON dumped into the transcript).
    if fail_open and host == "claude-code":
        meta = getattr(event, "metadata", None) or {}
        hook_name = (
            getattr(args, "hook", None)
            or meta.get("hook_event_name")
            or ""
        )
        kind_to_hook = {
            "session_start": "SessionStart",
            "user_message": "UserPromptSubmit",
            "tool_requested": "PreToolUse",
            "tool_completed": "PostToolUse",
            "assistant_result": "Stop",
            "turn_completed": "Stop",
            "session_end": "SessionEnd",
        }
        if not hook_name and getattr(event, "kind", "") in kind_to_hook:
            hook_name = kind_to_hook[event.kind]
        claude_out = claude_hooks_stdout(
            hook_event_name=str(hook_name),
            ok=result.ok,
            context_pack=payload.get("context_pack") if emit_pack else None,
            error=result.error,
        )
        if claude_out is not None:
            print(json.dumps(claude_out, ensure_ascii=False, default=str))
        # silent success / fail-open: no NativeEventResult on stdout
    else:
        print(json.dumps(payload, ensure_ascii=False, default=str))
    if not result.ok and not fail_open:
        raise SystemExit(1)


def _clip(text: object, n: int = 28) -> str:
    """Truncate long table cells so Rich fold does not wrap IDs across lines."""
    s = "" if text is None else str(text)
    return s if len(s) <= n else s[: max(1, n - 1)] + "…"


def _stage_status_line(report) -> list[tuple[str, str]]:
    """KV rows summarizing each brain stage's status + counts."""
    from ..cognition.episode_pipeline import STAGE_ORDER

    rows: list[tuple[str, str]] = []
    for st in STAGE_ORDER:
        outcome = report.stages.get(st.value)
        if outcome is None:
            continue
        counts = ", ".join(f"{k}={v}" for k, v in outcome.counts.items())
        detail = (outcome.detail or "").strip()
        val = outcome.status.value
        parts = [val]
        if counts:
            parts.append(counts)
        if detail and outcome.status.value in ("deferred", "blocked", "error"):
            parts.append(detail)
        rows.append((st.value, " · ".join(parts)))
    return rows


def _cognition_next_steps(report) -> list[tuple[str, str]]:
    """Honest next-steps from deferred/blocked stage details."""
    details = " ".join(
        (report.stages[s].detail or "").lower()
        for s in report.stages
        if report.stages[s].status.value in ("deferred", "blocked")
    )
    nexts: list[tuple[str, str]] = []
    if any(report.stages[s].status.value == "blocked" for s in report.stages):
        nexts.append(("→", "set TWIN_EXTRACTOR=auto — heuristic can't reason"))
        return nexts
    if "jsondecode" in details or "schema" in details or "error:" in details:
        nexts.append((
            "→",
            "model returned unusable output — re-run twin meditate "
            "(or try a smaller/stricter chat model via TWIN_LLM_MODEL)",
        ))
        return nexts
    if "unavailable" in details or report.deferred_stages():
        nexts.append((
            "→",
            "twin doctor   # confirm Ollama/chat model loads; then re-run",
        ))
    return nexts


def cmd_correlate(args) -> None:
    from . import ux
    from ..cognition.episode_pipeline import (
        STAGE_ORDER,
        BrainStage,
        run_episode_cognition,
    )

    ws = Workspace(args.home)
    mode = getattr(args, "mode", "full")
    until = getattr(args, "until", "cortex") or "cortex"
    try:
        until_stage = BrainStage(until)
    except ValueError:
        raise SystemExit(
            f"unknown --until stage '{until}'. choose one of: "
            + ", ".join(s.value for s in STAGE_ORDER
                        if s != BrainStage.hippocampus_consolidate
                        and s != BrainStage.prefrontal)
        )
    chain = " → ".join(
        s.value for s in STAGE_ORDER
        if STAGE_ORDER.index(s) <= STAGE_ORDER.index(until_stage)
    )
    with _work_spinner(args, f"correlating ({mode}) · sensory→{until}…"):
        report = run_episode_cognition(
            ws.store, ws.cfg, ws.embedder,
            connector_ids=args.connector or None,
            detect_conflicts=not args.no_conflicts,
            mode=mode,
            until=until_stage,
        )
    corr = report.correlation
    data = dict(report.to_dict())
    data["records_scanned"] = corr.records_scanned if corr else 0

    def pretty():
        ux.print_rule(f"correlate · {mode}")
        ux.print_dim(f"stages: {chain}")
        ux.print_kv(_stage_status_line(report))
        if report.episode_ids:
            rows = []
            for eid in report.episode_ids[:40]:
                ep = ws.store.get_work_episode(eid)
                if ep is None:
                    continue
                n_phases = len(ws.store.list_episode_phases(ep.id))
                n_edges = len(ws.store.list_episode_edges(ep.id))
                cons = "ready" if n_phases >= 2 else "—"
                rows.append([
                    ep.id,
                    getattr(ep.status, "value", ep.status),
                    _clip(ep.vault_id or "—", 16),
                    str(n_phases),
                    str(n_edges),
                    cons,
                    _clip(ep.title or "", 32),
                ])
            ux.print_table(
                ["id", "status", "vault", "ph", "ed", "consolidate", "title"],
                rows,
            )
            if len(report.episode_ids) > 40:
                ux.print_dim(f"… {len(report.episode_ids) - 40} more episode(s)")
        elif mode == "incremental" and data["records_scanned"] == 0:
            ux.print_dim("nothing dirty — incremental pass was a no-op")
        else:
            ux.print_warn("no episodes touched this pass")

        nexts = _cognition_next_steps(report)
        if not nexts:
            if until_stage != BrainStage.cortex and \
                    STAGE_ORDER.index(until_stage) < STAGE_ORDER.index(BrainStage.cortex):
                nexts.append(("→", "twin correlate   # continue to cortex "
                                   "(phases + edges)"))
            else:
                nexts.append(("→", "twin episode list"))
                nexts.append(("→", "twin meditate    # reflect → review → judgment"))
        ux.print_next(nexts)

    _emit(args, data, pretty)


def cmd_meditate(args) -> None:
    """Orchestrate the cognition chain up to the human gates.

    sensory → amygdala → basal → hippocampus_bind → cortex →
    hippocampus_consolidate → [optional review] → prefrontal (drafts only).
    Never auto-confirms Memory nor auto-approves Judgment.

    Twin v2: prefer ``twin cognize``; this path respects LLM-or-halt.
    """
    import os
    import sys

    from . import ux
    from ..cognition.episode_pipeline import BrainStage, run_episode_cognition
    from ..cognize.gate import require_chat_llm

    ws = Workspace(args.home)
    gate = require_chat_llm(
        extractor=ws.cfg.extractor,
        chat_provider=ws.cfg.normalized_llm_provider,
        allow_echo_cognition=os.environ.get("TWIN_ALLOW_ECHO_COGNITION", "") == "1",
    )
    if gate.halted:
        ux.print_rule("meditate")
        ux.print_warn(
            f"Cognize halted: {gate.halt_reason.value if gate.halt_reason else 'unknown'}"
            f" — {gate.detail}"
        )
        if getattr(args, "json", False):
            _emit(args, {
                "ok": False,
                "halted": True,
                "halt_reason": gate.halt_reason.value if gate.halt_reason else None,
                "detail": gate.detail,
            }, None)
        return

    mode = getattr(args, "mode", "full")
    no_reflect = bool(getattr(args, "no_reflect", False))
    no_propose = bool(getattr(args, "no_propose", False))
    dry = bool(getattr(args, "dry_run", False))
    limit = int(getattr(args, "limit", 50) or 50)
    want_review = bool(getattr(args, "review", False))

    # Stop the automated pass before prefrontal so a human review can slot in
    # between consolidation and judgment drafting.
    stop = BrainStage.cortex if no_reflect else BrainStage.hippocampus_consolidate
    with _work_spinner(args, f"meditating ({mode}) · sensory→{stop.value}…"):
        report = run_episode_cognition(
            ws.store, ws.cfg, ws.embedder,
            connector_ids=getattr(args, "connector", None) or None,
            detect_conflicts=not getattr(args, "no_conflicts", False),
            mode=mode, until=stop, reflect_limit=limit, dry_run=dry,
        )

    review_ran = False
    is_tty = getattr(sys.stdin, "isatty", lambda: False)() and not getattr(args, "json", False)
    if want_review and report.candidate_ids and not dry and is_tty:
        shim = argparse.Namespace(
            home=args.home, analyze=False, conflicts=False,
            project=None, priority=None, json=False,
        )
        try:
            cmd_review(shim)
            review_ran = True
        except SystemExit:
            pass

    # prefrontal: draft judgment proposals from now-confirmed trajectories.
    proposal_ids: list[str] = []
    if not no_reflect and not no_propose and not dry:
        from ..judgment.proposals import propose_from_episode

        for eid in report.episode_ids:
            try:
                proposal = propose_from_episode(ws.store, eid)
            except Exception:
                continue
            if proposal is not None:
                proposal_ids.append(proposal.id)
        report.proposal_ids = proposal_ids
        pre = report.stage(BrainStage.prefrontal)
        from ..cognition.episode_pipeline import StageStatus as _SS
        pre.status = _SS.ok
        pre.detail = "drafts from confirmed trajectories"
        if proposal_ids:
            pre.counts["proposals"] = len(proposal_ids)

    data = dict(report.to_dict())
    data["review_ran"] = review_ran

    def pretty():
        ux.print_rule(f"meditate · {mode}")
        chain = "sensory → amygdala → basal → hippocampus_bind → cortex"
        if not no_reflect:
            chain += " → hippocampus_consolidate"
        if not no_reflect and not no_propose:
            chain += " → prefrontal"
        ux.print_dim(f"stages: {chain}")
        ux.print_kv(_stage_status_line(report))
        ux.print_kv([
            ("episodes", str(len(report.episode_ids))),
            ("candidates", str(len(report.candidate_ids))),
            ("proposals", str(len(report.proposal_ids))),
        ])
        if report.candidate_ids:
            ux.print_dim("new trajectory candidate(s): "
                         + ", ".join(report.candidate_ids[:6])
                         + (" …" if len(report.candidate_ids) > 6 else ""))
        if report.proposal_ids:
            ux.print_dim("judgment draft(s): " + ", ".join(report.proposal_ids[:6]))

        nexts = _cognition_next_steps(report)
        if not nexts:
            if report.candidate_ids and not review_ran:
                nexts.append(("→", "twin review      # confirm trajectory candidates"))
            if report.proposal_ids:
                nexts.append(("→", "twin judgment preview <proposal_id>"))
            if not report.candidate_ids and not report.proposal_ids:
                nexts.append(("→", "twin episode list"))
        ux.print_next(nexts)

    _emit(args, data, pretty)


def cmd_episode(args) -> None:
    from . import ux

    ws = Workspace(args.home)
    cmd = args.episode_command

    def _status(ep) -> str:
        return getattr(ep.status, "value", ep.status)

    def _require(episode_id: str):
        ep = ws.store.get_work_episode(episode_id)
        if ep is None:
            raise SystemExit(f"episode {episode_id} not found")
        return ep

    def _reflect_ready(n_phases: int, edges=None) -> bool:
        # Ready once the cortex stage produced an arc (≥2 phases). The reflect
        # (hippocampus_consolidate) LLM decides whether that arc yields a claim.
        return n_phases >= 2

    if cmd == "list":
        eps = ws.store.list_work_episodes(
            vault_id=getattr(args, "vault", None),
            limit=args.limit,
        )
        rows = []
        for ep in eps:
            phases = ws.store.list_episode_phases(ep.id)
            edges = ws.store.list_episode_edges(ep.id)
            ready = _reflect_ready(len(phases), edges)
            rows.append({
                "id": ep.id,
                "status": _status(ep),
                "vault_id": ep.vault_id or "",
                "confidence": round(float(ep.confidence or 0), 2),
                "phases": len(phases),
                "edges": len(edges),
                "reflect": "ready" if ready else "—",
                "refs": len(ep.source_refs or []),
                "title": ep.title or "",
                "started_at": ep.started_at or "",
                "ended_at": ep.ended_at or "",
            })

        def pretty():
            ux.print_rule("episode · list")
            if not rows:
                ux.print_warn("no episodes — run twin correlate after connector sync")
                ux.print_next([("→", "twin correlate")])
                return
            for r in rows:
                print(
                    f"  {r['id']}  [{r['status']}]  "
                    f"ph={r['phases']} ed={r['edges']}  reflect={r['reflect']}"
                )
                if r["title"]:
                    ux.print_dim(f"    {_clip(r['title'], 72)}")
            ready_n = sum(1 for r in rows if r["reflect"] == "ready")
            if ready_n:
                ux.print_dim(f"{ready_n} consolidate-ready (cortex built ≥2 phases)")
            else:
                ux.print_dim(
                    "none consolidate-ready — run twin correlate so the cortex "
                    "stage (LLM) builds phases; deferred if the model is down"
                )
            ux.print_next([
                ("→", "twin episode show <id>"),
                ("→", "twin meditate                # reflect ready episodes"),
            ])

        _emit(args, {"episodes": rows, "count": len(rows)}, pretty)

    elif cmd == "show":
        ep = _require(args.episode_id)
        phases = ws.store.list_episode_phases(ep.id)
        edges = ws.store.list_episode_edges(ep.id)
        links = ws.store.list_episode_links(ep.id)
        active_links = [
            lk for lk in links
            if getattr(lk.status, "value", lk.status) == "active"
        ]
        data = {
            "id": ep.id,
            "title": ep.title,
            "status": _status(ep),
            "vault_id": ep.vault_id,
            "project_id": ep.project_id,
            "confidence": ep.confidence,
            "correlation_key": ep.correlation_key,
            "independence_group": ep.independence_group,
            "started_at": ep.started_at,
            "ended_at": ep.ended_at,
            "participants": list(ep.participant_actor_ids or []),
            "source_refs": list(ep.source_refs or []),
            "phases": [
                {
                    "order": ph.order,
                    "kind": getattr(ph.kind, "value", ph.kind),
                    "started_at": ph.started_at,
                    "ended_at": ph.ended_at,
                    "summary": ph.summary,
                    "members": list(ph.member_external_refs or []),
                }
                for ph in phases
            ],
            "edges": [
                {
                    "id": ed.id,
                    "relation": getattr(ed.relation, "value", ed.relation),
                    "status": getattr(ed.status, "value", ed.status),
                    "from": ed.from_ref,
                    "to": ed.to_ref,
                    "confidence": ed.confidence,
                    "evidence_quote": ed.evidence_quote,
                }
                for ed in edges
            ],
            "active_links": len(active_links),
        }

        def pretty():
            ux.print_rule(f"episode · {ep.id}")
            ux.print_kv([
                ("title", ep.title or "—"),
                ("status", _status(ep)),
                ("vault", ep.vault_id or "—"),
                ("project", ep.project_id or "—"),
                ("confidence", f"{ep.confidence:.2f}"),
                ("span", f"{ep.started_at or '?'} → {ep.ended_at or '?'}"),
                ("participants",
                 ", ".join(ep.participant_actor_ids) or "—"),
                ("active links", str(len(active_links))),
            ])
            if phases:
                ux.print_table(
                    ["#", "kind", "from", "to", "summary"],
                    [[
                        ph.order,
                        getattr(ph.kind, "value", ph.kind),
                        (ph.started_at or "?")[:16],
                        (ph.ended_at or "?")[:16],
                        _clip(ph.summary or "", 44),
                    ] for ph in phases],
                )
            else:
                ux.print_warn(
                    "no phases — the cortex stage (LLM) builds them; "
                    "run twin correlate (deferred if the model is down)"
                )
            if edges:
                ux.print_table(
                    ["id", "relation", "status", "from → to"],
                    [[
                        ed.id,
                        getattr(ed.relation, "value", ed.relation),
                        getattr(ed.status, "value", ed.status),
                        _clip(
                            f"{ed.from_ref.get('id')} → {ed.to_ref.get('id')}",
                            36,
                        ),
                    ] for ed in edges],
                )
            ready = _reflect_ready(len(phases), edges)
            nexts = []
            if ready:
                nexts.append(("→", f"twin episode reflect {ep.id}"))
            else:
                nexts.append((
                    "→",
                    "no arc yet — run twin correlate so cortex builds phases",
                ))
            if edges:
                nexts.append(("→", "twin episode confirm-edge <edge_id>  "
                                   "# survives cortex rebuild"))
            nexts.append(("→", f"twin episode explain {ep.id}"))
            ux.print_next(nexts)

        _emit(args, data, pretty)

    elif cmd == "phases":
        ep = _require(args.episode_id)
        phases = ws.store.list_episode_phases(ep.id)
        rows = [
            {
                "order": ph.order,
                "kind": getattr(ph.kind, "value", ph.kind),
                "started_at": ph.started_at,
                "ended_at": ph.ended_at,
                "confidence": ph.confidence,
                "summary": ph.summary,
                "members": list(ph.member_external_refs or []),
                "phase_key": ph.phase_key,
                "id": ph.id,
            }
            for ph in phases
        ]

        def pretty():
            ux.print_rule(f"episode phases · {ep.id}")
            if not rows:
                ux.print_warn("no phases — run twin correlate first")
                ux.print_next([("→", "twin correlate")])
                return
            for r in rows:
                ux.print_kv([
                    (f"#{r['order']} {r['kind']}",
                     f"{r['started_at'] or '?'} → {r['ended_at'] or '?'}"),
                    ("summary", r["summary"] or "—"),
                    ("members", ", ".join(r["members"]) or "—"),
                ])
            ux.print_next([
                ("→", f"twin episode edges {ep.id}"),
                ("→", f"twin episode reflect {ep.id}"),
            ])

        _emit(args, {"episode_id": ep.id, "phases": rows, "count": len(rows)},
              pretty)

    elif cmd == "edges":
        ep = _require(args.episode_id)
        edges = ws.store.list_episode_edges(ep.id)
        rows = [
            {
                "id": ed.id,
                "relation": getattr(ed.relation, "value", ed.relation),
                "status": getattr(ed.status, "value", ed.status),
                "from": ed.from_ref.get("id"),
                "to": ed.to_ref.get("id"),
                "confidence": ed.confidence,
                "evidence_quote": ed.evidence_quote,
            }
            for ed in edges
        ]

        def pretty():
            ux.print_rule(f"episode edges · {ep.id}")
            if not rows:
                ux.print_warn("no edges — run twin correlate first")
                ux.print_next([("→", "twin correlate")])
                return
            ux.print_table(
                ["id", "relation", "status", "conf", "from → to"],
                [[
                    r["id"], r["relation"], r["status"],
                    f"{r['confidence']:.2f}",
                    _clip(f"{r['from']} → {r['to']}", 36),
                ] for r in rows],
            )
            for r in rows:
                if r.get("evidence_quote"):
                    ux.print_dim(f"  {r['id']}: “{_clip(r['evidence_quote'], 90)}”")
            nexts = [
                ("→", "twin episode confirm-edge <edge_id>"),
                ("→", "twin episode reject-edge <edge_id>"),
            ]
            if _reflect_ready(len(ws.store.list_episode_phases(ep.id))):
                nexts.append(("→", f"twin episode reflect {ep.id}"))
            ux.print_next(nexts)

        _emit(args, {"episode_id": ep.id, "edges": rows, "count": len(rows)},
              pretty)

    elif cmd in ("confirm-edge", "reject-edge"):
        from ..cognition.correlation.edges import confirm_edge, reject_edge

        action = "confirm" if cmd == "confirm-edge" else "reject"
        ed = (confirm_edge if action == "confirm" else reject_edge)(
            ws.store, args.edge_id,
        )
        data = {
            "id": ed.id,
            "status": getattr(ed.status, "value", ed.status),
            "relation": getattr(ed.relation, "value", ed.relation),
            "episode_id": ed.episode_id,
        }

        def pretty():
            ux.print_rule(f"episode · {action}-edge")
            ux.print_ok(f"{ed.id} → {data['status']}")
            ux.print_kv([
                ("relation", data["relation"]),
                ("episode", ed.episode_id),
            ])
            ux.print_next([
                ("→", f"twin episode edges {ed.episode_id}"),
                ("→", f"twin episode reflect {ed.episode_id}"),
            ])

        _emit(args, data, pretty)

    elif cmd == "reflect":
        from ..cognition.episode_reflect import reflect_episode

        ep = _require(args.episode_id)
        dry = bool(args.dry_run)
        with _work_spinner(args, f"reflecting episode {ep.id}…"):
            result = reflect_episode(
                ws.store, ws.cfg, ws.embedder, ep.id, dry_run=dry,
            )
        data = {
            "episode_id": ep.id,
            "dry_run": dry,
            "claims": result.claims,
            "skipped_reason": result.skipped_reason,
            "count": len(result.claims),
        }

        def pretty():
            ux.print_rule(f"hippocampus_consolidate · {ep.id}")
            if result.skipped_reason and not result.claims:
                ux.print_warn(result.skipped_reason)
                low = result.skipped_reason.lower()
                if "model failed" in low:
                    ux.print_next([
                        ("→", "twin doctor      # check the analysis model / key / endpoint"),
                        ("→", "twin usage       # the failed call is logged (ok=false)"),
                        ("→", f"twin episode reflect {ep.id}   # retry after fixing config"),
                    ])
                elif "deferred" in low or "unavailable" in low:
                    ux.print_next([
                        ("→", "twin interpret   # model unreachable; "
                              "start Ollama / configure a chat client"),
                        ("→", f"twin episode reflect {ep.id}   # retry once it's up"),
                    ])
                else:
                    ux.print_next([
                        ("→", "twin correlate   # run cortex to build the arc"),
                        ("→", "twin episode list"),
                    ])
                return
            if dry:
                ux.print_dim("dry-run — nothing persisted")
            for claim in result.claims:
                created = claim.get("created")
                marker = "created" if created else ("dry-run" if dry else "corroborated")
                ux.print_ok(f"[{claim.get('type')}] {claim.get('title')}")
                ux.print_kv([
                    ("valid_from", claim.get("valid_from") or "—"),
                    ("action", marker),
                    ("candidate", claim.get("memory_id") or "—"),
                ])
            if result.claims and not dry:
                ux.print_next([
                    ("→", "twin review"),
                    ("→", f"twin judgment propose-episode {ep.id}  "
                          "# after confirming trajectory candidates"),
                ])

        _emit(args, data, pretty)

    elif cmd == "explain":
        from ..cognition.correlation.explain import explain_episode

        data = explain_episode(ws.store, args.episode_id)
        if data.get("error"):
            raise SystemExit(data["error"])

        def pretty():
            import json as _json
            ux.print_rule(f"episode explain · {args.episode_id}")
            ux.print_panel(
                _json.dumps(data, indent=2, default=str),
                title="anchors / links / phases / edges",
            )

        _emit(args, data, pretty)

    else:
        raise SystemExit(f"unknown episode command: {cmd}")



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
    kv = [
        ("home", str(ws.cfg.home)),
        ("db", ws.cfg.resolved_db_url),
        ("llm", f"{ws.cfg.normalized_llm_provider} @ {ws.cfg.resolved_llm_base_url}"),
        ("model", ws.cfg.resolved_llm_model),
    ]
    try:
        from datetime import datetime, timedelta, timezone

        from ..cognition.llm.usage import JsonlLedger, default_ledger_path, summarize
        _since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        _rows = JsonlLedger(default_ledger_path(ws.cfg.home)).read(since=_since)
        if _rows:
            _t = summarize(_rows)["totals"]
            _c = _t["cost_usd"]
            _cost = "$0" if _c == 0 else (f"${_c:.4f}" if _c < 0.01 else f"${_c:.2f}")
            kv.append(("spend 7d", f"{_cost} · {_t['calls']} calls "
                                   f"({_t['total_tokens']:,} tok) — twin usage"))
    except Exception:
        pass
    ux.print_kv(kv)
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


def _fmt_tokens(n: int) -> str:
    n = int(n or 0)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def _fmt_cost(v: float) -> str:
    v = float(v or 0.0)
    if v == 0:
        return "$0"
    if v < 0.01:
        return f"${v:.4f}"
    return f"${v:.2f}"


def cmd_usage(args) -> None:
    from datetime import datetime, timedelta, timezone

    from . import ux
    from ..cognition.llm.usage import JsonlLedger, default_ledger_path, summarize

    ws = Workspace(args.home)
    ledger = JsonlLedger(default_ledger_path(ws.cfg.home))

    since = getattr(args, "since", None)
    days = getattr(args, "days", None)
    if not since and days:
        since = (datetime.now(timezone.utc) - timedelta(days=int(days))).isoformat()
    rows = ledger.read(since=since)
    stage_filter = getattr(args, "stage", None)
    if stage_filter:
        rows = [r for r in rows if r.get("stage") == stage_filter]

    sub = getattr(args, "usage_command", None) or "summary"

    if sub == "log":
        limit = int(getattr(args, "limit", 20) or 20)
        recent = rows[-limit:][::-1]

        def pretty_log():
            ux.print_rule("usage · recent calls")
            if not recent:
                ux.print_warn("no usage recorded yet")
                return
            ux.print_table(
                ["when", "stage", "role", "model", "in", "out", "cost", "ms", "ok"],
                [[
                    (r.get("at") or "")[5:16].replace("T", " "),
                    str(r.get("stage") or "—"),
                    str(r.get("role") or "—"),
                    str(r.get("model") or "—")[:24],
                    _fmt_tokens(r.get("input_tokens")),
                    _fmt_tokens(r.get("output_tokens")),
                    _fmt_cost(r.get("cost_usd")),
                    str(r.get("latency_ms") or 0),
                    "✓" if r.get("ok", True) else "✗",
                ] for r in recent],
            )

        _emit(args, {"calls": recent, "count": len(recent)}, pretty_log)
        return

    report = summarize(rows)

    def pretty():
        span = f"since {since[:10]}" if since else "all time"
        ux.print_rule(f"usage · {span}")
        t = report["totals"]
        if not rows:
            ux.print_warn("no usage recorded yet — any model call (extract, "
                          "observe, correlate, meditate, reflect, pattern, cloud "
                          "embeddings) is recorded here automatically")
            ux.print_dim(f"ledger: {default_ledger_path(ws.cfg.home)}")
            return
        ux.print_kv([
            ("calls", f"{t['calls']}  ({t['errors']} failed)"),
            ("tokens in / out", f"{_fmt_tokens(t['input_tokens'])} / "
                                f"{_fmt_tokens(t['output_tokens'])}"),
            ("tokens total", _fmt_tokens(t["total_tokens"])),
            ("est. cost", _fmt_cost(t["cost_usd"])),
            ("avg latency", f"{t['avg_latency_ms']} ms"),
        ])
        if t["unpriced_calls"]:
            ux.print_warn(
                f"{t['unpriced_calls']} cloud call(s) had no price in the table — "
                f"cost is understated. Add prices in {ws.cfg.home / 'pricing.json'}"
            )

        def _bucket_table(title: str, bucket: dict, key_label: str):
            if not bucket:
                return
            ux.print_rule(title)
            ordered = sorted(
                bucket.items(), key=lambda kv: kv[1]["cost_usd"], reverse=True,
            )
            ux.print_table(
                [key_label, "calls", "in", "out", "cost"],
                [[
                    k,
                    str(v["calls"]),
                    _fmt_tokens(v["input_tokens"]),
                    _fmt_tokens(v["output_tokens"]),
                    _fmt_cost(v["cost_usd"]),
                ] for k, v in ordered],
            )

        _bucket_table("by stage (where it was spent)", report["by_stage"], "stage")
        _bucket_table("by model", report["by_model"], "model")
        _bucket_table("hot-path vs analysis", report["by_role"], "role")

        # last 14 active days
        by_day = report["by_day"]
        if by_day:
            ux.print_rule("by day")
            recent_days = sorted(by_day.items())[-14:]
            ux.print_table(
                ["day", "calls", "tokens", "cost"],
                [[
                    k, str(v["calls"]), _fmt_tokens(v["total_tokens"]),
                    _fmt_cost(v["cost_usd"]),
                ] for k, v in recent_days],
            )
        ux.print_dim(f"ledger: {default_ledger_path(ws.cfg.home)}")

    _emit(args, report, pretty)


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


def cmd_cognize(args) -> None:
    from . import ux
    from .commands import cognize_cmd

    ws = Workspace(args.home)
    sub = getattr(args, "cognize_command", None) or "run"
    if sub == "status":
        data = cognize_cmd.cognize_status(ws, args)
    else:
        data = cognize_cmd.cognize_run(ws, args)
    if getattr(args, "json", False):
        _emit(args, data, None)
        return
    ux.print_rule("cognize")
    if data.get("halted"):
        ux.print_warn(f"halted: {data.get('halt_reason')} — {data.get('detail')}")
        return
    if sub == "status":
        ux.print_ok(
            f"pending={data.get('pending_percepts')} open_reflections={data.get('open_reflections')} "
            f"llm={data.get('llm_reachable')} gate_ok={data.get('gate_ok')}"
        )
        if data.get("halt_reason"):
            ux.print_dim(f"{data.get('halt_reason')}: {data.get('detail')}")
        return
    for st in data.get("stages") or []:
        print(f"  {st.get('stage')}: {st.get('status')} {st.get('counts')}")
    ux.print_ok(
        f"situations={len(data.get('situation_ids') or [])} "
        f"reflections={len(data.get('reflection_ids') or [])} "
        f"interpretations={len(data.get('interpretation_ids') or [])}"
    )


def cmd_narrative(args) -> None:
    from . import ux
    from .commands import cognize_cmd

    ws = Workspace(args.home)
    sub = getattr(args, "narrative_command", None)
    if sub == "show":
        data = cognize_cmd.narrative_show(ws, args)
    elif sub == "commit":
        data = cognize_cmd.narrative_commit(ws, args)
    elif sub == "backfill":
        data = cognize_cmd.narrative_backfill(ws, args)
    else:
        data = cognize_cmd.narrative_search(ws, args)
    if getattr(args, "json", False):
        _emit(args, data, None)
        return
    ux.print_rule("narrative")
    if not data.get("ok", True) and data.get("error"):
        ux.print_warn(str(data.get("error")))
        return
    print(data)


def cmd_stance(args) -> None:
    from . import ux
    from .commands import cognize_cmd

    ws = Workspace(args.home)
    data = cognize_cmd.stance_list(ws, args)
    if getattr(args, "json", False):
        _emit(args, data, None)
        return
    ux.print_rule("stance")
    ux.print_ok(f"{data.get('count', 0)} stance(s)")
    for s in data.get("stances") or []:
        print(f"  [{s.get('status')}] {s.get('kind')}: {s.get('statement')[:120]}")


def cmd_inject(args) -> None:
    from . import ux
    from .commands import cognize_cmd

    ws = Workspace(args.home)
    data = cognize_cmd.inject_pack(ws, args)
    if getattr(args, "json", False):
        _emit(args, data, None)
        return
    ux.print_rule("inject pack")
    print(data.get("context_pack") or "")
    n = len(data.get("narratives") or [])
    r = len(data.get("open_reflections") or [])
    ux.print_dim(f"narratives={n} open_reflections={r}")


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

    pi = sub.add_parser("interpret", help="cognitive interpretation status ")
    pis = pi.add_subparsers(dest="interpret_command", required=True)
    pistatus = pis.add_parser("status", help="counts by interpretation status")
    pistatus.set_defaults(func=cmd_interpret)
    pisd = pis.add_parser("deferred", help="percepts awaiting a cognitive interpreter")
    pisd.set_defaults(func=cmd_interpret)
    pisig = pis.add_parser("signals", help="heuristic detection hints (never memories)")
    pisig.set_defaults(func=cmd_interpret)
    _add_json_flag_tree(pi)

    p = sub.add_parser("review", help="interactive priority review queue")
    p.add_argument("--priority", choices=["high"], default=None)
    p.add_argument("--project", default=None)
    p.add_argument("--conflicts", action="store_true")
    p.add_argument("--analyze", action="store_true", help="run quality analyzer on candidates")
    _add_json_flag(p)
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
    _add_json_flag_tree(p)

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
    _add_json_flag_tree(p)

    p = sub.add_parser("eval", help="run extraction/retrieval benchmarks")
    es = p.add_subparsers(dest="eval_command", required=True)
    es.add_parser("extraction").set_defaults(func=cmd_eval)
    es.add_parser("retrieval").set_defaults(func=cmd_eval)
    es.add_parser("golden", help="run golden cognitive work-loop scenario"
                  ).set_defaults(func=cmd_eval)
    es.add_parser("compare").set_defaults(func=cmd_eval)
    _add_json_flag_tree(p)

    p = sub.add_parser("source", help="show source calibration")
    p.add_argument("source", nargs="?", default="all")
    _add_json_flag(p)
    p.set_defaults(func=cmd_source)

    p = sub.add_parser("retention", help="apply retention policies")
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--apply", action="store_true")
    _add_json_flag(p)
    p.set_defaults(func=cmd_retention)

    p = sub.add_parser("delete-source", help="propagate deletion from a source system")
    p.add_argument("source_system")
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--apply", action="store_true")
    _add_json_flag(p)
    p.set_defaults(func=cmd_delete_source)

    p = sub.add_parser("undo", help="undo a recorded memory operation")
    p.add_argument("operation_id")
    _add_json_flag(p)
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
    _add_json_flag(p)
    p.set_defaults(func=cmd_observe)

    p = sub.add_parser("workspace", help="parallel memory workspace ")
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
    _add_json_flag_tree(p)

    p = sub.add_parser("consolidate", help="daily/weekly consolidation cycle ")
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
    _add_json_flag_tree(p)

    p = sub.add_parser("runtime", help="durable cognitive runtime (v1.0)")
    rs = p.add_subparsers(dest="runtime_command", required=True)
    rst = rs.add_parser("start", help="run scheduler + workers (twin-runtime)")
    rst.add_argument("--workers", type=int, default=2)
    rst.add_argument("--vault", default=None, help="isolate worker to one vault")
    rst.add_argument("--lease", type=int, default=60, help="lease seconds")
    rst.add_argument("--schedule-interval", type=float, default=30.0)
    rst.add_argument("--offline", action="store_true",
                     help="scheduler only; do not claim jobs")
    rst.add_argument(
        "--no-live", action="store_true",
        help="disable live processing panel (logs only)",
    )
    rst.set_defaults(func=cmd_runtime)
    rstat = rs.add_parser(
        "status", help="queue depth + failed / dead-letter / recent jobs",
    )
    rstat.add_argument(
        "--limit", type=int, default=20,
        help="max rows per section (failed / dead-letter / recent)",
    )
    rstat.set_defaults(func=cmd_runtime)
    rs.add_parser("schedule", help="enqueue due temporal jobs once").set_defaults(
        func=cmd_runtime,
    )
    re = rs.add_parser("enqueue", help="enqueue a job")
    re.add_argument("kind", choices=[
        "interpret_percept", "workspace_tick", "attention_evaluate",
        "consolidate_daily", "consolidate_weekly", "reembed_memory",
        "integrity_check", "connector_reconcile", "backfill_partition",
        "session_domain_resolve", "session_complete",
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
    _add_json_flag_tree(p)

    preidx = sub.add_parser("reindex", help="regenerate embeddings")
    _add_json_flag(preidx)
    preidx.set_defaults(func=cmd_reindex)

    p = sub.add_parser("promote", help="propose promoting a memory into judgment")
    p.add_argument("memory_id")
    _add_json_flag(p)
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
    ppe = js.add_parser(
        "propose-episode",
        help="seed a judgment proposal from an episode's confirmed trajectory",
    )
    ppe.add_argument("episode_id")
    ppe.add_argument("--domain", default=None)
    ppe.set_defaults(func=cmd_judgment)
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
    _add_json_flag_tree(p)

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

    p = sub.add_parser("connector", help="professional connectors ")
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
                           help="list repositories the token can reach; "
                                "--select picks them as the sync scope")
    cghr.add_argument("connector_id")
    cghr.add_argument("--select", nargs="+", metavar="OWNER/NAME",
                      help="set the repositories to sync (owner/name …)")
    cghr.set_defaults(func=cmd_connector)
    csl = cs.add_parser("slack", help="slack-specific helpers")
    csls = csl.add_subparsers(dest="slack_command", required=True)
    cslc = csls.add_parser("channels",
                           help="list channels; --select picks them as the scope")
    cslc.add_argument("connector_id")
    cslc.add_argument("--select", nargs="+", metavar="CHANNEL_ID",
                      help="set the channels to sync (channel ids)")
    cslc.set_defaults(func=cmd_connector)
    cgm = cs.add_parser("gmail", help="gmail-specific helpers")
    cgms = cgm.add_subparsers(dest="gmail_command", required=True)
    cgml = cgms.add_parser("labels",
                           help="list labels; --select picks them as the scope")
    cgml.add_argument("connector_id")
    cgml.add_argument("--select", nargs="+", metavar="LABEL_ID",
                      help="set the labels to sync (label ids)")
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
                        help="preview / create / watch partitionable BackfillJob")
    cbf.add_argument("connector_id", nargs="?", default=None)
    cbf.add_argument("--preview", action="store_true")
    cbf.add_argument("--create", action="store_true",
                     help="create a year-month BackfillJob (no ingest)")
    cbf.add_argument("--cancel", action="store_true",
                     help="cancel a BackfillJob (requires --job-id); frees you "
                          "to --create a fresh one, e.g. to re-anchor its floor")
    cbf.add_argument("--jobs", action="store_true",
                     help="list BackfillJobs for the connector")
    cbf.add_argument("--run", action="store_true",
                     help="enqueue + watch runtime drain all partitions "
                          "(requires twin runtime start; does not ingest in-CLI)")
    cbf.add_argument("--run-partition", dest="run_partition",
                     action="store_true",
                     help="debug: advance one partition in-process; requires --job-id")
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
    csetup.add_argument("--connector-id", default=None,
                        help="reflect a specific connector's setup progress")
    csetup.set_defaults(func=cmd_connector)
    cs.add_parser("due", help="list connectors the local scheduler would run now"
                  ).set_defaults(func=cmd_connector)
    csyncdue = cs.add_parser("sync-due", help="run one scheduler pass over due connectors")
    csyncdue.add_argument("--no-percepts", action="store_true")
    csyncdue.set_defaults(func=cmd_connector)
    cs.add_parser("contract", help="print adapter contract matrix"
                  ).set_defaults(func=cmd_connector)
    cs.add_parser(
        "production-ready",
        help="report which real adapters meet the production-ready contract",
    ).set_defaults(func=cmd_connector)
    # every connector command is human-pretty by default with --json for scripts
    _add_json_flag_tree(p)

    p = sub.add_parser("supersede", help="mark a memory as superseding another")
    p.add_argument("new_id")
    p.add_argument("old_id")
    _add_json_flag(p)
    p.set_defaults(func=cmd_supersede)

    p = sub.add_parser("contradict", help="flag two memories as contradictory")
    p.add_argument("id_a")
    p.add_argument("id_b")
    _add_json_flag(p)
    p.set_defaults(func=cmd_contradict)

    pstats = sub.add_parser("stats", help="memory quality metrics")
    _add_json_flag(pstats)
    pstats.set_defaults(func=cmd_stats)

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
        help="cognition: sensory scaffold → amygdala → basal → hippocampus_bind "
             "→ cortex (phases + edges). Needs an interpreting extractor.",
    )
    p.add_argument("--connector", action="append",
                   help="limit to connector instance id (repeatable)")
    p.add_argument("--no-conflicts", action="store_true")
    p.add_argument(
        "--until", default="cortex",
        choices=["sensory", "amygdala", "basal", "hippocampus_bind", "cortex"],
        help="stop after this brain stage (default: cortex). "
             "--until sensory = structural scaffold only (debug).",
    )
    mode_grp = p.add_mutually_exclusive_group()
    mode_grp.add_argument(
        "--full", dest="mode", action="store_const", const="full",
        help="full rebuild (correctness oracle; default)",
    )
    mode_grp.add_argument(
        "--incremental", dest="mode", action="store_const", const="incremental",
        help="only re-correlate records marked dirty since last pass",
    )
    p.set_defaults(func=cmd_correlate, mode="full")
    _add_json_flag(p)

    p = sub.add_parser(
        "meditate",
        help="orchestrate the full cognition chain up to the human gates: "
             "correlate → reflect → (review) → judgment drafts. Never "
             "auto-confirms Memory or auto-approves Judgment.",
    )
    p.add_argument("--connector", action="append",
                   help="limit to connector instance id (repeatable)")
    p.add_argument("--no-conflicts", action="store_true")
    p.add_argument("--no-reflect", action="store_true",
                   help="stop after cortex (skip hippocampus_consolidate)")
    p.add_argument("--no-propose", action="store_true",
                   help="skip prefrontal judgment drafting")
    p.add_argument("--review", action="store_true",
                   help="step through the review queue between consolidate and "
                        "prefrontal (interactive TTY only)")
    p.add_argument("--limit", type=int, default=50,
                   help="max episodes to reflect this pass (default: 50)")
    p.add_argument("--dry-run", action="store_true",
                   help="reflect without persisting candidates")
    mmode = p.add_mutually_exclusive_group()
    mmode.add_argument("--full", dest="mode", action="store_const", const="full",
                       help="full rebuild (default)")
    mmode.add_argument("--incremental", dest="mode", action="store_const",
                       const="incremental",
                       help="only re-correlate dirty records (day-to-day path)")
    p.set_defaults(func=cmd_meditate, mode="full")
    _add_json_flag(p)

    p = sub.add_parser(
        "episode",
        help="inspect WorkEpisodes, phases/edges, and reflect trajectory candidates",
    )
    ep_sub = p.add_subparsers(dest="episode_command", required=True)
    ep = ep_sub.add_parser(
        "list", help="list episodes (run twin correlate first after sync)",
    )
    ep.add_argument("--limit", type=int, default=50)
    ep.add_argument("--vault", default=None, help="filter by vault id")
    ep.set_defaults(func=cmd_episode)
    ep = ep_sub.add_parser("show", help="episode summary + phases + edges")
    ep.add_argument("episode_id")
    ep.set_defaults(func=cmd_episode)
    ep = ep_sub.add_parser(
        "phases", help="goal → decision → execution → outcome arc",
    )
    ep.add_argument("episode_id")
    ep.set_defaults(func=cmd_episode)
    ep = ep_sub.add_parser(
        "edges", help="causal/narrative edges (motivated, superseded, …)",
    )
    ep.add_argument("episode_id")
    ep.set_defaults(func=cmd_episode)
    ep = ep_sub.add_parser(
        "confirm-edge", help="confirm a narrative edge (survives rebuilds)",
    )
    ep.add_argument("edge_id")
    ep.set_defaults(func=cmd_episode)
    ep = ep_sub.add_parser(
        "reject-edge", help="reject a narrative edge (survives rebuilds)",
    )
    ep.add_argument("edge_id")
    ep.set_defaults(func=cmd_episode)
    ep = ep_sub.add_parser(
        "reflect",
        help="synthesize trajectory MemoryCandidates from the episode arc",
    )
    ep.add_argument("episode_id")
    ep.add_argument(
        "--dry-run", action="store_true",
        help="show trajectory claims without persisting candidates",
    )
    ep.set_defaults(func=cmd_episode)
    ep = ep_sub.add_parser(
        "explain", help="why this episode exists (anchors / links / phases / edges)",
    )
    ep.add_argument("episode_id")
    ep.set_defaults(func=cmd_episode)
    _add_json_flag_tree(p)

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

    p = sub.add_parser("usage", help="LLM token / cost accounting")
    us = p.add_subparsers(dest="usage_command", required=False)
    for _name, _help in (("summary", "totals + breakdowns"), ("log", "recent calls")):
        sp = us.add_parser(_name, help=_help)
        sp.add_argument("--days", type=int, default=30,
                        help="look back this many days (default 30)")
        sp.add_argument("--since", default=None, help="ISO cutoff (overrides --days)")
        sp.add_argument("--stage", default=None,
                        help="filter to one stage (interpret|observe|amygdala|"
                             "cortex|reflect|pattern|embed)")
        sp.add_argument("--limit", type=int, default=20,
                        help="rows for `log` (default 20)")
        sp.add_argument("--json", action="store_true", help="machine-readable output")
        sp.set_defaults(func=cmd_usage)
    # bare `twin usage` → summary over the default window
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--since", default=None)
    p.add_argument("--stage", default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_usage, usage_command="summary", limit=20)

    p = sub.add_parser("setup", help="bootstrap local infrastructure")
    p.add_argument("target", choices=["ollama", "postgres", "mcp"])
    p.add_argument("client", nargs="?", default=None)
    p.set_defaults(func=cmd_setup)

    sub.add_parser("mcp", help="run MCP server (stdio)").set_defaults(func=cmd_mcp)

    p = sub.add_parser(
        "native",
        help="host-native observation (Claude Code hooks)",
    )
    nat = p.add_subparsers(dest="native_command", required=True)
    ni = nat.add_parser(
        "install",
        help="write Claude Code hooks and merge into ~/.claude/settings.json",
    )
    ni.add_argument("--dir", default=None, help="snippet output directory")
    ni.add_argument("--twin-bin", default="twin")
    ni.add_argument(
        "--settings", default=None,
        help="Claude Code settings.json to merge into (default: ~/.claude/settings.json)",
    )
    ni.add_argument(
        "--no-merge", action="store_true",
        help="write snippet only; do not patch Claude Code settings",
    )
    ni.add_argument(
        "--profile", default="standard",
        choices=("minimal", "standard", "verbose"),
        help=(
            "observation profile: minimal (lifecycle only), "
            "standard (+ PostToolUse, default), verbose (+ PreToolUse)"
        ),
    )
    ni.set_defaults(func=cmd_native)
    ni = nat.add_parser(
        "uninstall",
        help="remove Twin hooks from ~/.claude/settings.json",
    )
    ni.add_argument(
        "--settings", default=None,
        help="Claude Code settings.json to clean (default: ~/.claude/settings.json)",
    )
    ni.add_argument(
        "--restore-backup", action="store_true",
        help="restore the most recent .twin-bak instead of unmerging",
    )
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

    p = sub.add_parser("backup", help="sovereignty backup create/validate/restore ")
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
    _add_json_flag_tree(p)

    pexport = sub.add_parser("export", help="export everything as JSON")
    _add_json_flag(pexport)
    pexport.set_defaults(func=cmd_export)

    # Twin v2 cognition surface
    pc = sub.add_parser("cognize", help="run Cognize pipeline (LLM-or-halt)")
    pcs = pc.add_subparsers(dest="cognize_command")
    pcr = pcs.add_parser("run", help="Salience→…→Evidence audit; never commits Narrative")
    pcr.add_argument("--until", default=None, help="stop after stage id")
    pcr.add_argument("--dry-run", action="store_true")
    pcr.add_argument("--limit", type=int, default=50)
    pcr.add_argument("--vault", default="default")
    pcr.set_defaults(func=cmd_cognize, cognize_command="run")
    pcsst = pcs.add_parser("status", help="pending percepts / halt reason")
    pcsst.add_argument("--vault", default="default")
    pcsst.set_defaults(func=cmd_cognize, cognize_command="status")
    _add_json_flag_tree(pc)
    pc.set_defaults(func=cmd_cognize, cognize_command="run")

    pn = sub.add_parser("narrative", help="search / show / commit Narratives")
    pns = pn.add_subparsers(dest="narrative_command", required=True)
    pnsr = pns.add_parser("search")
    pnsr.add_argument("query", nargs="?", default="")
    pnsr.add_argument("--vault", default="default")
    pnsr.set_defaults(func=cmd_narrative)
    pnss = pns.add_parser("show")
    pnss.add_argument("narrative_id")
    pnss.set_defaults(func=cmd_narrative)
    pnsc = pns.add_parser("commit")
    pnsc.add_argument("--account", required=True)
    pnsc.add_argument("--evidence", action="append", default=[])
    pnsc.add_argument("--evidence-id", default=None)
    pnsc.add_argument("--interpretation", action="append", default=[])
    pnsc.add_argument("--dissent", action="append", default=[])
    pnsc.add_argument("--domain", default="")
    pnsc.add_argument("--vault", default="default")
    pnsc.add_argument("--actor", default="user")
    pnsc.set_defaults(func=cmd_narrative)
    pnsb = pns.add_parser("backfill", help="dual-read migrate memories → narratives")
    pnsb.add_argument("--apply", action="store_true")
    pnsb.add_argument("--vault", default="default")
    pnsb.add_argument("--limit", type=int, default=10_000)
    pnsb.set_defaults(func=cmd_narrative)
    _add_json_flag_tree(pn)

    pst = sub.add_parser("stance", help="Stance (ex-Judgment) surface")
    psts = pst.add_subparsers(dest="stance_command")
    pstl = psts.add_parser("list")
    pstl.set_defaults(func=cmd_stance)
    pst.set_defaults(func=cmd_stance)
    _add_json_flag_tree(pst)

    pin = sub.add_parser("inject", help="Inject-facing helpers")
    pins = pin.add_subparsers(dest="inject_command", required=True)
    pinp = pins.add_parser("pack", help="context pack with EpistemicState")
    pinp.add_argument("query")
    pinp.add_argument("--domain", default="technical")
    pinp.add_argument("--max-tokens", type=int, default=1200)
    pinp.set_defaults(func=cmd_inject)
    _add_json_flag_tree(pin)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
