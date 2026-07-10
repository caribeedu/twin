"""twin CLI.

    twin init                          create ~/.twin (db + default policies/judgment)
    twin ingest <paths...>             ingest docs/transcripts/meetings/slack exports
    twin extract                       extract memories from un-processed sources
    twin review                        interactive review of the candidate queue
    twin search "query" [--domain d]   hybrid search
    twin pack "task" [--domain d]      build a safe context pack
    twin observe "current text"        memory observer suggestion
    twin serve [--port 8765]           local API + review UI
    twin mcp                           MCP server over stdio
    twin export                        dump memories/entities/judgment as JSON
"""

from __future__ import annotations

import argparse
import json
import sys

from .workspace import Workspace


def _print(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def cmd_init(args) -> None:
    ws = Workspace(args.home)
    print(f"initialized twin home at {ws.cfg.home}")
    print(f"  db:        {ws.cfg.db_path}")
    print(f"  policies:  {ws.cfg.policies_path}")
    print(f"  judgment:  {ws.cfg.judgment_path}")


def cmd_ingest(args) -> None:
    from .ingest import ingest_paths

    ws = Workspace(args.home)
    new_ids, skipped = ingest_paths(ws.db, args.paths)
    print(f"ingested {len(new_ids)} source(s)")
    for s in skipped:
        print(f"  skipped: {s}")


def cmd_extract(args) -> None:
    from .extract import extract_pending

    ws = Workspace(args.home)
    reports = extract_pending(ws.db, ws.cfg, ws.embedder)
    if not reports:
        print("nothing to extract (all sources already processed)")
        return
    total = sum(len(r.inserted) for r in reports)
    review = sum(r.flagged_for_review for r in reports)
    dups = sum(r.duplicates for r in reports)
    for r in reports:
        print(f"{r.source_id}: {len(r.inserted)} memories via {r.extractor}"
              f" ({r.flagged_for_review} to review, {r.duplicates} duplicates,"
              f" {r.pii_findings} PII findings masked)")
    print(f"total: {total} new, {review} queued for review, {dups} duplicates")


def cmd_review(args) -> None:
    from .models import MemoryStatus

    ws = Workspace(args.home)
    queue = [m for m in ws.db.list_memories(status="candidate") if m.needs_review]
    if not queue:
        queue = ws.db.list_memories(status="candidate")
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
        for ev in ws.db.get_evidence(mem.id)[:1]:
            print(f'  evidence: "{ev.quote[:140]}"')
        choice = input("  [a/r/s/q] > ").strip().lower()
        if choice == "a":
            ws.db.set_status(mem.id, MemoryStatus.confirmed)
        elif choice == "r":
            ws.db.set_status(mem.id, MemoryStatus.rejected)
        elif choice == "q":
            break
        print()


def cmd_search(args) -> None:
    from .search import search

    ws = Workspace(args.home)
    result = search(ws.db, ws.embedder, args.query, target_domain=args.domain,
                    firewall=ws.firewall, limit=args.limit)
    for h in result.hits:
        print(f"{h.score:.3f}  [{h.memory.type.value}] {h.memory.title}  ({h.why})")
    if result.blocked:
        print(f"\n{len(result.blocked)} memories blocked by firewall:")
        for b in result.blocked:
            print(f"  {b.memory_id}: {b.rule}")


def cmd_pack(args) -> None:
    from .context_pack import build_context_pack

    ws = Workspace(args.home)
    pack = build_context_pack(ws.db, ws.cfg, ws.embedder, args.query,
                              target_domain=args.domain, max_tokens=args.max_tokens,
                              firewall=ws.firewall)
    if args.json:
        _print(pack.__dict__)
    else:
        print(pack.context_pack or "(empty pack)")
        if pack.blocked:
            print(f"\n[{len(pack.blocked)} memories withheld by firewall]")


def cmd_observe(args) -> None:
    from .observer import observe

    ws = Workspace(args.home)
    s = observe(ws.db, ws.cfg, ws.embedder, args.text, args.domain)
    _print({
        "inferred_domain": s.inferred_domain,
        "suggested_context": s.suggested_context,
        "blocked_context": s.blocked_context,
    })


def cmd_serve(args) -> None:
    from .api import main as serve_main

    serve_main(args.home, host=args.host, port=args.port)


def cmd_mcp(args) -> None:
    from .mcp_server import main as mcp_main

    mcp_main(args.home)


def cmd_export(args) -> None:
    from .judgment import load_profile

    ws = Workspace(args.home)
    memories = ws.db.list_memories(limit=100000)
    _print({
        "memories": [
            {
                **m.model_dump(),
                "type": m.type.value, "sensitivity": m.sensitivity.value,
                "status": m.status.value,
                "evidence": [e.model_dump() for e in ws.db.get_evidence(m.id)],
            }
            for m in memories
        ],
        "entities": [e.model_dump() for e in ws.db.list_entities()],
        "judgment": load_profile(ws.cfg.judgment_path),
    })


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="twin", description="Personal Cognitive OS")
    parser.add_argument("--home", default=None, help="twin home dir (default ~/.twin or $TWIN_HOME)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="initialize the twin home").set_defaults(func=cmd_init)

    p = sub.add_parser("ingest", help="ingest files or directories")
    p.add_argument("paths", nargs="+")
    p.set_defaults(func=cmd_ingest)

    sub.add_parser("extract", help="extract memories from pending sources").set_defaults(func=cmd_extract)
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
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_pack)

    p = sub.add_parser("observe", help="memory observer suggestion")
    p.add_argument("text")
    p.add_argument("--domain", default=None)
    p.set_defaults(func=cmd_observe)

    p = sub.add_parser("serve", help="run local API + review UI")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(func=cmd_serve)

    sub.add_parser("mcp", help="run MCP server (stdio)").set_defaults(func=cmd_mcp)
    sub.add_parser("export", help="export everything as JSON").set_defaults(func=cmd_export)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
