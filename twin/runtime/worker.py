"""Background worker: claim → dispatch → complete/fail."""

from __future__ import annotations

import logging
import threading
import uuid
from typing import Optional

from twin.config import Config
from twin.memory.embeddings import Embedder
from twin.memory.store.base import MemoryStore
from twin.runtime.handlers import HandlerError, dispatch
from twin.runtime.models import ErrorClass
from twin.runtime.queue import RuntimeQueue

log = logging.getLogger("twin.runtime.worker")


class RuntimeWorker:
    """One worker loop. Multiple processes/threads may run concurrently;
    CAS claim guarantees exclusive execution per job."""

    def __init__(
        self,
        store: MemoryStore,
        cfg: Config,
        embedder: Embedder,
        *,
        worker_id: str = "",
        vault_id: Optional[str] = None,
        lease_seconds: int = 60,
        poll_interval: float = 0.5,
        idle_sleep: float = 1.0,
    ):
        self.store = store
        self.cfg = cfg
        self.embedder = embedder
        self.worker_id = worker_id or f"worker_{uuid.uuid4().hex[:10]}"
        self.vault_id = vault_id
        self.lease_seconds = lease_seconds
        self.poll_interval = poll_interval
        self.idle_sleep = idle_sleep
        self.queue = RuntimeQueue(store)
        self._stop = threading.Event()
        self.jobs_completed = 0
        self.jobs_failed = 0

    def stop(self) -> None:
        self._stop.set()

    def run_once(self) -> bool:
        """Claim and run at most one job. Returns True if work was done."""
        job = self.queue.claim(
            self.worker_id,
            vault_id=self.vault_id,
            lease_seconds=self.lease_seconds,
        )
        if job is None:
            return False
        stage = "dispatch"
        try:
            result = dispatch(self.store, self.cfg, self.embedder, job)
            ok = self.queue.complete(job, result)
            if ok:
                self.jobs_completed += 1
            else:
                log.warning("complete lost lease job=%s worker=%s", job.id, self.worker_id)
            return True
        except HandlerError as exc:
            stage = exc.stage or stage
            self.queue.fail(job, exc, stage=stage, error_class=exc.error_class)
            self.jobs_failed += 1
            return True
        except Exception as exc:
            self.queue.fail(
                job, exc, stage=stage, error_class=ErrorClass.transient,
            )
            self.jobs_failed += 1
            return True

    def run_forever(self) -> None:
        log.info("runtime worker start id=%s vault=%s", self.worker_id, self.vault_id or "*")
        while not self._stop.is_set():
            try:
                did = self.run_once()
            except Exception:
                log.exception("worker loop error id=%s", self.worker_id)
                did = False
            if self._stop.wait(self.poll_interval if did else self.idle_sleep):
                break
        log.info(
            "runtime worker stop id=%s completed=%s failed=%s",
            self.worker_id, self.jobs_completed, self.jobs_failed,
        )


def run_worker_pool(
    store: MemoryStore,
    cfg: Config,
    embedder: Embedder,
    *,
    workers: int = 2,
    vault_id: Optional[str] = None,
    lease_seconds: int = 60,
    stop_event: Optional[threading.Event] = None,
) -> list[RuntimeWorker]:
    """Start ``workers`` threads sharing ``stop_event``."""
    stop = stop_event or threading.Event()
    pool: list[RuntimeWorker] = []
    for i in range(max(1, workers)):
        w = RuntimeWorker(
            store, cfg, embedder,
            worker_id=f"worker_{i}_{uuid.uuid4().hex[:6]}",
            vault_id=vault_id,
            lease_seconds=lease_seconds,
        )
        w._stop = stop
        t = threading.Thread(target=w.run_forever, name=w.worker_id, daemon=True)
        pool.append(w)
        t.start()
    return pool
