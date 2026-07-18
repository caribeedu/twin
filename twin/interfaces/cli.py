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
    from ..cognition.quality import analyze_candidates, review_queue
    from ..memory.models import MemoryStatus

    ws = Workspace(args.home)
    if getattr(args, "analyze", False):
        reports = analyze_candidates(ws.store, ws.embedder)
        print(f"analyzed {len(reports)} candidates")
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
        print("review queue is empty")
        return
    print(f"{len(queue)} memories to review (priority order). "
          "[a]pprove / [r]eject / [s]kip / [q]uit\n")
    for mem in queue:
        print(f"— prio {mem.review_priority:.2f} · {mem.type.value} · {mem.domain} · "
              f"{mem.sensitivity.value} · conf {mem.confidence:.2f}")
        if mem.quality_flags:
            print(f"  flags: {', '.join(mem.quality_flags)}")
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
    from ..privacy.identity import ensure_local_identity, resolve_access
    from ..privacy.yaml_io import bootstrap_policy_set

    ws = Workspace(args.home)
    bootstrap_policy_set(ws.store, policies_path=ws.cfg.policies_path)
    ensure_local_identity(ws.store)
    access = resolve_access(
        ws.store, surface="cli", client="local-cli",
        persona=getattr(args, "persona", None) or "individual",
        purpose=getattr(args, "purpose", None) or "memory_retrieval",
        audience=getattr(args, "audience", None) or "self",
        requested_domains=[args.domain] if getattr(args, "domain", None) else [],
    )
    pack = build_context_pack(ws.store, ws.cfg, ws.embedder, args.query,
                              target_domain=args.domain, max_tokens=args.max_tokens,
                              include_candidates=args.include_candidates,
                              firewall=ws.firewall, access=access)
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
