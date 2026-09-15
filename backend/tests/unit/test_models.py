"""
Tests untuk ORM models: User, VoiceProfile, dan TrainingJob.
Wave 1 — Task 1.2 dan 1.3 (updated: native UUIDType, FK users enforced).

Fixtures `session` dan `engine` disediakan oleh conftest.py.
Factories `make_user` dan `make_voice_profile` disediakan oleh conftest.py
sebagai fixture, atau diakses via helper lokal di bawah untuk backward compat.
"""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect


# ---------------------------------------------------------------------------
# Local helpers — wrapper tipis atas factory fixtures
# (dipakai oleh tests yang tidak bisa menerima fixture factory langsung)
# ---------------------------------------------------------------------------

def _make_user(session, **kwargs):
    """Helper lokal: buat User langsung via ORM (tanpa fixture injection)."""
    from backend.app.models.user_model import User
    data = {
        "id": uuid.uuid4(),
        "email": f"u_{uuid.uuid4().hex[:8]}@test.com",
        "password_hash": "hashed",
    }
    data.update(kwargs)
    user = User(**data)
    session.add(user)
    session.flush()
    return user


def _make_voice_profile(session, user=None, **kwargs):
    """Helper lokal: buat VoiceProfile langsung via ORM (tanpa fixture injection)."""
    from backend.app.models.voice_profile_model import VoiceProfile
    if user is None:
        user = _make_user(session)
    data = {
        "id": uuid.uuid4(),
        "user_id": user.id,
        "name": "Suara Gue",
        "source_type": "own_voice",
        "status": "pending",
        "duration_seconds": 15.0,
    }
    data.update(kwargs)
    vp = VoiceProfile(**data)
    session.add(vp)
    session.flush()
    return vp


# ---------------------------------------------------------------------------
# User model — sanity checks
# ---------------------------------------------------------------------------

class TestUserModel:

    def test_table_name_is_users(self):
        from backend.app.models.user_model import User
        assert User.__tablename__ == "users"

    def test_can_create_and_persist(self, session):
        from backend.app.models.user_model import User
        user = _make_user(session)
        session.commit()
        fetched = session.get(User, user.id)
        assert fetched is not None
        assert fetched.email == user.email

    def test_email_is_unique(self, session):
        from backend.app.models.user_model import User
        from sqlalchemy.exc import IntegrityError
        email = f"dup_{uuid.uuid4().hex[:8]}@test.com"
        _make_user(session, email=email)
        session.commit()
        # Buat user kedua dengan email yang sama — harus raise IntegrityError
        # saat flush (karena UNIQUE constraint)
        from backend.app.models.user_model import User
        dup = User(id=uuid.uuid4(), email=email, password_hash="hashed")
        session.add(dup)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

    def test_id_returns_as_uuid_object(self, session):
        """UUIDType harus mengembalikan uuid.UUID, bukan string."""
        user = _make_user(session)
        session.commit()
        session.expire(user)
        session.refresh(user)
        assert isinstance(user.id, uuid.UUID)


# ---------------------------------------------------------------------------
# VoiceProfile model
# ---------------------------------------------------------------------------

