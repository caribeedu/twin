"""Optional local encryption at rest.

When ``TWIN_ENCRYPTION_KEY`` is set (and the ``cryptography`` package is
installed), the raw text the system holds — percept content and verbatim
evidence quotes — is encrypted before touching the store and decrypted on
read. Memory titles/summaries stay plaintext on purpose: they are the
distilled, searchable layer (FTS needs them), while the raw captured text is
where the real exposure lives.

Key derivation: PBKDF2-HMAC-SHA256 over the passphrase with a random per-home
salt (``~/.twin/.salt``). Ciphertext is prefixed with ``enc1:`` so plaintext
written before encryption was enabled keeps working (read-through).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

_PREFIX = "enc1:"


class ContentCodec(Protocol):
    def encrypt(self, text: str) -> str: ...
    def decrypt(self, text: str) -> str: ...


class NullCodec:
    def encrypt(self, text: str) -> str:
        return text

    def decrypt(self, text: str) -> str:
        return text


class FernetCodec:
    def __init__(self, passphrase: str, salt_path: Path):
        import base64

        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives.hashes import SHA256
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

        salt_path.parent.mkdir(parents=True, exist_ok=True)
        if not salt_path.exists():
            salt_path.write_bytes(os.urandom(16))
        salt = salt_path.read_bytes()
        kdf = PBKDF2HMAC(algorithm=SHA256(), length=32, salt=salt, iterations=600_000)
        key = base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))
        self._fernet = Fernet(key)

    def encrypt(self, text: str) -> str:
        return _PREFIX + self._fernet.encrypt(text.encode("utf-8")).decode("ascii")

    def decrypt(self, text: str) -> str:
        if not text.startswith(_PREFIX):
            return text  # written before encryption was enabled
        return self._fernet.decrypt(text[len(_PREFIX):].encode("ascii")).decode("utf-8")


def build_codec(passphrase: str, home: Path) -> ContentCodec:
    if not passphrase:
        return NullCodec()
    try:
        return FernetCodec(passphrase, home / ".salt")
    except ImportError as exc:
        raise RuntimeError(
            "TWIN_ENCRYPTION_KEY is set but the 'cryptography' package is not "
            "installed. Run: pip install 'twin[crypto]'"
        ) from exc
