"""Integration tests untuk Training Worker, Job Consumer, dan State Transitions.
Wave 7 - Task 13.1, 13.4 (Property 5).
"""
import os
import uuid
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from backend.app.models.training_job_model import TrainingJob
from backend.app.models.user_model import User
from backend.app.models.voice_profile_model import VoiceProfile
from backend.app.schemas.voice_profile_schema import SourceType
from backend.app.services.training_job_service import TrainingJobService
from backend.workers.training_worker import execute_training_job, process_queue_jobs


class TestTrainingWorkerExecution:

    def test_execute_training_job_success_rvc(
        self, db_session, make_user, make_voice_profile, mock_storage, mock_queue
    ):
        user = make_user()
        vp = make_voice_profile(
            user=user,
            source_type="own_voice",
            status="pending",
            sample_audio_path=str(mock_storage["sample_dir"] / "test_rvc.opus"),
        )
        db_session.commit()

        service = TrainingJobService(queue=mock_queue)
        dispatch_resp = service.dispatch(voice_profile_id=vp.id, user_id=user.id, db=db_session)

        # Jalankan worker
        result = execute_training_job(
            voice_profile_id=str(vp.id),
            source_type="own_voice",
            db=db_session,
        )

        assert result["status"] == "completed"
        assert os.path.exists(result["checkpoint_path"])

        db_session.expire_all()
        reloaded_vp = db_session.get(VoiceProfile, vp.id)
        reloaded_job = db_session.get(TrainingJob, dispatch_resp.training_job_id)

        assert reloaded_vp.status == "ready"
        assert reloaded_vp.model_checkpoint_path == result["checkpoint_path"]
        assert reloaded_job.status == "completed"
        assert reloaded_job.progress_pct == 100
        assert reloaded_job.started_at is not None
        assert reloaded_job.completed_at is not None

    def test_execute_training_job_success_svc(
        self, db_session, make_user, make_voice_profile, mock_storage, mock_queue
    ):
        user = make_user()
        vp = make_voice_profile(
            user=user,
            source_type="character",
            status="pending",
            sample_audio_path=str(mock_storage["sample_dir"] / "test_svc.opus"),
        )
        db_session.commit()

        service = TrainingJobService(queue=mock_queue)
        dispatch_resp = service.dispatch(voice_profile_id=vp.id, user_id=user.id, db=db_session)

        result = execute_training_job(
            voice_profile_id=str(vp.id),
            source_type="character",
            db=db_session,
        )

        assert result["status"] == "completed"
        assert os.path.exists(result["checkpoint_path"])

        db_session.expire_all()
        reloaded_vp = db_session.get(VoiceProfile, vp.id)
        reloaded_job = db_session.get(TrainingJob, dispatch_resp.training_job_id)

        assert reloaded_vp.status == "ready"
        assert reloaded_job.status == "completed"
        assert reloaded_job.progress_pct == 100

    def test_execute_training_job_simulated_failure(
        self, db_session, make_user, make_voice_profile, mock_storage, mock_queue, monkeypatch
    ):
        monkeypatch.setenv("SONANCE_SIMULATE_TRAINING_FAILURE", "true")

        user = make_user()
        vp = make_voice_profile(
            user=user,
            source_type="own_voice",
            status="pending",
            sample_audio_path=str(mock_storage["sample_dir"] / "test_fail.opus"),
        )
        db_session.commit()

        service = TrainingJobService(queue=mock_queue)
        dispatch_resp = service.dispatch(voice_profile_id=vp.id, user_id=user.id, db=db_session)

        result = execute_training_job(
            voice_profile_id=str(vp.id),
            source_type="own_voice",
            db=db_session,
        )

        assert result["status"] == "failed"
        assert "error" in result

        db_session.expire_all()
        reloaded_vp = db_session.get(VoiceProfile, vp.id)
        reloaded_job = db_session.get(TrainingJob, dispatch_resp.training_job_id)

        assert reloaded_vp.status == "failed"
        assert reloaded_vp.error_message is not None
        assert len(reloaded_vp.error_message) <= 500
        assert reloaded_job.status == "failed"
        assert reloaded_job.error_log is not None
        assert "Traceback" in reloaded_job.error_log

    def test_execute_training_job_non_existent_profile_raises_value_error(self, db_session):
        random_id = uuid.uuid4()
        with pytest.raises(ValueError) as exc_info:
            execute_training_job(
                voice_profile_id=random_id,
                source_type="own_voice",
                db=db_session,
            )
        assert "tidak ditemukan" in str(exc_info.value)


class TestQueueConsumerIntegration:

    def test_process_queue_jobs_end_to_end(
        self, db_session, make_user, make_voice_profile, mock_storage, mock_queue
    ):
        user = make_user()
        vp1 = make_voice_profile(
            user=user,
            source_type="own_voice",
            status="pending",
            name="Profil 1",
            sample_audio_path=str(mock_storage["sample_dir"] / "vp1.opus"),
        )
        vp2 = make_voice_profile(
            user=user,
            source_type="character",
            status="pending",
            name="Profil 2",
            sample_audio_path=str(mock_storage["sample_dir"] / "vp2.opus"),
        )
        db_session.commit()

        service = TrainingJobService(queue=mock_queue)
        service.dispatch(voice_profile_id=vp1.id, user_id=user.id, db=db_session)
        service.dispatch(voice_profile_id=vp2.id, user_id=user.id, db=db_session)

        assert len(mock_queue.enqueued_jobs) == 2

        # Jalankan in-memory consumer
        results = process_queue_jobs(mock_queue, db=db_session)

        assert len(results) == 2
        assert all(r["status"] == "completed" for r in results)
        assert len(mock_queue.enqueued_jobs) == 0

        db_session.expire_all()
        assert db_session.get(VoiceProfile, vp1.id).status == "ready"
        assert db_session.get(VoiceProfile, vp2.id).status == "ready"


