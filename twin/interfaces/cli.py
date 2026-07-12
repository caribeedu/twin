"""twin CLI.

    twin init                          create ~/.twin (config + default policies/judgment)
    twin ingest <paths...>             run sensors over docs/transcripts/meetings/slack exports
    twin extract                       extract memories from un-processed percepts
    twin review                        interactive review of the candidate queue
    twin search "query" [--domain d]   hybrid search
    twin pack "task" [--domain d]      build a safe context pack (confirmed only;
                                       --include-candidates to loosen)
    twin observe "current text"        memory observer suggestion
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
    twin export                        dump memories/entities/judgment as JSON
"""

from __future__ import annotations

import argparse
import json

from ..workspace import Workspace


def _print(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def cmd_init(args) -> None:
    ws = Workspace(args.home)
    print(f"initialized twin home at {ws.cfg.home}")
    print(f"  db:        {ws.cfg.resolved_db_url}")
    print(f"  policies:  {ws.cfg.policies_path}")
    print(f"  judgment:  {ws.cfg.judgment_path}")
    print(f"  embedder:  {ws.embedder.name}")


def cmd_ingest(args) -> None:
    ws = Workspace(args.home)
    new_ids, skipped = ws.ingest(args.paths)
    print(f"ingested {len(new_ids)} percept(s)")
    for s in skipped:
        print(f"  skipped: {s}")


def cmd_extract(args) -> None:
    from ..cognition import extract_pending

    ws = Workspace(args.home)
    reports = extract_pending(ws.store, ws.cfg, ws.embedder)
    if not reports:
        print("nothing to extract (all percepts already processed)")
        return
    total = sum(len(r.inserted) for r in reports)
    review = sum(r.flagged_for_review for r in reports)
    dups = sum(r.duplicates for r in reports)
    for r in reports:
        print(f"{r.percept_id}: {len(r.inserted)} memories via {r.extractor}"
              f" ({r.flagged_for_review} to review, {r.duplicates} duplicates,"
              f" {r.pii_findings} PII findings masked)")
    print(f"total: {total} new, {review} queued for review, {dups} duplicates")


def cmd_review(args) -> None:
    from ..memory.models import MemoryStatus

    ws = Workspace(args.home)
    queue = [m for m in ws.store.list_memories(status="candidate") if m.needs_review]
    if not queue:
        queue = ws.store.list_memories(status="candidate")
    if not queue:
        print("review queue is empty")
        return
    print(f"{len(queue)} memories to review. [a]pprove / [r]eject / [s]kip / [q]uit\n")
    for mem in queue:
        print(f"— {mem.type.value} · {mem.domain} · {mem.sensitivity.value} · conf {mem.confidence:.2f}")
        if mem.review_reason:
            print(f"  reason: {mem.review_reason}")
        print(f"  {mem.title}")
        if mem.summary != mem.title:
            print(f"  {mem.summary}")
        for ev in ws.store.get_evidence(mem.id)[:1]:
            print(f'  evidence: "{ev.quote[:140]}"')
        choice = input("  [a/r/s/q] > ").strip().lower()
        if choice == "a":
            ws.store.set_status(mem.id, MemoryStatus.confirmed)
        elif choice == "r":
            ws.store.set_status(mem.id, MemoryStatus.rejected)
        elif choice == "q":
            break
        print()


def cmd_search(args) -> None:
    from ..memory.search import search

    ws = Workspace(args.home)
    result = search(ws.store, ws.embedder, args.query, target_domain=args.domain,
                    firewall=ws.firewall, limit=args.limit)
    for h in result.hits:
        print(f"{h.score:.3f}  [{h.memory.type.value}] {h.memory.title}  ({h.why})")
    if result.blocked:
        print(f"\n{len(result.blocked)} memories blocked by firewall:")
        for b in result.blocked:
            print(f"  {b.memory_id}: {b.rule}")


def cmd_pack(args) -> None:
    from ..cognition.context_pack import build_context_pack

    ws = Workspace(args.home)
    pack = build_context_pack(ws.store, ws.cfg, ws.embedder, args.query,
                              target_domain=args.domain, max_tokens=args.max_tokens,
                              include_candidates=args.include_candidates,
                              firewall=ws.firewall)
    if args.json:
        _print(pack.__dict__)
    else:
        print(pack.context_pack or "(empty pack)")
        if pack.blocked:
            print(f"\n[{len(pack.blocked)} memories withheld by firewall]")


def cmd_observe(args) -> None:
    from ..cognition.observer import observe

    ws = Workspace(args.home)
    s = observe(ws.store, ws.cfg, ws.embedder, args.text, args.domain)
    _print({
        "inferred_domain": s.inferred_domain,
        "suggested_context": s.suggested_context,
        "blocked_context": s.blocked_context,
    })


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
    section = promote_memory(ws.cfg.judgment_path, mem)
    ws.store.update_memory(mem.id, payload={**mem.payload, "promoted_to_judgment": True})
    print(f"promoted {mem.id} into judgment profile section '{section}'")


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
    ses = complete_session(ws.store, ws.cfg, ws.embedder, args.session_id,
                           summary=args.summary or "", abandoned=args.abandon)
    print(f"session {ses.id} {ses.status.value}")
    if ses.created_memory_ids:
        print(f"  {len(ses.created_memory_ids)} candidate memories created"
              f" — review with: twin review")


def cmd_session_feedback(args) -> None:
    from ..cognition.sessions import record_feedback

    ws = Workspace(args.home)
    ses = record_feedback(ws.store, args.session_id, args.verdict,
                          memory_id=args.memory, note=args.note or "")
    print(f"session {ses.id}: feedback '{args.verdict}' recorded")


def cmd_project(args) -> None:
    ws = Workspace(args.home)
    if args.project_command == "add":
        from ..cognition.sessions import ensure_project

        project = ensure_project(ws.store, args.name,
                                 repos=args.repo or [], aliases=args.alias or [])
        # idempotent add also updates repos/aliases
        project.repos = sorted(set(project.repos) | set(args.repo or []))
        project.aliases = sorted(set(project.aliases) | set(args.alias or []))
        if args.goal:
            project.goals = sorted(set(project.goals) | set(args.goal))
        ws.store.update_project(project)
        print(f"{project.id}: {project.name} (repos: {', '.join(project.repos) or '—'})")
    else:
        for p in ws.store.list_projects():
            sessions = len(ws.store.list_sessions(project_id=p.id))
            memories = len(ws.store.list_memories(project_id=p.id, limit=100000))
            print(f"{p.id}  {p.name} [{p.status}]"
                  f" — {memories} memories, {sessions} sessions,"
                  f" repos: {', '.join(p.repos) or '—'}")


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
    from .ops import doctor

    ws = Workspace(args.home)
    checks = doctor(ws.cfg)
    icons = {"ok": "✓", "warn": "!", "fail": "✗"}
    worst = "ok"
    for c in checks:
        print(f" {icons[c.status]} {c.name:24} {c.detail}")
        if c.status == "fail" or (c.status == "warn" and worst == "ok"):
            worst = c.status
    if worst == "fail":
        raise SystemExit(1)


def cmd_setup(args) -> None:
    from .ops import setup_mcp, setup_ollama, setup_postgres

    ws = Workspace(args.home)
    if args.target == "ollama":
        lines = setup_ollama(ws.cfg)
    elif args.target == "postgres":
        lines = setup_postgres(ws.cfg)
    else:
        if not args.client:
            raise SystemExit("usage: twin setup mcp <claude-code|claude-desktop|cursor>")
        lines = setup_mcp(ws.cfg, args.client)
    print("\n".join(lines))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="twin", description="Personal Cognitive OS")
    parser.add_argument("--home", default=None, help="twin home dir (default ~/.twin or $TWIN_HOME)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="initialize the twin home").set_defaults(func=cmd_init)

    p = sub.add_parser("ingest", help="run sensors over files or directories")
    p.add_argument("paths", nargs="+")
    p.set_defaults(func=cmd_ingest)

    sub.add_parser("extract", help="extract memories from pending percepts").set_defaults(func=cmd_extract)
    sub.add_parser("review", help="interactive review queue").set_defaults(func=cmd_review)

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

    sub.add_parser("reindex", help="regenerate embeddings").set_defaults(func=cmd_reindex)

    p = sub.add_parser("promote", help="promote a memory into the judgment profile")
    p.add_argument("memory_id")
    p.set_defaults(func=cmd_promote)

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
    ps.add_argument("--memory", default=None)
    ps.add_argument("--note", default=None)
    ps.set_defaults(func=cmd_session_feedback)

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
    sub.add_parser("export", help="export everything as JSON").set_defaults(func=cmd_export)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
