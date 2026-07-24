"""twin-runtime process: scheduler + worker pool with graceful shutdown."""

from __future__ import annotations

import logging
import signal
import threading
import time
from typing import Optional

from twin.config import Config
from twin.memory.embeddings import Embedder, get_embedder_for_config
from twin.memory.store.base import MemoryStore
from twin.runtime.queue import RuntimeQueue
from twin.runtime.scheduler import RuntimeScheduler
from twin.runtime.worker import RuntimeWorker, run_worker_pool

log = logging.getLogger("twin.runtime")


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
    ):
        self.store = store
        self.cfg = cfg
        self.embedder = embedder or get_embedder_for_config(cfg)
        self.workers_n = max(1, workers)
        self.vault_id = vault_id
        self.lease_seconds = lease_seconds
        self.schedule_interval = schedule_interval
        self.offline = offline
        self.queue = RuntimeQueue(store)
        self.scheduler = RuntimeScheduler(
            self.queue, vault_id=vault_id or "vault_general",
        )
        self._stop = threading.Event()
        self._pool: list[RuntimeWorker] = []

    def health(self) -> dict:
        depth = self.store.runtime_queue_depth()
        return {
            "ok": True,
            "offline": self.offline,
            "workers": self.workers_n,
            "worker_ids": [w.worker_id for w in self._pool],
            "queue": depth,
            "completed": sum(w.jobs_completed for w in self._pool),
            "failed": sum(w.jobs_failed for w in self._pool),
            "stopping": self._stop.is_set(),
        }

    def run(self) -> None:
        """Block until SIGINT/SIGTERM or ``stop()``."""
        def _handle(signum, frame):
            log.info("signal %s — graceful shutdown", signum)
            self.stop()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _handle)
            except (ValueError, OSError):
                pass

        if not self.offline:
            self._pool = run_worker_pool(
                self.store, self.cfg, self.embedder,
                workers=self.workers_n,
                vault_id=self.vault_id,
                lease_seconds=self.lease_seconds,
                stop_event=self._stop,
            )
        else:
            log.info("offline mode — scheduler only, no workers")

        log.info(
            "twin-runtime up workers=%s offline=%s vault=%s",
            self.workers_n, self.offline, self.vault_id or "*",
        )
        last_sched = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            if now - last_sched >= self.schedule_interval:
                try:
                    ids = self.scheduler.tick()
                    log.debug("scheduler enqueued %s", ids)
                except Exception:
                    log.exception("scheduler tick failed")
                last_sched = now
            self._stop.wait(1.0)

        # Give workers a moment to finish current claim
        time.sleep(0.2)
        log.info("twin-runtime stopped health=%s", self.health())

    def stop(self) -> None:
        self._stop.set()
        for w in self._pool:
            w.stop()
