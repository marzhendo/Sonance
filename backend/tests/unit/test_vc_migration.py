"""
Tests untuk Alembic migration 0003 (tabel vc_sessions).
Wave 0: Database Migration.

Memverifikasi bahwa file migration 0003:
1. Memiliki revision metadata dan rantai yang valid (0002 -> 0003).
2. Sukses upgrade: membuat tabel vc_sessions dengan seluruh kolom, foreign keys, dan indexes.
3. Sukses downgrade: menghapus indexes dan tabel vc_sessions dengan bersih.
4. Menegakkan perilaku foreign key: ON DELETE RESTRICT untuk user_id dan ON DELETE CASCADE untuk voice_profile_id.
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


class TestVCSessionMigration:

    def test_migration_revision_chain(self):
        """Memverifikasi revision metadata dan rantai head migrasi 0003."""
        mig_0003 = importlib.import_module("backend.alembic.versions.0003_create_vc_sessions")

        assert mig_0003.revision == "0003"
        assert mig_0003.down_revision == "0002"
        assert mig_0003.branch_labels is None
        assert mig_0003.depends_on is None

        cfg = Config("alembic.ini")
        script_dir = ScriptDirectory.from_config(cfg)
        assert "0003" in script_dir.get_heads()

    def test_vc_sessions_migration_upgrade_and_downgrade(self, alembic_cfg, temp_db_url):
        """Memverifikasi skema tabel vc_sessions saat upgrade dan pembersihan saat downgrade."""
        command.upgrade(alembic_cfg, "0003")

        engine = create_engine(temp_db_url)
        inspector = inspect(engine)

        tables = inspector.get_table_names()
        assert "vc_sessions" in tables
        assert "tts_jobs" in tables
        assert "voice_profiles" in tables
        assert "users" in tables

        columns = {col["name"]: col for col in inspector.get_columns("vc_sessions")}
        expected_columns = [
            "id",
            "user_id",
            "voice_profile_id",
            "started_at",
            "ended_at",
            "avg_latency_ms",
            "settings",
        ]
        for col_name in expected_columns:
            assert col_name in columns, f"Kolom {col_name} harus ada di tabel vc_sessions"

        assert columns["id"]["nullable"] is False
        assert columns["user_id"]["nullable"] is False
        assert columns["voice_profile_id"]["nullable"] is False
        assert columns["started_at"]["nullable"] is False
        assert columns["settings"]["nullable"] is False

        assert columns["ended_at"]["nullable"] is True
        assert columns["avg_latency_ms"]["nullable"] is True

        indexes = {idx["name"]: idx for idx in inspector.get_indexes("vc_sessions")}
        assert "idx_vc_sessions_user_started" in indexes
        assert "idx_vc_sessions_voice_profile_id" in indexes

        foreign_keys = inspector.get_foreign_keys("vc_sessions")
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

        # Downgrade ke 0002 harus menghapus tabel vc_sessions
        command.downgrade(alembic_cfg, "0002")

        engine_downgraded = create_engine(temp_db_url)
        inspector_downgraded = inspect(engine_downgraded)
        remaining_tables = inspector_downgraded.get_table_names()

        assert "vc_sessions" not in remaining_tables
        assert "tts_jobs" in remaining_tables
        assert "voice_profiles" in remaining_tables
        assert "users" in remaining_tables

        engine_downgraded.dispose()

    def test_vc_sessions_foreign_key_behavior(self, alembic_cfg, temp_db_url):
        """Memverifikasi FK user_id RESTRICT dan voice_profile_id CASCADE."""
        command.upgrade(alembic_cfg, "0003")

        engine = create_engine(temp_db_url)

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        with engine.begin() as conn:
            u_id = str(uuid.uuid4())
            vp_id = str(uuid.uuid4())
            session_id = str(uuid.uuid4())

            conn.execute(
                text(
                    "INSERT INTO users (id, email, password_hash) "
                    "VALUES (:id, 'vc_fk_test@test.com', 'hashed')"
                ),
                {"id": u_id},
            )
            conn.execute(
                text(
                    "INSERT INTO voice_profiles (id, user_id, name, source_type, status, duration_seconds) "
                    "VALUES (:id, :uid, 'VP VC Test', 'own_voice', 'ready', 15.0)"
                ),
                {"id": vp_id, "uid": u_id},
            )
            conn.execute(
                text(
                    "INSERT INTO vc_sessions (id, user_id, voice_profile_id, settings) "
                    "VALUES (:id, :uid, :vpid, '{\"pitch_shift\": 0}')"
                ),
                {"id": session_id, "uid": u_id, "vpid": vp_id},
            )

            # Upaya menghapus user harus gagal dengan IntegrityError karena ON DELETE RESTRICT
            with pytest.raises(IntegrityError):
                conn.execute(
                    text("DELETE FROM users WHERE id = :id"),
                    {"id": u_id},
                )

            # Menghapus voice_profile harus berhasil dan CASCADE menghapus record vc_sessions
            conn.execute(
                text("DELETE FROM voice_profiles WHERE id = :vpid"),
                {"vpid": vp_id},
            )

            # Verifikasi vc_sessions ikut terhapus akibat CASCADE dari voice_profile
            session_count = conn.execute(
                text("SELECT count(*) FROM vc_sessions WHERE id = :id"),
                {"id": session_id},
            ).scalar()
            assert session_count == 0

            # Setelah vc_sessions terhapus via cascade, user bisa dihapus dengan aman
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
