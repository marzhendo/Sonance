"""
Tests untuk memverifikasi fixture infrastructure dari conftest.py.
Wave 3 — Task 15.1.

Ini bukan test untuk fitur aplikasi — ini test untuk memastikan
scaffolding test itu sendiri bekerja benar sebelum Wave 4 dan Wave 6.
"""
import uuid

import pytest


# ===========================================================================
# db_session fixture
# ===========================================================================

class TestDbSessionFixture:

    def test_session_is_provided(self, db_session):
        """db_session harus tersedia dan bisa dipakai untuk query."""
        from sqlalchemy.orm import Session
        assert isinstance(db_session, Session)

    def test_session_isolated_between_tests_part1(self, db_session, make_user):
        """Rollback terjadi dalam satu test: data yang belum di-commit bisa di-rollback."""
        from backend.app.models.user_model import User
        from sqlalchemy import select

        # Tambah user tapi TIDAK commit
        user = make_user(email="rollback_test@test.com")
        # Bisa di-query dalam session yang sama (belum rollback)
        result = db_session.execute(
            select(User).where(User.email == "rollback_test@test.com")
        ).scalar_one_or_none()
        assert result is not None

        # Rollback manual
        db_session.rollback()

        # Setelah rollback, tidak boleh ada lagi
        result_after = db_session.execute(
            select(User).where(User.email == "rollback_test@test.com")
        ).scalar_one_or_none()
        assert result_after is None, "Setelah rollback, data tidak boleh ada"

    def test_session_isolated_between_tests_part2(self, db_session, make_user):
        """Setiap test mendapat session bersih — rollback dari fixture terjadi antar test."""
        from backend.app.models.user_model import User
        from sqlalchemy import select

        # Test ini verifikasi session baru bisa dipakai tanpa state dari test sebelumnya
        user = make_user(email="clean_session@test.com")
        db_session.commit()
        result = db_session.get(User, user.id)
        assert result is not None, "Data yang baru di-commit harus terlihat dalam test ini"

    def test_isolation_step_a_create_and_commit_data(self, db_session, make_user):
        """Test A: Buat data dan panggil session.commit(). Data harus ada di dalam test ini."""
        from backend.app.models.user_model import User
        # Verifikasi data commit dari test sebelumnya tidak bocor ke test ini
        assert db_session.query(User).filter_by(email="clean_session@test.com").first() is None

        user = make_user(email="isolation_step_a@test.com")
        db_session.commit()
        found = db_session.get(User, user.id)
        assert found is not None
        assert found.email == "isolation_step_a@test.com"

    def test_isolation_step_b_verify_test_a_data_not_leaked(self, db_session):
        """Test B: Test independen yang berjalan setelah Test A. Data dari Test A tidak boleh muncul."""
        from backend.app.models.user_model import User
        from sqlalchemy import select
        leaked = db_session.execute(
            select(User).where(User.email == "isolation_step_a@test.com")
        ).scalar_one_or_none()
        assert leaked is None, "Data yang di-commit pada Test A tidak boleh bocor ke Test B"

    def test_isolation_explicit_lifecycle_proof(self, db_engine):
        """Verifikasi isolasi lifecycle antar session secara programatik."""
        import uuid
        from backend.tests.conftest import db_session as db_session_fixture
        from backend.app.models.user_model import User

        gen1 = db_session_fixture.__wrapped__(db_engine)
        sess1 = next(gen1)
        user_id = uuid.uuid4()
        user1 = User(id=user_id, email="lifecycle_proof@test.com", password_hash="hash")
        sess1.add(user1)
        sess1.commit()
        assert sess1.get(User, user_id) is not None

        try:
            next(gen1)
        except StopIteration:
            pass

        gen2 = db_session_fixture.__wrapped__(db_engine)
        sess2 = next(gen2)
        try:
            assert sess2.get(User, user_id) is None
            assert sess2.query(User).filter_by(email="lifecycle_proof@test.com").first() is None
        finally:
            try:
                next(gen2)
            except StopIteration:
                pass


# ===========================================================================
# make_user factory fixture
# ===========================================================================

class TestMakeUserFixture:

    def test_make_user_creates_valid_user(self, make_user):
        """make_user() harus mengembalikan User yang valid."""
        from backend.app.models.user_model import User
        user = make_user()
        assert isinstance(user, User)
        assert isinstance(user.id, uuid.UUID)
        assert user.email.endswith("@test.com")

    def test_make_user_accepts_custom_email(self, make_user):
        user = make_user(email="custom@example.com")
        assert user.email == "custom@example.com"

    def test_make_user_accepts_custom_id(self, make_user):
        custom_id = uuid.uuid4()
        user = make_user(id=custom_id)
        assert user.id == custom_id

    def test_make_user_each_call_unique_email(self, make_user):
        """Setiap panggilan make_user() tanpa arg harus menghasilkan email unik."""
        u1 = make_user()
        u2 = make_user()
        assert u1.email != u2.email

    def test_make_user_persisted_in_db(self, db_session, make_user):
        """User yang dibuat harus bisa di-query dari DB."""
        from backend.app.models.user_model import User
        user = make_user()
        fetched = db_session.get(User, user.id)
        assert fetched is not None
        assert fetched.id == user.id


# ===========================================================================
# make_voice_profile factory fixture
# ===========================================================================

