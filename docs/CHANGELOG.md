[← README](../README.md) · [FOUNDATIONS](FOUNDATIONS.md) · [PRODUCT](PRODUCT.md) · [ROADMAP](ROADMAP.md) · [CHANGELOG](CHANGELOG.md) · [ARCHITECTURE](ARCHITECTURE.md) · [INTERFACES](INTERFACES.md) · [SETUP](SETUP.md) · [OPERATIONS](OPERATIONS.md)

# Changelog

**Source of truth for:** what each released version delivered.

Product definition in [PRODUCT.md](PRODUCT.md). Future work in [ROADMAP.md](ROADMAP.md). Overview in [README](../README.md).

### v0.1 — Local Technical Memory

Goal: prove the system reduces re-explanation in technical work.

Delivered:

- local ingestion with normalized percepts;
- local extraction through Ollama with an offline heuristic fallback;
- selective review and confirmed-only context packs by default;
- sectioned context packs with judgment, decisions, constraints, tasks, preferences, facts/events and evidence;
- source qualification through trust, scope and confidentiality;
- explicit promotion, supersedence and contradiction lifecycle operations;
- memory quality metrics;
- expanded PII detection and optional local encryption;
- PostgreSQL + pgvector and zero-config SQLite backends;
- MCP, API, CLI and per-client MCP documentation;
- initial observer domain inference using keywords and graph signals;
- initial judgment profile.

### v0.2 — Operational Cognitive Workflow

Goal: close the loop between retrieving context and capturing what changed during real technical work.

Delivered:

- cognitive sessions with start, observe, complete and feedback over MCP, API and CLI;
- task-aware context packs (coding, architecture, debugging, writing, planning, review, meeting prep);
- first-class projects with repos, aliases, goals and session/percept linkage;
- product usefulness feedback and session/product metrics;
- multi-stage retrieval with graph expansion, firewall and source-trust weighting;
- fast and deep observer modes with domain/project/task uncertainty;
- `twin doctor` and `twin setup` for ollama, postgres and MCP clients;
- incremental developer sensors (Git, watch) preserving artifact ≠ percept ≠ memory.

### v0.3 — Memory Quality, Consolidation and Review at Scale

Goal: keep memory quality, coherence and auditability as ingestion scales beyond manual curation.

Delivered:

- quality analyzer with neighborhood discovery, claim-aware findings and recomputable review priority (with conflict/privacy floors);
- Review workbench with priority queue, side-by-side diffs, keyboard shortcuts and batch preview/apply;
- transactional merge and split with compatibility gates, evidence mapping on split, provenance and full undo;
- artifact provenance chain via explicit artifact↔percept links (no content-hash cascade);
- source×type calibration and soft confidence adjustment at extraction;
- safe duplicate-group automation (single canonical survivor) and policy-gated task archival;
- retention and deletion propagation with tombstones and dry-run;
- isolated extraction/retrieval eval harness (firewall/consolidation evals scaffolded, not delivered);
- API, CLI and MCP surfaces for review, consolidation, provenance and evals;
- retrieval that excludes merged, split, archived, unsupported and stale memories by default.

### v0.4 — Evolving Judgment Model

Goal: make different LLMs apply a stable yet evolving model of how the user evaluates trade-offs — without confusing observed behavior with personal principle, and without silent identity changes.

Delivered:

- first-class `JudgmentItem` taxonomy (preference, belief, principle, value, heuristic, constraint) with confidence, strength, stability and typed scope;
- canonical judgment store (SQLite/PostgreSQL) with YAML as bootstrap/export only;
- immutable `JudgmentRevision`s; versions and snapshots point at revision IDs (restore clones history, never rewrites it);
- proposal engine (`propose_from_memory` / demo pattern detector) — observation may propose, only the user constitutes;
- state-aware preview tokens covering final payload, edits and supporting-memory fingerprints;
- all proposal actions (`create`, `update` as patch, `weaken`, `strengthen`, `supersede`, `add_exception`, `deprecate`) with transactional approve/versioning;
- constitutional mutations require `confirm_constitutional`, including when the target is already constitutional;
- application engine with `JudgmentContext` (domain, persona, project, audience, client, stage, conditions) and exception effects (`disable`, `reduce_strength`, `replace_with`, `require_confirmation`);
- explainable `simulate` / counterfactual (`evaluate` without side effects); abstention when judgment signal is insufficient;
- conflict detection that records open conflicts without deactivating active judgment;
- Twin-influenced evidence down-weighted; sessions that consumed judgment auto-mark extracted memories;
- structured applicable judgment section in context packs (not the full profile);
- CLI (`twin judgment …`), HTTP API and MCP tools for proposals, applicable packs, simulate and approve;
- `evals/judgment/` fixtures for scope/precedence scenarios.

### v0.5 — Persona-aware Privacy and Governance

Goal: transform the domain firewall into contextual, verifiable governance independent of the main LLM.

Delivered:

- authorization context (`AccessRequest`: principal, persona, purpose, audience, tool) shared across pack/session surfaces;
- governance policy engine with precedence (constitutional deny, then deny, then grant/redact, then allow, else default-deny in restricted mode);
- `PrivacyDecision` audit trail with per-resource effects and policy-set version references;
- field/domain/ownership classification and ephemeral `RedactionPlan` transforms (canonical store untouched);
- temporary `PermissionGrant`s with TTL, max-uses and compare-and-set consumption;
- prompt-injection quarantine before extraction (quarantined content cannot become memory/judgment);
- logical vault labels and employer-ownership policies (no work data to personal cloud);
- deletion preview/execute with lineage accounting; leakage canaries;
- context packs evaluate privacy after retrieval (deny/redact before assembly; evidence skipped for redacted items);
- sessions capture persona/purpose/tool and privacy decision ids;
- CLI (`twin privacy …`) for simulate, explain, grants, quarantine and delete-preview;
- `tests/privacy/test_engine.py` covering deny/redact/grant/quarantine/canary invariants.

### v0.6 — Professional Connectors

Goal: capture operational knowledge from work through authorized, incremental connectors rather than manual exports alone.

Priority sources:

- GitHub repositories, commits, pull requests, issues and review discussions;
- Slack channels and threads;
- professional Gmail and Outlook;
- Calendar;
- Fireflies;
- Meetily;
- shared technical documents.

Each connector must preserve authorization, source ownership, incremental checkpoints, provenance, confidentiality and deletion behavior. Employer data should remain physically and cryptographically separable from personal data when policy requires it.

Delivered:

Phase 1 — Connector Framework:

- shared `ProfessionalConnector` contract + adapter manifest/registry (with declared `auth_mode`); no real providers yet;
- `SourceAccount` / `ConnectorInstance` with declared ownership (`personal | employer | client | opensource | shared | unknown`), a mandatory owner principal, per-organization work vaults (`ensure_org_vault`) and preview-first, audited reclassification;
- `CredentialStore` (encrypted file, fail-closed — no crypto backend means no connector) with locked atomic writes and backup recovery; the DB keeps only a `credential_ref`, never the secret; provisioning is compensable and `revoke` is resumable (`revoked_with_residual_secret` is reported, never claimed clean);
- idempotent ingest spine: `RawConnectorItem` to staged `ConnectorRecord` to quarantine gate to `Percept`, keyed by `connector:account:type:id:revision`; the same revision with different content is a `revision_collision` dead letter, never an overwrite, and persisted records are immutable (processing state lives in columns);
- nothing becomes cognitively visible before a consistent commit: records, percepts, the committed batch and the CAS-versioned checkpoint land in one transaction; partial batches persist only raw items + dead letters; per-(connector, stream) leases keep concurrent workers out;
- edits (new revision, old retained); deletions resolve prior lineage into a `ConnectorDeletionEvent` for the deletion planner; auth-expiry and rate-limit handling; sanitized persisted errors; dead-letter retry/replay from raw items;
- `FakeConnector` proving the full path; CLI (`twin connector …`), REST (`/api/connectors`) and MCP tools, all gated by `connector:*` capabilities. Confirmation model: the agent-facing MCP surface is preview/confirm with state-fingerprinted tokens (`connector_sync`), and ownership reclassification is state-fingerprinted on every surface; the authenticated HTTP API is otherwise a direct command surface for administrators — capability-gated, but without preview tokens;
- per-(connector, stream) leases carry a monotonic fencing token, are renewed after every fetched page, and the finalize transaction re-asserts ownership — a worker that outlived its lease cannot publish results;
- `tests/connectors/test_service.py` + `tests/connectors/test_authz.py` contract suites (SQLite and Postgres) + `evals/connectors/` scenarios (normalization, replay, partial batch, revision collision, checkpoint failure, quarantine, source deletion). Connectors capture evidence; cognition still creates understanding — no connector path writes confirmed Memory or Judgment.

Phase 2 — GitHub Connector:

- REST v3 adapter (`twin/connectors/github/`) over the Phase 1 framework: `GitHubClient` (Link-header pagination, per-stream page budget, rate-limit to structured `retry_after` the scheduler respects), read-only PAT auth (`awaiting_auth` without a token; write scopes detected via `X-OAuth-Scopes` degrade health with a least-privilege warning);
- dynamic streams per repository — `repo:{owner}/{name}:{issues|pulls|commits|releases}` from the new optional `plan_streams()` protocol method — each with its own checkpoint/lease; incremental cursor is the provider's `updated_at` watermark re-fetched with a lookback window and deduplicated by revision; PRs are detected via the `since`-capable issues listing, then re-fetched from `/pulls` as the authoritative object;
- nine external types normalized to `ConnectorRecord`s (`repository`, `issue`, `issue_comment`, `pull_request`, `review`, `review_comment`, `commit`, `release`, `check_summary`) with `github:{login}` actor ids, a shared `thread_key`/`lineage_root` per issue/PR, and honest affordances (`deletions: false` — not observable via REST polling);
- lifecycle-aware source trust (merged PR 0.95 > approved review 0.90 > commit 0.85 > body/release 0.80 > human comment 0.75 > check 0.70; bots 0.50 — below the review threshold, marked `derived=likely_notification`); every PR lifecycle revision is retained so the merged state wins without erasing rejected alternatives, and the heuristic extractor now captures "decided against / instead of X use Y" as decisions carrying `payload.rejected_alternative`;
- per-source candidate policy at extraction (`twin/cognition/source_policy.py`): GitHub proposes decisions/constraints/procedures/facts/events/tasks, never preferences or beliefs; tasks are born needing review; instances can narrow the policy via `configuration.ingestion_policy`;
- setup and backfill preview surfaces: `twin connector github repositories`, `twin connector backfill --preview` / `POST /api/connectors/{id}/backfill?preview=true` / MCP `connector_backfill_preview` (capability `connector:backfill`) — previews report scope, vault, policy and volume signals and never ingest; Phase 2 backfill itself is the first unwatermarked sync bounded by `configuration.backfill_since` (the partitionable BackfillJob is Phase 4);
- optional webhook receiver `POST /api/webhooks/github/{connector_id}`: HMAC-authenticated (`X-Hub-Signature-256` against a dedicated secret in the CredentialStore, uniform 401 on every failure), it only marks the sync state due with a `targeted_streams` hint the scheduler consumes — the payload never becomes canonical state and polling remains the authoritative reconciliation;
- `tests/connectors/github/test_adapter.py` contract suite against an offline API double (`tests/connectors/github/github_mock.py`), a Postgres mirror test, and `evals/connectors/` scenarios `github_pr_lifecycle` and `github_bot_lineage`.

Phase 3 — Slack Connector:

