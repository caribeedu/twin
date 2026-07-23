"""Prefixed, sortable identifiers (mem_..., src_..., ent_...)."""

import secrets
import time

_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"  # crockford-ish, unambiguous


def _base32(value: int, length: int) -> str:
    out = []
    for _ in range(length):
        out.append(_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(out))


def new_id(prefix: str) -> str:
    """Time-ordered id: <prefix>_<48-bit ms timestamp><40-bit random>."""
    ts = int(time.time() * 1000)
    rand = secrets.randbits(40)
    return f"{prefix}_{_base32(ts, 10)}{_base32(rand, 8)}"


def memory_id() -> str:
    return new_id("mem")


def source_id() -> str:
    return new_id("src")


def entity_id() -> str:
    return new_id("ent")


def evidence_id() -> str:
    return new_id("ev")


def relation_id() -> str:
    return new_id("rel")


def project_id() -> str:
    return new_id("proj")


def session_id() -> str:
    return new_id("ses")


def artifact_id() -> str:
    return new_id("art")


def finding_id() -> str:
    return new_id("rf")


def review_batch_id() -> str:
    return new_id("rb")


def operation_id() -> str:
    return new_id("op")


def eval_run_id() -> str:
    return new_id("eval")


def judgment_id() -> str:
    return new_id("jud")


def judgment_proposal_id() -> str:
    return new_id("jprop")


def judgment_version_id() -> str:
    return new_id("jver")


def judgment_snapshot_id() -> str:
    return new_id("jsnap")


def judgment_conflict_id() -> str:
    return new_id("jconf")


def judgment_trace_id() -> str:
    return new_id("jtrace")


def judgment_exception_id() -> str:
    return new_id("jexc")


def judgment_revision_id() -> str:
    return new_id("jrev")


def tradeoff_id() -> str:
    return new_id("toff")


def host_session_binding_id() -> str:
    return new_id("hsb")


def runtime_job_id() -> str:
    return new_id("rjob")


def worker_lease_id() -> str:
    return new_id("wlease")


def dead_letter_id() -> str:
    return new_id("rdlq")


def session_event_id() -> str:
    return new_id("sevt")


def session_checkpoint_id() -> str:
    return new_id("schk")


def session_closure_id() -> str:
    return new_id("scls")


def attention_emission_id() -> str:
    return new_id("attn")
