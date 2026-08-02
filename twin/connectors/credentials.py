"""CredentialStore — external secrets never touch the common payload store.

Default backend is an encrypted file under ``$TWIN_HOME/secrets/``. The DB only
ever holds a ``credential_ref`` plus non-sensitive metadata (provider, scopes,
expiry). Tokens are generated with high entropy; human passwords are refused.

Security posture is fail-closed on every axis:

- no real encryption backend (``cryptography`` missing) → the store refuses
  to exist and a connector cannot be configured;
- credential files exist but none is readable/decryptable → operations raise
  ``CredentialStoreCorrupted`` instead of silently reinitializing an empty
  map (which would erase every stored secret on the next ``put``).

Concurrency/durability (twin is local-first and must behave on Windows too):

- every mutation holds an exclusive cross-platform file lock — ``fcntl`` on
  POSIX, ``msvcrt.locking`` on Windows; if neither exists the store refuses
  to operate rather than running lockless;
- writes go to a temp file unique per PID/UUID (two writers can never clobber
  each other's temp), are fsynced, validated (JSON *and* decryptability),
  and atomically replace the target; the directory is fsynced after;
- the last known-good file is preserved as ``credentials.enc.bak`` and is
  only ever overwritten by a file that was itself loaded as valid — a
  corrupted main file is never copied over a healthy backup.
"""

from __future__ import annotations

import errno
import json
import os
import secrets
import shutil
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Protocol


class CredentialStore(Protocol):
    provider: str

    def put(self, credential_ref: str, secret: str) -> None: ...
    def get(self, credential_ref: str) -> Optional[str]: ...
    def delete(self, credential_ref: str) -> None: ...


class CredentialBackendUnavailable(RuntimeError):
    """No real encryption/locking backend — connectors cannot be configured."""


class CredentialLockTimeout(RuntimeError):
    """Could not acquire the credential-store lock within the deadline."""


class CredentialStoreCorrupted(RuntimeError):
    """Credential files exist but none is valid. Refusing to reinitialize —
    a fresh empty map would silently erase every stored secret."""


def generate_token(nbytes: int = 32) -> str:
    """Cryptographically strong opaque token — never a human password."""
    return secrets.token_urlsafe(nbytes)


def _build_fernet(key_path: Path):
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:  # fail closed — never degrade to obfuscation
        raise CredentialBackendUnavailable(
            "credential encryption backend unavailable: the 'cryptography' "
            "package is not installed. Install it (pip install \"twin-cognition[crypto]\") "
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


# -- cross-platform advisory file lock ------------------------------------------

LOCK_TIMEOUT_SECONDS = 30.0
_LOCK_POLL_SECONDS = 0.05

# errno values Windows uses for "the region is locked by someone else" —
# anything outside this set is a permanent failure (bad descriptor, denied
# permission, I/O error, incompatible filesystem) and must raise, never spin
_CONTENTION_ERRNOS = frozenset(
    getattr(errno, name) for name in ("EACCES", "EAGAIN", "EDEADLK")
    if hasattr(errno, name)
)


def _lock_fd(fd: int, timeout_seconds: Optional[float] = None) -> str:
    """Acquire an exclusive lock on ``fd``. POSIX uses fcntl (blocking flock
    is fine for a local store); Windows uses non-blocking msvcrt attempts
    under an explicit deadline. No silent lockless mode: if neither backend
    exists, refuse.

    Contention waits (bounded by ``timeout_seconds``, default
    LOCK_TIMEOUT_SECONDS → CredentialLockTimeout); any other OSError is a
    permanent backend failure and raises immediately — it never turns into
    an infinite retry loop."""
    if timeout_seconds is None:
        timeout_seconds = LOCK_TIMEOUT_SECONDS
    try:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX)
        return "fcntl"
    except ImportError:
        pass
    try:
        import msvcrt
    except ImportError:
        raise CredentialBackendUnavailable(
            "no file-locking backend available (fcntl/msvcrt); refusing to "
            "run the credential store without mutual exclusion"
        )
    deadline = time.monotonic() + timeout_seconds
    while True:
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            # non-blocking probe → the timeout is ours, not msvcrt's
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return "msvcrt"
        except OSError as exc:
            if exc.errno not in _CONTENTION_ERRNOS:
                raise CredentialBackendUnavailable(
                    f"credential lock failed permanently: "
                    f"[errno {exc.errno}] {exc.strerror or exc}"
                ) from exc
            if time.monotonic() >= deadline:
                raise CredentialLockTimeout(
                    f"timed out after {timeout_seconds:.0f}s acquiring the "
                    "credential store lock — another process is holding it"
                ) from exc
            time.sleep(_LOCK_POLL_SECONDS)


