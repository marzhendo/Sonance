"""
Tests untuk ORM model TTSJob.
Wave 1: ORM Model.

Memverifikasi bahwa model TTSJob:
1. Menggunakan Mapped[] annotation style SQLAlchemy 2.x dan UUIDType.
2. Default value terpasang dengan benar (status="queued", settings, created_at).
3. Relasi N-to-1 ke User dan VoiceProfile bekerja dua arah.
4. Relasi 1-to-N di User (RESTRICT) dan VoiceProfile (CASCADE) bekerja sesuai spesifikasi.
5. __repr__ informatif.
"""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError


class TestTTSJobModel:

    def test_create_tts_job_success(self, db_session, make_user, make_voice_profile):
        """TTSJob berhasil dibuat dengan atribut valid dan UUIDType."""
        from backend.app.models.tts_job_model import TTSJob

        user = make_user()
        vp = make_voice_profile(user=user, status="ready")

        job = TTSJob(
            user_id=user.id,
            voice_profile_id=vp.id,
            input_text="Halo, ini adalah pengujian sintesis suara.",
            settings={"language": "id", "speed": 1.0, "pitch_shift": 0, "temperature": 0.7, "output_format": "opus"},
        )
        db_session.add(job)
        db_session.flush()

        assert isinstance(job.id, uuid.UUID)
        assert job.user_id == user.id
        assert job.voice_profile_id == vp.id
        assert job.status == "queued"
        assert job.input_text == "Halo, ini adalah pengujian sintesis suara."
        assert job.settings["language"] == "id"
        assert job.output_audio_path is None
        assert job.error_message is None
        assert job.gpu_wait_started_at is None
        assert job.started_at is None
        assert job.completed_at is None
        assert isinstance(job.created_at, datetime)

    def test_tts_job_relationships(self, db_session, make_user, make_voice_profile):
        """Relasi TTSJob ke User dan VoiceProfile dapat diakses dua arah."""
        from backend.app.models.tts_job_model import TTSJob

        user = make_user()
        vp = make_voice_profile(user=user, status="ready")

        job = TTSJob(
            user_id=user.id,
            voice_profile_id=vp.id,
            input_text="Teks sintesis relasi",
            settings={"language": "id"},
        )
        db_session.add(job)
        db_session.flush()

        # N-to-1 dari job
        assert job.user.id == user.id
        assert job.voice_profile.id == vp.id

        # 1-to-N dari user dan voice profile
        assert job in user.tts_jobs
        assert job in vp.tts_jobs

    def test_tts_job_cascade_delete_on_voice_profile_removal(
        self, db_session, make_user, make_voice_profile
    ):
        """Menghapus VoiceProfile otomatis menghapus TTSJob terkait (CASCADE)."""
        from backend.app.models.tts_job_model import TTSJob
        from backend.app.models.voice_profile_model import VoiceProfile

        user = make_user()
        vp = make_voice_profile(user=user, status="ready")
        job = TTSJob(
            user_id=user.id,
            voice_profile_id=vp.id,
            input_text="Teks untuk uji cascade delete",
            settings={},
        )
        db_session.add(job)
        db_session.commit()

        job_id = job.id

        # Hapus voice profile
        db_session.delete(vp)
        db_session.commit()

        # Job harus ikut terhapus
        assert db_session.get(TTSJob, job_id) is None

    def test_tts_job_restrict_on_user_removal(
        self, db_session, make_user, make_voice_profile
    ):
        """Menghapus User yang memiliki TTSJob ditolak (RESTRICT)."""
        from backend.app.models.tts_job_model import TTSJob

        owner = make_user()
        user = make_user()
        vp = make_voice_profile(user=owner, status="ready")
        job = TTSJob(
            user_id=user.id,
            voice_profile_id=vp.id,
            input_text="Teks untuk uji restrict user",
            settings={},
        )
        db_session.add(job)
        db_session.commit()

        # Hapus user harus raise IntegrityError karena tts_jobs milik user ini masih ada dan ondelete=RESTRICT
        db_session.delete(user)
        with pytest.raises(IntegrityError):
            db_session.commit()

        db_session.rollback()

    def test_tts_job_repr(self, make_user, make_voice_profile):
        """String representasi TTSJob mencakup id dan status."""
        from backend.app.models.tts_job_model import TTSJob

        user = make_user()
        vp = make_voice_profile(user=user)
        job_id = uuid.uuid4()
        job = TTSJob(
            id=job_id,
            user_id=user.id,
            voice_profile_id=vp.id,
            input_text="Teks repr",
            status="processing",
            settings={},
        )
        representation = repr(job)
        assert "TTSJob" in representation
        assert str(job_id)[:8] in representation
        assert "processing" in representation
