"""경량 인프로세스 잡 매니저.

생성·역설계처럼 오래 걸리는 액션을 백그라운드 스레드로 실행하고 상태를
폴링할 수 있게 한다. 단일 프로세스 운영 콘솔용(외부 큐 없음). SaaS 전환 시
이 인터페이스를 실제 작업 큐로 교체하면 된다.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..utils.time import now_utc


@dataclass
class Job:
    id: str
    name: str
    status: str = "running"          # running | done | error
    progress: float = 0.0            # 0.0 ~ 1.0
    message: str = ""
    result: Optional[dict] = None
    error: Optional[str] = None
    started_at: str = field(default_factory=lambda: now_utc().isoformat())

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "status": self.status,
            "progress": round(self.progress, 3), "message": self.message,
            "result": self.result, "error": self.error,
        }


# report 콜백 시그니처: report(message: str, progress: float)
Reporter = Callable[[str, float], None]
JobBody = Callable[[Reporter], dict]


class JobManager:
    def __init__(self, keep: int = 50):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._keep = keep

    def start(self, name: str, body: JobBody) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], name=name)
        with self._lock:
            self._jobs[job.id] = job
            self._evict()

        def report(message: str, progress: float) -> None:
            job.message = message
            job.progress = max(0.0, min(1.0, progress))

        def run() -> None:
            try:
                job.result = body(report)
                job.progress = 1.0
                job.status = "done"
                if not job.message:
                    job.message = "완료"
            except Exception as e:  # noqa: BLE001
                job.status = "error"
                job.error = str(e)

        threading.Thread(target=run, daemon=True).start()
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def _evict(self) -> None:
        if len(self._jobs) <= self._keep:
            return
        # 오래된 순으로 정리 (완료/에러 우선)
        done = [j for j in self._jobs.values() if j.status != "running"]
        for j in sorted(done, key=lambda x: x.started_at)[: len(self._jobs) - self._keep]:
            self._jobs.pop(j.id, None)