class TestVoiceProfileModel:

    def test_table_name_is_voice_profiles(self):
        from backend.app.models.voice_profile_model import VoiceProfile
        assert VoiceProfile.__tablename__ == "voice_profiles"

    def test_can_create_and_persist(self, session):
        """VoiceProfile bisa di-INSERT dan di-query kembali."""
        from backend.app.models.voice_profile_model import VoiceProfile
        vp = _make_voice_profile(session)
        session.commit()
        fetched = session.get(VoiceProfile, vp.id)
        assert fetched is not None
        assert fetched.name == "Suara Gue"
        assert fetched.source_type == "own_voice"
        assert fetched.status == "pending"
        assert fetched.duration_seconds == 15.0

    def test_id_returns_as_uuid_object(self, session):
        """UUIDType harus mengembalikan uuid.UUID, bukan string."""
        vp = _make_voice_profile(session)
        session.commit()
        session.expire(vp)
        session.refresh(vp)
        assert isinstance(vp.id, uuid.UUID)
        assert isinstance(vp.user_id, uuid.UUID)

    def test_required_fields_present(self):
        """Semua kolom wajib terdefinisi di model."""
        from backend.app.models.voice_profile_model import VoiceProfile
        cols = {c.key for c in VoiceProfile.__table__.columns}
        required = {
            "id", "user_id", "name", "source_type", "status",
            "sample_audio_path", "model_checkpoint_path",
            "duration_seconds", "error_message", "created_at", "updated_at",
        }
        assert required.issubset(cols)

    def test_fk_to_users_enforced(self, session):
        """user_id harus FK valid — insert dengan user_id tidak dikenal harus gagal."""
        from backend.app.models.voice_profile_model import VoiceProfile
        from sqlalchemy.exc import IntegrityError
        orphan = VoiceProfile(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),  # tidak ada di tabel users
            name="Orphan",
            source_type="own_voice",
            duration_seconds=15.0,
        )
        session.add(orphan)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_nullable_optional_fields(self, session):
        """Field opsional boleh NULL."""
        vp = _make_voice_profile(session)
        session.commit()
        session.refresh(vp)
        assert vp.sample_audio_path is None
        assert vp.model_checkpoint_path is None
        assert vp.error_message is None

    def test_default_status_is_pending(self, session):
        """Status default harus 'pending'."""
        from backend.app.models.voice_profile_model import VoiceProfile
        user = _make_user(session)
        vp = VoiceProfile(
            id=uuid.uuid4(),
            user_id=user.id,
            name="Test",
            source_type="own_voice",
            duration_seconds=10.0,
        )
        session.add(vp)
        session.commit()
        session.refresh(vp)
        assert vp.status == "pending"

    def test_all_source_types_accepted(self, session):
        """Semua nilai source_type valid bisa disimpan."""
        for st in ("own_voice", "other_person", "character"):
            _make_voice_profile(session, source_type=st)
        session.commit()

    def test_all_status_values_accepted(self, session):
        """Semua nilai status valid bisa disimpan."""
        for s in ("pending", "processing", "ready", "failed"):
            _make_voice_profile(session, status=s)
        session.commit()

    def test_updated_at_auto_populated(self, session):
        """updated_at otomatis terisi saat record dibuat."""
        vp = _make_voice_profile(session)
        session.commit()
        session.refresh(vp)
        assert vp.updated_at is not None

    def test_training_job_relationship_starts_none(self, session):
        """Relasi training_job kosong saat baru dibuat."""
        vp = _make_voice_profile(session)
        session.commit()
        session.refresh(vp)
        assert vp.training_job is None

    def test_user_relationship_accessible(self, session):
        """VoiceProfile.user harus menunjuk ke User yang benar."""
        user = _make_user(session)
        vp = _make_voice_profile(session, user=user)
        session.commit()
        session.refresh(vp)
        assert vp.user is not None
        assert vp.user.id == user.id

    def test_user_id_index_exists(self, engine):
        """Index pada user_id harus ada di tabel voice_profiles."""
        insp = inspect(engine)
        col_sets = [set(i["column_names"]) for i in insp.get_indexes("voice_profiles")]
        assert any("user_id" in cols for cols in col_sets), \
            "Tidak ada index pada kolom user_id di voice_profiles"


# ---------------------------------------------------------------------------
# TrainingJob model
# ---------------------------------------------------------------------------