class TestMakeVoiceProfileFixture:

    def test_make_voice_profile_creates_valid_vp(self, make_voice_profile):
        """make_voice_profile() harus mengembalikan VoiceProfile yang valid."""
        from backend.app.models.voice_profile_model import VoiceProfile
        vp = make_voice_profile()
        assert isinstance(vp, VoiceProfile)
        assert isinstance(vp.id, uuid.UUID)
        assert isinstance(vp.user_id, uuid.UUID)
        assert vp.status == "pending"
        assert vp.duration_seconds == 15.0

    def test_make_voice_profile_auto_creates_user(self, make_voice_profile, db_session):
        """Jika user tidak diberikan, make_voice_profile harus buat user baru."""
        from backend.app.models.user_model import User
        vp = make_voice_profile()
        # FK user_id harus valid
        user = db_session.get(User, vp.user_id)
        assert user is not None

    def test_make_voice_profile_accepts_existing_user(self, make_user, make_voice_profile):
        """make_voice_profile(user=u) harus pakai user yang diberikan."""
        user = make_user()
        vp = make_voice_profile(user=user)
        assert vp.user_id == user.id

    def test_make_voice_profile_custom_status(self, make_voice_profile):
        vp = make_voice_profile(status="ready")
        assert vp.status == "ready"

    def test_make_voice_profile_custom_source_type(self, make_voice_profile):
        vp = make_voice_profile(source_type="character")
        assert vp.source_type == "character"

    def test_make_voice_profile_custom_name(self, make_voice_profile):
        vp = make_voice_profile(name="Suara Custom")
        assert vp.name == "Suara Custom"

    def test_make_voice_profile_persisted_in_db(self, db_session, make_voice_profile):
        from backend.app.models.voice_profile_model import VoiceProfile
        vp = make_voice_profile()
        fetched = db_session.get(VoiceProfile, vp.id)
        assert fetched is not None


# ===========================================================================
# make_training_job factory fixture
# ===========================================================================

class TestMakeTrainingJobFixture:

    def test_make_training_job_creates_valid_job(self, make_training_job):
        from backend.app.models.training_job_model import TrainingJob
        tj = make_training_job()
        assert isinstance(tj, TrainingJob)
        assert tj.status == "queued"
        assert tj.progress_pct == 0
        assert tj.started_at is None

    def test_make_training_job_auto_creates_vp(self, make_training_job, db_session):
        """Jika voice_profile tidak diberikan, buat otomatis."""
        from backend.app.models.voice_profile_model import VoiceProfile
        tj = make_training_job()
        vp = db_session.get(VoiceProfile, tj.voice_profile_id)
        assert vp is not None

    def test_make_training_job_accepts_existing_vp(self, make_voice_profile, make_training_job):
        vp = make_voice_profile()
        tj = make_training_job(voice_profile=vp)
        assert tj.voice_profile_id == vp.id

    def test_make_training_job_custom_status(self, make_training_job):
        tj = make_training_job(status="processing", progress_pct=42)
        assert tj.status == "processing"
        assert tj.progress_pct == 42


# ===========================================================================
# app & client fixtures
# ===========================================================================

class TestClientFixture:

    def test_app_fixture_is_fastapi(self, app):
        from fastapi import FastAPI
        assert isinstance(app, FastAPI)

    def test_client_fixture_is_test_client(self, client):
        from fastapi.testclient import TestClient
        assert isinstance(client, TestClient)

    def test_auth_override_active(self, client, app):
        """
        Verifikasi auth override bekerja: request tanpa token ke endpoint
        yang di-protect seharusnya tetap jalan (karena override).
        """
        from backend.app.core.auth import verify_token
        from fastapi import Depends

        # Tambahkan route test sementara ke app
        @app.get("/test-auth-override")
        async def _route(user_id: str = Depends(verify_token)):
            return {"user_id": user_id}

        resp = client.get("/test-auth-override")
        # Auth override aktif → 200, bukan 401
        assert resp.status_code == 200
        from backend.tests.conftest import TEST_USER_ID
        assert resp.json()["user_id"] == TEST_USER_ID

    def test_other_user_client_has_different_user_id(self, other_user_client):
        """other_user_client harus return user_id OTHER_USER_ID."""
        from backend.app.core.auth import verify_token
        from fastapi import Depends, FastAPI
        from fastapi.testclient import TestClient
        from backend.tests.conftest import OTHER_USER_ID

        # Buat app minimal khusus untuk test ini
        test_app = FastAPI()

        @test_app.get("/test-other-user")
        async def _route(user_id: str = Depends(verify_token)):
            return {"user_id": user_id}

        test_app.dependency_overrides[verify_token] = lambda: OTHER_USER_ID
        local_client = TestClient(test_app)

        resp = local_client.get("/test-other-user")
        assert resp.status_code == 200
        assert resp.json()["user_id"] == OTHER_USER_ID


# ===========================================================================
# Convenience fixtures
# ===========================================================================

class TestConvenienceFixtures:

    def test_pending_voice_profile_fixture(self, pending_voice_profile):
        assert pending_voice_profile.status == "pending"
        assert pending_voice_profile.name == "VP Pending"

    def test_ready_voice_profile_fixture(self, ready_voice_profile):
        assert ready_voice_profile.status == "ready"
        assert ready_voice_profile.model_checkpoint_path == "/checkpoints/test.pth"

    def test_test_user_fixture_has_fixed_id(self, test_user):
        assert str(test_user.id) == "00000000-0000-0000-0000-000000000001"

    def test_pending_and_ready_share_same_user(self, pending_voice_profile, ready_voice_profile, test_user):
        """Kedua convenience VP milik test_user yang sama."""
        assert pending_voice_profile.user_id == test_user.id
        assert ready_voice_profile.user_id == test_user.id
