"""Tests untuk Queue Adapter dan Factory.
Wave 7 - Task 13.1 (Integrasi RQ + Redis Adapter).
"""
import pytest

from backend.app.core.queue import InMemoryJob, InMemoryQueue, RQQueueAdapter, get_queue


class TestQueueAdapter:

    def test_get_queue_returns_in_memory_when_no_redis_url(self, monkeypatch):
        monkeypatch.delenv("SONANCE_REDIS_URL", raising=False)
        q = get_queue()
        assert isinstance(q, InMemoryQueue)

    def test_get_queue_returns_rq_adapter_when_redis_url_set(self, monkeypatch):
        monkeypatch.setenv("SONANCE_REDIS_URL", "redis://127.0.0.1:6379/0")
        q = get_queue()
        assert isinstance(q, RQQueueAdapter)
        assert q.name == "training"

    def test_get_queue_force_in_memory_overrides_env(self, monkeypatch):
        monkeypatch.setenv("SONANCE_REDIS_URL", "redis://127.0.0.1:6379/0")
        q = get_queue(force_in_memory=True)
        assert isinstance(q, InMemoryQueue)

    def test_in_memory_queue_enqueue_and_job_id(self):
        q = InMemoryQueue(name="test-queue")
        job = q.enqueue(
            "execute_training_job",
            voice_profile_id="1234",
            source_type="own_voice",
        )

        assert isinstance(job, InMemoryJob)
        assert job.id.startswith("job-")
        assert len(q.enqueued_jobs) == 1

        enqueued = q.enqueued_jobs[0]
        assert enqueued["task_name"] == "execute_training_job"
        assert enqueued["kwargs"]["voice_profile_id"] == "1234"
        assert enqueued["kwargs"]["source_type"] == "own_voice"
        assert enqueued["id"] == job.id

    def test_rq_adapter_normalizes_task_name(self, monkeypatch):
        from unittest.mock import MagicMock

        monkeypatch.setenv("SONANCE_REDIS_URL", "redis://127.0.0.1:6379/0")
        adapter = RQQueueAdapter(redis_url="redis://127.0.0.1:6379/0", queue_name="training")

        mock_rq = MagicMock()
        adapter.rq_queue = mock_rq

        adapter.enqueue("execute_training_job", voice_profile_id="abc", source_type="character")
        mock_rq.enqueue.assert_called_once_with(
            "backend.workers.training_worker.execute_training_job",
            voice_profile_id="abc",
            source_type="character",
        )
