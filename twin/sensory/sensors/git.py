"""Git Sensor — commits, branch and repository metadata.

Points at a working copy and emits one percept per recent commit. The
artifact is the commit itself (referenced by sha in ``content_refs``); the
percept is the normalized observation; memories are extracted downstream.
Dedup is natural: the percept content hash is derived from the commit sha,
so re-sensing a repository only ingests what is new.
"""

from __future__ import annotations

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


class GitSensor(Sensor):
    name = "git"
    handles_directories = True

    def __init__(self, commit_limit: int = DEFAULT_COMMIT_LIMIT):
        self.commit_limit = commit_limit

    def can_handle(self, path: Path) -> bool:
        return path.is_dir() and (path / ".git").exists()

    def sense(self, path: Path) -> Iterable[Percept]:
        repo = path.resolve()
        try:
            branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
            raw = _git(repo, "log", f"-{self.commit_limit}",
                       f"--pretty=format:{_LOG_FORMAT}", "--name-only")
        except (RuntimeError, OSError, subprocess.TimeoutExpired):
            return
        for record in raw.split("\x1e"):
            parts = record.split("\x1f")
            if len(parts) < 6:
                continue
            sha, author, date, subject = (p.strip() for p in parts[:4])
            body = parts[4].strip()
            files = [f for f in parts[5].strip().splitlines() if f.strip()]
            content_lines = [f"commit {sha[:12]} on {repo.name}@{branch} by {author}",
                             f"subject: {subject}"]
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
                content_refs=[{"kind": "git_commit", "repo": str(repo), "sha": sha}],
                privacy_hints={"domain_hint": "technical"},
                metadata={"repo": repo.name, "branch": branch, "sha": sha,
                          "files_changed": len(files)},
                # commits are authored, versioned records: high trust
                source_trust=0.9,
                source_scope="technical",
                source_confidentiality="internal",
            )
            # dedup key is the commit itself, not the rendered text
            percept.integrity["content_hash"] = f"git:{repo.name}:{sha}"
            yield percept.seal()
