"""Tests untuk TrainingJobService.
Wave 4: Task 9.1 (dispatch).
"""
import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from backend.app.models.training_job_model import TrainingJob
from backend.app.models.voice_profile_model import VoiceProfile
from backend.app.schemas.training_job_schema import TrainingJobDispatchResponse
from backend.app.services.training_job_service import TrainingJobService


class TestTrainingJobServiceDispatch:

    def test_dispatch_success(self, db_session, make_user, make_voice_profile, mock_queue):
        user = make_user()
        vp = make_voice_profile(user=user, status="pending", source_type="own_voice")
        db_session.commit()

        service = TrainingJobService()
        result = service.dispatch(
            voice_profile_id=vp.id,
            user_id=user.id,
            db=db_session,
            queue=mock_queue,
        )

        assert isinstance(result, TrainingJobDispatchResponse)
        assert result.training_job_id is not None
        assert result.status == "queued"

        # Verifikasi record training_jobs dibuat di DB
        job = db_session.get(TrainingJob, result.training_job_id)
        assert job is not None
        assert job.voice_profile_id == vp.id
        assert job.status == "queued"
        assert job.progress_pct == 0
        assert job.started_at is None

        # Verifikasi di-enqueue ke job queue
        assert len(mock_queue.enqueued_jobs) == 1
        enqueued = mock_queue.enqueued_jobs[0]
        assert enqueued["kwargs"]["voice_profile_id"] == str(vp.id)
        assert enqueued["kwargs"]["source_type"] == "own_voice"

    def test_dispatch_non_existent_voice_profile_raises_404(
        self, db_session, make_user, mock_queue
    ):
        user = make_user()
        service = TrainingJobService()

        with pytest.raises(HTTPException) as exc_info:
            service.dispatch(
                voice_profile_id=uuid.uuid4(),
                user_id=user.id,
                db=db_session,
                queue=mock_queue,
            )

        assert exc_info.value.status_code == 404
        assert "tidak ditemukan" in exc_info.value.detail

    def test_dispatch_other_user_profile_raises_404(
        self, db_session, make_user, make_voice_profile, mock_queue
    ):
        user_a = make_user()
        user_b = make_user()
        vp_b = make_voice_profile(user=user_b, status="pending")
        db_session.commit()

        service = TrainingJobService()
        with pytest.raises(HTTPException) as exc_info:
            service.dispatch(
                voice_profile_id=vp_b.id,
                user_id=user_a.id,
                db=db_session,
                queue=mock_queue,
            )

        assert exc_info.value.status_code == 404
        assert len(mock_queue.enqueued_jobs) == 0

    @pytest.mark.parametrize("invalid_status", ["processing", "ready", "failed"])
    def test_dispatch_status_not_pending_raises_409(
        self, db_session, make_user, make_voice_profile, mock_queue, invalid_status
    ):
        user = make_user()
        vp = make_voice_profile(user=user, status=invalid_status)
        db_session.commit()

        service = TrainingJobService()
        with pytest.raises(HTTPException) as exc_info:
            service.dispatch(
                voice_profile_id=vp.id,
                user_id=user.id,
                db=db_session,
                queue=mock_queue,
            )

        assert exc_info.value.status_code == 409
        assert "pending" in exc_info.value.detail.lower()
        assert len(mock_queue.enqueued_jobs) == 0

    def test_dispatch_queue_failure_rolls_back_job_and_keeps_pending(
        self, db_session, make_user, make_voice_profile
    ):
        user = make_user()
        vp = make_voice_profile(user=user, status="pending")
        db_session.commit()

        # Mock queue yang melempar exception saat enqueue
        broken_queue = MagicMock()
        broken_queue.enqueue.side_effect = RuntimeError("Redis connection lost")

        service = TrainingJobService()
        with pytest.raises(HTTPException) as exc_info:
            service.dispatch(
                voice_profile_id=vp.id,
                user_id=user.id,
                db=db_session,
                queue=broken_queue,
            )

        assert exc_info.value.status_code == 500

        # Verifikasi tidak ada record training_jobs yang tertinggal
        jobs = db_session.query(TrainingJob).filter_by(voice_profile_id=vp.id).all()
        assert len(jobs) == 0

        # Verifikasi voice profile tetap pending
        db_session.expire_all()
        reloaded_vp = db_session.get(VoiceProfile, vp.id)
        assert reloaded_vp.status == "pending"


class TestTrainingJobServiceUpdateStart:

    def test_update_start_success(self, db_session, make_user, make_voice_profile, make_training_job):
        user = make_user()
        vp = make_voice_profile(user=user, status="pending")
        tj = make_training_job(voice_profile=vp, status="queued")
        db_session.commit()

        service = TrainingJobService()
        service.update_start(training_job_id=tj.id, voice_profile_id_or_db=vp.id, db=db_session)

        db_session.expire_all()
        reloaded_job = db_session.get(TrainingJob, tj.id)
        reloaded_vp = db_session.get(VoiceProfile, vp.id)

        assert reloaded_job.status == "processing"
        assert reloaded_job.started_at is not None
        assert reloaded_vp.status == "processing"

    def test_update_start_job_not_found_raises_404(self, db_session, make_user, make_voice_profile):
        user = make_user()
        vp = make_voice_profile(user=user, status="pending")
        db_session.commit()

        service = TrainingJobService()
        with pytest.raises(HTTPException) as exc_info:
            service.update_start(training_job_id=uuid.uuid4(), voice_profile_id_or_db=vp.id, db=db_session)

        assert exc_info.value.status_code == 404


