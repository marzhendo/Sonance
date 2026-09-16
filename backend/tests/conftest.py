"""
Shared test fixtures untuk seluruh test suite Sonance backend.
Wave 3 — Task 15.1 (updated: proper test isolation via nested transaction).

Isolation strategy — Nested Transaction + SAVEPOINT pattern (SQLAlchemy 2.x):

  Cara kerja:
  1. db_engine (scope=session): satu engine SQLite in-memory, schema dibuat sekali.
  2. Per test: buka dedicated connection, mulai OUTER TRANSACTION (tidak pernah commit).
  3. Buat Session dengan expire_on_commit=False dan join=True ke connection itu.
  4. begin_nested() → SAVEPOINT. Session sekarang ada di dalam savepoint.
  5. Di akhir test: outer transaction di-rollback → semua data hilang.

  Kenapa expire_on_commit=False:
    Dengan nested transaction, session.commit() akan commit ke savepoint (level DB),
    lalu SQLAlchemy expire semua object. Karena object di-expire sebelum kita sempat
    rollback outer trans, re-load mereka akan fail. expire_on_commit=False mencegah ini.

  Kenapa re-begin_nested setelah setiap commit:
    Setelah commit ke savepoint, savepoint tersebut "consumed". Kita perlu buka
    savepoint baru agar test berikutnya dalam test yang sama bisa commit lagi.
    SQLAlchemy event 'after_transaction_end' dipakai untuk ini secara otomatis.

  Referensi pattern: SQLAlchemy docs "Joining a Session into an External Transaction"
  https://docs.sqlalchemy.org/en/20/orm/session_transaction.html#joining-a-session-into-an-external-transaction-such-as-for-test-suites
"""
import uuid
from typing import Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.database import Base


# ===========================================================================
# Constants
# ===========================================================================

TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000002"
TEST_TOKEN = "test-sonance-token"


# ===========================================================================
# Database Engine — satu engine per test session (SQLite in-memory)
# ===========================================================================

@pytest.fixture(scope="session")
def db_engine():
    """
    SQLite in-memory engine, scope=session.
    Schema dibuat sekali untuk semua tests; FK enforcement diaktifkan.
    """
    from backend.app.models.user_model import User                    # noqa: F401
    from backend.app.models.voice_profile_model import VoiceProfile   # noqa: F401
    from backend.app.models.training_job_model import TrainingJob     # noqa: F401
    from backend.app.models.tts_job_model import TTSJob               # noqa: F401

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
        # Non-legacy transaction mode so SQLite SAVEPOINTs participate in outer transaction.
        dbapi_conn.isolation_level = None

    @event.listens_for(engine, "begin")
    def do_begin(conn):
        conn.exec_driver_sql("BEGIN")

    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


# ===========================================================================
# Database Session — true isolation via nested transaction
# ===========================================================================

@pytest.fixture
def db_session(db_engine) -> Generator[Session, None, None]:
    """
    Session per-test dengan true isolation via nested transaction / SAVEPOINT.

    Mekanisme:
    - Connection dibuka dari db_engine (scope=session).
    - Outer transaction dibuka di connection level: outer_trans = connection.begin().
      Outer transaction ini tidak pernah di-commit selama test.
    - Session di-bind ke connection dengan join_transaction_mode="create_savepoint"
      dan expire_on_commit=False.
      Mode ini membuat Session selalu menggunakan connection.begin_nested() (SAVEPOINT)
      untuk setiap siklus transaksi Session, sehingga session.commit() hanya me-release
      SAVEPOINT tanpa menyentuh outer transaction.
    - Di akhir test:
      session.close() menutup Session, lalu outer_trans.rollback() membatalkan semua
      perubahan yang terjadi di dalam test (termasuk yang di-commit ke savepoint).
    """
    connection = db_engine.connect()
    outer_trans = connection.begin()

    session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )

    try:
        yield session
    finally:
        session.close()
        if outer_trans.is_active:
            outer_trans.rollback()
        connection.close()


