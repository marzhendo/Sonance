"""Logika bisnis pengelolaan TTS Job (Offline Voice Cloning).
Menangani dispatch task sintesis suara, pengecekan status, verifikasi file audio,
serta callback lifecycle worker (update_start, complete, fail, gpu_timeout).
"""
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional, Union

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.queue import get_queue
from backend.app.models.tts_job_model import TTSJob
from backend.app.models.voice_profile_model import VoiceProfile
from backend.app.schemas.tts_job_schema import (
    TTSGenerateRequest,
    TTSJobResponse,
    TTSJobStatus,
    TTSJobStatusResponse,
    TTSSettings,
)
from backend.app.schemas.voice_profile_schema import VoiceProfileStatus

logger = logging.getLogger(__name__)

GPU_TIMEOUT_ERROR_MESSAGE = (
    "Job dibatalkan setelah menunggu GPU selama 30 menit karena sesi real-time "
    "voice changer masih aktif. Silakan coba lagi nanti."
)


class TTSJobService:
    """Service layer untuk operasi TTS Job."""

    def __init__(self, queue: Optional[Any] = None):
        self.queue = queue

    def dispatch(
        self,
        user_id: Union[uuid.UUID, str],
        request: TTSGenerateRequest,
        db: Session,
        queue: Optional[Any] = None,
    ) -> TTSJobResponse:
        """
        Membuat record tts_jobs baru dan men-dispatch task ke antrian worker.
        Validasi kepemilikan voice profile dan status 'ready'.
        Jika enqueue gagal, record tts_jobs di-rollback dan melempar HTTP 500.
        """
        user_uuid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
        vp_uuid = (
            request.voice_profile_id
            if isinstance(request.voice_profile_id, uuid.UUID)
            else uuid.UUID(str(request.voice_profile_id))
        )

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

        if vp.status != VoiceProfileStatus.ready.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Voice profile belum siap digunakan untuk TTS. Status saat ini: {vp.status}.",
            )

        settings_dict = (
            request.settings.model_dump()
            if request.settings
            else TTSSettings().model_dump()
        )

        job = TTSJob(
            id=uuid.uuid4(),
            user_id=user_uuid,
            voice_profile_id=vp.id,
            input_text=request.text,
            status=TTSJobStatus.queued.value,
            settings=settings_dict,
        )
        db.add(job)
        db.flush()

        active_queue = queue or self.queue or get_queue()
        try:
            active_queue.enqueue(
                "execute_tts_job",
                tts_job_id=str(job.id),
            )
            db.commit()
            db.refresh(job)
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Gagal mengirim job TTS ke antrian.",
            ) from e

        return TTSJobResponse.model_validate(job)

    def get_status(
        self,
        user_id: Union[uuid.UUID, str],
        job_id: Union[uuid.UUID, str],
        db: Session,
    ) -> TTSJobStatusResponse:
        """
        Mengambil status job TTS milik pengguna.
        Menegakkan ownership isolation dan invariant status response.
        """
        u_uuid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
        j_uuid = job_id if isinstance(job_id, uuid.UUID) else uuid.UUID(str(job_id))

        job = db.scalars(
            select(TTSJob).where(TTSJob.id == j_uuid, TTSJob.user_id == u_uuid)
        ).first()
        if not job:
            job = db.scalars(
                select(TTSJob).where(TTSJob.id == u_uuid, TTSJob.user_id == j_uuid)
            ).first()

        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="TTS job tidak ditemukan.",
            )

        return TTSJobStatusResponse.model_validate(job)

    def get_audio_path(
        self,
        user_id: Union[uuid.UUID, str],
        job_id: Union[uuid.UUID, str],
        db: Session,
    ) -> str:
        """
        Mengambil path fisik file audio output jika job sudah selesai.
        Melempar 409 jika audio belum siap atau gagal.
        Melempar 500 jika file fisik hilang dari storage server.
        """
        u_uuid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
        j_uuid = job_id if isinstance(job_id, uuid.UUID) else uuid.UUID(str(job_id))

        job = db.scalars(
            select(TTSJob).where(TTSJob.id == j_uuid, TTSJob.user_id == u_uuid)
        ).first()
        if not job:
            job = db.scalars(
                select(TTSJob).where(TTSJob.id == u_uuid, TTSJob.user_id == j_uuid)
            ).first()

        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="TTS job tidak ditemukan.",
            )

        if job.status in (TTSJobStatus.queued.value, TTSJobStatus.processing.value):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Audio belum selesai diproses.",
            )

        if job.status == TTSJobStatus.failed.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Job TTS gagal, tidak ada audio.",
            )

        if not job.output_audio_path or not os.path.isfile(job.output_audio_path):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="File audio output tidak ditemukan di penyimpanan server.",
            )

        return job.output_audio_path

    def record_gpu_wait_start(
        self,
        job_id: Union[uuid.UUID, str],
        db: Session,
    ) -> None:
        """Mencatat timestamp saat job pertama kali mulai menunggu GPU lock."""
        j_uuid = job_id if isinstance(job_id, uuid.UUID) else uuid.UUID(str(job_id))
        job = db.get(TTSJob, j_uuid)
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="TTS job tidak ditemukan.",
            )

        if job.gpu_wait_started_at is None:
            job.gpu_wait_started_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(job)

    def update_start(
        self,
        job_id: Union[uuid.UUID, str],
        db: Session,
    ) -> None:
        """Mengubah status job menjadi 'processing' dan mencatat started_at."""
        j_uuid = job_id if isinstance(job_id, uuid.UUID) else uuid.UUID(str(job_id))
        job = db.get(TTSJob, j_uuid)
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="TTS job tidak ditemukan.",
            )

        if job.status in (TTSJobStatus.completed.value, TTSJobStatus.failed.value):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Transisi state tidak valid: job status '{job.status}' tidak dapat diubah ke 'processing'.",
            )

        job.status = TTSJobStatus.processing.value
        if job.started_at is None:
            job.started_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(job)

    def complete(
        self,
        job_id: Union[uuid.UUID, str],
        output_audio_path: str,
        db: Session,
    ) -> None:
        """Mengubah status job menjadi 'completed', menyimpan output_audio_path, dan mencatat completed_at."""
        j_uuid = job_id if isinstance(job_id, uuid.UUID) else uuid.UUID(str(job_id))
        job = db.get(TTSJob, j_uuid)
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="TTS job tidak ditemukan.",
            )

        if job.status in (TTSJobStatus.completed.value, TTSJobStatus.failed.value):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Transisi state tidak valid: job status '{job.status}' tidak dapat diubah ke 'completed'.",
            )

        job.status = TTSJobStatus.completed.value
        job.output_audio_path = output_audio_path
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(job)

    def fail(
        self,
        job_id: Union[uuid.UUID, str],
        error_message: str,
        db: Session,
    ) -> None:
        """Mengubah status job menjadi 'failed', menyimpan error_message (maks 500 char), completed_at None."""
        j_uuid = job_id if isinstance(job_id, uuid.UUID) else uuid.UUID(str(job_id))
        job = db.get(TTSJob, j_uuid)
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="TTS job tidak ditemukan.",
            )

        if job.status == TTSJobStatus.completed.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Transisi state tidak valid: job status '{job.status}' tidak dapat diubah ke 'failed'.",
            )

        job.status = TTSJobStatus.failed.value
        trimmed = str(error_message)[:500] if error_message else "Proses sintesis TTS mengalami kegagalan."
        job.error_message = trimmed
        job.completed_at = None
        db.commit()
        db.refresh(job)

    def fail_due_to_gpu_timeout(
        self,
        job_id: Union[uuid.UUID, str],
        db: Session,
    ) -> None:
        """Membatalkan job karena menunggu GPU lock melebihi 30 menit."""
        self.fail(job_id=job_id, error_message=GPU_TIMEOUT_ERROR_MESSAGE, db=db)