def _unlock_fd(fd: int, backend: str) -> None:
    if backend == "fcntl":
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)
    elif backend == "msvcrt":
        import msvcrt
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


@contextmanager
def _file_lock(lock_path: Path):
    """Exclusive advisory lock so concurrent writers serialize, not clobber.
    Works across processes on POSIX and Windows."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
    try:  # msvcrt locks a byte range — make sure byte 0 exists
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"\0")
            os.lseek(fd, 0, os.SEEK_SET)
    except OSError:
        pass
    backend = None
    try:
        backend = _lock_fd(fd)
        yield
    finally:
        if backend:
            try:
                _unlock_fd(fd, backend)
            except OSError:
                pass
        os.close(fd)


def _atomic_write(path: Path, text: str) -> Path:
    """Write to a temp file unique per PID/UUID, fsync, atomically replace,
    fsync the directory. Returns the final path."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)
    finally:
        if tmp.exists():  # failed before replace — never leave secrets around
            try:
                tmp.unlink()
            except OSError:
                pass
    try:
        dfd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass
    return path


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

    def _try_read(self, path: Path) -> Optional[dict[str, str]]:
        """A file only counts as valid when it parses AND every stored
        ciphertext decrypts — truncated JSON and corrupted tokens are both
        detected, never half-trusted."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return None
            for value in data.values():
                self._dec(value)
            return data
        except Exception:
            return None

    def _load(self) -> tuple[dict[str, str], str]:
        """Returns (data, source) with source in {"main", "backup", "empty"}.

        Raises CredentialStoreCorrupted when files exist but none is valid —
        an empty map is only ever the state of a store that never had one."""
        main_exists = self._path.exists()
        bak_exists = self._bak.exists()
        if main_exists:
            data = self._try_read(self._path)
            if data is not None:
                return data, "main"
        if bak_exists:
            data = self._try_read(self._bak)
            if data is not None:
                return data, "backup"
        if main_exists or bak_exists:
            raise CredentialStoreCorrupted(
                f"credential files at {self._dir} exist but none is readable/"
                "decryptable; refusing to reinitialize an empty store — "
                "restore credentials.enc(.bak) from a backup or remove them "
                "explicitly after rotating every connector credential"
            )
        return {}, "empty"

    def _save(self, data: dict[str, str], loaded_from: str) -> None:
        """Persist, preserving the last known-good file.

        Only a main file that was itself loaded as valid may become the
        backup. When recovery came from the backup, the corrupted main is
        NEVER copied over it — the healthy backup survives until a new valid
        main has been written."""
        self._dir.mkdir(parents=True, exist_ok=True)
        if loaded_from == "main" and self._path.exists():
            try:
                shutil.copy2(self._path, self._bak)
                os.chmod(self._bak, 0o600)
            except OSError:
                pass
        text = json.dumps(data)
        final = _atomic_write(self._path, text)
        # paranoia: the file we just wrote must itself load as valid
        if self._try_read(final) is None:
            raise CredentialStoreCorrupted(
                "freshly written credential file failed validation; the "
                "previous known-good state was preserved"
            )

    def put(self, credential_ref: str, secret: str) -> None:
        if not secret:
            raise ValueError("refusing to store an empty credential")
        with _file_lock(self._lockfile):
            data, source = self._load()
            data[credential_ref] = self._enc(secret)
            self._save(data, source)

    def get(self, credential_ref: str) -> Optional[str]:
        with _file_lock(self._lockfile):
            data, _source = self._load()
            token = data.get(credential_ref)
        return self._dec(token) if token is not None else None

    def delete(self, credential_ref: str) -> None:
        with _file_lock(self._lockfile):
            data, source = self._load()
            if data.pop(credential_ref, None) is not None:
                self._save(data, source)


def build_credential_store(home: Path) -> CredentialStore:
    """Fail-closed factory: raises CredentialBackendUnavailable when no real
    encryption backend exists — a connector can then not be configured."""
    return EncryptedFileCredentialStore(home)
