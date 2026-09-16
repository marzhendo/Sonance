"""create tts_jobs table

Wave 0: Database Migration
Spec: TTS Pipeline (Offline Voice Cloning)

Schema dikunci dari:
  - spec.md: Database Schema & Migration (Table tts_jobs)
  - ADR-007: Opus audio container standard
  - tasks.md: Wave 0 - Task 1.1

Revision ID: 0002
Revises: 0001 (voice_profiles and training_jobs)
Create Date: 2026-09-15
"""
from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: str = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tts_jobs",
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
            sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_tts_jobs_user_id"),
            nullable=False,
            comment="Pemilik TTS job (FK ke users.id)",
        ),
        sa.Column(
            "voice_profile_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey(
                "voice_profiles.id",
                ondelete="CASCADE",
                name="fk_tts_jobs_voice_profile_id",
            ),
            nullable=False,
            comment="Voice profile yang digunakan (FK ke voice_profiles.id)",
        ),
        sa.Column(
            "input_text",
            sa.Text,
            nullable=False,
            comment="Teks input yang disintesis, 1-1000 karakter",
        ),
        sa.Column(
            "status",
            sa.VARCHAR(20),
            nullable=False,
            server_default="queued",
            comment="Lifecycle: queued -> processing -> completed | failed",
        ),
        sa.Column(
            "output_audio_path",
            sa.VARCHAR(500),
            nullable=True,
            comment="Path file audio output Opus di storage",
        ),
        sa.Column(
            "settings",
            sa.JSON,
            nullable=False,
            comment="Pengaturan TTS (JSON: language, speed, pitch_shift, temperature, output_format)",
        ),
        sa.Column(
            "error_message",
            sa.Text,
            nullable=True,
            comment="Pesan error jika status=failed",
        ),
        sa.Column(
            "gpu_wait_started_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
            comment="Waktu pertama kali job mulai menunggu GPU lock",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "started_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
            comment="Waktu worker mulai memproses job",
        ),
        sa.Column(
            "completed_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
            comment="Waktu job selesai (success atau failed)",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'completed', 'failed')",
            name="ck_tts_jobs_status",
        ),
    )

    op.create_index(
        "idx_tts_jobs_user_created",
        "tts_jobs",
        ["user_id", "created_at"],
    )
    op.create_index(
        "idx_tts_jobs_status",
        "tts_jobs",
        ["status"],
    )
    op.create_index(
        "idx_tts_jobs_user_status",
        "tts_jobs",
        ["user_id", "status"],
    )
    op.create_index(
        "idx_tts_jobs_voice_profile_id",
        "tts_jobs",
        ["voice_profile_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_tts_jobs_voice_profile_id", table_name="tts_jobs")
    op.drop_index("idx_tts_jobs_user_status", table_name="tts_jobs")
    op.drop_index("idx_tts_jobs_status", table_name="tts_jobs")
    op.drop_index("idx_tts_jobs_user_created", table_name="tts_jobs")
    op.drop_table("tts_jobs")
