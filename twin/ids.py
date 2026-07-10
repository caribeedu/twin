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
