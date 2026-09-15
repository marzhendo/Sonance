"""Logika bisnis pengelolaan Voice Profile.
Menangani pembuatan, listing, pembacaan, rename, penghapusan, dan status Voice Profile.
"""
import logging
import os
import uuid
from typing import Any, BinaryIO, Union

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from backend.app.models.voice_profile_model import VoiceProfile
from backend.app.schemas.voice_profile_schema import (
    SourceType,
    TrainingJobStatusResponse,
    VoiceProfileResponse,
    VoiceProfileStatus,
    VoiceProfileStatusResponse,
)
from backend.app.services.audio_utils import validate_and_extract_duration


class VoiceProfileService:
    """Service layer untuk operasi Voice Profile."""

    def create(
        self,
        user_id: Union[uuid.UUID, str],
        name: str,
        source_type: Union[SourceType, str],
        sample_audio: Union[UploadFile, bytes, BinaryIO],
        db: Session,
    ) -> VoiceProfileResponse:
        """
        Membuat Voice Profile baru dan menyimpan sample audio Opus ke storage lokal.
        Status awal selalu 'pending'.
        """
        user_uuid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))

        # Validasi nama Voice Profile
        if not isinstance(name, str):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Field name harus berupa string.",
            )
        trimmed_name = name.strip()
        if not trimmed_name:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Nama tidak boleh kosong atau hanya berisi whitespace.",
            )
        if len(trimmed_name) > 255:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Nama tidak boleh melebihi 255 karakter setelah di-trim.",
            )

        # Validasi source_type
        if isinstance(source_type, str):
            try:
                source_type = SourceType(source_type)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Field source_type tidak valid.",
                )

        # Baca konten audio mentah dari berbagai format input
        if isinstance(sample_audio, UploadFile):
            data = sample_audio.file.read()
        elif hasattr(sample_audio, "read"):
            data = sample_audio.read()
        elif isinstance(sample_audio, bytes):
            data = sample_audio
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File sample audio tidak valid.",
            )

        # Validasi format Opus dan rentang durasi 10–30 detik
        duration = validate_and_extract_duration(data)

        # Simpan file audio ke direktori konfigurasi
        storage_base = os.environ.get("SONANCE_SAMPLE_AUDIO_DIR", "/tmp/sonance/samples")
        user_dir = os.path.join(storage_base, str(user_uuid))
        profile_id = uuid.uuid4()
        filepath = os.path.join(user_dir, f"{profile_id}.opus")

        try:
            os.makedirs(user_dir, exist_ok=True)
            with open(filepath, "wb") as f:
                f.write(data)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Gagal menyimpan file audio ke storage lokal.",
            ) from e

        # Buat record di database dengan status 'pending'
        source_val = source_type.value if hasattr(source_type, "value") else str(source_type)
        try:
            vp = VoiceProfile(
                id=profile_id,
                user_id=user_uuid,
                name=trimmed_name,
                source_type=source_val,
                status=VoiceProfileStatus.pending.value,
                sample_audio_path=filepath,
                duration_seconds=duration,
            )
            db.add(vp)
            db.commit()
            db.refresh(vp)
        except Exception as e:
            db.rollback()
            # Bersihkan file dari disk agar tidak ada file yatim piatu
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except OSError:
                    pass
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Gagal menyimpan data voice profile ke database.",
            ) from e

        return VoiceProfileResponse.model_validate(vp)

    def list(
        self,
        user_id: Union[uuid.UUID, str],
        db: Session,
    ) -> list[VoiceProfileResponse]:
        """
        Mengambil daftar Voice Profile milik user terautentikasi, diurutkan created_at descending.
        Mengembalikan list kosong jika tidak ada data.
        Raises HTTPException 403 jika terdapat kebocoran data user lain (defense in depth).
        """
        user_uuid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
        stmt = (
            select(VoiceProfile)
            .where(VoiceProfile.user_id == user_uuid)
            .order_by(VoiceProfile.created_at.desc())
        )
        records = db.scalars(stmt).all()

        # Defense in depth: pastikan seluruh record benar-benar milik user_uuid
        for r in records:
            if r.user_id != user_uuid:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Akses terlarang: isolasi kepemilikan resource gagal.",
                )

        return [VoiceProfileResponse.model_validate(r) for r in records]

    def get(
        self,
        voice_profile_id: Union[uuid.UUID, str],
        user_id: Union[uuid.UUID, str],
        db: Session,
    ) -> VoiceProfileResponse:
        """
        Mengambil satu Voice Profile berdasarkan ID dan kepemilikan user.
        Raises HTTPException 404 jika tidak ditemukan atau milik user lain.
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
        record = db.scalars(stmt).first()
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Voice profile tidak ditemukan.",
            )

        return VoiceProfileResponse.model_validate(record)

    def rename(
        self,
        voice_profile_id: Union[uuid.UUID, str],
        user_id: Union[uuid.UUID, str],
        new_name: str,
        db: Session,
    ) -> VoiceProfileResponse:
        """
        Mengubah nama Voice Profile.
        Memvalidasi bahwa nama tidak kosong setelah di-trim dan tidak melebihi 100 karakter.
        Mempertahankan seluruh field lainnya tanpa perubahan.
        """
        vp_uuid = (
            voice_profile_id
            if isinstance(voice_profile_id, uuid.UUID)
            else uuid.UUID(str(voice_profile_id))
        )
        user_uuid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))

        if not isinstance(new_name, str):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Field name harus berupa string.",
            )

        trimmed = new_name.strip()
        if not trimmed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Nama tidak boleh kosong atau hanya berisi whitespace.",
            )
        if len(trimmed) > 100:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Nama tidak boleh melebihi 100 karakter setelah di-trim.",
            )

        stmt = select(VoiceProfile).where(
            VoiceProfile.id == vp_uuid,
            VoiceProfile.user_id == user_uuid,
        )
        record = db.scalars(stmt).first()
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Voice profile tidak ditemukan.",
            )

        record.name = trimmed
        from datetime import datetime, timezone
        record.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(record)

        return VoiceProfileResponse.model_validate(record)

    def delete(
        self,
        voice_profile_id: Union[uuid.UUID, str],
        user_id: Union[uuid.UUID, str],
        db: Session,
    ) -> None:
        """
        Menghapus Voice Profile beserta file audio dan checkpoint terkait di storage.
        Status 'processing' ditolak dengan HTTP 409.
        FileNotFoundError pada file fisik ditoleransi; OSError/PermissionError membatalkan
        penghapusan DB dan mengembalikan HTTP 500.
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
        record = db.scalars(stmt).first()
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Voice profile tidak ditemukan.",
            )

        if record.status == VoiceProfileStatus.processing.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Voice profile sedang diproses dan tidak dapat dihapus.",
            )

        # Hapus file fisik di filesystem sebelum menghapus record DB
        files_to_delete = [record.sample_audio_path, record.model_checkpoint_path]
        for fpath in files_to_delete:
            if fpath:
                try:
                    os.remove(fpath)
                except FileNotFoundError:
                    # FileNotFoundError ditoleransi sesuai spec
                    pass
                except (OSError, PermissionError) as e:
                    # I/O error menghentikan proses, DB tidak dihapus
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Gagal menghapus file dari storage.",
                    ) from e

        # Hapus record dari database (cascade akan otomatis menghapus training_job)
        db.delete(record)
        db.commit()

    def get_status(
        self,
        voice_profile_id: Union[uuid.UUID, str],
        user_id: Union[uuid.UUID, str],
        db: Session,
    ) -> VoiceProfileStatusResponse:
        """
        Mengambil status Voice Profile beserta status Training Job terkait.
        Memenuhi invarian status processing, failed, dan ready.
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

        job_resp = None
        if vp.training_job:
            tj = vp.training_job
            job_completed_at = tj.completed_at
            if vp.status == VoiceProfileStatus.failed.value:
                job_completed_at = None
            elif vp.status == VoiceProfileStatus.ready.value:
                if job_completed_at is None:
                    logger.warning(
                        "Voice profile %s berstatus 'ready' tetapi training_job.completed_at bernilai None di database. Menggunakan fallback updated_at untuk response API.",
                        vp.id,
                    )
                job_completed_at = job_completed_at or vp.updated_at

            progress = max(0, min(100, tj.progress_pct)) if tj.progress_pct is not None else 0
            job_resp = TrainingJobStatusResponse(
                status=tj.status,
                progress_pct=progress,
                started_at=tj.started_at,
                completed_at=job_completed_at,
            )

        if vp.status == VoiceProfileStatus.failed.value:
            error_msg = vp.error_message or "Terjadi kegagalan pada proses training voice profile."
        else:
            error_msg = None

        return VoiceProfileStatusResponse(
            id=vp.id,
            status=VoiceProfileStatus(vp.status),
            error_message=error_msg,
            training_job=job_resp,
        )
