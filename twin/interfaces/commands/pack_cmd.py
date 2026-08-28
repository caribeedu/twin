"""Context-pack CLI handler."""

from __future__ import annotations

from typing import Any


def build_pack(ws, args) -> Any:
    from twin.inject.context_pack import build_context_pack
    from twin.privacy.identity import ensure_local_identity, resolve_access
    from twin.privacy.yaml_io import bootstrap_policy_set

    persona = getattr(args, "persona", None) or "individual"
    domain = getattr(args, "domain", None) or "technical"
    bootstrap_policy_set(ws.store, policies_path=ws.cfg.policies_path)
    ensure_local_identity(ws.store)
    access = resolve_access(
        ws.store,
        surface="cli",
        client="local-cli",
        persona=persona,
        purpose=getattr(args, "purpose", None) or "context_retrieval",
        audience=getattr(args, "audience", None) or "self",
        requested_domains=[args.domain] if getattr(args, "domain", None) else [],
    )
    return build_context_pack(
        ws.store,
        ws.cfg,
        ws.embedder,
        args.query,
        target_domain=domain,
        max_tokens=args.max_tokens,
        include_candidates=args.include_candidates,
        firewall=ws.firewall,
        access=access,
    )
