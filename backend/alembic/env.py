"""
Alembic environment configuration untuk Sonance.

Import semua ORM models di bawah agar Base.metadata mengenal semua tabel
sebelum Alembic melakukan autogenerate atau migration.
"""
import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# Tambahkan root project ke sys.path agar import backend.* bisa resolve
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Import Base dan semua model agar autogenerate bekerja
from backend.app.core.database import Base  # noqa: F401
from backend.app.models.voice_profile_model import VoiceProfile  # noqa: F401
from backend.app.models.training_job_model import TrainingJob      # noqa: F401
from backend.app.models.tts_job_model import TTSJob  # noqa: F401

# Alembic Config object — akses ke nilai di alembic.ini
config = context.config

# Setup logging dari alembic.ini (skip saat running di pytest agar caplog tidak terhapus)
if config.config_file_name is not None and not os.environ.get("PYTEST_CURRENT_TEST"):
    fileConfig(config.config_file_name, disable_existing_loggers=False)


# Target metadata untuk autogenerate
target_metadata = Base.metadata


def get_database_url() -> str:
    """Ambil DATABASE_URL dari env var SONANCE_DATABASE_URL."""
    url = os.environ.get("SONANCE_DATABASE_URL")
    if not url:
        # Fallback ke nilai di alembic.ini untuk local dev
        url = config.get_main_option("sqlalchemy.url", "")
    return url


def run_migrations_offline() -> None:
    """Jalankan migration dalam 'offline' mode (tanpa koneksi aktif)."""
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Jalankan migration dalam 'online' mode (dengan koneksi aktif)."""
    db_url = get_database_url()
    configuration = dict(config.get_section(config.config_ini_section, {}))
    if db_url:
        configuration["sqlalchemy.url"] = db_url

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
