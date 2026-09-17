"""
Tests untuk ORM model VCSession.
Wave 1: ORM Model.

Memverifikasi bahwa model VCSession:
1. Menggunakan Mapped[] annotation style SQLAlchemy 2.x dan UUIDType.
2. Default value terpasang dengan benar (id, started_at, settings).
3. Relasi N-to-1 ke User dan VoiceProfile bekerja dua arah.
4. Relasi 1-to-N di User (RESTRICT) dan VoiceProfile (CASCADE) bekerja sesuai spesifikasi.
5. __repr__ informatif.
"""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError


class TestVCSessionModel:

    def test_create_vc_session_success(self, db_session, make_user, make_voice_profile):
        """VCSession berhasil dibuat dengan atribut valid dan UUIDType."""
        from backend.app.models.vc_session_model import VCSession

        user = make_user()
        vp = make_voice_profile(user=user, status="ready")

        session = VCSession(
            user_id=user.id,
            voice_profile_id=vp.id,
            settings={"pitch_shift": 0, "sample_rate": 16000, "chunk_duration_ms": 30},
        )
        db_session.add(session)
        db_session.flush()

        assert isinstance(session.id, uuid.UUID)
        assert session.user_id == user.id
        assert session.voice_profile_id == vp.id
        assert session.settings["sample_rate"] == 16000
        assert session.settings["chunk_duration_ms"] == 30
        assert session.ended_at is None
        assert session.avg_latency_ms is None
        assert isinstance(session.started_at, datetime)

    def test_vc_session_relationships(self, db_session, make_user, make_voice_profile):
        """Relasi VCSession ke User dan VoiceProfile dapat diakses dua arah."""
        from backend.app.models.vc_session_model import VCSession

        user = make_user()
        vp = make_voice_profile(user=user, status="ready")

        session = VCSession(
            user_id=user.id,
            voice_profile_id=vp.id,
            settings={"pitch_shift": 2},
        )
        db_session.add(session)
        db_session.flush()

        # N-to-1 dari session
        assert session.user.id == user.id
        assert session.voice_profile.id == vp.id

        # 1-to-N dari user dan voice profile
        assert session in user.vc_sessions
        assert session in vp.vc_sessions

    def test_vc_session_cascade_delete_on_voice_profile_removal(
        self, db_session, make_user, make_voice_profile
    ):
        """Menghapus VoiceProfile otomatis menghapus VCSession terkait (CASCADE)."""
        from backend.app.models.vc_session_model import VCSession
        from backend.app.models.voice_profile_model import VoiceProfile

        user = make_user()
        vp = make_voice_profile(user=user, status="ready")
        session = VCSession(
            user_id=user.id,
            voice_profile_id=vp.id,
            settings={},
        )
        db_session.add(session)
        db_session.commit()

        session_id = session.id

        # Hapus voice profile
        db_session.delete(vp)
        db_session.commit()

        # VCSession harus ikut terhapus karena cascade delete-orphan
        assert db_session.get(VCSession, session_id) is None

    def test_vc_session_restrict_on_user_removal(
        self, db_session, make_user, make_voice_profile
    ):
        """Menghapus User yang memiliki VCSession ditolak (RESTRICT)."""
        from backend.app.models.vc_session_model import VCSession

        owner = make_user()
        user = make_user()
        vp = make_voice_profile(user=owner, status="ready")
        session = VCSession(
            user_id=user.id,
            voice_profile_id=vp.id,
            settings={},
        )
        db_session.add(session)
        db_session.commit()

        # Hapus user harus raise IntegrityError karena vc_sessions milik user ini masih ada dan ondelete=RESTRICT
        db_session.delete(user)
        with pytest.raises(IntegrityError):
            db_session.commit()

        db_session.rollback()

    def test_vc_session_repr(self, make_user, make_voice_profile):
        """String representasi VCSession mencakup id, user_id, dan voice_profile_id."""
        from backend.app.models.vc_session_model import VCSession

        user = make_user()
        vp = make_voice_profile(user=user)
        session_id = uuid.uuid4()
        session = VCSession(
            id=session_id,
            user_id=user.id,
            voice_profile_id=vp.id,
            settings={},
        )
        repr_str = repr(session)
        assert str(session_id)[:8] in repr_str
        assert str(user.id)[:8] in repr_str
        assert str(vp.id)[:8] in repr_str

    def test_make_vc_session_fixture(self, make_vc_session):
        """Fixture make_vc_session berfungsi dengan baik."""
        session = make_vc_session(avg_latency_ms=75.5)
        assert session.avg_latency_ms == 75.5
        assert isinstance(session.id, uuid.UUID)
        assert session.voice_profile is not None
        assert session.user is not None
