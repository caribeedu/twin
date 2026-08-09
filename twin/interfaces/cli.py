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



from .commands.cli_handlers import (  # noqa: E402
    cmd_init,
    cmd_ingest,
    cmd_interpret,
    cmd_extract,
    cmd_review,
    cmd_review_batch,
    cmd_memory,
    cmd_eval,
    cmd_source,
    cmd_retention,
    cmd_delete_source,
    cmd_undo,
    cmd_search,
    cmd_pack,
    cmd_observe,
    cmd_workspace,
    cmd_consolidate,
    cmd_runtime,
    cmd_reindex,
    cmd_promote,
    cmd_judgment,
    cmd_privacy,
    cmd_connector,
    cmd_supersede,
    cmd_contradict,
    cmd_stats,
    cmd_serve,
    cmd_mcp,
    cmd_backup,
    cmd_export,
    cmd_session_start,
    cmd_session_observe,
    cmd_session_complete,
    cmd_session_feedback,
    cmd_session_cleanup,
    cmd_project,
    cmd_native,
    cmd_correlate,
    cmd_meditate,
    cmd_episode,
    cmd_identity,
    cmd_watch,
    cmd_doctor,
    cmd_usage,
    cmd_setup,
    cmd_cognize,
    cmd_narrative,
    cmd_stance,
    cmd_inject,
    _add_json_flag,
    _add_json_flag_tree,
    _print,
    _emit,
)

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

    pc = sub.add_parser("cognize", help="run Cognize pipeline (halts without chat LLM)")
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
    pcrev = pcs.add_parser(
        "review",
        help="open Reflections and competing Interpretations",
    )
    pcrev.add_argument("--vault", default="default")
    pcrev.set_defaults(func=cmd_cognize, cognize_command="review")
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
    pnscp = pns.add_parser("commit-preview", help="fingerprint token before commit")
    pnscp.add_argument("--account", required=True)
    pnscp.add_argument("--evidence", action="append", default=[])
    pnscp.add_argument("--evidence-id", default=None)
    pnscp.add_argument("--interpretation", action="append", default=[])
    pnscp.add_argument("--dissent", action="append", default=[])
    pnscp.add_argument("--domain", default="")
    pnscp.add_argument("--vault", default="default")
    pnscp.set_defaults(func=cmd_narrative)
    pnsc = pns.add_parser("commit")
    pnsc.add_argument("--account", required=True)
    pnsc.add_argument("--evidence", action="append", default=[])
    pnsc.add_argument("--evidence-id", default=None)
    pnsc.add_argument("--interpretation", action="append", default=[])
    pnsc.add_argument("--dissent", action="append", default=[])
    pnsc.add_argument("--domain", default="")
    pnsc.add_argument("--vault", default="default")
    pnsc.add_argument("--actor", default="user")
    pnsc.add_argument("--supersedes", default=None)
    pnsc.add_argument("--token", default=None, help="preview_token from commit-preview")
    pnsc.add_argument(
        "--require-token",
        action="store_true",
        help="fail if --token missing/mismatched",
    )
    pnsc.set_defaults(func=cmd_narrative)
    pnsb = pns.add_parser("backfill", help="migrate memories into Narratives / Interpretations")
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
