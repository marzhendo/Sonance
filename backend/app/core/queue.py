"""Adapter dan factory untuk Message Queue (RQ + Redis dan fallback in-memory).
Wave 7 - Integrasi RQ.
"""
import logging
import os
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class InMemoryJob:
    """Representasi job stub yang kompatibel dengan atribut RQ Job."""

    def __init__(self, job_id: Optional[str] = None):
        self.id = job_id or f"job-{uuid.uuid4()}"


class InMemoryQueue:
    """
    In-memory queue adapter untuk mode testing dan fallback saat Redis tidak tersedia.
    Menyediakan atribut enqueued_jobs yang dapat diinspeksi oleh test suite.
    """

    def __init__(self, name: str = "training"):
        self.name = name
        self.enqueued_jobs: List[Dict[str, Any]] = []

    def enqueue(self, f_or_task_name: Any, *args, **kwargs) -> InMemoryJob:
        job_id = f"job-{uuid.uuid4()}"
        task_str = (
            f_or_task_name
            if isinstance(f_or_task_name, str)
            else getattr(f_or_task_name, "__name__", str(f_or_task_name))
        )
        self.enqueued_jobs.append(
            {
                "task_name": task_str,
                "args": args,
                "kwargs": kwargs,
                "id": job_id,
            }
        )
        return InMemoryJob(job_id=job_id)


class RQQueueAdapter:
    """
    Adapter untuk RQ Queue yang terhubung ke message broker Redis sesungguhnya.
    Digunakan pada environment produksi dan deployment lokal dengan Redis.
    """

    def __init__(self, redis_url: str, queue_name: str = "training"):
        import redis
        from rq import Queue

        self.redis_conn = redis.from_url(redis_url)
        self.rq_queue = Queue(name=queue_name, connection=self.redis_conn)
        self.name = queue_name

    def enqueue(self, f_or_task_name: Any, *args, **kwargs) -> Any:
        target = f_or_task_name
        if target == "execute_training_job":
            target = "backend.workers.training_worker.execute_training_job"
        return self.rq_queue.enqueue(target, *args, **kwargs)


def get_queue(queue_name: str = "training", force_in_memory: bool = False) -> Any:
    """
    Factory function untuk mendapatkan queue adapter.
    - Jika force_in_memory=True: mengembalikan InMemoryQueue.
    - Jika SONANCE_REDIS_URL diset: mengembalikan RQQueueAdapter yang terhubung ke Redis.
    - Jika SONANCE_REDIS_URL tidak diset atau koneksi gagal: fallback ke InMemoryQueue.
    """
    if force_in_memory:
        return InMemoryQueue(name=queue_name)

    redis_url = os.environ.get("SONANCE_REDIS_URL", "").strip()
    if redis_url:
        try:
            return RQQueueAdapter(redis_url=redis_url, queue_name=queue_name)
        except Exception as err:
            logger.warning(
                "Gagal menghubungkan ke Redis (%s), fallback ke InMemoryQueue: %s",
                redis_url,
                err,
            )
            return InMemoryQueue(name=queue_name)

    return InMemoryQueue(name=queue_name)