class TestTrainingWorkerLifecycleProperty:
    """Property 5: Training Job Lifecycle - State Transitions (Task 13.4)."""

    @settings(max_examples=25, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
    @given(
        source_type=st.sampled_from([SourceType.own_voice, SourceType.other_person, SourceType.character]),
        simulate_fail=st.booleans(),
    )
    def test_property_5_training_lifecycle_state_transitions(
        self, source_type, simulate_fail, db_session, make_user, make_voice_profile, mock_storage, mock_queue, monkeypatch
    ):
        # Feature: voice-profile-management, Property 5: Training Job Lifecycle State Transitions
        # Validates: Requirements 2.6, 2.7, 2.8
        if simulate_fail:
            monkeypatch.setenv("SONANCE_SIMULATE_TRAINING_FAILURE", "true")
        else:
            monkeypatch.delenv("SONANCE_SIMULATE_TRAINING_FAILURE", raising=False)

        user = make_user()
        vp = make_voice_profile(
            user=user,
            source_type=source_type.value,
            status="pending",
            sample_audio_path=str(mock_storage["sample_dir"] / f"{uuid.uuid4().hex}.opus"),
        )
        db_session.commit()

        service = TrainingJobService(queue=mock_queue)
        dispatch_res = service.dispatch(voice_profile_id=vp.id, user_id=user.id, db=db_session)

        # Status awal sebelum worker jalan
        db_session.expire_all()
        job_before = db_session.get(TrainingJob, dispatch_res.training_job_id)
        assert job_before.status == "queued"
        assert job_before.progress_pct == 0
        assert job_before.started_at is None
        assert job_before.completed_at is None

        # Jalankan worker
        exec_res = execute_training_job(
            voice_profile_id=str(vp.id),
            source_type=source_type,
            db=db_session,
        )

        db_session.expire_all()
        vp_after = db_session.get(VoiceProfile, vp.id)
        job_after = db_session.get(TrainingJob, dispatch_res.training_job_id)

        assert job_after.started_at is not None

        if simulate_fail:
            assert exec_res["status"] == "failed"
            assert vp_after.status == "failed"
            assert vp_after.error_message is not None
            assert len(vp_after.error_message) <= 500
            assert job_after.status == "failed"
            assert job_after.error_log is not None
        else:
            assert exec_res["status"] == "completed"
            assert vp_after.status == "ready"
            assert vp_after.model_checkpoint_path is not None
            assert os.path.exists(vp_after.model_checkpoint_path)
            assert job_after.status == "completed"
            assert job_after.progress_pct == 100
            assert job_after.completed_at is not None

        # Cleanup data untuk siklus property test berikutnya
        db_session.query(TrainingJob).filter_by(voice_profile_id=vp.id).delete()
        db_session.query(VoiceProfile).filter_by(id=vp.id).delete()
        db_session.query(User).filter_by(id=user.id).delete()
        db_session.commit()

    @settings(max_examples=25, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
    @given(
        terminal_status=st.sampled_from(["completed", "failed"]),
        attempt_transition=st.sampled_from(["update_start", "complete", "fail"]),
    )
    def test_property_5_invalid_state_transitions_strictly_rejected(
        self, terminal_status, attempt_transition, db_session, make_user, make_voice_profile, make_training_job
    ):
        # Feature: voice-profile-management, Property 5: Rejection of Invalid State Transitions
        # Validates: Requirements 2.6, 2.7, 2.8
        from fastapi import HTTPException

        user = make_user()
        vp_status = "ready" if terminal_status == "completed" else "failed"
        vp = make_voice_profile(user=user, status=vp_status)
        tj = make_training_job(
            voice_profile=vp,
            status=terminal_status,
            progress_pct=100 if terminal_status == "completed" else 50,
        )
        db_session.commit()

        service = TrainingJobService()

        # Jika job sudah di status terminal (completed/failed), transisi terlarang harus raise HTTP 409
        if attempt_transition == "update_start":
            with pytest.raises(HTTPException) as exc:
                service.update_start(training_job_id=tj.id, voice_profile_id_or_db=vp.id, db=db_session)
            assert exc.value.status_code == 409
        elif attempt_transition == "complete":
            with pytest.raises(HTTPException) as exc:
                service.complete(
                    training_job_id=tj.id,
                    voice_profile_id_or_checkpoint=vp.id,
                    checkpoint_path_or_db="/tmp/new.pth",
                    db=db_session,
                )
            assert exc.value.status_code == 409
        elif attempt_transition == "fail":
            if terminal_status == "completed":
                with pytest.raises(HTTPException) as exc:
                    service.fail(
                        training_job_id=tj.id,
                        voice_profile_id_or_error_summary=vp.id,
                        error_summary_or_log="Error baru",
                        error_log_or_db="Traceback...",
                        db=db_session,
                    )
                assert exc.value.status_code == 409

        # Invariant: status di DB tidak berubah setelah transisi terlarang ditolak
        db_session.expire_all()
        assert db_session.get(VoiceProfile, vp.id).status == vp_status
        assert db_session.get(TrainingJob, tj.id).status == terminal_status

        # Cleanup
        db_session.query(TrainingJob).filter_by(voice_profile_id=vp.id).delete()
        db_session.query(VoiceProfile).filter_by(id=vp.id).delete()
        db_session.query(User).filter_by(id=user.id).delete()
        db_session.commit()
