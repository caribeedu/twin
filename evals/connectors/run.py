"""Tiny offline runner for connector eval cases (Phase 1).

Runs each JSON case in ``cases/`` against the FakeConnector on an isolated
in-memory store. No network, no production DB.

Case ``scenario`` selects the harness:

    normalization        sync once, assert records/percepts/lineage
    replay               sync N times, assert idempotency
    partial_batch        one item fails → NO percepts visible, checkpoint still;
                         retry succeeds → everything lands together
    revision_collision   same external revision, different content → DLQ,
                         original evidence preserved
    checkpoint_failure   fault-injected finalize → batch not committed AND
                         checkpoint unchanged (never one without the other)
    quarantine           malicious content → quarantined, zero percepts
    source_deletion      tombstone → deletion event with prior lineage,
                         no new percepts

    python -m evals.connectors.run
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from twin.connectors import (
    add_connector_instance,
    build_credential_store,
    register_source_account,
    sync_connector,
)
from twin.memory.store.sqlite import SqliteStore

_CASES = Path(__file__).resolve().parent / "cases"


def _setup(case: dict, tmp: str):
    store = SqliteStore(":memory:")
    creds = build_credential_store(Path(tmp))
    acc = register_source_account(
        store,
        connector_type=case.get("connector_type", "fake"),
        source_owner=case["source_owner"],
        org_key=case.get("org_key"),
        owner_principal_id="principal_eval",
    )
    inst = add_connector_instance(
        store, creds, account_id=acc.id, secret="eval-token",
        configuration={"fixtures": case["fixtures"],
                       **case.get("configuration", {})},
    )
    return store, creds, acc, inst


def _check_expected(case, store, inst, acc, result) -> tuple[bool, str]:
    exp = case["expected"]
    records = store.list_connector_records(inst.id)
    percepts = store.list_percepts()
    if "records" in exp and len(records) != exp["records"]:
        return False, f"records {len(records)} != {exp['records']}"
    if "percepts" in exp and result.percepts != exp["percepts"]:
        return False, f"percepts {result.percepts} != {exp['percepts']}"
    if "record" in exp:
        rec = records[0]
        for key, want in exp["record"].items():
            got = getattr(rec, key)
            got = getattr(got, "value", got)
            if got != want:
                return False, f"record.{key} {got!r} != {want!r}"
    if "percept_metadata" in exp:
        meta = percepts[0].metadata
        for key, want in exp["percept_metadata"].items():
            if meta.get(key) != want:
                return False, f"percept.metadata.{key} {meta.get(key)!r} != {want!r}"
    if exp.get("checkpoint_advances"):
        if store.get_connector_checkpoint(inst.id, "issues") is None:
            return False, "checkpoint did not advance"
    if "dead_letters" in exp:
        dead = store.list_connector_dead_letters(inst.id)
        if len(dead) != exp["dead_letters"]:
            return False, f"dead letters {len(dead)} != {exp['dead_letters']}"
    if "deletion_events" in exp:
        events = store.list_connector_deletion_events(inst.id)
        if len(events) != exp["deletion_events"]:
            return False, f"deletion events {len(events)} != {exp['deletion_events']}"
    if "quarantined" in exp:
        quarantined = sum(1 for r in records if r.quarantined)
        if quarantined != exp["quarantined"]:
            return False, f"quarantined {quarantined} != {exp['quarantined']}"
    return True, "ok"


def _run_simple(case: dict) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="twin-conn-eval-") as tmp:
        store, creds, acc, inst = _setup(case, tmp)
        result = sync_connector(store, creds, inst.id)
        ok, detail = _check_expected(case, store, inst, acc, result)
        if not ok:
            return ok, detail
        exp = case["expected"]
        for _ in range(case.get("replays", 1) - 1):
            again = sync_connector(store, creds, inst.id)
            if "second_pass_new_percepts" in exp and \
                    again.percepts != exp["second_pass_new_percepts"]:
                return False, f"replay percepts {again.percepts} != " \
                              f"{exp['second_pass_new_percepts']}"
    return True, "ok"


def _run_partial_batch(case: dict) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="twin-conn-eval-") as tmp:
        store, creds, acc, inst = _setup(case, tmp)
        first = sync_connector(store, creds, inst.id)
        if first.percepts != 0:
            return False, "partial batch exposed percepts before commit"
        if store.list_percepts():
            return False, "percepts visible from uncommitted batch"
        if store.get_connector_checkpoint(inst.id, "issues") is not None:
            return False, "checkpoint advanced on partial failure"
        # heal the failing item and retry: everything lands together
        store.update_connector_instance(
            inst.id, configuration={"fixtures": case["fixtures"]})
        second = sync_connector(store, creds, inst.id)
        exp = case["expected"]
        if second.percepts != exp["percepts_after_retry"]:
            return False, f"retry percepts {second.percepts} != " \
                          f"{exp['percepts_after_retry']}"
        if store.get_connector_checkpoint(inst.id, "issues") is None:
            return False, "checkpoint did not advance after healthy retry"
    return True, "ok"


def _run_revision_collision(case: dict) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="twin-conn-eval-") as tmp:
        store, creds, acc, inst = _setup(case, tmp)
        sync_connector(store, creds, inst.id)
        original = store.list_connector_records(inst.id)[0].content
        # same revision, different content
        store.update_connector_instance(
            inst.id, configuration={"fixtures": case["collision_fixtures"]})
        second = sync_connector(store, creds, inst.id)
        dead = store.list_connector_dead_letters(inst.id)
        if not any(d.failure_class.value == "revision_collision" for d in dead):
            return False, "collision did not dead-letter"
        if store.list_connector_records(inst.id)[0].content != original:
            return False, "original evidence was overwritten"
        if any(s.committed for s in second.streams if s.stream == "issues"):
            return False, "collision batch was committed"
    return True, "ok"


def _run_checkpoint_failure(case: dict) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="twin-conn-eval-") as tmp:
        store, creds, acc, inst = _setup(case, tmp)
        original_cas = store.cas_connector_checkpoint

        def failing_cas(checkpoint, expected_version):
            return False  # simulate a concurrent advance

        store.cas_connector_checkpoint = failing_cas
        result = sync_connector(store, creds, inst.id)
        store.cas_connector_checkpoint = original_cas
        if any(s.committed for s in result.streams):
            return False, "batch claimed committed without checkpoint"
        if store.get_connector_checkpoint(inst.id, "issues") is not None:
            return False, "checkpoint advanced despite CAS failure"
        if store.list_percepts():
            return False, "percepts visible from aborted batch"
        # retry with a healthy store completes everything together
        retry = sync_connector(store, creds, inst.id)
        if retry.percepts != case["expected"]["percepts_after_retry"]:
            return False, "retry did not deliver the batch"
    return True, "ok"


def _run_source_deletion(case: dict) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="twin-conn-eval-") as tmp:
        store, creds, acc, inst = _setup(case, tmp)
        sync_connector(store, creds, inst.id)
        percepts_before = len(store.list_percepts())
        store.update_connector_instance(
            inst.id, configuration={"fixtures": case["deletion_fixtures"]})
        sync_connector(store, creds, inst.id)
        events = store.list_connector_deletion_events(inst.id)
        exp = case["expected"]
        if len(events) != exp["deletion_events"]:
            return False, f"deletion events {len(events)} != {exp['deletion_events']}"
        event = events[0]
        if len(event.prior_record_ids) != exp["prior_records"]:
            return False, f"prior records {len(event.prior_record_ids)}"
        if len(event.affected_percept_ids) != exp["affected_percepts"]:
            return False, f"affected percepts {len(event.affected_percept_ids)}"
        if len(store.list_percepts()) != percepts_before:
            return False, "deletion created or removed percepts by itself"
    return True, "ok"


def _github_env():
    """Route the real GitHub adapter at the offline API double from the test
    suite. Returns (api, restore) — call restore() in a finally block."""
    import httpx

    tests_dir = Path(__file__).resolve().parents[2] / "tests"
    if str(tests_dir) not in sys.path:
        sys.path.insert(0, str(tests_dir))
    from github_mock import FakeGitHubAPI, _user

    from twin.connectors.github import client as ghclient

    api = FakeGitHubAPI()
    real_build = ghclient._build_http

    def fake_build(base_url, token):
        original = real_build(base_url, token)
        headers = dict(original.headers)
        original.close()
        return httpx.Client(transport=api.transport(),
                            base_url="https://api.github.com", headers=headers)

    ghclient._build_http = fake_build
    return api, _user, (lambda: setattr(ghclient, "_build_http", real_build))


def _setup_github(case: dict, tmp: str, repo: str):
    store = SqliteStore(":memory:")
    creds = build_credential_store(Path(tmp))
    acc = register_source_account(
        store, connector_type="github", source_owner=case["source_owner"],
        org_key=case.get("org_key"), owner_principal_id="principal_eval",
    )
    inst = add_connector_instance(
        store, creds, account_id=acc.id, secret="gh-test-token",
        configuration={"repositories": [repo]},
    )
    return store, creds, acc, inst


def _run_github_pr_lifecycle(case: dict) -> tuple[bool, str]:
    api, _user, restore = _github_env()
    repo, number = case["repo"], case["pr_number"]
    exp = case["expected"]
    try:
        with tempfile.TemporaryDirectory(prefix="twin-conn-eval-") as tmp:
            store, creds, acc, inst = _setup_github(case, tmp, repo)
            api.add_repo(repo)
            pr = api.add_pull(repo, number, title="Queue backend",
                              body="We decided to use Redis for the queue.",
                              updated_at="2026-01-01T10:00:00Z", head_sha="s3")
            sync_connector(store, creds, inst.id)

            api.add_review(repo, number, 501, state="CHANGES_REQUESTED",
                           body="Do not use Redis here — persistence requirements.",
                           submitted_at="2026-01-02T10:00:00Z")
            pr["updated_at"] = "2026-01-02T10:00:00Z"
            sync_connector(store, creds, inst.id)

            pr["body"] = "We decided to use PostgreSQL advisory locks for the queue."
            pr["merged"] = True
            pr["merged_at"] = "2026-01-03T10:00:00Z"
            pr["state"] = "closed"
            pr["updated_at"] = "2026-01-03T10:00:00Z"
            sync_connector(store, creds, inst.id)
            # ingesting the same final state twice must change nothing
            replay = sync_connector(store, creds, inst.id)
            if replay.percepts != 0:
                return False, "replay of the final state produced new percepts"

            prs = [r for r in store.list_connector_records(inst.id)
                   if r.external_type == "pull_request"]
            if len(prs) != exp["pr_revisions"]:
                return False, f"pr revisions {len(prs)} != {exp['pr_revisions']}"
            final = max(prs, key=lambda r: r.external_revision)
            early = min(prs, key=lambda r: r.external_revision)
            if final.confidentiality["source_trust"] != exp["final_trust"]:
                return False, "merged state did not carry the highest trust"
            if "PostgreSQL advisory locks" not in final.content:
                return False, "final decision content missing from merged state"
            if early.confidentiality["source_trust"] != exp["early_trust"]:
                return False, "pre-merge revision trust drifted"
            if "Redis" not in early.content:
                return False, "rejected alternative was erased"
            lineage = [r for r in store.list_connector_records(inst.id)
                       if r.thread_key]
            if not lineage or any(r.thread_key != exp["thread_key"] for r in lineage):
                return False, "lineage does not share one thread_key"
            percepts = store.list_percepts()
            if not percepts or any(p.metadata.get("vault_id") != exp["vault_id"]
                                   for p in percepts):
                return False, "ownership not sealed on every percept"

            # extraction (offline heuristic): both decisions become
            # candidates, the merged one outranks, nothing auto-confirms
            from twin.cognition import extract_pending
            from twin.config import Config
            from twin.memory.embeddings import get_embedder
            cfg = Config(home=Path(tmp) / "twin-home")
            cfg.extractor = "heuristic"
            cfg.embedder = "hash"
            cfg.ensure_home()
            extract_pending(store, cfg, get_embedder("hash", cfg.embedding_dim))
            decisions = [m for m in store.list_memories()
                         if m.type.value == "decision"]
            pg = [m for m in decisions if "PostgreSQL" in m.summary]
            redis = [m for m in decisions if "Redis" in m.summary
                     and "PostgreSQL" not in m.summary]
            if not pg or not redis:
                return False, "extraction lost the decision or its alternative"
            if max(m.confidence for m in pg) <= max(m.confidence for m in redis):
                return False, "merged decision does not outrank the alternative"
            if any(m.status.value != "candidate" for m in decisions):
                return False, "a connector-derived decision was auto-confirmed"
        return True, "ok"
    finally:
        restore()


def _run_github_bot_lineage(case: dict) -> tuple[bool, str]:
    api, _user, restore = _github_env()
    repo = case["repo"]
    exp = case["expected"]
    try:
        with tempfile.TemporaryDirectory(prefix="twin-conn-eval-") as tmp:
            store, creds, acc, inst = _setup_github(case, tmp, repo)
            api.add_repo(repo)
            api.add_issue(repo, 1, title="Queue decision",
                          body="We must pick a queue backend.",
                          updated_at="2026-01-01T09:00:00Z")
            api.add_issue_comment(
                repo, 900, 1,
                body="We decided to use PostgreSQL for the queue.",
                updated_at="2026-01-01T10:00:00Z",
                user=_user("release-bot[bot]", bot=True))
            sync_connector(store, creds, inst.id)

            bots = [r for r in store.list_connector_records(inst.id)
                    if r.external_type == "issue_comment"]
            if len(bots) != 1:
                return False, f"expected 1 bot comment record, got {len(bots)}"
            bot = bots[0]
            if bot.confidentiality["source_trust"] != exp["bot_trust"]:
                return False, "bot trust not calibrated below the threshold"
            if bot.source_metadata.get("derived") != exp["derived"]:
                return False, "bot comment not marked as a derived notification"
            if bot.source_metadata.get("lineage_root") != exp["lineage_root"]:
                return False, "bot comment lost the lineage root it references"

            from twin.cognition import extract_pending
            from twin.config import Config
            from twin.memory.embeddings import get_embedder
            cfg = Config(home=Path(tmp) / "twin-home")
            cfg.extractor = "heuristic"
            cfg.embedder = "hash"
            cfg.ensure_home()
            extract_pending(store, cfg, get_embedder("hash", cfg.embedding_dim))
            memories = store.list_memories()
            if not memories:
                return False, "extraction produced nothing to review"
            if not all(m.needs_review for m in memories):
                return False, "a bot-derived memory was born without review"
        return True, "ok"
    finally:
        restore()


def _slack_env():
    import httpx

    tests_dir = Path(__file__).resolve().parents[2] / "tests"
    if str(tests_dir) not in sys.path:
        sys.path.insert(0, str(tests_dir))
    from slack_mock import FakeSlackAPI

    from twin.connectors.slack import client as slclient

    api = FakeSlackAPI()
    real_build = slclient._build_http

    def fake_build(base_url, token):
        original = real_build(base_url, token)
        headers = dict(original.headers)
        original.close()
        return httpx.Client(transport=api.transport(),
                            base_url="https://slack.com/api/", headers=headers)

    slclient._build_http = fake_build
    return api, (lambda: setattr(slclient, "_build_http", real_build))


def _run_slack_thread_bot_lineage(case: dict) -> tuple[bool, str]:
    api, restore = _slack_env()
    channel = case["channel"]
    exp = case["expected"]
    try:
        with tempfile.TemporaryDirectory(prefix="twin-conn-eval-") as tmp:
            store = SqliteStore(":memory:")
            creds = build_credential_store(Path(tmp))
            acc = register_source_account(
                store, connector_type="slack",
                source_owner=case["source_owner"],
                org_key=case.get("org_key"),
                owner_principal_id="principal_eval",
            )
            inst = add_connector_instance(
                store, creds, account_id=acc.id, secret="xoxb-test-token",
                configuration={"channels": [channel]},
            )
            api.add_channel(channel, name="engineering")
            api.add_message(channel, "1700000001.000100",
                            text="Should we use Redis for the queue?",
                            reply_count=1)
            api.add_reply(channel, "1700000001.000100", "1700000001.000200",
                          text="Prefer PostgreSQL advisory locks.")
            api.add_message(channel, "1700000002.000100",
                            text="GitHub: PR #8 opened in acme/atlas",
                            user="U_BOT", bot_id="B1", subtype="bot_message")
            for m in api.messages[channel]:
                if m["ts"] == "1700000001.000100":
                    m["reply_count"] = 1
            sync_connector(store, creds, inst.id)

            records = store.list_connector_records(inst.id)
            human = [r for r in records
                     if r.external_type in ("message", "thread_reply")
                     and r.source_metadata.get("author_kind") == "human"]
            if len(human) < 2:
                return False, f"expected root+reply, got {len(human)} human records"
            if any(r.thread_key != exp["thread_key"] for r in human):
                return False, "thread items do not share one thread_key"
            bots = [r for r in records
                    if r.source_metadata.get("author_kind") == "bot"]
            if not bots:
                return False, "bot notification missing"
            bot = bots[0]
            if bot.confidentiality["source_trust"] != exp["bot_trust"]:
                return False, "bot trust not calibrated"
            if bot.source_metadata.get("derived") != exp["derived"]:
                return False, "bot not marked derived"
            percepts = store.list_percepts()
            if not percepts or any(p.metadata.get("vault_id") != exp["vault_id"]
                                   for p in percepts):
                return False, "ownership not sealed on every percept"
        return True, "ok"
    finally:
        restore()


def _gmail_env():
    import httpx

    tests_dir = Path(__file__).resolve().parents[2] / "tests"
    if str(tests_dir) not in sys.path:
        sys.path.insert(0, str(tests_dir))
    from gmail_mock import FakeGmailAPI
    from twin.connectors.gmail import client as gclient

    api = FakeGmailAPI()
    real_build = gclient._build_http

    def fake_build(base_url, token):
        original = real_build(base_url, token)
        headers = dict(original.headers)
        original.close()
        return httpx.Client(
            transport=api.transport(),
            base_url="https://gmail.googleapis.com/gmail/v1/",
            headers=headers,
        )

    gclient._build_http = fake_build
    return api, (lambda: setattr(gclient, "_build_http", real_build))


def _calendar_env():
    import httpx
    from calendar_mock import FakeCalendarAPI
    from twin.connectors.calendar import client as cclient

    api = FakeCalendarAPI()
    real_build = cclient._build_http

    def fake_build(base_url, token):
        original = real_build(base_url, token)
        headers = dict(original.headers)
        original.close()
        return httpx.Client(
            transport=api.transport(),
            base_url="https://www.googleapis.com/calendar/v3/",
            headers=headers,
        )

    cclient._build_http = fake_build
    return api, (lambda: setattr(cclient, "_build_http", real_build))


def _fireflies_env():
    import httpx
    from fireflies_mock import FakeFirefliesAPI
    from twin.connectors.fireflies import client as fclient

    api = FakeFirefliesAPI()
    real_build = fclient._build_http

    def fake_build(base_url, token):
        original = real_build(base_url, token)
        headers = dict(original.headers)
        original.close()
        return httpx.Client(
            transport=api.transport(),
            base_url="https://api.fireflies.ai/graphql",
            headers=headers,
        )

    fclient._build_http = fake_build
    return api, (lambda: setattr(fclient, "_build_http", real_build))


def _run_calendar_meeting_correlation(case: dict) -> tuple[bool, str]:
    """Calendar + Fireflies share fingerprint; summary derived; speaker unresolved."""
    import sys
    tests_dir = Path(__file__).resolve().parents[2] / "tests"
    if str(tests_dir) not in sys.path:
        sys.path.insert(0, str(tests_dir))

    cal_api, restore_cal = _calendar_env()
    ff_api, restore_ff = _fireflies_env()
    exp = case["expected"]
    try:
        with tempfile.TemporaryDirectory(prefix="twin-conn-eval-") as tmp:
            store = SqliteStore(":memory:")
            creds = build_credential_store(Path(tmp))
            cal_acc = register_source_account(
                store, connector_type="calendar",
                source_owner=case["source_owner"],
                org_key=case.get("org_key"),
                owner_principal_id="principal_eval",
                external_account_id="edu@acme.com",
            )
            cal_inst = add_connector_instance(
                store, creds, account_id=cal_acc.id, secret="ya29.cal-test-token",
                configuration={"calendars": ["primary"]},
            )
            cal_api.add_event(
                "evt_arch_1",
                summary="Architecture sync",
                start="2026-07-15T15:00:00Z",
                hangout_link="https://meet.google.com/abc-defg",
                ical_uid="evt_arch_1@google.com",
            )
            sync_connector(store, creds, cal_inst.id)

            ff_acc = register_source_account(
                store, connector_type="fireflies",
                source_owner=case["source_owner"],
                org_key=case.get("org_key"),
                owner_principal_id="principal_eval",
                external_account_id="edu@acme.com",
            )
            ff_inst = add_connector_instance(
                store, creds, account_id=ff_acc.id, secret="ff-test-token",
            )
            ff_api.add_transcript(
                "mtg_1",
                title="Architecture sync",
                date="2026-07-15T15:00:00Z",
                cal_id="evt_arch_1",
                calendar_id="evt_arch_1",
                sentences=[
                    {"index": 0, "speaker_name": "Speaker 1", "text": "Hello?"},
                    {"index": 1, "speaker_name": "Alice", "speaker_id": "a",
                     "text": "Prefer PostgreSQL advisory locks."},
                ],
                speakers=[{"name": "Alice", "email": "alice@acme.com", "id": "a"}],
                participants=["alice@acme.com"],
                meeting_attendees=[{"name": "Alice", "email": "alice@acme.com"}],
            )
            sync_connector(store, creds, ff_inst.id)

            cal_recs = store.list_connector_records(cal_inst.id)
            if not cal_recs:
                return False, "calendar record missing"
            cal = cal_recs[0]
            ff_recs = store.list_connector_records(ff_inst.id)
            transcripts = [r for r in ff_recs
                           if r.external_type == "meeting_transcript_chunk"]
            summaries = [r for r in ff_recs
                         if r.external_type == "meeting_summary"]
            if not transcripts or not summaries:
                return False, "expected transcript chunk + summary"
            tr, sm = transcripts[0], summaries[0]
            fp_cal = cal.source_metadata.get("correlation_fingerprint")
            fp_tr = tr.source_metadata.get("correlation_fingerprint")
            if not fp_cal or not str(fp_cal).startswith(exp["fingerprint_prefix"]):
                return False, f"bad calendar fingerprint: {fp_cal}"
            if fp_cal != fp_tr:
                return False, f"fingerprint mismatch cal={fp_cal} meet={fp_tr}"
            if cal.source_metadata.get("calendar_event_id") != exp["calendar_event_id"]:
                return False, "calendar_event_id missing on calendar"
            if tr.source_metadata.get("calendar_event_id") != exp["calendar_event_id"]:
                return False, "calendar_event_id missing on meeting"
            if tr.confidentiality.get("source_trust") != exp["transcript_trust"]:
                return False, "transcript trust wrong"
            if sm.confidentiality.get("source_trust") != exp["summary_trust"]:
                return False, "summary trust wrong"
            if sm.source_metadata.get("derived") != exp["derived"]:
                return False, "summary not marked derived"
            if exp["unresolved_speaker"] not in (
                tr.source_metadata.get("unresolved_speakers") or []
            ):
                return False, "Speaker 1 should stay unresolved"
            if cal.external_id != "google_calendar:primary:evt_arch_1":
                return False, f"calendar id not qualified: {cal.external_id}"
            percepts = store.list_percepts()
            if not percepts or any(
                p.metadata.get("vault_id") != exp["vault_id"] for p in percepts
            ):
                return False, "ownership not sealed on every percept"
        return True, "ok"
    finally:
        restore_cal()
        restore_ff()


def _run_gmail_thread_lineage(case: dict) -> tuple[bool, str]:
    api, restore = _gmail_env()
    label = case["label"]
    exp = case["expected"]
    try:
        with tempfile.TemporaryDirectory(prefix="twin-conn-eval-") as tmp:
            store = SqliteStore(":memory:")
            creds = build_credential_store(Path(tmp))
            acc = register_source_account(
                store, connector_type="gmail",
                source_owner=case["source_owner"],
                org_key=case.get("org_key"),
                owner_principal_id="principal_eval",
                external_account_id="edu@acme.com",
            )
            inst = add_connector_instance(
                store, creds, account_id=acc.id, secret="ya29.test-token",
                configuration={"labels": [label]},
            )
            api.add_message(
                "m_root", thread_id="t_arch", subject="Architecture",
                body="Should we use Redis for the queue?",
                from_addr="alice@acme.com",
                internal_date_ms=1700000001000,
            )
            api.add_message(
                "m_reply", thread_id="t_arch", subject="Re: Architecture",
                body="Prefer PostgreSQL advisory locks.",
                from_addr="edu@acme.com",
                internal_date_ms=1700000002000,
                in_reply_to="<m_root@mail.acme.com>",
            )
            api.add_message(
                "m_bot", thread_id="t_gh", subject="[GitHub] PR #8 opened",
                body="opened a pull request in acme/atlas",
                from_addr="notifications@github.com",
                internal_date_ms=1700000003000,
            )
            sync_connector(store, creds, inst.id)

            records = store.list_connector_records(inst.id)
            human = [r for r in records
                     if r.source_metadata.get("author_kind") == "human"
                     and r.thread_key == exp["thread_key"]]
            if len(human) < 2:
                return False, f"expected root+reply, got {len(human)} human records"
            if any(r.source_metadata.get("classification")
                   != exp["classification_human"] for r in human):
                return False, "human classification wrong"
            bots = [r for r in records
                    if r.source_metadata.get("author_kind") == "automated"]
            if not bots:
                return False, "notification missing"
            bot = bots[0]
            if bot.confidentiality["source_trust"] != exp["bot_trust"]:
                return False, "notification trust not calibrated"
            if bot.source_metadata.get("derived") != exp["derived"]:
                return False, "notification not marked derived"
            if bot.source_metadata.get("classification") != exp["classification_bot"]:
                return False, "notification classification wrong"
            percepts = store.list_percepts()
            if not percepts or any(p.metadata.get("vault_id") != exp["vault_id"]
                                   for p in percepts):
                return False, "ownership not sealed on every percept"
        return True, "ok"
    finally:
        restore()


def _run_folder_document_revisions(case: dict) -> tuple[bool, str]:
    """Local folder: ingest → edit revision → delete tombstone + ownership."""
    import tempfile
    from pathlib import Path

    exp = case["expected"]
    with tempfile.TemporaryDirectory(prefix="twin-folder-eval-") as tmp:
        root = Path(tmp) / "shared"
        root.mkdir()
        doc = root / "rfc.md"
        doc.write_text(
            "---\nauthor: Edu\n---\n\n# RFC\n\nDecision: use Postgres.\n",
            encoding="utf-8",
        )
        store = SqliteStore(":memory:")
        creds = build_credential_store(Path(tmp) / "creds")
        acc = register_source_account(
            store, connector_type="folder",
            source_owner=case["source_owner"],
            org_key=case.get("org_key"),
            owner_principal_id="principal_eval",
            external_account_id="local-docs",
        )
        inst = add_connector_instance(
            store, creds, account_id=acc.id, secret=None,
            configuration={"roots": [{
                "id": "eng-docs", "path": str(root),
            }]},
        )
        sync_connector(store, creds, inst.id)
        recs = store.list_connector_records(inst.id)
        chunks = [
            r for r in recs
            if r.external_type == "document_revision_chunk" and not r.deleted
        ]
        manifests = [
            r for r in recs
            if r.external_type == "document_manifest" and not r.deleted
        ]
        if len(chunks) != 1 or len(manifests) != 1:
            return False, (
                f"expected 1 chunk + 1 manifest after ingest, "
                f"got {len(chunks)} chunks / {len(manifests)} manifests"
            )
        rec = chunks[0]
        if rec.source_metadata.get("document_id") != exp["document_id"]:
            return False, f"document id wrong: {rec.source_metadata.get('document_id')}"
        if not str(rec.thread_key).startswith(exp["thread_prefix"]):
            return False, f"thread key wrong: {rec.thread_key}"
        if rec.confidentiality.get("source_trust") != exp["trust"]:
            return False, "document trust not calibrated"
        if "Postgres" not in rec.content:
            return False, "content missing"
        if rec.actor_ids:
            return False, "front-matter author label must not auto-promote to actor_ids"

        doc.write_text(
            "---\nauthor: Edu\n---\n\n# RFC\n\nDecision: use MySQL instead.\n",
            encoding="utf-8",
        )
        sync_connector(store, creds, inst.id)
        revs = store.list_connector_records_for_object(
            inst.id, "document_revision_chunk", f"{exp['document_id']}:chunk:0",
        )
        if len(revs) < 2:
            return False, "edit did not create a new revision"
        if len({r.thread_key for r in revs}) != 1:
            return False, "revisions do not share thread_key"

        doc.unlink()
        sync_connector(store, creds, inst.id)
        latest = store.list_connector_records_for_object(
            inst.id, "document_revision_chunk", f"{exp['document_id']}:chunk:0",
        )[-1]
        if not latest.deleted:
            return False, "delete did not tombstone latest chunk"
        events = store.list_connector_deletion_events(inst.id)
        if not events or not any(e.affected_percept_ids for e in events):
            return False, "deletion event missing affected percepts"
        percepts = store.list_percepts()
        if not percepts or any(
            p.metadata.get("vault_id") != exp["vault_id"] for p in percepts
        ):
            return False, "ownership not sealed on every percept"
    return True, "ok"


def _run_cross_source_work_episode(case: dict) -> tuple[bool, str]:
    """Phase 7: PR + Slack → WorkEpisode; shared independence; temporal conflict."""
    from twin.cognition.correlation import (
        independence_group_for,
        run_correlation_pass,
    )
    from twin.cognition.sessions import ensure_project
    from twin.connectors.models import (
        ConnectorInstance,
        ConnectorRecord,
        ConnectorStatus,
        OwnershipClass,
        SourceAccount,
        idempotency_key,
    )
    from twin.memory.models import FindingType

    exp = case["expected"]
    root = exp["lineage_root"]
    with tempfile.TemporaryDirectory(prefix="twin-corr-eval-") as tmp:
        store = SqliteStore(":memory:")
        ensure_project(store, exp["project_name"], repos=["acme/atlas"])
        acc = SourceAccount(
            id="acct_eval",
            connector_type="github",
            external_account_id="edu",
            owner_principal_id="principal_eval",
            source_owner=OwnershipClass.employer,
            vault_id="vault_work_acme",
            org_key=case.get("org_key"),
        )
        store.insert_source_account(acc)
        inst = ConnectorInstance(
            id="conn_eval",
            connector_type="github",
            account_id=acc.id,
            status=ConnectorStatus.active,
        )
        store.insert_connector_instance(inst)

        def _mk(eid, etype, content, *, actor_ids=None, occurred_at=None, **meta):
            rec = ConnectorRecord(
                connector_id=inst.id,
                source_account_id=acc.id,
                external_type=etype,
                external_id=eid,
                external_revision="1",
                content=content,
                actor_ids=list(actor_ids or ["github:alice"]),
                source_metadata=dict(meta),
                ownership={"vault_id": "vault_work_acme", "source_owner": "employer"},
                occurred_at=occurred_at or "2026-07-10T10:00:00Z",
            )
            rec.idempotency_key = idempotency_key(
                "github", acc.id, etype, eid, "1",
            )
            store.insert_connector_record(rec)
            return rec

        pr = _mk(
            "acme/atlas#8", "pull_request",
            "# Caching\n\nShip Friday with Redis.",
            repo="acme/atlas", lineage_root=root,
            occurred_at="2026-07-10T10:00:00Z",
        )
        slack = _mk(
            "C1.100", "message",
            "Release postponed — see PR #8",
            repo="acme/atlas", lineage_root=root,
            actor_ids=["slack:T:U1"],
            occurred_at="2026-07-11T12:00:00Z",
        )
        bot = _mk(
            "comment-bot", "issue_comment",
            "[bot] Ship Friday with Redis.",
            repo="acme/atlas", lineage_root=root,
            derived="likely_notification", notification_of=root,
            actor_ids=["github:release-bot[bot]"],
            occurred_at="2026-07-10T11:00:00Z",
        )

        g_pr = independence_group_for({
            "source_metadata": pr.source_metadata, "external_id": pr.external_id,
        })
        g_bot = independence_group_for({
            "source_metadata": bot.source_metadata, "external_id": bot.external_id,
        })
        if exp.get("independence_shared") and g_pr != g_bot:
            return False, f"independence groups diverge: {g_pr} vs {g_bot}"

        report = run_correlation_pass(store, connector_ids=[inst.id])
        if report.episodes < 1:
            return False, "no WorkEpisode created"
        episodes = store.list_work_episodes()
        ep = episodes[0]
        if len(ep.source_refs) < exp["min_episode_refs"]:
            return False, f"episode refs {len(ep.source_refs)} < {exp['min_episode_refs']}"
        if ep.vault_id != "vault_work_acme":
            return False, f"episode vault wrong: {ep.vault_id}"
        if not ep.correlation_key:
            return False, "episode missing correlation_key"
        if ep.independence_group != f"lineage:{root}":
            return False, f"bad episode independence_group: {ep.independence_group}"
        if not ep.project_id:
            return False, "episode missing project mapping"
        # Idempotent second pass
        report2 = run_correlation_pass(store, connector_ids=[inst.id])
        if report2.episodes_created != 0:
            return False, "second pass created duplicate episodes"
        findings = store.get_findings(f"episode:{ep.id}", unresolved_only=False)
        if not any(f.type.value == exp["conflict_type"] for f in findings):
            # also accept findings keyed only by type across all open findings
            # when memory_id lookup is empty
            if report.conflicts < 1:
                return False, "expected cross_source_temporal_conflict"
        _ = slack  # retained for lineage in episode source_refs
    return True, "ok"


def _run_ops_health_metrics(case: dict) -> tuple[bool, str]:
    """Phase 9 — health §57 + metrics §58 + setup/preview never ingest."""
    from twin.connectors import (
        backfill_preview,
        compute_connector_metrics,
        connector_health,
        plan_connector_setup,
    )

    with tempfile.TemporaryDirectory(prefix="twin-conn-eval-") as tmp:
        store, creds, acc, inst = _setup(case, tmp)
        result = sync_connector(store, creds, inst.id)
        if result.percepts != case["expected"]["percepts"]:
            return False, f"percepts {result.percepts} != {case['expected']['percepts']}"
        records = store.list_connector_records(inst.id)
        if len(records) != case["expected"]["records"]:
            return False, f"records {len(records)} != {case['expected']['records']}"

        health = connector_health(store, inst.id)
        for key in case["expected"]["health_keys"]:
            if key not in health:
                return False, f"health missing {key}"
        for key in ("schedule_lag_seconds", "checkpoint_age_seconds"):
            if key not in health:
                return False, f"health missing {key}"
        if health.get("health") != "healthy":
            return False, f"health={health.get('health')}"
        if health.get("last_checkpoint_at") is None:
            return False, "last_checkpoint_at missing after sync"
        # lag_seconds is schedule lag — unknown until next_run_at exists
        if health.get("lag_seconds") not in (None, 0):
            return False, f"unexpected lag_seconds={health.get('lag_seconds')}"

        metrics = compute_connector_metrics(store)["connectors"]
        min_fetch = case["expected"]["metrics_min_fetch"]
        if metrics.get("connector_fetch_total", 0) < min_fetch:
            return False, (
                f"connector_fetch_total {metrics.get('connector_fetch_total')} "
                f"< {min_fetch}"
            )
        if "connector_memory_candidates" in metrics:
            return False, "obsolete connector_memory_candidates still present"
        if metrics.get("connector_percepts_total", 0) < min_fetch:
            return False, "connector_percepts_total missing/low"

        before = len(store.list_percepts())
        plan = plan_connector_setup(
            store, connector_type="github", source_owner="employer", org_key="acme",
        )
        if plan.get("ingests") is not False or plan.get("started") is not False:
            return False, "setup plan must not start ingestion"
        preview = backfill_preview(
            store, creds, inst.id, principal_id="principal_eval",
        )
        if preview.get("started") is not False:
            return False, "backfill preview started unexpectedly"
        if len(store.list_percepts()) != before:
            return False, "setup/preview mutated percepts"
        return True, "ok"


_SCENARIOS = {
    "normalization": _run_simple,
    "replay": _run_simple,
    "quarantine": _run_simple,
    "partial_batch": _run_partial_batch,
    "revision_collision": _run_revision_collision,
    "checkpoint_failure": _run_checkpoint_failure,
    "source_deletion": _run_source_deletion,
    "github_pr_lifecycle": _run_github_pr_lifecycle,
    "github_bot_lineage": _run_github_bot_lineage,
    "slack_thread_bot_lineage": _run_slack_thread_bot_lineage,
    "gmail_thread_lineage": _run_gmail_thread_lineage,
    "calendar_meeting_correlation": _run_calendar_meeting_correlation,
    "folder_document_revisions": _run_folder_document_revisions,
    "cross_source_work_episode": _run_cross_source_work_episode,
    "ops_health_metrics": _run_ops_health_metrics,
}


def main() -> int:
    cases = sorted(_CASES.glob("*.json"))
    passed = 0
    for path in cases:
        case = json.loads(path.read_text(encoding="utf-8"))
        runner = _SCENARIOS.get(case.get("scenario", "normalization"), _run_simple)
        try:
            ok, detail = runner(case)
        except Exception as exc:  # an eval crash is a failure, not an abort
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        passed += int(ok)
        print(f"[{'PASS' if ok else 'FAIL'}] {case['id']}: {detail}")
    print(f"\n{passed}/{len(cases)} connector eval cases passed")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