- Web API adapter (`twin/connectors/slack/`) over the Phase 1 framework: `SlackClient` (cursor pagination, per-stream page budget, rate-limit to structured `retry_after`), `auth_mode=slack_bot_token` with honest "privilege unverified via auth.test" health detail; read-only operation (no chat:write);
- dynamic streams per allowlisted channel — `channel:{id}` from `plan_streams()` — each with its own checkpoint/lease; incremental cursor is the maximum observed Slack event `ts` across history roots and thread replies (not a pure history cursor) plus lookback; substreams `history` then `threads`; durable continuation when the page budget is exhausted;
- activity on roots older than the lookback window is recovered via durable Events API hints (`pending_threads`, `pending_message_refreshes`, `pending_tombstones`) — the webhook never becomes canonical content; each hint generation has an `id` (`event_id` or synthetic) so a fetch only consumes generations it observed; consumption uses commit-free `consume_connector_sync_hints_cas` inside finalize (CAS conflict aborts the whole batch);
- external types `channel` / `message` / `thread_reply` with workspace-qualified ids (`slack:{team_id}:{user}`, `thread_key=slack:{team_id}:{channel}:{thread_ts}`); edit revisions via `edited.ts`+content hash; reply deletions preserve `external_type=thread_reply` for lineage; file bytes are not fetched — messages may carry `slack_file` artifact refs with `download_status=metadata_only`;
- channel metadata revalidated via `conversations.info` each sync (TTL cache, default 1h); `channel_kind` fails closed — stale metadata with a failed refresh never authorizes as public; `include_private_channels` / `include_direct_messages` enforced at sync time;
- conservative source trust (human root 0.70 / reply 0.65; bots 0.45 marked `derived=likely_notification`, with GitHub-ref extraction); Slack source policy requires review for every allowed candidate type;
- setup helpers: `twin connector slack channels`, backfill preview, optional Events API webhook `POST /api/webhooks/slack/{connector_id}` (HMAC `X-Slack-Signature`, url_verification, `event_id` dedupe);
- `tests/connectors/slack/test_adapter.py` against `tests/connectors/slack/slack_mock.py` and `evals/connectors/` scenario `slack_thread_bot_lineage`.

Phase 4 — Professional Email:

- shared cognitive mail layer (`twin/connectors/mail/`): MIME split (authored/quoted/signature), HTML kept only as `body_html_untrusted_stub` (never safe-to-render), source-heuristic classification, conservative trust, and one `ConnectorRecord` normalizer (`actor_ids` = sender only; `participant_ids` = sender+to+cc; `thread_key=mail:{provider}:{account}:{thread_id}`); attachment mode is explicit (`metadata_only` / discovery — bytes not downloaded by default);
- Gmail adapter (`gmail.readonly`): bootstrap captures `bootstrap_history_id` *before* the time-range scan, then History catch-up seals `history_id` (no gap for concurrent arrivals); label removal tombs only when no allowlisted label remains; tombstones resolve `thread_message` vs `message`;
- Outlook/Graph adapter (`Mail.Read`): continuous sync bootstraps via delta enumeration (all `value`s processed, never discarded); `@removed`/`changed` resolves current folder membership before global tombstone; attachment discovery + shared nextLink/deltaLink error decoder;
- partitionable `BackfillJob`: `SyncExecutionContext` bounds; namespaced streams; per-stream partition progress; claim CAS + finalize fence + heartbeat renew (stale workers cannot publish); completes only when every stream is `done`;
- email source policy stricter than Slack; notifications marked `derived=likely_notification`;
- `tests/connectors/gmail/test_adapter.py` + `tests/connectors/outlook/test_adapter.py` + `tests/connectors/mail/test_normalize.py` and eval `gmail_thread_lineage`.

Phase 5 — Calendar and meetings:

- shared meeting cognitive layer (`twin/connectors/meeting/`): provider-agnostic `MeetingRecord` / `TranscriptSegment` / `SpeakerIdentity`; speaker mapping with explicit confidence (never auto-merge `Speaker N`); account-scoped speaker ids; `actor_ids` = speakers who spoke at ≥0.70 confidence (silent attendees stay in `participant_ids` only); calendar↔meeting correlation via `calendar_event_id` / `iCalUID` / `conference_url` / `correlation_fingerprint` on metadata + artifact_refs (no WorkEpisode yet);
- long transcripts emit `meeting_manifest` + `meeting_transcript_chunk` records (segment-aligned chunking — never silent truncation); provider summary is a separate derived record with its own content hash revision;
- Calendar adapter (Google Calendar v3, read-only): calendar-qualified event ids (`google_calendar:{calendar_id}:{event_id}`); allowlist (empty means `awaiting_configuration`); `updated` watermark + lookback; cancelled to tombstone; `freebusy_only` redacts the persisted raw payload (not only record content); paginated calendarList discovery; `max_pages_per_stream` honored;
- Fireflies adapter talks real GraphQL (`POST https://api.fireflies.ai/graphql`); stream `meetings`; `creation_watermark` is meeting-creation only (`fromDate`), not update time — incomplete IDs stay in durable `pending_transcripts` and are re-fetched by ID until terminal; recent completes are periodically reconciled for late edits; page `skip` advances with overlap; processing/live/partial marked incomplete; chunk/summary shrinks emit tombstones; recording artifact id is the transcript id (signed media URLs are not persisted); **deletion feed not offered by provider** (`deletions=false` — retain until offboarding/reconcile);
- source policies require review for every allowed candidate type; scheduler intervals `calendar: 15m`, `fireflies: 30m`;
- setup helpers: `twin connector calendar calendars`, `twin connector fireflies meetings`;
- `tests/connectors/calendar/test_adapter.py` + `tests/connectors/fireflies/test_adapter.py` + `tests/connectors/meeting/test_normalize.py` and eval `calendar_meeting_correlation`.

Phase 6 — Shared documents:

- shared document cognitive layer (`twin/connectors/documents/`): provider-agnostic `DocumentRecord` / `DocumentRevision` + `DocumentProvider` protocol for future Drive / OneDrive / Notion; long bodies emit `document_manifest` + `document_revision_chunk` (heading/paragraph/line chunking — never silent truncation); oversized files (`max_file_bytes`) emit metadata-only manifests (`content_available=false`, `evidence_role=artifact_metadata`); decode-lossy content is `operational` + `requires_review`; prior revisions remain addressable after edits;
- document identity for the folder adapter is **path-stable, not rename-stable** (rename = delete + create unless a future correlator links them);
- authorship: email to `mail:{email}` actors; plain front-matter names stay account-scoped `author_label` metadata (confidence 0.30) and are never auto-promoted to global person ids;
- local folder adapter (`twin/connectors/folder/`): explicit watch roots (empty means `awaiting_configuration`); duplicate root ids and overlapping roots fail closed (`allow_overlapping_roots=true` to permit); include/exclude globs (defaults: md/markdown/txt/rst — json/yaml recognized as text only when included); **full scan** each sync (content-hash skips unchanged files; `max_pages_per_stream` is not a work budget); checkpoint `known_files` capped by `max_known_files` (default 50k); deletes / chunk shrinks to tombstones; `auth_mode=none`; symlinks rejected by default (`follow_symlinks=true` requires target inside the same root); POSIX permission bits inspected (Windows to `permission_inspection=not_evaluated`);
- source policy requires review for decision/constraint/procedure/fact/task; scheduler interval `folder: 5m`;
- setup helper: `twin connector folder roots`;
- `tests/connectors/folder/test_adapter.py` + `tests/connectors/documents/test_normalize.py` and eval `folder_document_revisions`.

Phase 7 — Cross-source cognition:

- cognitive correlation layer (`twin/cognition/correlation/`): `ExternalIdentity` / `IdentityLink`, `ProjectLink`, `WorkEpisode` / `EpisodeLink` — connectors still only capture evidence; correlation proposes structure, never confirmed Memory or Judgment;
- vault partition: every correlation pass clusters per `vault_id`; anchors and `correlation_key` are vault-qualified — no WorkEpisode / IdentityLink / finding may mix vaults without explicit cross-domain action;
- episode identity: idempotent via `correlation_key` + `episode_anchors` (lineage, calendar id, fingerprint, thread) — repeated passes attach sources, do not duplicate episodes;
- reconciliation: EpisodeLinks carry `active|removed` lifecycle; tombstones drop membership and rebuild participants / dates / source_refs / confidence from active links only (`max(active EpisodeLink.confidence)`; empty to `closed` + 0.0) — still not full multi-factor scoring;
- independence: per-`EpisodeLink` `independence_group` + `directness` (episode keeps aggregate count / primary lineage); derived notifications/summaries do not inflate corroboration;
- identity: upsert from actor ids within the same vault; email to candidate links only inside a vault; never merge by display name; cross-vault confirm refused without explicit flag; confirm / unconfirm / reject with `ExternalIdentity.confirmed` cleared when no confirmed edges remain;
- project mapping: exact `Project.repos` / aliases become `ProjectLink` with lifecycle `candidate | confirmed | historical | rejected` (`confirmed` bool kept as mirror); soft hint matches stay candidates; `historical` / `rejected` never attach `episode.project_id` and block auto-recreating a fresh candidate for the same container;
- clustering: merge anchors (lineage, PR/issue refs, calendar ids) form components; fingerprint / thread are contextual (attach or candidate-only, no transitive overmerge of distinct merge components); soft temporal co-occurrence alone does not merge;
- conflict findings: true cross-source only (distinct sources must disagree); idempotent via `finding_key` (reuse / supersede / close); never auto-resolved;
- explainability CLI (read-only): `twin episode explain`, `twin identity why`, `twin project explain` over anchors / links / findings already stored;
- CLI: `twin correlate`, `twin episode list|show|explain`, `twin identity list|links|confirm|unconfirm|reject|why`, `twin project link|links|confirm|reject|historical|explain`;
- `tests/cognition/correlation/test_service.py`, `tests/cognition/correlation/test_lifecycle.py`, and eval `cross_source_work_episode`.

