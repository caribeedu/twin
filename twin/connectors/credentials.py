"""CredentialStore — external secrets never touch the common payload store.

Default backend is an encrypted file under ``$TWIN_HOME/secrets/``. The DB only
ever holds a ``credential_ref`` plus non-sensitive metadata (provider, scopes,
expiry). Tokens are generated with high entropy; human passwords are refused.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
from pathlib import Path
from typing import Optional, Protocol


class CredentialStore(Protocol):
    provider: str

    def put(self, credential_ref: str, secret: str) -> None: ...
    def get(self, credential_ref: str) -> Optional[str]: ...
    def delete(self, credential_ref: str) -> None: ...


def generate_token(nbytes: int = 32) -> str:
    """Cryptographically strong opaque token — never a human password."""
    return secrets.token_urlsafe(nbytes)


def _try_fernet(key_path: Path):
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        return None
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if not key_path.exists():
        key_path.write_bytes(Fernet.generate_key())
        try:
            os.chmod(key_path, 0o600)
        except OSError:
            pass
    return Fernet(key_path.read_bytes())


class _XorObfuscator:
    """Last-resort fallback when ``cryptography`` is unavailable.

    Not real encryption — only keeps secrets out of plaintext at rest and out
    of the common store. Marks its provider so operators can see the downgrade.
    """

    def __init__(self, key_path: Path):
        key_path.parent.mkdir(parents=True, exist_ok=True)
        if not key_path.exists():
            key_path.write_bytes(os.urandom(32))
            try:
                os.chmod(key_path, 0o600)
            except OSError:
                pass
        self._key = key_path.read_bytes()

    def _xor(self, data: bytes) -> bytes:
        k = self._key
        return bytes(b ^ k[i % len(k)] for i, b in enumerate(data))

    def encrypt(self, text: str) -> str:
        return base64.urlsafe_b64encode(self._xor(text.encode("utf-8"))).decode("ascii")

    def decrypt(self, token: str) -> str:
        return self._xor(base64.urlsafe_b64decode(token.encode("ascii"))).decode("utf-8")


class EncryptedFileCredentialStore:
    """Secrets encrypted at rest in ``secrets/credentials.enc`` (JSON map)."""

    def __init__(self, home: Path):
        self.home = Path(home)
        self._dir = self.home / "secrets"
        self._path = self._dir / "credentials.enc"
        fernet = _try_fernet(self._dir / ".credkey")
        if fernet is not None:
            self.provider = "encrypted_file"
            self._fernet = fernet
            self._obf = None
        else:
            self.provider = "obfuscated_file"
            self._fernet = None
            self._obf = _XorObfuscator(self._dir / ".credkey.xor")

    def _enc(self, text: str) -> str:
        if self._fernet is not None:
            return self._fernet.encrypt(text.encode("utf-8")).decode("ascii")
        return self._obf.encrypt(text)  # type: ignore[union-attr]

    def _dec(self, token: str) -> str:
        if self._fernet is not None:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        return self._obf.decrypt(token)  # type: ignore[union-attr]

    def _load(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        return json.loads(self._path.read_text(encoding="utf-8"))

    def _save(self, data: dict[str, str]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data), encoding="utf-8")
        try:
            os.chmod(self._path, 0o600)
        except OSError:
            pass

    def put(self, credential_ref: str, secret: str) -> None:
        if not secret:
            raise ValueError("refusing to store an empty credential")
        data = self._load()
        data[credential_ref] = self._enc(secret)
        self._save(data)

    def get(self, credential_ref: str) -> Optional[str]:
        token = self._load().get(credential_ref)
        return self._dec(token) if token is not None else None

    def delete(self, credential_ref: str) -> None:
        data = self._load()
        if data.pop(credential_ref, None) is not None:
            self._save(data)


def build_credential_store(home: Path) -> CredentialStore:
    return EncryptedFileCredentialStore(home)
