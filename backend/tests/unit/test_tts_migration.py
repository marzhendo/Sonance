"""
Tests untuk Alembic migration 0002 (tabel tts_jobs).
Wave 0: Database Migration.

Memverifikasi bahwa file migration 0002:
1. Memiliki revision chain yang valid (0001 -> 0002).
2. Sukses upgrade: membuat tabel tts_jobs dengan seluruh kolom, foreign keys, check constraints, dan indexes.
3. Sukses downgrade: menghapus indexes dan tabel tts_jobs dengan bersih.
4. Menegakkan check constraint status.
"""
import importlib
import os
import tempfile
import uuid

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError


@pytest.fixture
def temp_db_url():
    """Menyediakan URL SQLite sementara untuk pengujian migrasi."""
    temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    temp_file.close()
    db_path = temp_file.name
    db_url = f"sqlite:///{db_path}"
    yield db_url
    if os.path.exists(db_path):
        os.remove(db_path)


@pytest.fixture
def alembic_cfg(temp_db_url, monkeypatch):
    """Menyediakan Alembic Config yang terhubung ke temporary database."""
    monkeypatch.setenv("SONANCE_DATABASE_URL", temp_db_url)
    cfg = Config("alembic.ini")
    return cfg


class TestTTSMigration:

    def test_migration_revision_chain(self):
        """Memverifikasi revision metadata dan rantai head migrasi."""
        mig_0002 = importlib.import_module("backend.alembic.versions.0002_create_tts_jobs")

        assert mig_0002.revision == "0002"
        assert mig_0002.down_revision == "0001"
        assert mig_0002.branch_labels is None
        assert mig_0002.depends_on is None

        cfg = Config("alembic.ini")
        script_dir = ScriptDirectory.from_config(cfg)
        assert "0002" in script_dir.get_heads()

    def test_tts_migration_upgrade_and_downgrade(self, alembic_cfg, temp_db_url):
        """Memverifikasi skema tabel tts_jobs saat upgrade dan pembersihan saat downgrade."""
        command.upgrade(alembic_cfg, "0002")

        engine = create_engine(temp_db_url)
        inspector = inspect(engine)

        tables = inspector.get_table_names()
        assert "tts_jobs" in tables
        assert "voice_profiles" in tables
        assert "users" in tables

        columns = {col["name"]: col for col in inspector.get_columns("tts_jobs")}
        expected_columns = [
            "id",
            "user_id",
            "voice_profile_id",
            "input_text",
            "status",
            "output_audio_path",
            "settings",
            "error_message",
            "gpu_wait_started_at",
            "created_at",
            "started_at",
            "completed_at",
        ]
        for col_name in expected_columns:
            assert col_name in columns, f"Kolom {col_name} harus ada di tabel tts_jobs"

        assert columns["id"]["nullable"] is False
        assert columns["user_id"]["nullable"] is False
        assert columns["voice_profile_id"]["nullable"] is False
        assert columns["input_text"]["nullable"] is False
        assert columns["status"]["nullable"] is False
        assert columns["settings"]["nullable"] is False
        assert columns["created_at"]["nullable"] is False

        assert columns["output_audio_path"]["nullable"] is True
        assert columns["error_message"]["nullable"] is True
        assert columns["gpu_wait_started_at"]["nullable"] is True
        assert columns["started_at"]["nullable"] is True
        assert columns["completed_at"]["nullable"] is True

        indexes = {idx["name"]: idx for idx in inspector.get_indexes("tts_jobs")}
        assert "idx_tts_jobs_user_created" in indexes
        assert "idx_tts_jobs_status" in indexes
        assert "idx_tts_jobs_user_status" in indexes

        foreign_keys = inspector.get_foreign_keys("tts_jobs")
        fk_by_col = {fk["constrained_columns"][0]: fk for fk in foreign_keys}
        assert "user_id" in fk_by_col
        assert "voice_profile_id" in fk_by_col
        assert fk_by_col["user_id"]["referred_table"] == "users"
        assert fk_by_col["voice_profile_id"]["referred_table"] == "voice_profiles"
        if "options" in fk_by_col["user_id"] and "ondelete" in fk_by_col["user_id"]["options"]:
            assert fk_by_col["user_id"]["options"]["ondelete"].upper() == "RESTRICT"
        if "options" in fk_by_col["voice_profile_id"] and "ondelete" in fk_by_col["voice_profile_id"]["options"]:
            assert fk_by_col["voice_profile_id"]["options"]["ondelete"].upper() == "CASCADE"

        engine.dispose()

        command.downgrade(alembic_cfg, "0001")

        engine_downgraded = create_engine(temp_db_url)
        inspector_downgraded = inspect(engine_downgraded)
        remaining_tables = inspector_downgraded.get_table_names()

        assert "tts_jobs" not in remaining_tables
        assert "voice_profiles" in remaining_tables
        assert "users" in remaining_tables

        engine_downgraded.dispose()

    def test_tts_jobs_user_id_foreign_key_restrict_behavior(self, alembic_cfg, temp_db_url):
        """Memverifikasi FK user_id pada tts_jobs menegakkan RESTRICT dan voice_profile_id CASCADE."""
        command.upgrade(alembic_cfg, "0002")

        engine = create_engine(temp_db_url)

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        with engine.begin() as conn:
            u_id = str(uuid.uuid4())
            vp_id = str(uuid.uuid4())
            job_id = str(uuid.uuid4())

            conn.execute(
                text(
                    "INSERT INTO users (id, email, password_hash) "
                    "VALUES (:id, 'fk_restrict@test.com', 'hashed')"
                ),
                {"id": u_id},
            )
            conn.execute(
                text(
                    "INSERT INTO voice_profiles (id, user_id, name, source_type, status, duration_seconds) "
                    "VALUES (:id, :uid, 'VP Restrict Test', 'own_voice', 'ready', 15.0)"
                ),
                {"id": vp_id, "uid": u_id},
            )
            conn.execute(
                text(
                    "INSERT INTO tts_jobs (id, user_id, voice_profile_id, input_text, status, settings) "
                    "VALUES (:id, :uid, :vpid, 'Testing RESTRICT', 'queued', '{}')"
                ),
                {"id": job_id, "uid": u_id, "vpid": vp_id},
            )

            # Upaya menghapus user harus gagal dengan IntegrityError karena ON DELETE RESTRICT
            with pytest.raises(IntegrityError):
                conn.execute(
                    text("DELETE FROM users WHERE id = :id"),
                    {"id": u_id},
                )

            # Menghapus voice_profile harus berhasil dan CASCADE menghapus record tts_jobs
            conn.execute(
                text("DELETE FROM voice_profiles WHERE id = :vpid"),
                {"vpid": vp_id},
            )

            # Verifikasi tts_jobs ikut terhapus akibat CASCADE dari voice_profile
            job_count = conn.execute(
                text("SELECT count(*) FROM tts_jobs WHERE id = :id"),
                {"id": job_id},
            ).scalar()
            assert job_count == 0

            # Setelah tts_jobs dan voice_profile terhapus, user bisa dihapus
            conn.execute(
                text("DELETE FROM users WHERE id = :id"),
                {"id": u_id},
            )
            user_count = conn.execute(
                text("SELECT count(*) FROM users WHERE id = :id"),
                {"id": u_id},
            ).scalar()
            assert user_count == 0

        engine.dispose()

    def test_tts_jobs_status_check_constraint(self, alembic_cfg, temp_db_url):
        """Memverifikasi check constraint status menolak nilai di luar enum."""
        command.upgrade(alembic_cfg, "0002")

        engine = create_engine(temp_db_url)
        with engine.begin() as conn:
            u_id = str(uuid.uuid4())
            vp_id = str(uuid.uuid4())
            conn.execute(
                text(
                    "INSERT INTO users (id, email, password_hash) "
                    "VALUES (:id, 'tts_test@test.com', 'hashed')"
                ),
                {"id": u_id},
            )
            conn.execute(
                text(
                    "INSERT INTO voice_profiles (id, user_id, name, source_type, status, duration_seconds) "
                    "VALUES (:id, :uid, 'VP Test', 'own_voice', 'ready', 15.0)"
                ),
                {"id": vp_id, "uid": u_id},
            )

            conn.execute(
                text(
                    "INSERT INTO tts_jobs (id, user_id, voice_profile_id, input_text, status, settings) "
                    "VALUES (:id, :uid, :vpid, 'Halo dunia', 'queued', '{}')"
                ),
                {"id": str(uuid.uuid4()), "uid": u_id, "vpid": vp_id},
            )

            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "INSERT INTO tts_jobs (id, user_id, voice_profile_id, input_text, status, settings) "
                        "VALUES (:id, :uid, :vpid, 'Halo dunia', 'invalid_status', '{}')"
                    ),
                    {"id": str(uuid.uuid4()), "uid": u_id, "vpid": vp_id},
                )

        engine.dispose()