# ===========================================================================
# Factory Fixtures
# ===========================================================================

@pytest.fixture
def make_user(db_session):
    """
    Factory fixture — buat dan persist User dummy.

    Penggunaan:
        user = make_user()
        user = make_user(email="x@y.com")
    """
    from backend.app.models.user_model import User

    def _factory(**kwargs) -> User:
        data = {
            "id": uuid.uuid4(),
            "email": f"u_{uuid.uuid4().hex[:8]}@test.com",
            "password_hash": "hashed_password",
        }
        data.update(kwargs)
        user = User(**data)
        db_session.add(user)
        db_session.flush()
        return user

    return _factory


@pytest.fixture
def make_voice_profile(db_session, make_user):
    """
    Factory fixture — buat dan persist VoiceProfile dummy.
    FK ke users selalu valid; user dibuat otomatis jika tidak diberikan.

    Penggunaan:
        vp = make_voice_profile()
        vp = make_voice_profile(user=existing_user, status="ready")
    """
    from backend.app.models.voice_profile_model import VoiceProfile

    def _factory(user=None, **kwargs) -> VoiceProfile:
        if user is None:
            user = make_user()
        data = {
            "id": uuid.uuid4(),
            "user_id": user.id,
            "name": "Suara Test",
            "source_type": "own_voice",
            "status": "pending",
            "duration_seconds": 15.0,
        }
        data.update(kwargs)
        vp = VoiceProfile(**data)
        db_session.add(vp)
        db_session.flush()
        return vp

    return _factory


@pytest.fixture
def make_training_job(db_session, make_voice_profile):
    """
    Factory fixture — buat dan persist TrainingJob dummy.

    Penggunaan:
        tj = make_training_job()
        tj = make_training_job(voice_profile=vp, status="processing", progress_pct=50)
    """
    from backend.app.models.training_job_model import TrainingJob

    def _factory(voice_profile=None, **kwargs) -> TrainingJob:
        if voice_profile is None:
            voice_profile = make_voice_profile()
        data = {
            "id": uuid.uuid4(),
            "voice_profile_id": voice_profile.id,
            "status": "queued",
            "progress_pct": 0,
        }
        data.update(kwargs)
        tj = TrainingJob(**data)
        db_session.add(tj)
        db_session.flush()
        return tj

    return _factory


@pytest.fixture
def make_tts_job(db_session, make_voice_profile):
    """
    Factory fixture - buat dan persist TTSJob dummy.

    Penggunaan:
        job = make_tts_job()
        job = make_tts_job(voice_profile=vp, status="processing")
    """
    from backend.app.models.tts_job_model import TTSJob

    def _factory(user=None, voice_profile=None, **kwargs) -> TTSJob:
        if voice_profile is None:
            voice_profile = make_voice_profile(user=user, status="ready")
        actual_user_id = user.id if user is not None else voice_profile.user_id
        data = {
            "id": uuid.uuid4(),
            "user_id": actual_user_id,
            "voice_profile_id": voice_profile.id,
            "input_text": "Contoh input teks untuk sintesis suara TTS.",
            "status": "queued",
            "settings": {"language": "id", "speed": 1.0, "pitch_shift": 0, "temperature": 0.7, "output_format": "opus"},
        }
        data.update(kwargs)
        job = TTSJob(**data)
        db_session.add(job)
        db_session.flush()
        return job

    return _factory


# ===========================================================================
# FastAPI App
# ===========================================================================

def _build_app() -> FastAPI:
    from backend.app.main import create_app
    return create_app()


@pytest.fixture
def app(db_engine) -> FastAPI:
    """FastAPI app dengan auth override: verify_token → TEST_USER_ID."""
    from backend.app.core.auth import verify_token
    _app = _build_app()
    _app.dependency_overrides[verify_token] = lambda: TEST_USER_ID
    return _app


