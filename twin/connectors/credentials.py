"""CredentialStore — external secrets never touch the common payload store.

Default backend is an encrypted file under ``$TWIN_HOME/secrets/``. The DB only
ever holds a ``credential_ref`` plus non-sensitive metadata (provider, scopes,
expiry). Tokens are generated with high entropy; human passwords are refused.

Security posture is fail-closed: if no real encryption backend is available
(``cryptography`` missing), the store refuses to exist — a connector cannot be
configured. There is no reversible-obfuscation fallback; a silent downgrade
would turn "credentials encrypted at rest" into a false claim.

Concurrency/durability: every mutation takes an exclusive file lock, writes to
a temp file, fsyncs, atomically replaces the target and fsyncs the directory.
The previous version is kept as ``credentials.enc.bak`` so an interrupted or
corrupted write never loses the earlier secrets.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Protocol


class CredentialStore(Protocol):
    provider: str

    def put(self, credential_ref: str, secret: str) -> None: ...
    def get(self, credential_ref: str) -> Optional[str]: ...
    def delete(self, credential_ref: str) -> None: ...


class CredentialBackendUnavailable(RuntimeError):
    """No real encryption backend — connectors cannot be configured."""


def generate_token(nbytes: int = 32) -> str:
    """Cryptographically strong opaque token — never a human password."""
    return secrets.token_urlsafe(nbytes)


def _build_fernet(key_path: Path):
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:  # fail closed — never degrade to obfuscation
        raise CredentialBackendUnavailable(
            "credential encryption backend unavailable: the 'cryptography' "
            "package is not installed. Install it (pip install \"twin[crypto]\") "
            "or use an OS keyring; twin will not store connector credentials "
            "without real encryption."
        ) from exc
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if not key_path.exists():
        key_path.write_bytes(Fernet.generate_key())
        try:
            os.chmod(key_path, 0o600)
        except OSError:
            pass
    return Fernet(key_path.read_bytes())


@contextmanager
def _file_lock(lock_path: Path):
    """Exclusive advisory lock so concurrent writers serialize, not clobber."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)
        except ImportError:  # non-POSIX: fall back to O_CREAT lock semantics
            pass
        yield
    finally:
        try:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
        except ImportError:
            pass
        os.close(fd)


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)
    # fsync the directory so the rename itself is durable
    try:
        dfd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass


class EncryptedFileCredentialStore:
    """Secrets encrypted at rest in ``secrets/credentials.enc`` (JSON map)."""

    provider = "encrypted_file"

    def __init__(self, home: Path):
        self.home = Path(home)
        self._dir = self.home / "secrets"
        self._path = self._dir / "credentials.enc"
        self._bak = self._dir / "credentials.enc.bak"
        self._lockfile = self._dir / "credentials.lock"
        self._fernet = _build_fernet(self._dir / ".credkey")

    def _enc(self, text: str) -> str:
        return self._fernet.encrypt(text.encode("utf-8")).decode("ascii")

    def _dec(self, token: str) -> str:
        return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")

    def _load(self) -> dict[str, str]:
        for candidate in (self._path, self._bak):
            if not candidate.exists():
                continue
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except (json.JSONDecodeError, OSError):
                # corrupted main file → previous version stays recoverable
                continue
        return {}

    def _save(self, data: dict[str, str]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        if self._path.exists():
            try:
                shutil.copy2(self._path, self._bak)
                os.chmod(self._bak, 0o600)
            except OSError:
                pass
        _atomic_write(self._path, json.dumps(data))

    def put(self, credential_ref: str, secret: str) -> None:
        if not secret:
            raise ValueError("refusing to store an empty credential")
        with _file_lock(self._lockfile):
            data = self._load()
            data[credential_ref] = self._enc(secret)
            self._save(data)

    def get(self, credential_ref: str) -> Optional[str]:
        with _file_lock(self._lockfile):
            token = self._load().get(credential_ref)
        return self._dec(token) if token is not None else None

    def delete(self, credential_ref: str) -> None:
        with _file_lock(self._lockfile):
            data = self._load()
            if data.pop(credential_ref, None) is not None:
                self._save(data)


def build_credential_store(home: Path) -> CredentialStore:
    """Fail-closed factory: raises CredentialBackendUnavailable when no real
    encryption backend exists — a connector can then not be configured."""
    return EncryptedFileCredentialStore(home)
