"""Git Sensor — commits, branch and repository metadata.

Points at a working copy and emits one percept per recent commit. The
artifact is the commit itself (referenced by sha in ``content_refs``); the
percept is the normalized observation; memories are extracted downstream.

Dedup is natural but identity-aware: the dedup key combines a stable
repository identity (canonical remote URL when available, otherwise a hash
of the toplevel path) with the commit sha — two clones of the same remote
dedupe together, while two unrelated repositories that happen to share a
directory basename never collide.

The sensor never claims a commit was *created* on a branch: it only knows
which branch the worktree had checked out at collection time, recorded as
``observed_from_branch``.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Iterable

from ...clock import now_iso
from ..base import Sensor
from ..percept import Percept

# record separator leads and the body is closed with a unit separator, so the
# --name-only file list (git prints it after the format) stays in its record
_LOG_FORMAT = "%x1e%H%x1f%an%x1f%aI%x1f%s%x1f%b%x1f"
DEFAULT_COMMIT_LIMIT = 50


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, timeout=30,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or f"git {' '.join(args)} failed")
    return out.stdout


def _normalize_remote(url: str) -> str:
    """Canonical form of a remote URL: scheme/credentials/.git stripped,
    lowercased — https/ssh/user@ variants of one repo become one identity."""
    url = url.strip().lower().removesuffix(".git").rstrip("/")
    for prefix in ("https://", "http://", "ssh://", "git://"):
        url = url.removeprefix(prefix)
    if "@" in url.split("/")[0]:  # user@host[:path] → host[:path]
        head, _, tail = url.partition("/")
        url = head.split("@", 1)[1] + ("/" + tail if tail else "")
    return url.replace(":", "/")


def repository_identity(repo: Path) -> str:
    """Stable identity of a working copy, in preference order: canonical
    remote URL, then a hash of the resolved toplevel path. Never just the
    directory basename — names do not identify repositories."""
    try:
        remote = _git(repo, "config", "--get", "remote.origin.url").strip()
        if remote:
            return _normalize_remote(remote)
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        pass
    try:
        toplevel = _git(repo, "rev-parse", "--show-toplevel").strip()
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        toplevel = str(repo.resolve())
    return "path:" + hashlib.sha256(toplevel.encode("utf-8")).hexdigest()[:16]


class GitSensor(Sensor):
    name = "git"
    handles_directories = True

    def __init__(self, commit_limit: int = DEFAULT_COMMIT_LIMIT):
        self.commit_limit = commit_limit

    def can_handle(self, path: Path) -> bool:
        # .git may be a file in linked worktrees, so exists(), not is_dir()
        return path.is_dir() and (path / ".git").exists()

    def sense(self, path: Path) -> Iterable[Percept]:
        repo = path.resolve()
        try:
            branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
            raw = _git(repo, "log", f"-{self.commit_limit}",
                       f"--pretty=format:{_LOG_FORMAT}", "--name-only")
        except (RuntimeError, OSError, subprocess.TimeoutExpired):
            return
        identity = repository_identity(repo)
        for record in raw.split("\x1e"):
            parts = record.split("\x1f")
            if len(parts) < 6:
                continue
            sha, author, date, subject = (p.strip() for p in parts[:4])
            body = parts[4].strip()
            files = [f for f in parts[5].strip().splitlines() if f.strip()]
            content_lines = [
                f"commit {sha[:12]} in {repo.name} by {author}"
                f" (observed from branch {branch})",
                f"subject: {subject}",
            ]
            if body:
                content_lines.append(f"body: {body}")
            if files:
                content_lines.append("changed files: " + ", ".join(files[:30]))
            percept = Percept(
                percept_type="git_commit",
                source_sensor=self.name,
                occurred_at=date,
                ingested_at=now_iso(),
                actors=[author],
                content="\n".join(content_lines),
                content_refs=[{"kind": "git_commit", "repo": str(repo),
                               "repository": identity, "sha": sha}],
                privacy_hints={"domain_hint": "technical"},
                metadata={"repo": repo.name, "repository": identity,
                          "observed_from_branch": branch, "sha": sha,
                          "files_changed": len(files)},
                # commits are authored, versioned records: high trust
                source_trust=0.9,
                source_scope="technical",
                source_confidentiality="internal",
            )
            # dedup key is the commit within its repository identity,
            # not the rendered text and not the directory name
            percept.integrity["content_hash"] = f"git:{identity}:{sha}"
            yield percept.seal()
