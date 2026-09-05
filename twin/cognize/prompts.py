"""Shared Cognize judgment prompts — audience, owner, bar.

Used by raise_reflections, form_interpretations, narrative_revision, and
Stage 10 Stance draft. Mechanical stages (salience / situate / cross / audit)
do not take this block.
"""

from __future__ import annotations

from typing import Any

_SEEKING = (
    "how the owner thinks; which trade-offs they value; what they never want "
    "mixed; which tone they prefer; when privacy beats convenience; when "
    "simplicity beats elegant architecture"
)

_BAR = """Bar — emit an item only if it is:
(a) a catch: contradiction, dropped commitment, quietly building risk, or a question still unresolved as of the latest evidence in this brief;
(b) a dense, self-contained fact useful cold (names, dates, decisions) without the source;
(c) a recurring pattern in how one specific named person operates, evidenced by more than one separate instance — never a single anecdote inflated into a trait;
(d) the owner's own preference, decision style, or trade-off (the primary subject of Stance — not "how the team operates" unless that is all the evidence supports).
Returning fewer items, or zero, is the correct and expected outcome when nothing clears the bar. Do not narrate a period of activity."""


def _dedupe(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in items:
        text = (raw or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def owner_aliases(store: Any, vault_id: str = "") -> list[str]:
    """Connected-account handles for this vault — the owner, not teammates."""
    aliases: list[str] = []
    account_keys: set[str] = set()
    try:
        accounts = store.list_source_accounts() if hasattr(store, "list_source_accounts") else []
    except Exception:
        accounts = []
    for acc in accounts or []:
        vid = str(getattr(acc, "vault_id", "") or "")
        if vault_id and vid and vid != vault_id:
            continue
        name = str(getattr(acc, "display_name", "") or "").strip()
        ext = str(getattr(acc, "external_account_id", "") or "").strip()
        ctype = str(getattr(acc, "connector_type", "") or "").strip()
        if name:
            aliases.append(name)
        if ext:
            account_keys.add(ext.casefold())
            aliases.append(f"{ctype}:{ext}" if ctype else ext)
    try:
        if hasattr(store, "list_external_identities"):
            idents = store.list_external_identities(vault_id=vault_id or None)
        else:
            idents = []
    except TypeError:
        try:
            idents = store.list_external_identities()
        except Exception:
            idents = []
    except Exception:
        idents = []
    for ident in idents or []:
        ext = str(getattr(ident, "external_id", "") or "").strip()
        if ext.casefold() not in account_keys:
            continue
        actor = str(getattr(ident, "actor_id", "") or "").strip()
        if actor:
            aliases.append(actor)
        dn = str(getattr(ident, "display_name", "") or "").strip()
        if dn:
            aliases.append(dn)
        email = str(getattr(ident, "email", "") or "").strip()
        if email:
            aliases.append(email)
    return _dedupe(aliases)


def owner_seeks(store: Any) -> list[str]:
    """Active Stance statements — what the owner already evaluates by."""
    out: list[str] = []
    try:
        items = (
            store.list_judgment_items(status="active", limit=8)
            if hasattr(store, "list_judgment_items")
            else []
        )
    except TypeError:
        try:
            items = store.list_judgment_items()
        except Exception:
            items = []
    except Exception:
        items = []
    for item in items or []:
        st = getattr(item, "status", None)
        val = st.value if hasattr(st, "value") else str(st or "")
        if val and val not in ("active", "approved"):
            continue
        stmt = str(getattr(item, "statement", "") or "").strip()
        if stmt:
            out.append(stmt[:240])
        if len(out) >= 8:
            break
    return out


def judgment_purpose(store: Any, vault_id: str = "") -> str:
    aliases = owner_aliases(store, vault_id)
    seeks = owner_seeks(store)
    who = (
        "Owner identity (who you are modeling — not a teammate who happens to recur):\n"
        + "\n".join(f"- {a}" for a in aliases)
        if aliases
        else (
            "Owner identity handles are unknown this run. Still treat first-person "
            "and self-attributed acts in the brief as the owner's; never fold them "
            "into \"the team.\""
        )
    )
    want = (
        "What the owner already holds as Stance (what they seek / how they evaluate):\n"
        + "\n".join(f"- {s}" for s in seeks)
        if seeks
        else f"No confirmed Stance yet. Look for: {_SEEKING}."
    )
    return (
        "You are Cognize for this Twin vault. Readers: (1) the account owner; "
        "(2) later models that will see only this output, never the source percepts again.\n"
        f"{who}\n"
        f"{want}\n"
        f"{_BAR}"
    )


REFLECTION_ADDENDUM = """Raise Reflections. You have autonomy to mark a Reflection answered when later percepts in this brief settle it — that correlation is required, not optional.

An answered Reflection is not news and must not be analyzed as a new open question. Still emit it with status=answered, answered_rationale, and answered_by_percept_ids so later stages can correlate other work against the settlement.

Only status=open is an unresolved gap (Review). JSON:
{"reflections":[{"text":"...","status":"open|answered","answered_rationale":"...","answered_by_percept_ids":["percept id"]}]}
Each text must be only the question itself — no preamble."""


INTERPRETATION_ADDENDUM = """Form competing explanations of the same ambiguous evidence — not one Interpretation per Situation theme. Use answered Reflections as correlation context, not as puzzles to re-open.

JSON: {"interpretations":[{"explanation":"...","evidence_percept_ids":["..."],"why_it_matters":"..."}]}
why_it_matters is the stake for the owner (or a named person), not a summary of activity."""


REVISION_ADDENDUM = """Decide how new interpretations revise prior Narratives. Prefer the owner's evaluative posture over team-level restatement.

JSON: {"outcome":"integrate|branch|contradict|supersede|keep_separate|defer","surprise":"low|medium|high","explanatory_delta":"...","rationale":"...","retained_dissent_ids":["<interpretation id from the list>"]}"""


STANCE_DRAFT_ADDENDUM = """Draft a durable evaluative Stance from a Narrative. Stance answers how THIS owner evaluates trade-offs, not what happened.

If the Narrative is substantially the owner's own acts or decisions, write the statement as their posture. If it is only a team pattern, say so — do not pretend it is the owner's preference. Do not restate the Narrative account.

Return JSON {statement, rationale}."""


def judgment_system(store: Any, vault_id: str, addendum: str) -> str:
    return judgment_purpose(store, vault_id) + "\n\n" + addendum.strip()
