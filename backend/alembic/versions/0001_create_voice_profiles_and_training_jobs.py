"""create voice_profiles and training_jobs tables

Wave 0 — Task 1.1
Spec: Voice Profile Management

Schema dikunci dari:
  - PRD-Sonance.md § 8. Database Schema
  - CONTEXT.md § 2. Entity Reference
  - design.md § Data Models > Database Schema SQL

Revision ID: 0001
Revises: 0000 (users table)
Create Date: 2026-09-13
"""
from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: str = "0000"  # users harus ada dulu sebelum migration ini
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Tabel: voice_profiles
    # ------------------------------------------------------------------
    op.create_table(
        "voice_profiles",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            primary_key=True,
            nullable=False,
            comment="UUID primary key",
        ),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_voice_profiles_user_id"),
            nullable=False,
            comment="Pemilik voice profile (FK ke users.id)",
        ),
        sa.Column(
            "name",
            sa.VARCHAR(255),
            nullable=False,
            comment="Nama tampilan voice profile, maks 255 karakter",
        ),
        sa.Column(
            "source_type",
            sa.VARCHAR(20),
            nullable=False,
            comment="Asal suara: own_voice | other_person | character",
        ),
        sa.Column(
            "status",
            sa.VARCHAR(20),
            nullable=False,
            server_default="pending",
            comment="Lifecycle: pending → processing → ready | failed",
        ),
        sa.Column(
            "sample_audio_path",
            sa.VARCHAR(1024),
            nullable=True,
            comment="Path ke file Opus sample audio di SONANCE_SAMPLE_AUDIO_DIR",
        ),
        sa.Column(
            "model_checkpoint_path",
            sa.VARCHAR(1024),
            nullable=True,
            comment="Path ke file .pth checkpoint di SONANCE_CHECKPOINT_DIR",
        ),
        sa.Column(
            "duration_seconds",
            sa.Float,
            nullable=False,
            comment="Durasi sample audio dalam detik (10–30 detik)",
        ),
        sa.Column(
            "error_message",
            sa.Text,
            nullable=True,
            comment="Ringkasan error jika status=failed, maks 500 karakter",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "source_type IN ('own_voice', 'other_person', 'character')",
            name="ck_voice_profiles_source_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'ready', 'failed')",
            name="ck_voice_profiles_status",
        ),
        sa.CheckConstraint(
            "error_message IS NULL OR length(error_message) <= 500",
            name="ck_voice_profiles_error_message_length",
        ),
    )

    op.create_index("idx_voice_profiles_user_id", "voice_profiles", ["user_id"])
    op.create_index(
        "idx_voice_profiles_user_created",
        "voice_profiles",
        ["user_id", "created_at"],
    )

    # ------------------------------------------------------------------
    # Tabel: training_jobs
    # ------------------------------------------------------------------
    op.create_table(
        "training_jobs",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            primary_key=True,
            nullable=False,
            comment="UUID primary key",
        ),
        sa.Column(
            "voice_profile_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey(
                "voice_profiles.id",
                ondelete="CASCADE",
                name="fk_training_jobs_voice_profile_id",
            ),
            nullable=False,
            comment="FK ke voice_profiles.id, UNIQUE untuk relasi 1-to-1 (ADR-006)",
        ),
        sa.Column(
            "status",
            sa.VARCHAR(20),
            nullable=False,
            server_default="queued",
            comment="State: queued → processing → completed | failed",
        ),
        sa.Column(
            "progress_pct",
            sa.Integer,
            nullable=False,
            server_default="0",
            comment="Progress training 0–100%",
        ),
        sa.Column(
            "started_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
            comment="Timestamp saat worker mulai memproses job",
        ),
        sa.Column(
            "completed_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
            comment="Timestamp saat job selesai (success atau failed)",
        ),
        sa.Column(
            "error_log",
            sa.Text,
            nullable=True,
            comment="Stack trace lengkap jika training gagal",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'completed', 'failed')",
            name="ck_training_jobs_status",
        ),
        sa.CheckConstraint(
            "progress_pct >= 0 AND progress_pct <= 100",
            name="ck_training_jobs_progress_pct",
        ),
        sa.UniqueConstraint(
            "voice_profile_id",
            name="uq_training_jobs_voice_profile_id",
        ),
    )

    op.create_index(
        "idx_training_jobs_voice_profile_id",
        "training_jobs",
        ["voice_profile_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_training_jobs_voice_profile_id", table_name="training_jobs")
    op.drop_table("training_jobs")

    op.drop_index("idx_voice_profiles_user_created", table_name="voice_profiles")
    op.drop_index("idx_voice_profiles_user_id", table_name="voice_profiles")
    op.drop_table("voice_profiles")