class TestTrainingJobModel:

    def test_table_name_is_training_jobs(self):
        from backend.app.models.training_job_model import TrainingJob
        assert TrainingJob.__tablename__ == "training_jobs"

    def test_can_create_and_persist(self, session):
        """TrainingJob bisa di-INSERT dan di-query kembali."""
        from backend.app.models.training_job_model import TrainingJob
        vp = _make_voice_profile(session)
        tj = TrainingJob(id=uuid.uuid4(), voice_profile_id=vp.id, status="queued")
        session.add(tj)
        session.commit()
        fetched = session.get(TrainingJob, tj.id)
        assert fetched is not None
        assert fetched.status == "queued"
        assert fetched.progress_pct == 0

    def test_id_returns_as_uuid_object(self, session):
        """UUIDType harus mengembalikan uuid.UUID, bukan string."""
        from backend.app.models.training_job_model import TrainingJob
        vp = _make_voice_profile(session)
        tj = TrainingJob(id=uuid.uuid4(), voice_profile_id=vp.id)
        session.add(tj)
        session.commit()
        session.expire(tj)
        session.refresh(tj)
        assert isinstance(tj.id, uuid.UUID)
        assert isinstance(tj.voice_profile_id, uuid.UUID)

    def test_required_fields_present(self):
        """Semua kolom wajib terdefinisi di model."""
        from backend.app.models.training_job_model import TrainingJob
        cols = {c.key for c in TrainingJob.__table__.columns}
        required = {
            "id", "voice_profile_id", "status",
            "progress_pct", "started_at", "completed_at", "error_log",
        }
        assert required.issubset(cols)

    def test_default_status_is_queued(self, session):
        """Status default TrainingJob adalah 'queued'."""
        from backend.app.models.training_job_model import TrainingJob
        vp = _make_voice_profile(session)
        tj = TrainingJob(id=uuid.uuid4(), voice_profile_id=vp.id)
        session.add(tj)
        session.commit()
        session.refresh(tj)
        assert tj.status == "queued"

    def test_default_progress_pct_is_zero(self, session):
        """progress_pct default adalah 0."""
        from backend.app.models.training_job_model import TrainingJob
        vp = _make_voice_profile(session)
        tj = TrainingJob(id=uuid.uuid4(), voice_profile_id=vp.id)
        session.add(tj)
        session.commit()
        session.refresh(tj)
        assert tj.progress_pct == 0

    def test_nullable_timestamp_fields(self, session):
        """started_at, completed_at, error_log boleh NULL."""
        from backend.app.models.training_job_model import TrainingJob
        vp = _make_voice_profile(session)
        tj = TrainingJob(id=uuid.uuid4(), voice_profile_id=vp.id)
        session.add(tj)
        session.commit()
        session.refresh(tj)
        assert tj.started_at is None
        assert tj.completed_at is None
        assert tj.error_log is None

    def test_voice_profile_id_is_unique(self, session):
        """voice_profile_id harus UNIQUE (1-to-1 dengan VoiceProfile)."""
        from backend.app.models.training_job_model import TrainingJob
        from sqlalchemy.exc import IntegrityError
        vp = _make_voice_profile(session)
        tj1 = TrainingJob(id=uuid.uuid4(), voice_profile_id=vp.id)
        session.add(tj1)
        session.commit()
        tj2 = TrainingJob(id=uuid.uuid4(), voice_profile_id=vp.id)
        session.add(tj2)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_all_status_values_accepted(self, session):
        """Semua nilai status valid bisa disimpan."""
        from backend.app.models.training_job_model import TrainingJob
        for s in ("queued", "processing", "completed", "failed"):
            vp = _make_voice_profile(session)
            tj = TrainingJob(id=uuid.uuid4(), voice_profile_id=vp.id, status=s)
            session.add(tj)
        session.commit()

    def test_back_reference_to_voice_profile(self, session):
        """TrainingJob.voice_profile harus menunjuk ke VoiceProfile yang benar."""
        from backend.app.models.training_job_model import TrainingJob
        vp = _make_voice_profile(session)
        tj = TrainingJob(id=uuid.uuid4(), voice_profile_id=vp.id)
        session.add(tj)
        session.commit()
        session.refresh(tj)
        assert tj.voice_profile is not None
        assert tj.voice_profile.id == vp.id

    def test_cascade_delete_from_voice_profile(self, session):
        """Saat VoiceProfile dihapus, TrainingJob ikut terhapus (CASCADE)."""
        from backend.app.models.training_job_model import TrainingJob
        vp = _make_voice_profile(session)
        tj = TrainingJob(id=uuid.uuid4(), voice_profile_id=vp.id)
        session.add(tj)
        session.commit()
        tj_id = tj.id
        session.delete(vp)
        session.commit()
        assert session.get(TrainingJob, tj_id) is None

    def test_voice_profile_training_job_bidirectional(self, session):
        """VoiceProfile.training_job dan TrainingJob.voice_profile saling terhubung."""
        from backend.app.models.training_job_model import TrainingJob
        vp = _make_voice_profile(session)
        tj = TrainingJob(id=uuid.uuid4(), voice_profile_id=vp.id)
        session.add(tj)
        session.commit()
        session.refresh(vp)
        assert vp.training_job is not None
        assert vp.training_job.id == tj.id
