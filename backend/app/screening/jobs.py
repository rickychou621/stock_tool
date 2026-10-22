from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Literal
from uuid import uuid4

from app.core.db import SessionLocal
from app.screening.scan_service import ScanSummary, ScreeningScanService


class ScanBusy(ValueError):
    pass


@dataclass
class ScanJob:
    job_id: str
    started_at: datetime
    status: Literal["running", "done", "failed"] = "running"
    done: int = 0
    total: int = 0
    summary: ScanSummary | None = None
    error: str | None = None


class ScanJobManager:
    def __init__(self, session_factory=SessionLocal):
        self.sessions = session_factory
        self.executor = None
        self._lock = Lock()
        self._job: ScanJob | None = None
        self._closing = False

    def start(self) -> str:
        with self._lock:
            if self._job and self._job.status == "running":
                raise ScanBusy("已有掃描進行中，請等待完成。")
            if self._closing:
                raise RuntimeError("掃描服務正在關閉。")
            job = ScanJob(job_id=str(uuid4()), started_at=datetime.now(UTC))
            self._job = job
            try:
                if self.executor is None:
                    self.executor = ThreadPoolExecutor(
                        max_workers=1, thread_name_prefix="screening-job"
                    )
                self.executor.submit(self._run, job)
            except Exception as exc:
                job.status = "failed"
                job.error = f"{type(exc).__name__}: {str(exc)[:200]}"
                raise
            return job.job_id

    def latest(self) -> ScanJob | None:
        with self._lock:
            return deepcopy(self._job)

    def _run(self, job: ScanJob) -> None:
        def progress(done: int, total: int) -> None:
            with self._lock:
                job.done = done
                job.total = total

        try:
            with self.sessions() as db:
                summary = ScreeningScanService(db).run_scan(progress=progress)
            with self._lock:
                job.summary = summary
                job.status = "done"
        except Exception as exc:
            with self._lock:
                job.status = "failed"
                job.error = f"{type(exc).__name__}: {str(exc)[:200]}"

    def close(self) -> None:
        with self._lock:
            self._closing = True
            executor = self.executor
        try:
            if executor:
                executor.shutdown(wait=True)
        finally:
            with self._lock:
                self.executor = None
                self._closing = False


manager = ScanJobManager()
