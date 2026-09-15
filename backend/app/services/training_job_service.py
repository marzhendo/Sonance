"""Logika bisnis pengelolaan Training Job.
Menangani dispatch training job ke antrian, pelacakan progress, dan pembaruan lifecycle.
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Optional, Union

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.queue import get_queue
from backend.app.models.training_job_model import TrainingJob
from backend.app.models.voice_profile_model import VoiceProfile
from backend.app.schemas.training_job_schema import TrainingJobDispatchResponse
from backend.app.schemas.voice_profile_schema import VoiceProfileStatus


class TrainingJobService:
    """Service layer untuk operasi Training Job."""

    def __init__(self, queue: Optional[Any] = None):
        self.queue = queue

    def dispatch(
        self,
        voice_profile_id: Union[uuid.UUID, str],
        user_id: Union[uuid.UUID, str],
        db: Session,
        queue: Optional[Any] = None,
    ) -> TrainingJobDispatchResponse:
        """
        Membuat record training_job dan men-dispatch task ke antrian worker.
        Voice Profile wajib memiliki status 'pending'.
        Jika dispatch gagal, record training_job di-rollback dan voice_profiles.status tetap 'pending'.
        """
        vp_uuid = (
            voice_profile_id
            if isinstance(voice_profile_id, uuid.UUID)
            else uuid.UUID(str(voice_profile_id))
        )
        user_uuid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))

        stmt = select(VoiceProfile).where(
            VoiceProfile.id == vp_uuid,
            VoiceProfile.user_id == user_uuid,
        )
        vp = db.scalars(stmt).first()
        if not vp:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Voice profile tidak ditemukan.",
            )

        if vp.status != VoiceProfileStatus.pending.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Training hanya dapat dijalankan pada Voice Profile dengan status pending.",
            )

        training_job = TrainingJob(
            id=uuid.uuid4(),
            voice_profile_id=vp.id,
            status="queued",
            progress_pct=0,
        )
        db.add(training_job)

        active_queue = queue or self.queue or get_queue()
        try:
            active_queue.enqueue(
                "execute_training_job",
                voice_profile_id=str(vp.id),
                source_type=vp.source_type,
            )
            db.commit()
            db.refresh(training_job)
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Gagal mengirim job training ke antrian.",
            ) from e

        return TrainingJobDispatchResponse(
            training_job_id=training_job.id,
            status=training_job.status,
        )

    def update_start(
        self,
        training_job_id: Union[uuid.UUID, str],
        voice_profile_id_or_db: Union[uuid.UUID, str, Session],
        db: Optional[Session] = None,
    ) -> None:
        """
        Pembaruan status awal saat worker mulai menjalankan proses training.
        Memperbarui status training_jobs dan voice_profiles menjadi 'processing'.
        Mencatat waktu started_at pada training_jobs.
        """
        if db is None and isinstance(voice_profile_id_or_db, Session):
            active_db = voice_profile_id_or_db
            vp_uuid = None
        else:
            active_db = db
            vp_uuid = (
                voice_profile_id_or_db
                if isinstance(voice_profile_id_or_db, uuid.UUID)
                else uuid.UUID(str(voice_profile_id_or_db))
            )

        job_uuid = (
            training_job_id
            if isinstance(training_job_id, uuid.UUID)
            else uuid.UUID(str(training_job_id))
        )

        job = active_db.get(TrainingJob, job_uuid)
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Training job tidak ditemukan.",
            )

        target_vp_id = vp_uuid or job.voice_profile_id
        vp = active_db.get(VoiceProfile, target_vp_id)
        if not vp:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Voice profile tidak ditemukan.",
            )

        if job.status in ("completed", "failed") or vp.status in (VoiceProfileStatus.ready.value, VoiceProfileStatus.failed.value):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Transisi state tidak valid: job status '{job.status}' tidak dapat diubah kembali ke 'processing'.",
            )

        job.status = "processing"
        now = datetime.now(timezone.utc)
        if job.started_at is None:
            job.started_at = now
        vp.status = VoiceProfileStatus.processing.value
        vp.updated_at = now
        active_db.commit()
        active_db.refresh(job)
        active_db.refresh(vp)

    def update_progress(
        self,
        training_job_id: Union[uuid.UUID, str],
        progress_pct: int,
        db: Session,
    ) -> None:
        """
        Pembaruan berkala persentase progress training job oleh worker.
        Nilai progress harus berada di antara 0 dan 100 inklusif.
        """
        if not isinstance(progress_pct, int) or progress_pct < 0 or progress_pct > 100:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Nilai progress_pct harus berupa bilangan bulat antara 0 dan 100.",
            )

        job_uuid = (
            training_job_id
            if isinstance(training_job_id, uuid.UUID)
            else uuid.UUID(str(training_job_id))
        )

        job = db.get(TrainingJob, job_uuid)
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Training job tidak ditemukan.",
            )

        job.progress_pct = progress_pct
        db.commit()
        db.refresh(job)

    def complete(
        self,
        training_job_id: Union[uuid.UUID, str],
        voice_profile_id_or_checkpoint: Union[uuid.UUID, str],
        checkpoint_path_or_db: Union[str, Session],
        db: Optional[Session] = None,
    ) -> None:
        """
        Pemberitahuan keberhasilan proses training oleh worker.
        Memperbarui status training_jobs menjadi 'completed' dan voice_profiles menjadi 'ready'.
        Menyimpan path checkpoint model dan mencatat waktu completed_at.
        """
        if db is None and isinstance(checkpoint_path_or_db, Session):
            active_db = checkpoint_path_or_db
            checkpoint_path = str(voice_profile_id_or_checkpoint)
            vp_uuid = None
        else:
            active_db = db
            checkpoint_path = str(checkpoint_path_or_db)
            vp_uuid = (
                voice_profile_id_or_checkpoint
                if isinstance(voice_profile_id_or_checkpoint, uuid.UUID)
                else uuid.UUID(str(voice_profile_id_or_checkpoint))
            )

        job_uuid = (
            training_job_id
            if isinstance(training_job_id, uuid.UUID)
            else uuid.UUID(str(training_job_id))
        )

        job = active_db.get(TrainingJob, job_uuid)
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Training job tidak ditemukan.",
            )

        target_vp_id = vp_uuid or job.voice_profile_id
        vp = active_db.get(VoiceProfile, target_vp_id)
        if not vp:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Voice profile tidak ditemukan.",
            )

        if job.status in ("completed", "failed") or vp.status in (VoiceProfileStatus.ready.value, VoiceProfileStatus.failed.value):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Transisi state tidak valid: job status '{job.status}' tidak dapat diubah ke 'completed'.",
            )

        now = datetime.now(timezone.utc)
        job.status = "completed"
        job.progress_pct = 100
        job.completed_at = now

        vp.status = VoiceProfileStatus.ready.value
        vp.model_checkpoint_path = checkpoint_path
        vp.updated_at = now

        active_db.commit()
        active_db.refresh(job)
        active_db.refresh(vp)

    def fail(
        self,
        training_job_id: Union[uuid.UUID, str],
        voice_profile_id_or_error_summary: Union[uuid.UUID, str],
        error_summary_or_log: Optional[str] = None,
        error_log_or_db: Optional[Union[str, Session]] = None,
        db: Optional[Session] = None,
    ) -> None:
        """
        Pemberitahuan kegagalan proses training oleh worker.
        Memperbarui status training_jobs dan voice_profiles menjadi 'failed'.
        Menyimpan pesan error diringkas maksimal 500 karakter dan full stack trace.
        """
        if db is None and isinstance(error_log_or_db, Session):
            active_db = error_log_or_db
            error_summary = str(voice_profile_id_or_error_summary)
            error_log = error_summary_or_log
            vp_uuid = None
        else:
            active_db = db
            vp_uuid = (
                voice_profile_id_or_error_summary
                if isinstance(voice_profile_id_or_error_summary, uuid.UUID)
                else uuid.UUID(str(voice_profile_id_or_error_summary))
            )
            error_summary = str(error_summary_or_log or "")
            error_log = str(error_log_or_db) if error_log_or_db is not None else None

        job_uuid = (
            training_job_id
            if isinstance(training_job_id, uuid.UUID)
            else uuid.UUID(str(training_job_id))
        )

        job = active_db.get(TrainingJob, job_uuid)
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Training job tidak ditemukan.",
            )

        target_vp_id = vp_uuid or job.voice_profile_id
        vp = active_db.get(VoiceProfile, target_vp_id)
        if not vp:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Voice profile tidak ditemukan.",
            )

        if job.status == "completed" or vp.status == VoiceProfileStatus.ready.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Transisi state tidak valid: job status '{job.status}' tidak dapat diubah ke 'failed'.",
            )

        now = datetime.now(timezone.utc)
        job.status = "failed"
        job.error_log = error_log

        vp.status = VoiceProfileStatus.failed.value
        trimmed_summary = error_summary[:500] if error_summary else "Proses training mengalami kegagalan."
        vp.error_message = trimmed_summary
        vp.updated_at = now

        active_db.commit()
        active_db.refresh(job)
        active_db.refresh(vp)