Still deferred to **[Correlation depth](ROADMAP.md#correlation-depth-planned-vx--after-phase-7)** (planned vX — not a Phase 10 blocker): episode phases, full multi-factor confidence, identity graphs + Entity resolution, intra-episode causality, incremental correlation, HTTP/MCP explain APIs, scale/replay evals.

Phase 8 — Native proof:

- one host-native adapter: Claude Code Hooks (`twin/interfaces/native/claude_code/`) — observes session start, user messages, tool request/completion, file/project context, session end; does **not** assemble Context Packs or create a parallel memory store;
- `HostSessionBinding` (`hsb_…`) links `(host_type, external_session_id, occurrence)` ↔ `CognitiveSession`; after Stop, the same external id opens occurrence N+1 (history preserved); **cwd never identifies a conversation** — missing session id is rejected;
- security freeze: domain / project / persona / purpose / audience / vault captured at bind; refresh cannot widen scope silently;
- observations are idempotent only with a trustworthy id (`event_id` / `delivery_id` / `tool_call_id+phase` / `sequence`); equal text alone never collapses events; only UNIQUE/PRIMARY KEY conflicts map to `duplicated` (never generic IntegrityError / NOT NULL / FK / CHECK);
- concurrent SessionStart: unique binding wins; loser abandons its orphan `CognitiveSession` and returns the winner;
- tool inputs pass redaction; unknown hooks become `unsupported_host_event` (never forged `user_message`); `transcript_path` becomes `transcript:{hash}` identity;
- fail-open hooks: Twin failures return `ok=false` + `error_id` (no traceback on stdout) and exit 0 with `--fail-open`; stderr/logger hold diagnostics; Context Pack only for SessionStart/pack_request;
- orphan policy: Stop without binding is a no-op; observations without / after an active binding are rejected; duplicate SessionStart reuses the open binding;
- `InterventionRecommendation` is a display-only *possible decision reversal cue* (heuristic; may false-positive) — no host interruption/action in v0.6; `HostCapabilities` declare what Claude Code can accept;
- MCP remains simultaneous: `native_bindings` / `native_session_status` expose the same Sessions/Projects/Memories; native path never confirms Memory;
- CLI: `twin native install|event|bindings`; `tests/interfaces/native/test_service.py` and eval `evals/native`.

Phase 9 — Evals and operations:

- connector observability (§58): durable `*_total` counters on `ConnectorSyncState`, applied **exactly once per `batch.id`** via `connector_counter_batches` ledger — claim + bump share one `store.transaction()` (claim never commits alone); `reconcile_connector_counters` recovers crash undercounts and can repair divergence with audit; summary metrics separated from high-cardinality `instances_detail`; `connector_percepts_total` counts Percepts (not Memory candidates); nested under `twin stats` / `GET /api/metrics`;
- health snapshot (§57): `lag_seconds` ≡ `schedule_lag_seconds` (`max(0, now - next_run_at)`, `null` when unscheduled); `checkpoint_age_seconds` and optional `source_lag_seconds` are separate; never-run connectors report `health=unknown`; `pending_items` counts DLQ + backlog queues only (not `targeted_streams` scope);
- setup plan (§77): `twin connector setup <type> --source-owner …` prints ownership, authenticate, scope, preview, confirm (never ingests) and surfaces ownership/vault/org warnings; backfill preview remains the historical import gate;
- scheduler ops: `twin connector due` / `twin connector sync-due`; `twin doctor` resolves credentials (ref must decrypt), classifies due by schedule grace, and reports unhealthy / lagged instances;
- §88 contract matrix: evidence-based cells (`pass|fail|not_supported|not_applicable|not_tested|partial|framework_only`) with test pointers; framework Fake proof is a separate layer and never auto-passes real adapters; `ok` fails closed on required `not_tested`/`fail`/`partial`;
- `tests/connectors/test_ops.py` and eval `ops_health_metrics`; per-adapter behavioural suites remain the real proof.

Phase 10 — Final Review:

- attests §93 Critérios de conclusão via evidence-based `completion_matrix()` (`twin/connectors/completion.py`) — criteria cells carry test/eval pointers; `pass` without evidence demoted; `ok` fails closed on `fail` / `not_tested` / `partial`;
- behavioural proofs live with their modules: lifecycle supersede after meeting candidate (`tests/memory/test_lifecycle.py`); authorized work pack (`tests/privacy/test_engine.py`); completion matrix mechanics (`tests/connectors/test_completion.py`);
- CLI: `twin connector completion` (exit 1 when matrix not ok);
- documents §94 out-of-scope and §95 thesis alongside the matrix payload;
- eval `connector_completion`.

v0.6 is complete when `twin connector completion` reports `ok: true` and the connector/correlation/native suites remain green. [Correlation depth](ROADMAP.md#correlation-depth-planned-vx--after-phase-7) (episode phases, multi-factor confidence, identity graphs, causality, incremental correlation, HTTP/MCP explain, scale evals) stays deferred to later `vX` — not a Phase 10 blocker.

### v0.7 — Cognitive Interpretation

Goal: ensure that meaning is identified and catalogued by a cognitive interpreter rather than inferred from shallow lexical patterns.

Connectors and sensors already normalize heterogeneous sources into Percepts while preserving provenance, ownership, confidentiality and lineage. This version strengthens the next boundary: cognition must interpret what a Percept means before proposing any change to memory. The interpreter may use source metadata, session context, project context, participants and related evidence; deterministic code remains responsible for authorization, quarantine, confidentiality floors, provenance, persistence integrity, idempotency and review policy. Lexical rules may support routing and detection signals, but must not independently establish semantic memory types, domains, entities or cognitive confidence. A Percept that has not been interpreted remains pending or deferred — never “understood” merely because a model was temporarily unavailable.

Delivered:

- a cognitive interpreter (`twin/cognition/interpreter/`) as the production path: the local LLM reads a Percept and emits grounded, act-aware `InterpretedItem`s — each with a cognitive act (statement, question, hypothesis, proposal, decision, opinion, third-party claim), a memory type (including rejected alternatives), a speaker/attribution, and a verbatim `evidence_span`; items the model cannot ground in the source are dropped rather than stored;
- deferral as a first-class outcome: in interpreting modes (`auto`/`ollama`) an unavailable or failing model records the Percept as `deferred` (or `error`) and catalogues nothing — lexical rules never fabricate cognitive conclusions in the production path. A `percept_interpretations` record tracks execution status, model, prompt and schema versions and attempt count, so *never interpreted*, *interpreted and empty*, and *deferred* are three distinct, non-conflated states; `extract_pending` selects by interpretation state, so a returning model resumes cleanly and settled Percepts are never re-interpreted (bounded retries via `MAX_INTERPRETATION_ATTEMPTS`);
- cognitive-act governance: a proposal is not a decision, and a question, hypothesis, opinion or third-party claim is born needing review regardless of the classifier's confidence; deterministic gates (quarantine, source policy, confidentiality floor, dedupe, calibration, review) still run exactly as before — the interpreter decides meaning, deterministic code decides use;
- lexical rules are detection-only: `heuristic` mode records `DetectionSignal`s (routing/prioritization hints — a candidate category and the source span) and creates no `MemoryItem` at all; establishing a memory type, domain, entity, confidence or evidence is the interpreter's job alone, and no offline path derives those from the text. The deterministic CI stand-in is an `echo` mock (the counterpart of the hash embedder): it grounds content as neutral, review-bound `fact`/`statement` observations with fixed confidence and **makes no classification** — any test that asserts meaning supplies authored ground truth (a recorded interpretation via `set_interpreter_override`), never a lexically-derived one. `TWIN_EXTRACTOR` is honoured at Config construction;
- evidence is validated deterministically: every catalogued item's `evidence_span` must appear verbatim (Unicode/quote/whitespace-normalized, no paraphrase) in the *masked* text the interpreter read — an invented span, even a non-empty one, is dropped, closing the hallucinated-evidence path; validation runs against masked text so PII placeholders line up and removed PII cannot return;
- a service outage is separated from a Percept-specific failure: availability and the HTTP client are resolved once per batch by an `InterpretationRuntime`; a `deferred`/`unavailable` outage never consumes a Percept's retry budget and is never abandoned, while a reachable-but-failing interpreter is an `error` with a failure class (transient/schema/permanent) bounded by `MAX_INTERPRETATION_ATTEMPTS` and `next_attempt_at` backoff before going terminal;
- no silent semantic fallbacks: an out-of-vocabulary memory type is dropped (never coerced to `fact`); an unrecognized domain becomes `unknown` and is routed to review (never silently `technical`); a speaker attribution is grounded against the Percept's known actors — an unknown speaker is flagged `attribution_unresolved` and an unverified owner claim `owner_claim_unverified`, both review-bound;
- quarantine is recorded as a pipeline/governance terminal with `interpretation_attempted = false`, not as an "interpretation"; per-stage counters (emitted / grounded / ungrounded / policy-dropped / deduplicated / inserted / review-bound / invalid) are persisted for observability;
- surfaces: `twin extract` reports deferrals, `twin interpret status` / `deferred` / `signals` inspect the queue and detection hints, and `POST /api/extract` returns `deferred`/`interpretation_status`/`unresolved_references`;
- `tests/cognition/test_interpreter.py` (deferral, outage-never-abandons, poison-input bounded, grounding incl. invented/paraphrase/masked-source, invalid type/domain, attribution) and `test_heuristic.py` (heuristic never creates a memory; the echo mock classifies nothing), a Postgres mirror test, `evals/interpretation/` contract scenarios driven by authored interpretations (no model/network in CI), and an optional `evals/interpretation_model/` layer that scores the real local model (act classification, type precision, attribution, evidence literality, invented-item rate) — skipped unless `TWIN_EVAL_MODEL=1`. Connectors and sensors still capture evidence; the interpreter now creates the understanding, and no interpretation path writes confirmed Memory or Judgment on its own.

### v0.8 — Parallel Memory and Consolidation

Goal: move from an on-demand observer toward a continuously updated extended-memory process inspired by the Global Workspace model. Natural consumer of [Correlation depth](ROADMAP.md#correlation-depth-planned-vx--after-phase-7): incremental correlation and episode-phase updates should feed consolidation without full rescans.

Delivered:

- **Workspace and consolidation spine for future continuous execution** — synchronous, invocable evaluation (`workspace_tick`) and windowed maintenance (`run_consolidation_cycle`), not yet a background worker/queue. Continuous / event-driven parallelism remains deferred.
- `workspace_tick` (`twin/cognition/workspace.py`) — stages `reading, observe, salience, recall, optional parallel_interpretation, done`; preserves observer **retrieval score** separately from memory confidence; optional interpretation only for `input_mode=delta` (snapshots do not invent deltas); refuses to interpret while domain is unclassified (never coerces to `technical`);
- identity / idempotency — durable `workspace_ticks` keyed by `idempotency_key`, `session_id+sequence`, or `session_id+content_hash` for delta interpretation; repeated completed calls return the tick (`duplicated=True`); concurrent `running` returns `blocked_concurrent` without executing; failed ticks persist `error`/`error_stage` and require `retry=True` with atomic CAS (`error to running`) so only one reclaimer executes; Percept id is persisted immediately and reused on retry;
- confidence + relevance recall (`twin/cognition/recall.py`) — eligibility = confidence gate AND retrieval score gate; novelty may reorder eligible suggestions but cannot clear the relevance bar; firewall `blocked` stays ids/reasons only;
- salience / novelty / contradiction cues (`twin/cognition/salience.py`) — salience excludes novelty; novelty is ranking/inspection only;
- daily / weekly consolidation (`twin/cognition/consolidation_cycle.py`) — logical windows with durable `consolidation_runs` (unique apply per window); concurrent `running` blocked; `error` requires `retry=True` with atomic CAS reclaim; confirmed Memory/Judgment invariant raises `ConsolidationInvariantError` (run marked `error`, never `completed`);
- surfaces: `twin workspace tick` (`--input-mode`, `--sequence`, `--idempotency-key`), `twin consolidate daily|weekly`, `POST /api/workspace/tick`, `POST /api/consolidate/{daily|weekly}`, MCP `workspace_tick` / `consolidate_cycle`, native `intervene_check` soft recall infos;
- `tests/cognition/test_recall.py`, `test_workspace.py`, `test_consolidation_cycle.py`, and offline `evals/consolidation/` (including score-vs-confidence and confirmed-set invariants).

### v0.9 — Cognitive OS Spine

Goal: harden Twin from the v0.8 workspace/consolidation spine into a durable, auditable Personal Cognitive OS path — runtime, sessions, memory formation, packs, attention, connector readiness, sovereignty and release gates — without yet calling the product v1.0.

Delivered:

Phase 1 — Durable Cognitive Runtime:

- **`twin-runtime` / `twin runtime start`** — durable background process with local scheduler + worker pool; not an autonomous agent (handlers call the same cognitive core as CLI/MCP/API);
- durable job queue (`runtime_jobs`) with priority, vault isolation, causal parent, idempotency keys, `not_before` backoff;
- exclusive CAS claim + worker leases + heartbeat + dead-worker reclaim (expired `running` leases);
- retries with backoff, dead-letter queue, cancel, explicit retry; model-unavailable failures never dead-letter model-gated kinds;
- initial job kinds: `interpret_percept`, `workspace_tick`, `consolidate_daily` / `consolidate_weekly`, `reembed_memory`, `integrity_check`, `connector_reconcile`;
- surfaces: `twin runtime {start,status,schedule,enqueue,job,retry,cancel}`, `POST/GET /api/runtime/jobs…`, `GET /api/runtime/health`, entrypoint `twin-runtime`;
- `tests/runtime/test_runtime.py` — exclusive claim, lease recovery, idempotent enqueue/schedule, vault isolation, DLQ, worker execution.

Phase 2 — Cognitive Sessions:

- lifecycle statuses: `active` / `paused` / `completed` / `abandoned` / `archived`;
- ordered `session_events` (deltas) with gap detection; checkpoints; structured `SessionClosure` (never auto-confirms Memory/Judgment);
- pause / resume / reopen / archive; continuity via `external_session_id` on events across tools;
- surfaces: `POST /api/sessions/{id}/{events,checkpoint,close,reopen,pause,resume}`, `GET …/closure`;
- `tests/cognition/test_session_lifecycle.py`.

Phase 3 — Memory Formation:

- `twin/memory/formation.py` — deterministic `formation_identity` / `mem_f…` ids; propose-or-corroborate; formation states (`candidate` to `corroborating` / `conflicting` / `awaiting_review` to `confirmed` / `rejected` / …); per-type policy (belief/procedure always review; never auto-confirm);
- confirm requires evidence; reject requires reason; restore rejected back to re-review; auditable `MemoryOperation`s; explain view;
- pipeline inserts via `propose_or_corroborate` (idempotent on identity);
- surfaces: `GET/POST /api/memory/candidates…`, `GET /api/memory/{id}/explain|history`;
- `tests/memory/test_formation.py`.

Phase 4 — Consolidation Engine:

- operational stages on the existing cycle: `closed_sessions`, `open_tasks`, `review_prepare`, `change_report` (+ weekly judgment proposals unchanged);
- auditable `cognitive_change_report` (counts + low-confidence inventory); review backlog stamps `formation_state=awaiting_review`;
- still never confirms Memory/Judgment; window apply remains idempotent (`duplicated=True` replays the same report);
- `tests/cognition/test_consolidation_cycle.py` covers operational stages + replay.

Phase 5 — Judgment and Personas:

- durable `PersonaRecord` (`privacy_personas`) bootstrapped with configurable starter personas; `resolve_access` intersects persona domains/vaults/capabilities with principal∩binding (never amplifies);
- `POST /api/judgment/versions/{id}/restore`, `GET /api/judgment/snapshots/{id}/explain`, `GET /api/personas`;
- `tests/privacy/test_personas.py`.

Phase 6 — Mature Context Packs:

- structured pack metadata: `active`, `uncertainty`, `provenance_summary`, `token_budget`, `blocked_count`, `explanation`;
- modes: `compact` / `explainable` / `references_only`; cognitive-act labels; dedupe + type diversity; pack-time prompt-injection screen;
- `POST /api/context_pack` accepts `mode`, `session_id`, `request_scope`;
- `tests/cognition/test_context_pack.py` covers modes + injection exclusion.

Phase 7 — Attention + MCP runtime surfaces:

- `twin/cognition/attention.py` — working-memory window, expected_value policy, typed outcomes, cooldown/cap/dedupe/suppress; default silence;
- `attention_emissions` ledger; `append_session_delta` enqueues `attention_evaluate` runtime job;
- surfaces: `GET /api/sessions/{id}/attention`, `POST /api/attention/{id}/feedback`, MCP `get_context_pack`, `append_session_delta`, `get_attention`, `provide_feedback`, `capabilities`, `health`;
- `tests/cognition/test_attention.py`.

Phase 8 — Professional Connectors production-ready:

- GitHub + Slack closed on §88 contract (collision DLQ, partial batch, quarantine, unauthorized, unknown schema);
- `production_ready_adapters()` + `twin connector production-ready` attest ≥2 real adapters (Fake never counts);
- runtime `connector_reconcile` runs due syncs via `sync_due` (recovery path, not a stub inventory);
- `tests/connectors/test_production_ready.py` + adapter contract gap tests.

Phase 9 — Data Sovereignty spine:

- `twin/sovereignty/` — NDJSON export bundle + manifest checksums; `create_backup` copies SQLite; `validate_backup` / `restore_sqlite_backup` to isolated path;
- integrity checks (confirmed-without-evidence, orphan evidence) via runtime `integrity_check` + `GET /api/health/cognition`;
- surfaces: `twin backup {create,validate,restore}`, `POST /api/backup`, `POST /api/backup/validate`, `POST /api/restore`;
- `tests/sovereignty/test_backup.py`.

Phase 10 — Reliability and Evals spine:

- golden work loop (`twin.evals.golden` / `twin eval golden`) — session, candidate, confirm, recall; injection never auto-confirms;
- fail-closed `v1_completion_matrix()` + `twin eval v1-completion`;
- adversarial checks: prompt-injection detection + cross-domain recall deny;
- `evals/v1/cases/golden_work_loop.json`, `tests/evals/test_golden_work_loop.py`, `tests/evals/test_security_adversarial.py`, `tests/evals/test_v1_completion.py`.

v0.9 is complete when the durability, formation, pack, attention, sovereignty and eval spines are green and GitHub + Slack attest production-ready. The v1.0 cut packages that spine as the daily-usable Personal Cognitive OS bar.

### v1.0 — Personal Cognitive OS

Goal: a trustworthy, daily-usable cognitive substrate — closed sessions, evidence-grounded memory, evolving judgment with human control, persona-aware privacy, mature MCP/connectors, export/backup/recovery, and measurable reduction in re-explanation. Not a complete autonomous mind. Built on the [v0.9 Cognitive OS Spine](#v09--cognitive-os-spine).

Delivered:

- closed cognitive sessions across tools;
- reliable cognitive interpretation, memory formation and consolidation;
- evolving judgment with human control;
- persona-aware privacy and auditability;
- mature MCP interoperability and professional connectors (GitHub + Slack production-ready attestation);
- parallel observation and controlled consolidation;
- export, backup, deletion and recovery;
- durable cognitive runtime (`twin-runtime`) with leases, DLQ and vault isolation;
- release gates: `twin eval v1-completion`, `twin connector production-ready`, `twin eval golden`;
- package/`__version__` to `1.0.0`;
- threat model ([ARCHITECTURE.md](ARCHITECTURE.md#threat-model)) and operator runbook ([OPERATIONS.md](OPERATIONS.md)).

Out of scope for v1.0:

- Multi-tenant SaaS isolation
- Formal methods proofs
- Hardware-backed secret enclaves
- Guaranteeing LLM non-hallucination (mitigated by evidence + human confirm)

Follow-on (not blocking v1.0): remaining adapter contract rows, unified explain UX, encrypted/incremental backups, soak/stress harness, re-explanation KPI dashboard.

### v1.1.0 — Adoption DX and mainstream LLM providers

Goal: make Twin easier to install, configure and trust day-to-day — guided setup, mainstream chat providers, clearer product docs and a friendlier local UI — without changing the cognitive core.

Delivered:

- guided `twin init` / setup wizard for Ollama (recommended), OpenAI-compatible, Anthropic and Gemini;
- pluggable chat LLM adapter with presets (`ollama`, `anthropic`/`claude`, `gemini`/`google`, `openai`, `groq`, `openrouter`, `lmstudio`, `vllm`, …);
- embeddings via Ollama, OpenAI-compatible, Gemini or hash; Anthropic chat pairs with a separate embed backend;
- env keys honored per provider (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`, …) plus `TWIN_LLM_*` / `TWIN_EMBED_*`;
- `twin doctor` provider-aware checks; Ollama base URL resolution respects `TWIN_OLLAMA_URL` / configured home env (WSL-friendly);
- CLI UX polish: review single-key actions, extract progress/ETA, `--auto-approve` / `-A`, clearer panels and contrast;
- `twin serve` Review workbench refresh — candidate/neighbor cards, evidence quotes, flags, friendly labels;
- Search / Pack / Memories: human-readable selects and metadata chips (implementation ids stay on CLI/MCP/API);
- Search relevance as relative % (top hit = 100%) with match-why chips under the score bar; Memories hides duplicate body when title equals summary;
- marketing README with banner / vision / before-after visuals; deep material under `docs/` (`FOUNDATIONS`, `PRODUCT`, `ROADMAP`, `CHANGELOG`, `ARCHITECTURE`, `CONNECTION`, `SETUP`, `OPERATIONS`);
- MCP client guides folded into INTERFACES; operator runbook moved to OPERATIONS; threat model moved to ARCHITECTURE; release history moved to CHANGELOG; future majors moved to ROADMAP;
- root `LICENSE` (MIT); package/`__version__` to `1.1.0`.

### v1.2.0 — Native lifecycle, domain resolution and CLI/host DX

Goal: make Claude Code's native path match a real chat lifecycle, make session/observer domain resolution evidence-based instead of keyword-fragile, harden the host contract so capabilities and identity actually gate behavior, and finish the host/CLI DX started in v1.1 — without changing the cognitive core's Memory / Judgment contracts.

Delivered:

- `twin native install` merges Twin hooks into `~/.claude/settings.json` by default (keeps non-Twin hooks; `--no-merge` / `--settings` escape hatches; `.twin-bak` backup on patch); event name comes from stdin `hook_event_name`, not a fake env var;
- observation profiles: `twin native install --profile minimal|standard|verbose` scopes which hooks are wired (lifecycle only → `+PostToolUse` default → `+PreToolUse`);
- `twin native uninstall` removes only Twin-owned handlers (keeps third-party hooks); `--restore-backup` restores the most recent `.twin-bak`;
- context packs return as Claude's `hookSpecificOutput.additionalContext` (observation hooks stay silent on stdout);
- lifecycle fix: Claude's **Stop** is end-of-turn only (`assistant_result` — binding stays open); **SessionEnd** closes the binding immediately and enqueues background `session_complete` (summary + extract via `twin-runtime`) — default install wires `SessionEnd` with per-hook timeouts (120s SessionStart / UserPromptSubmit / SessionEnd);
- deferred context pack: SessionStart with no prompt text opens `unclassified` (empty pack); the first `UserPromptSubmit` that **search-votes** a domain upgrades once and emits the pack — never waits on the local LLM in the hook;
- host capabilities on `session_start` gate real behavior: where a pack may surface, turn/session-end contract breaches fail closed, and intervention LLM calls respect `display_intervention`;
- stable install identity on bindings for provenance (derived from Twin home + host + user home — never a raw path); soft pack latency budgets drop over-budget packs while keeping binding/domain state;
- documented native adapter checklist + identity tuple; fake-host evals cover lifecycle, security, capabilities and budget.
- hot-path session domain is search-vote only (keyword/graph guess removed); inconclusive make it stay `unclassified` and enqueue background `session_domain_resolve` (multi-message LLM) or wait for client/MCP explicit domain;
- Memory Observer no longer invents the consumer domain from text: uses the frozen session domain or an explicit argument (else `unclassified` → default-deny), with a soft same-domain ranking boost on hybrid search;
- `session_summary` consolidation folds dialogue plus deliberate observations (`file` / `commit` / `doc` / `note` / host file/project context) with human speaker labels (`User:` / `Assistant:` …) so machine kind tags do not leak into evidence quotes; tool I/O, `turn_completed`, and session boilerplate stay on the session for replay;
- native auth uses `surface=native` + host `client` with allowlist tool `native-host` (not CLI masquerade); provider Stop maps to structural `turn_completed` (no `[turn_end]` text); background domain resolve marks `pending_context_pack` for the next injection-capable event.
- interpreter prompt/schema (interpret-v2) require `title` and `summary` so grounded items are no longer dropped as malformed;
- CLI DX: human-readable views across connector and day-to-day commands, with a uniform `--json` escape hatch for scripting (machine protocol surfaces — `twin native event`, `twin mcp`, `twin serve` — unchanged);
- runtime CLI documents `session_domain_resolve` / `session_complete` job kinds (`twin runtime enqueue|status|job|retry|…`; see INTERFACES + OPERATIONS);
- `twin runtime start` / `twin-runtime` show a live processing panel on TTY (in-flight workers, queue depth, recent jobs; `--no-live` / `TWIN_RUNTIME_NO_LIVE` escape hatch);
- `twin doctor` reports runtime queue backlog (pending / failed / dead-letter) from the store instead of pretending a worker is up;
- connector historical backfill runs as background runtime jobs; `twin connector backfill --run` enqueues and watches with progress/ETA (requires `twin runtime start`);
- MCP host identity is process-env only (`TWIN_MCP_CLIENT` / `TWIN_MCP_CLIENT_TOKEN`); `twin setup mcp <client>` provisions credentials into the host env block — tools no longer accept client tokens as arguments;
- drop versioned completion gates and phase folklore (`twin eval v1-completion` / connector completion matrices → behavior tests and `twin connector contract` / production-ready report);
- docs/README polish: `CONNECTION.md` → `INTERFACES.md`, ROADMAP for future majors, CHANGELOG as release history, clearer how-to-use and visuals;
- package/`__version__` to `1.2.0`.

---

Next: [ROADMAP.md](ROADMAP.md) · [PRODUCT.md](PRODUCT.md).
