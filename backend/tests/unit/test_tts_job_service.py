"""
Tests untuk TTSJobService.
Wave 3: Service Layer.
"""
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from backend.app.schemas.tts_job_schema import (
    TTSGenerateRequest,
    TTSJobResponse,
    TTSJobStatus,
    TTSJobStatusResponse,
    TTSSettings,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TestTTSJobServiceDispatch:

    def test_dispatch_success(self, db_session, make_user, make_voice_profile):
        """dispatch() berhasil membuat job TTS dan mengirim ke antrian."""
        from backend.app.models.tts_job_model import TTSJob
        from backend.app.services.tts_job_service import TTSJobService

        user = make_user()
        vp = make_voice_profile(user=user, status="ready")

        fake_queue = MagicMock()
        service = TTSJobService(queue=fake_queue)

        req = TTSGenerateRequest(
            voice_profile_id=vp.id,
            text="Halo dunia dari pengujian dispatch TTS.",
            settings=TTSSettings(speed=1.2),
        )

        resp = service.dispatch(user_id=user.id, request=req, db=db_session)

        assert isinstance(resp, TTSJobResponse)
        assert resp.status == TTSJobStatus.queued
        assert resp.input_text == "Halo dunia dari pengujian dispatch TTS."
        assert resp.voice_profile_id == vp.id
        assert resp.settings.speed == 1.2

        # Verifikasi record tersimpan di DB
        job_db = db_session.get(TTSJob, resp.id)
        assert job_db is not None
        assert job_db.status == "queued"
        assert job_db.settings["speed"] == 1.2

        # Verifikasi queue menerima enqueue yang tepat
        fake_queue.enqueue.assert_called_once_with(
            "execute_tts_job",
            tts_job_id=str(resp.id),
        )

    def test_dispatch_voice_profile_not_found_raises_404(self, db_session, make_user):
        """dispatch() dengan voice_profile_id tidak dikenal melempar 404."""
        from backend.app.services.tts_job_service import TTSJobService

        user = make_user()
        fake_queue = MagicMock()
        service = TTSJobService(queue=fake_queue)

        req = TTSGenerateRequest(
            voice_profile_id=uuid.uuid4(),
            text="Halo dunia",
        )

        with pytest.raises(HTTPException) as exc_info:
            service.dispatch(user_id=user.id, request=req, db=db_session)

        assert exc_info.value.status_code == 404
        assert "tidak ditemukan" in exc_info.value.detail

    def test_dispatch_other_user_voice_profile_raises_404(
        self, db_session, make_user, make_voice_profile
    ):
        """dispatch() dengan profile milik user lain melempar 404 (ownership isolation)."""
        from backend.app.services.tts_job_service import TTSJobService

        user1 = make_user()
        user2 = make_user()
        vp_user2 = make_voice_profile(user=user2, status="ready")

        fake_queue = MagicMock()
        service = TTSJobService(queue=fake_queue)

        req = TTSGenerateRequest(
            voice_profile_id=vp_user2.id,
            text="Halo dunia",
        )

        with pytest.raises(HTTPException) as exc_info:
            service.dispatch(user_id=user1.id, request=req, db=db_session)

        assert exc_info.value.status_code == 404

    @pytest.mark.parametrize("invalid_status", ["pending", "processing", "failed"])
    def test_dispatch_voice_profile_not_ready_raises_409(
        self, db_session, make_user, make_voice_profile, invalid_status
    ):
        """dispatch() dengan profile belum berstatus ready melempar 409 Conflict."""
        from backend.app.services.tts_job_service import TTSJobService

        user = make_user()
        vp = make_voice_profile(user=user, status=invalid_status)

        fake_queue = MagicMock()
        service = TTSJobService(queue=fake_queue)

        req = TTSGenerateRequest(
            voice_profile_id=vp.id,
            text="Halo dunia",
        )

        with pytest.raises(HTTPException) as exc_info:
            service.dispatch(user_id=user.id, request=req, db=db_session)

        assert exc_info.value.status_code == 409
        assert invalid_status in exc_info.value.detail

    def test_dispatch_queue_failure_rolls_back_and_raises_500(
        self, db_session, make_user, make_voice_profile
    ):
        """Jika enqueue gagal, DB di-rollback dan melempar 500 (rollback guarantee)."""
        from backend.app.models.tts_job_model import TTSJob
        from backend.app.services.tts_job_service import TTSJobService

        user = make_user()
        vp = make_voice_profile(user=user, status="ready")

        failing_queue = MagicMock()
        failing_queue.enqueue.side_effect = RuntimeError("Broker connection lost")
        service = TTSJobService(queue=failing_queue)

        req = TTSGenerateRequest(
            voice_profile_id=vp.id,
            text="Halo dunia",
        )

        with pytest.raises(HTTPException) as exc_info:
            service.dispatch(user_id=user.id, request=req, db=db_session)

        assert exc_info.value.status_code == 500
        # Verifikasi tidak ada tts_job yang tertinggal di DB
        jobs_in_db = db_session.query(TTSJob).filter_by(user_id=user.id).all()
        assert len(jobs_in_db) == 0


class TestTTSJobServiceGetStatus:

    def test_get_status_success(self, db_session, make_user, make_tts_job):
        """get_status() mengembalikan status job yang valid."""
        from backend.app.services.tts_job_service import TTSJobService

        user = make_user()
        job = make_tts_job(user=user, status="processing")

        service = TTSJobService()
        status_resp = service.get_status(user_id=user.id, job_id=job.id, db=db_session)

        assert isinstance(status_resp, TTSJobStatusResponse)
        assert status_resp.id == job.id
        assert status_resp.status == TTSJobStatus.processing
        assert status_resp.error_message is None

    def test_get_status_not_found_raises_404(self, db_session, make_user):
        """get_status() dengan job_id tidak dikenal melempar 404."""
        from backend.app.services.tts_job_service import TTSJobService

        user = make_user()
        service = TTSJobService()

        with pytest.raises(HTTPException) as exc_info:
            service.get_status(user_id=user.id, job_id=uuid.uuid4(), db=db_session)

        assert exc_info.value.status_code == 404

    def test_get_status_other_user_raises_404(self, db_session, make_user, make_tts_job):
        """get_status() pada job milik pengguna lain melempar 404."""
        from backend.app.services.tts_job_service import TTSJobService

        user1 = make_user()
        user2 = make_user()
        job_user2 = make_tts_job(user=user2)

        service = TTSJobService()
        with pytest.raises(HTTPException) as exc_info:
            service.get_status(user_id=user1.id, job_id=job_user2.id, db=db_session)

        assert exc_info.value.status_code == 404

    def test_get_status_failed_invariants(self, db_session, make_user, make_tts_job):
        """get_status() status failed menyertakan error_message dan completed_at null."""
        from backend.app.services.tts_job_service import TTSJobService

        user = make_user()
        job = make_tts_job(
            user=user,
            status="failed",
            error_message="Proses gagal karena kehabisan GPU memory.",
        )

        service = TTSJobService()
        status_resp = service.get_status(user_id=user.id, job_id=job.id, db=db_session)

        assert status_resp.status == TTSJobStatus.failed
        assert status_resp.error_message == "Proses gagal karena kehabisan GPU memory."
        assert status_resp.completed_at is None


class TestTTSJobServiceGetAudioPath:

    def test_get_audio_path_success(self, db_session, make_user, make_tts_job, tmp_path):
        """get_audio_path() mengembalikan path saat status completed dan file ada."""
        from backend.app.services.tts_job_service import TTSJobService

        audio_file = tmp_path / "tts_output.opus"
        audio_file.write_bytes(b"dummy opus data")

        user = make_user()
        job = make_tts_job(
            user=user,
            status="completed",
            output_audio_path=str(audio_file),
            completed_at=utcnow(),
        )

        service = TTSJobService()
        retrieved_path = service.get_audio_path(user_id=user.id, job_id=job.id, db=db_session)

        assert retrieved_path == str(audio_file)

    def test_get_audio_path_not_found_raises_404(self, db_session, make_user):
        """get_audio_path() dengan job_id tidak dikenal melempar 404."""
        from backend.app.services.tts_job_service import TTSJobService

        user = make_user()
        service = TTSJobService()

        with pytest.raises(HTTPException) as exc_info:
            service.get_audio_path(user_id=user.id, job_id=uuid.uuid4(), db=db_session)

        assert exc_info.value.status_code == 404

    def test_get_audio_path_other_user_raises_404(self, db_session, make_user, make_tts_job):
        """get_audio_path() untuk job user lain melempar 404."""
        from backend.app.services.tts_job_service import TTSJobService

        user1 = make_user()
        user2 = make_user()
        job = make_tts_job(user=user2, status="completed")

        service = TTSJobService()
        with pytest.raises(HTTPException) as exc_info:
            service.get_audio_path(user_id=user1.id, job_id=job.id, db=db_session)

        assert exc_info.value.status_code == 404

    @pytest.mark.parametrize("in_progress_status", ["queued", "processing"])
    def test_get_audio_path_in_progress_raises_409(
        self, db_session, make_user, make_tts_job, in_progress_status
    ):
        """get_audio_path() saat status queued/processing melempar 409 Conflict."""
        from backend.app.services.tts_job_service import TTSJobService

        user = make_user()
        job = make_tts_job(user=user, status=in_progress_status)

        service = TTSJobService()
        with pytest.raises(HTTPException) as exc_info:
            service.get_audio_path(user_id=user.id, job_id=job.id, db=db_session)

        assert exc_info.value.status_code == 409
        assert "belum selesai" in exc_info.value.detail

    def test_get_audio_path_failed_raises_409(self, db_session, make_user, make_tts_job):
        """get_audio_path() saat status failed melempar 409 Conflict."""
        from backend.app.services.tts_job_service import TTSJobService

        user = make_user()
        job = make_tts_job(user=user, status="failed", error_message="Error")

        service = TTSJobService()
        with pytest.raises(HTTPException) as exc_info:
            service.get_audio_path(user_id=user.id, job_id=job.id, db=db_session)

        assert exc_info.value.status_code == 409
        assert "gagal" in exc_info.value.detail

    def test_get_audio_path_file_missing_raises_500(self, db_session, make_user, make_tts_job):
        """get_audio_path() saat file fisik tidak ditemukan di storage melempar 500."""
        from backend.app.services.tts_job_service import TTSJobService

        user = make_user()
        job = make_tts_job(
            user=user,
            status="completed",
            output_audio_path="/non/existent/path/audio.opus",
            completed_at=utcnow(),
        )

        service = TTSJobService()
        with pytest.raises(HTTPException) as exc_info:
            service.get_audio_path(user_id=user.id, job_id=job.id, db=db_session)

        assert exc_info.value.status_code == 500


class TestTTSJobServiceWorkerCallbacks:

    def test_record_gpu_wait_start_success(self, db_session, make_tts_job):
        """record_gpu_wait_start() mencatat waktu tunggu awal."""
        from backend.app.services.tts_job_service import TTSJobService

        job = make_tts_job(status="queued")
        assert job.gpu_wait_started_at is None

        service = TTSJobService()
        service.record_gpu_wait_start(job_id=job.id, db=db_session)

        db_session.refresh(job)
        assert job.gpu_wait_started_at is not None
        initial_time = job.gpu_wait_started_at

        # Panggilan ulang tidak menimpa waktu awal
        service.record_gpu_wait_start(job_id=job.id, db=db_session)
        db_session.refresh(job)
        assert job.gpu_wait_started_at == initial_time

    def test_update_start_success(self, db_session, make_tts_job):
        """update_start() mengubah status ke processing dan mencatat started_at."""
        from backend.app.services.tts_job_service import TTSJobService

        job = make_tts_job(status="queued")

        service = TTSJobService()
        service.update_start(job_id=job.id, db=db_session)

        db_session.refresh(job)
        assert job.status == "processing"
        assert job.started_at is not None

    def test_update_start_invalid_transition_raises_409(self, db_session, make_tts_job):
        """update_start() pada job completed/failed melempar 409."""
        from backend.app.services.tts_job_service import TTSJobService

        job = make_tts_job(status="completed", completed_at=utcnow())

        service = TTSJobService()
        with pytest.raises(HTTPException) as exc_info:
            service.update_start(job_id=job.id, db=db_session)

        assert exc_info.value.status_code == 409

    def test_complete_success(self, db_session, make_tts_job):
        """complete() mengubah status ke completed, menyimpan path, dan mencatat completed_at."""
        from backend.app.services.tts_job_service import TTSJobService

        job = make_tts_job(status="processing", started_at=utcnow())

        service = TTSJobService()
        service.complete(job_id=job.id, output_audio_path="/storage/out.opus", db=db_session)

        db_session.refresh(job)
        assert job.status == "completed"
        assert job.output_audio_path == "/storage/out.opus"
        assert job.completed_at is not None

    def test_complete_invalid_transition_raises_409(self, db_session, make_tts_job):
        """complete() pada job failed melempar 409."""
        from backend.app.services.tts_job_service import TTSJobService

        job = make_tts_job(status="failed", error_message="Failed")

        service = TTSJobService()
        with pytest.raises(HTTPException) as exc_info:
            service.complete(job_id=job.id, output_audio_path="/storage/out.opus", db=db_session)

        assert exc_info.value.status_code == 409

    def test_fail_success(self, db_session, make_tts_job):
        """fail() mengubah status ke failed, memotong error_message <= 500, dan completed_at None."""
        from backend.app.services.tts_job_service import TTSJobService

        job = make_tts_job(status="processing", started_at=utcnow())

        long_error = "E" * 600
        service = TTSJobService()
        service.fail(job_id=job.id, error_message=long_error, db=db_session)

        db_session.refresh(job)
        assert job.status == "failed"
        assert len(job.error_message) == 500
        assert job.completed_at is None

    def test_fail_invalid_transition_raises_409(self, db_session, make_tts_job):
        """fail() pada job completed melempar 409."""
        from backend.app.services.tts_job_service import TTSJobService

        job = make_tts_job(status="completed", completed_at=utcnow())

        service = TTSJobService()
        with pytest.raises(HTTPException) as exc_info:
            service.fail(job_id=job.id, error_message="Error", db=db_session)

        assert exc_info.value.status_code == 409

    def test_fail_due_to_gpu_timeout_success(self, db_session, make_tts_job):
        """fail_due_to_gpu_timeout() mengisi pesan error standar 30 menit GPU timeout."""
        from backend.app.services.tts_job_service import TTSJobService

        job = make_tts_job(status="queued")

        service = TTSJobService()
        service.fail_due_to_gpu_timeout(job_id=job.id, db=db_session)

        db_session.refresh(job)
        assert job.status == "failed"
        assert "30 menit" in job.error_message
        assert "real-time voice changer" in job.error_message
        assert job.completed_at is None
