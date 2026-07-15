"""GitHub webhook receiver support (v0.6 §24).

A webhook is a *hint*, never a source of truth: the only effect of a valid
delivery is nudging the scheduler (``next_run_at = now`` plus a
``targeted_streams`` hint) so the authoritative polling path fetches the
change. The payload is never normalized, never persisted as a record and
never becomes canonical state — a forged or replayed body can at worst
trigger one extra poll of data the connector was already authorized to read.

Authentication is HMAC (``X-Hub-Signature-256``) against a *dedicated*
webhook secret kept in the CredentialStore — never the API token — with a
uniform 401 for every failure mode so the endpoint leaks neither connector
existence nor configuration state.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Optional

from ...clock import now_iso
from ..models import ConnectorSyncState

# GitHub event name → stream family the poller should visit.
EVENT_FAMILIES = {
    "issues": "issues",
    "issue_comment": "issues",
    "pull_request": "pulls",
    "pull_request_review": "pulls",
    "pull_request_review_comment": "pulls",
    "check_suite": "pulls",
    "check_run": "pulls",
    "status": "pulls",
    "push": "commits",
    "release": "releases",
}


class WebhookRejected(Exception):
    def __init__(self, status_code: int, reason: str):
        super().__init__(reason)
        self.status_code = status_code
        self.reason = reason


def verify_signature(secret: str, body: bytes, signature: Optional[str]) -> bool:
    if not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def targeted_streams(event: str, payload: dict[str, Any],
                     configured_repos: set[str]) -> list[str]:
    """Translate one delivery into the streams the poller should visit.
    Only repositories the instance is already configured for count — a
    webhook can never widen the connector's scope."""
    family = EVENT_FAMILIES.get(event)
    repo = (payload.get("repository") or {}).get("full_name")
    if not family or not repo or repo not in configured_repos:
        return []
    streams = [f"repo:{repo}:{family}"]
    # a comment on a pull request arrives as issue_comment with a marker
    if event == "issue_comment" and (payload.get("issue") or {}).get("pull_request"):
        streams = [f"repo:{repo}:pulls"]
    return streams


def set_webhook_secret(store, credentials, connector_id: str,
                       secret: str) -> str:
    """Store a dedicated webhook secret (never the API token) and remember
    its ref in ``configuration["webhook_secret_ref"]``. Compensable: a
    failure leaves no orphan secret and no dangling ref."""
    from ..models import CredentialRef

    instance = store.get_connector_instance(connector_id)
    if instance is None:
        raise ValueError(f"connector {connector_id} not found")
    ref = CredentialRef(provider=getattr(credentials, "provider", "encrypted_file"),
                        scopes=["webhook:verify"])
    store.insert_credential_ref(ref)
    try:
        credentials.put(ref.id, secret)
        config = dict(instance.configuration or {})
        old_ref = config.get("webhook_secret_ref")
        config["webhook_secret_ref"] = ref.id
        store.update_connector_instance(connector_id, configuration=config)
    except Exception:
        try:
            credentials.delete(ref.id)
        except Exception:
            pass
        try:
            store.delete_credential_ref(ref.id)
        except Exception:
            pass
        raise
    if old_ref:
        # rotation: best-effort cleanup of the previous secret
        try:
            credentials.delete(old_ref)
            store.delete_credential_ref(old_ref)
        except Exception:
            pass
    return ref.id


def handle_github_webhook(
    store, credentials, connector_id: str, *,
    event: Optional[str], body: bytes, signature: Optional[str],
) -> dict[str, Any]:
    """Validate one delivery and, if genuine, mark the sync state as due.

    Every rejection is a uniform 401 — the endpoint must not reveal whether
    the connector exists, is a GitHub connector, or has a webhook secret."""
    instance = store.get_connector_instance(connector_id)
    if instance is None or instance.connector_type != "github":
        raise WebhookRejected(401, "unknown or unauthorized webhook target")
    ref = (instance.configuration or {}).get("webhook_secret_ref")
    secret = None
    if ref:
        try:
            secret = credentials.get(ref)
        except Exception:
            secret = None
    if not secret:
        raise WebhookRejected(401, "unknown or unauthorized webhook target")
    if not verify_signature(secret, body, signature):
        raise WebhookRejected(401, "unknown or unauthorized webhook target")

    try:
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("payload must be a JSON object")
    except (ValueError, UnicodeDecodeError):
        raise WebhookRejected(400, "invalid JSON payload")

    repos = set((instance.configuration or {}).get("repositories") or [])
    streams = targeted_streams(event or "", payload, repos)
    if not streams:
        return {"scheduled": [], "detail": "event not mapped to a configured stream"}

    state = store.get_connector_sync_state(connector_id) \
        or ConnectorSyncState(id=connector_id)
    state.next_run_at = now_iso()
    meta = dict(state.metadata or {})
    hinted = set(meta.get("targeted_streams") or [])
    meta["targeted_streams"] = sorted(hinted | set(streams))
    meta["last_webhook_event"] = event  # the event NAME only, never the payload
    state.metadata = meta
    state.updated_at = now_iso()
    store.upsert_connector_sync_state(state)
    return {"scheduled": streams}
