"""twin-runtime process: scheduler + worker pool with graceful shutdown."""

from __future__ import annotations

import logging
import signal
import threading
import time
from collections import deque
from typing import Any, Callable, Optional

from twin.config import Config
from twin.memory.embeddings import Embedder, get_embedder_for_config
from twin.memory.store.base import MemoryStore
from twin.runtime.queue import RuntimeQueue
from twin.runtime.scheduler import RuntimeScheduler
from twin.runtime.worker import RuntimeWorker, run_worker_pool

log = logging.getLogger("twin.runtime")

TickCallback = Callable[[dict[str, Any]], None]


class TwinRuntime:
    """Durable cognitive runtime (not an autonomous agent)."""

    def __init__(
        self,
        store: MemoryStore,
        cfg: Config,
        embedder: Optional[Embedder] = None,
        *,
        workers: int = 2,
        vault_id: Optional[str] = None,
        lease_seconds: int = 60,
        schedule_interval: float = 30.0,
        offline: bool = False,
        on_tick: Optional[TickCallback] = None,
        recent_limit: int = 16,
    ):
        self.store = store
        self.cfg = cfg
        self.embedder = embedder or get_embedder_for_config(cfg)
        self.workers_n = max(1, workers)
        self.vault_id = vault_id
        self.lease_seconds = lease_seconds
        self.schedule_interval = schedule_interval
        self.offline = offline
        self.on_tick = on_tick
        self.queue = RuntimeQueue(store)
        self.scheduler = RuntimeScheduler(
            self.queue, vault_id=vault_id or "vault_general",
        )
        self._stop = threading.Event()
        self._pool: list[RuntimeWorker] = []
        self._recent: deque[dict[str, Any]] = deque(maxlen=max(4, recent_limit))
        self._lock = threading.Lock()
        self._started_at = ""
        self._last_scheduler: list[str] = []

    def note_job_event(self, event: dict[str, Any]) -> None:
        """Record a worker job transition for the live dashboard."""
        status = event.get("status")
        if status not in ("completed", "failed"):
            return
        with self._lock:
            self._recent.appendleft(dict(event))

    def snapshot(self) -> dict[str, Any]:
        """Queue + in-flight workers + recent terminal jobs (dashboard)."""
        try:
            depth = self.store.runtime_queue_depth()
        except Exception:
            depth = {}
        try:
            dead = len(self.store.list_runtime_dead_letters(limit=500))
        except Exception:
            dead = 0
        with self._lock:
            recent = list(self._recent)
            last_sched = list(self._last_scheduler)
        workers = []
        for w in self._pool:
            workers.append({
                "id": w.worker_id,
                "current": dict(w.current) if w.current else None,
                "completed": w.jobs_completed,
                "failed": w.jobs_failed,
            })
        return {
            "ok": True,
            "offline": self.offline,
            "workers_n": self.workers_n,
            "vault_id": self.vault_id or "*",
            "started_at": self._started_at,
            "stopping": self._stop.is_set(),
            "queue": depth,
            "dead_letters": dead,
            "workers": workers,
            "completed": sum(w.jobs_completed for w in self._pool),
            "failed": sum(w.jobs_failed for w in self._pool),
            "recent": recent,
            "last_scheduler": last_sched,
        }

    def health(self) -> dict:
        snap = self.snapshot()
        return {
            "ok": True,
            "offline": snap["offline"],
            "workers": snap["workers_n"],
            "worker_ids": [w["id"] for w in snap["workers"]],
            "queue": snap["queue"],
            "completed": snap["completed"],
            "failed": snap["failed"],
            "stopping": snap["stopping"],
        }

    def _tick_ui(self) -> None:
        if self.on_tick is None:
            return
        try:
            self.on_tick(self.snapshot())
        except Exception:
            log.debug("on_tick failed", exc_info=True)

    def run(self) -> None:
        """Block until SIGINT/SIGTERM or ``stop()``."""
        from twin.clock import now_iso

        def _handle(signum, frame):
            log.info("signal %s — graceful shutdown", signum)
            self.stop()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _handle)
            except (ValueError, OSError):
                pass

        self._started_at = now_iso()
        if not self.offline:
            self._pool = run_worker_pool(
                self.store, self.cfg, self.embedder,
                workers=self.workers_n,
                vault_id=self.vault_id,
                lease_seconds=self.lease_seconds,
                stop_event=self._stop,
                on_job_event=self.note_job_event,
            )
        else:
            log.info("offline mode — scheduler only, no workers")

        log.info(
            "twin-runtime up workers=%s offline=%s vault=%s",
            self.workers_n, self.offline, self.vault_id or "*",
        )
        self._tick_ui()
        last_sched = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            if now - last_sched >= self.schedule_interval:
                try:
                    ids = self.scheduler.tick()
                    self._last_scheduler = list(ids)
                    log.debug("scheduler enqueued %s", ids)
                except Exception:
                    log.exception("scheduler tick failed")
                last_sched = now
            self._tick_ui()
            self._stop.wait(0.5)

        # Give workers a moment to finish current claim
        time.sleep(0.2)
        self._tick_ui()
        log.info("twin-runtime stopped health=%s", self.health())

    def stop(self) -> None:
        self._stop.set()
        for w in self._pool:
            w.stop()