class TestTrainingJobServiceUpdateProgress:

    def test_update_progress_success(self, db_session, make_user, make_voice_profile, make_training_job):
        user = make_user()
        vp = make_voice_profile(user=user, status="processing")
        tj = make_training_job(voice_profile=vp, status="processing", progress_pct=10)
        db_session.commit()

        service = TrainingJobService()
        service.update_progress(training_job_id=tj.id, progress_pct=75, db=db_session)

        db_session.expire_all()
        reloaded_job = db_session.get(TrainingJob, tj.id)
        assert reloaded_job.progress_pct == 75

    @pytest.mark.parametrize("invalid_pct", [-1, 101, 150])
    def test_update_progress_out_of_bounds_raises_422(
        self, db_session, make_user, make_voice_profile, make_training_job, invalid_pct
    ):
        user = make_user()
        vp = make_voice_profile(user=user, status="processing")
        tj = make_training_job(voice_profile=vp, status="processing", progress_pct=0)
        db_session.commit()

        service = TrainingJobService()
        with pytest.raises(HTTPException) as exc_info:
            service.update_progress(training_job_id=tj.id, progress_pct=invalid_pct, db=db_session)

        assert exc_info.value.status_code == 422

    def test_update_progress_job_not_found_raises_404(self, db_session):
        service = TrainingJobService()
        with pytest.raises(HTTPException) as exc_info:
            service.update_progress(training_job_id=uuid.uuid4(), progress_pct=50, db=db_session)

        assert exc_info.value.status_code == 404


class TestTrainingJobServiceComplete:

    def test_complete_success(self, db_session, make_user, make_voice_profile, make_training_job):
        user = make_user()
        vp = make_voice_profile(user=user, status="processing")
        tj = make_training_job(voice_profile=vp, status="processing", progress_pct=90)
        db_session.commit()

        checkpoint_file = "/var/models/checkpoints/model_v1.pth"
        service = TrainingJobService()
        service.complete(
            training_job_id=tj.id,
            voice_profile_id_or_checkpoint=vp.id,
            checkpoint_path_or_db=checkpoint_file,
            db=db_session,
        )

        db_session.expire_all()
        reloaded_job = db_session.get(TrainingJob, tj.id)
        reloaded_vp = db_session.get(VoiceProfile, vp.id)

        assert reloaded_job.status == "completed"
        assert reloaded_job.progress_pct == 100
        assert reloaded_job.completed_at is not None
        assert reloaded_vp.status == "ready"
        assert reloaded_vp.model_checkpoint_path == checkpoint_file

    def test_complete_job_not_found_raises_404(self, db_session, make_user, make_voice_profile):
        user = make_user()
        vp = make_voice_profile(user=user, status="processing")
        db_session.commit()

        service = TrainingJobService()
        with pytest.raises(HTTPException) as exc_info:
            service.complete(
                training_job_id=uuid.uuid4(),
                voice_profile_id_or_checkpoint=vp.id,
                checkpoint_path_or_db="/tmp/cp.pth",
                db=db_session,
            )

        assert exc_info.value.status_code == 404


class TestTrainingJobServiceFail:

    def test_fail_success(self, db_session, make_user, make_voice_profile, make_training_job):
        user = make_user()
        vp = make_voice_profile(user=user, status="processing")
        tj = make_training_job(voice_profile=vp, status="processing", progress_pct=50)
        db_session.commit()

        error_msg = "CUDA out of memory during epoch 4"
        stack_trace = "Traceback (most recent call last):\nFile 'train.py', line 42..."
        service = TrainingJobService()
        service.fail(
            training_job_id=tj.id,
            voice_profile_id_or_error_summary=vp.id,
            error_summary_or_log=error_msg,
            error_log_or_db=stack_trace,
            db=db_session,
        )

        db_session.expire_all()
        reloaded_job = db_session.get(TrainingJob, tj.id)
        reloaded_vp = db_session.get(VoiceProfile, vp.id)

        assert reloaded_job.status == "failed"
        assert reloaded_job.error_log == stack_trace
        assert reloaded_vp.status == "failed"
        assert reloaded_vp.error_message == error_msg

    def test_fail_truncates_error_summary_to_500_chars(
        self, db_session, make_user, make_voice_profile, make_training_job
    ):
        user = make_user()
        vp = make_voice_profile(user=user, status="processing")
        tj = make_training_job(voice_profile=vp, status="processing")
        db_session.commit()

        long_error = "A" * 700
        service = TrainingJobService()
        service.fail(
            training_job_id=tj.id,
            voice_profile_id_or_error_summary=vp.id,
            error_summary_or_log=long_error,
            error_log_or_db="stack trace",
            db=db_session,
        )

        db_session.expire_all()
        reloaded_vp = db_session.get(VoiceProfile, vp.id)
        assert len(reloaded_vp.error_message) == 500
        assert reloaded_vp.error_message == "A" * 500


