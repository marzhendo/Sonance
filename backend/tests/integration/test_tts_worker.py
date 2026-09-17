"""Integration tests untuk TTS Worker (backend/workers/tts_worker.py).
Wave 6: Worker Layer & GPU Lock Timeout.
"""
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
import pytest

from backend.app.core.gpu_manager import get_gpu_manager
from backend.app.services.tts_job_service import GPU_TIMEOUT_ERROR_MESSAGE
from backend.ml.base import TTSPipeline
from backend.ml.xtts import XTTSPipeline
from backend.workers.tts_worker import execute_tts_job, process_queue_jobs


@pytest.fixture(autouse=True)
def clean_gpu():
    """Memastikan status GPU manager selalu bersih sebelum dan sesudah test."""
    gpu = get_gpu_manager()
    gpu.reset()
    yield
    gpu.reset()


class TestTTSWorkerExecution:

    def test_execute_success_without_lock(
        self, db_session, test_user, ready_voice_profile, make_tts_job, tmp_path
    ):
        """TTS job berhasil diproses normal saat GPU tidak terkunci."""
        job = make_tts_job(
            user=test_user,
            voice_profile=ready_voice_profile,
            input_text="Halo dari test worker tanpa GPU lock.",
        )

        result = execute_tts_job(
            tts_job_id=job.id,
            db=db_session,
            output_dir=str(tmp_path),
        )

        assert result["status"] == "completed"
        assert "output_audio_path" in result
        assert os.path.isfile(result["output_audio_path"])

        db_session.refresh(job)
        assert job.status == "completed"
        assert job.started_at is not None
        assert job.completed_at is not None
        assert job.error_message is None
        assert job.gpu_wait_started_at is None
        assert job.output_audio_path == result["output_audio_path"]

    def test_worker_does_not_process_audio_while_gpu_locked(
        self, db_session, test_user, ready_voice_profile, make_tts_job, tmp_path
    ):
        """Worker menunda proses dan TIDAK memanggil update_start() saat GPU masih terkunci."""
        gpu = get_gpu_manager()
        gpu.acquire_lock("session-realtime-voice-changer")

        job = make_tts_job(
            user=test_user,
            voice_profile=ready_voice_profile,
            input_text="Teks yang harus menunggu GPU lock dilepaskan.",
        )

        result = execute_tts_job(
            tts_job_id=job.id,
            db=db_session,
            output_dir=str(tmp_path),
            poll_interval=0.0,
            max_poll_iterations=1,
        )

        assert result["status"] == "waiting_for_gpu"

        db_session.refresh(job)
        # Status tetap queued dan started_at belum terisi
        assert job.status == "queued"
        assert job.started_at is None
        assert job.completed_at is None
        assert job.output_audio_path is None
        # Waktu mulai menunggu GPU harus tercatat di database
        assert job.gpu_wait_started_at is not None

    def test_execute_success_after_lock_released_in_wait_window(
        self, db_session, test_user, ready_voice_profile, make_tts_job, tmp_path
    ):
        """Worker menunggu saat terkunci, lalu melanjutkan sintesis setelah lock dilepas."""
        gpu = get_gpu_manager()
        gpu.acquire_lock("session-realtime-voice-changer")

        job = make_tts_job(
            user=test_user,
            voice_profile=ready_voice_profile,
            input_text="Teks yang disintesis setelah lock lepas.",
        )

        def release_lock_shortly():
            time.sleep(0.05)
            gpu.release_lock("session-realtime-voice-changer")

        releaser = threading.Thread(target=release_lock_shortly, daemon=True)
        releaser.start()

        result = execute_tts_job(
            tts_job_id=job.id,
            db=db_session,
            output_dir=str(tmp_path),
            poll_interval=0.01,
        )

        releaser.join()

        assert result["status"] == "completed"

        db_session.refresh(job)
        assert job.status == "completed"
        assert job.gpu_wait_started_at is not None
        assert job.started_at is not None
        assert job.completed_at is not None
        assert os.path.isfile(job.output_audio_path)

    def test_execute_fails_when_gpu_wait_times_out(
        self, db_session, test_user, ready_voice_profile, make_tts_job, tmp_path
    ):
        """Worker membatalkan job menjadi failed saat menunggu GPU melebihi 30 menit (simulasi waktu)."""
        gpu = get_gpu_manager()
        gpu.acquire_lock("session-realtime-active")

        # Set wait start ke 31 menit yang lalu
        past_started_at = datetime.now(timezone.utc) - timedelta(minutes=31)
        job = make_tts_job(
            user=test_user,
            voice_profile=ready_voice_profile,
            input_text="Teks yang akan timeout.",
            gpu_wait_started_at=past_started_at,
        )

        result = execute_tts_job(
            tts_job_id=job.id,
            db=db_session,
            output_dir=str(tmp_path),
        )

        assert result["status"] == "failed"
        assert result["error"] == "GPU wait timeout"

        db_session.refresh(job)
        assert job.status == "failed"
        assert job.started_at is None  # update_start TIDAK pernah dipanggil
        assert job.completed_at is None
        assert job.output_audio_path is None
        assert job.error_message == GPU_TIMEOUT_ERROR_MESSAGE

    def test_execute_pipeline_failure_records_failed_status(
        self, db_session, test_user, ready_voice_profile, make_tts_job, tmp_path
    ):
        """Kegagalan pipeline sintesis tercatat sebagai status failed dengan pesan error."""
        job = make_tts_job(
            user=test_user,
            voice_profile=ready_voice_profile,
            input_text="Teks dengan pipeline yang disimulasikan gagal.",
        )
        failing_pipeline = XTTSPipeline(simulate_failure=True)

        result = execute_tts_job(
            tts_job_id=job.id,
            db=db_session,
            pipeline=failing_pipeline,
            output_dir=str(tmp_path),
        )

        assert result["status"] == "failed"

        db_session.refresh(job)
        assert job.status == "failed"
        assert job.started_at is not None
        assert job.completed_at is None
        assert job.output_audio_path is None
        assert "Simulated XTTS synthesis failure" in (job.error_message or "")

    def test_execute_non_existent_job_raises_value_error(self, db_session):
        """execute_tts_job melempar ValueError jika ID job tidak ditemukan di database."""
        with pytest.raises(ValueError, match="TTSJob dengan ID .* tidak ditemukan"):
            execute_tts_job(tts_job_id=uuid.uuid4(), db=db_session)

    def test_execute_terminal_status_job_returns_early(
        self, db_session, test_user, ready_voice_profile, make_tts_job
    ):
        """execute_tts_job tidak memproses ulang job yang sudah berstatus terminal."""
        job = make_tts_job(
            user=test_user,
            voice_profile=ready_voice_profile,
            status="completed",
            output_audio_path="/fake/path.opus",
        )

        result = execute_tts_job(tts_job_id=job.id, db=db_session)
        assert result["status"] == "completed"
        assert "terminal status" in result.get("error", "")

    def test_process_queue_jobs_in_memory_success(
        self, db_session, test_user, ready_voice_profile, make_tts_job, mock_queue, tmp_path
    ):
        """process_queue_jobs mengeksekusi seluruh task di antrian in-memory dan mengosongkannya."""
        j1 = make_tts_job(user=test_user, voice_profile=ready_voice_profile, input_text="Job 1")
        j2 = make_tts_job(user=test_user, voice_profile=ready_voice_profile, input_text="Job 2")

        mock_queue.enqueue("execute_tts_job", tts_job_id=str(j1.id))
        mock_queue.enqueue("execute_tts_job", tts_job_id=str(j2.id))

        assert len(mock_queue.enqueued_jobs) == 2

        results = process_queue_jobs(
            queue=mock_queue,
            db=db_session,
            output_dir=str(tmp_path),
        )

        assert len(results) == 2
        assert all(r["status"] == "completed" for r in results)
        assert len(mock_queue.enqueued_jobs) == 0

        db_session.refresh(j1)
        db_session.refresh(j2)
        assert j1.status == "completed"
        assert j2.status == "completed"

    def test_execute_acquires_and_releases_lock_symmetrically(
        self, db_session, test_user, ready_voice_profile, make_tts_job, tmp_path
    ):
        """TTS worker memegang GPU lock selama proses sintesis dan melepaskannya setelah selesai."""
        gpu = get_gpu_manager()
        job = make_tts_job(
            user=test_user,
            voice_profile=ready_voice_profile,
            input_text="Cek kepemilikan lock GPU selama sintesis.",
        )
        expected_holder = f"tts-{job.id}"

        class LockCheckingPipeline(TTSPipeline):
            def __init__(self):
                self.lock_held = False
                self.holder_matched = False

            def synthesize(
                self, text, voice_profile_checkpoint_path, settings, output_dir, progress_cb=None
            ) -> str:
                self.lock_held = gpu.is_locked()
                self.holder_matched = (gpu.get_holder() == expected_holder)
                out_file = os.path.join(output_dir, "output.opus")
                with open(out_file, "wb") as f:
                    f.write(b"dummy audio")
                return out_file

        check_pipeline = LockCheckingPipeline()
        result = execute_tts_job(
            tts_job_id=job.id,
            db=db_session,
            pipeline=check_pipeline,
            output_dir=str(tmp_path),
        )

        assert result["status"] == "completed"
        assert check_pipeline.lock_held is True
        assert check_pipeline.holder_matched is True
        assert gpu.is_locked() is False
        assert gpu.get_holder() is None

    def test_execute_calls_acquire_and_release_with_exact_session_id(
        self, db_session, test_user, ready_voice_profile, make_tts_job, tmp_path
    ):
        """execute_tts_job memanggil acquire_lock dan release_lock dengan session_id f'tts-{id}'."""
        gpu = get_gpu_manager()
        mock_gpu = MagicMock(wraps=gpu)

        job = make_tts_job(
            user=test_user,
            voice_profile=ready_voice_profile,
            input_text="Cek parameter session_id lock.",
        )
        expected_id = f"tts-{job.id}"

        result = execute_tts_job(
            tts_job_id=job.id,
            db=db_session,
            gpu_manager=mock_gpu,
            output_dir=str(tmp_path),
        )

        assert result["status"] == "completed"
        mock_gpu.acquire_lock.assert_called_once_with(session_id=expected_id)
        mock_gpu.release_lock.assert_called_once_with(session_id=expected_id)
        assert gpu.is_locked() is False

    def test_execute_releases_lock_on_pipeline_exception(
        self, db_session, test_user, ready_voice_profile, make_tts_job, tmp_path
    ):
        """release_lock tetap dipanggil meski pipeline.synthesize() melempar exception."""
        gpu = get_gpu_manager()
        mock_gpu = MagicMock(wraps=gpu)

        job = make_tts_job(
            user=test_user,
            voice_profile=ready_voice_profile,
            input_text="Teks untuk simulasi exception pipeline.",
        )
        expected_id = f"tts-{job.id}"
        failing_pipeline = XTTSPipeline(simulate_failure=True)

        result = execute_tts_job(
            tts_job_id=job.id,
            db=db_session,
            pipeline=failing_pipeline,
            gpu_manager=mock_gpu,
            output_dir=str(tmp_path),
        )

        assert result["status"] == "failed"
        mock_gpu.acquire_lock.assert_called_once_with(session_id=expected_id)
        mock_gpu.release_lock.assert_called_once_with(session_id=expected_id)
        assert gpu.is_locked() is False

    def test_execute_race_condition_gpu_contention_returns_to_queue(
        self, db_session, test_user, ready_voice_profile, make_tts_job, tmp_path
    ):
        """Saat acquire_lock gagal karena race condition, job tetap queued dan gpu_wait_started_at di-reset."""
        gpu = get_gpu_manager()
        mock_gpu = MagicMock(wraps=gpu)
        mock_gpu.is_locked.return_value = False
        mock_gpu.acquire_lock.return_value = False

        past_wait = datetime.now(timezone.utc) - timedelta(seconds=10)
        job = make_tts_job(
            user=test_user,
            voice_profile=ready_voice_profile,
            input_text="Teks untuk race condition GPU contention.",
            gpu_wait_started_at=past_wait,
        )

        result = execute_tts_job(
            tts_job_id=job.id,
            db=db_session,
            gpu_manager=mock_gpu,
            output_dir=str(tmp_path),
        )

        assert result["status"] == "queued"
        assert "GPU lock contention" in result.get("error", "")

        db_session.refresh(job)
        assert job.status == "queued"
        assert job.started_at is None
        assert job.completed_at is None
        assert job.gpu_wait_started_at is None