@pytest.fixture
def client(app, db_session, test_user) -> Generator[TestClient, None, None]:
    """TestClient siap pakai (TEST_USER_ID) dengan db_session terisolasi."""
    from backend.app.core.database import get_db
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def other_user_client(db_session, other_user) -> Generator[TestClient, None, None]:
    """TestClient dengan OTHER_USER_ID untuk test isolasi kepemilikan."""
    from backend.app.core.auth import verify_token
    from backend.app.core.database import get_db
    other_app = _build_app()
    other_app.dependency_overrides[verify_token] = lambda: OTHER_USER_ID
    other_app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(other_app, raise_server_exceptions=False)


@pytest.fixture
def unauth_client(db_session) -> Generator[TestClient, None, None]:
    """TestClient tanpa auth override untuk menguji real auth guard dan HTTP 401."""
    from backend.app.core.database import get_db
    unauth_app = _build_app()
    unauth_app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(unauth_app, raise_server_exceptions=False)


# ===========================================================================
# Convenience Fixtures
# ===========================================================================

@pytest.fixture
def test_user(make_user):
    """User dengan fixed UUID sebagai owner resource default."""
    return make_user(id=uuid.UUID(TEST_USER_ID))


@pytest.fixture
def other_user(make_user):
    """User dengan fixed UUID sebagai secondary user."""
    return make_user(id=uuid.UUID(OTHER_USER_ID))


@pytest.fixture
def pending_voice_profile(make_voice_profile, test_user):
    """VoiceProfile status=pending milik test_user."""
    return make_voice_profile(user=test_user, status="pending", name="VP Pending")


@pytest.fixture
def ready_voice_profile(make_voice_profile, test_user):
    """VoiceProfile status=ready milik test_user."""
    return make_voice_profile(
        user=test_user,
        status="ready",
        name="VP Ready",
        model_checkpoint_path="/checkpoints/test.pth",
    )


@pytest.fixture
def sample_opus_factory():
    """Factory fixture yang menghasilkan bytes Ogg Opus valid dengan durasi yang bisa ditentukan."""
    import struct

    def _factory(duration_seconds: float = 15.0) -> bytes:
        opus_head = b"OpusHead" + struct.pack("<BBHIhB", 1, 1, 0, 48000, 0, 0)
        page1 = bytearray(
            b"OggS" + struct.pack("<BBqIIIB", 0, 2, 0, 12345, 0, 0, 1) + bytes([len(opus_head)]) + opus_head
        )
        opus_tags = b"OpusTags" + struct.pack("<I", 7) + b"Sonance" + struct.pack("<I", 0)
        page2 = bytearray(
            b"OggS" + struct.pack("<BBqIIIB", 0, 0, 0, 12345, 1, 0, 1) + bytes([len(opus_tags)]) + opus_tags
        )
        granule = int(duration_seconds * 48000)
        payload = b"\xf8\xff\xfe"
        page3 = bytearray(
            b"OggS" + struct.pack("<BBqIIIB", 0, 4, granule, 12345, 2, 0, 1) + bytes([len(payload)]) + payload
        )
        return bytes(page1 + page2 + page3)

    return _factory


@pytest.fixture
def mock_storage(tmp_path, monkeypatch):
    """Menyiapkan direktori penyimpanan sample audio dan checkpoint di folder sementara."""
    sample_dir = tmp_path / "samples"
    checkpoint_dir = tmp_path / "checkpoints"
    sample_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SONANCE_SAMPLE_AUDIO_DIR", str(sample_dir))
    monkeypatch.setenv("SONANCE_CHECKPOINT_DIR", str(checkpoint_dir))
    return {"sample_dir": sample_dir, "checkpoint_dir": checkpoint_dir}


@pytest.fixture
def mock_queue():
    """Mock queue untuk menangkap task yang di-enqueue tanpa menjalankannya."""
    class MockQueue:
        def __init__(self):
            self.enqueued_jobs = []

        def enqueue(self, task_name, *args, **kwargs):
            self.enqueued_jobs.append({"task_name": task_name, "args": args, "kwargs": kwargs})
            return f"mock-job-{len(self.enqueued_jobs)}"

    return MockQueue()

