"""create vc_sessions table

Wave 0: Database Migration
Spec: Real-time Voice Changer (WebSocket)

Schema dikunci dari:
  - spec.md: Database Schema & Migration (Table vc_sessions)
  - tasks.md: Wave 0 - Task 1.1

Revision ID: 0003
Revises: 0002 (tts_jobs)
Create Date: 2026-09-17
"""
from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: str = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vc_sessions",
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
            sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_vc_sessions_user_id"),
            nullable=False,
            comment="Pemilik sesi voice changer (FK ke users.id)",
        ),
        sa.Column(
            "voice_profile_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey(
                "voice_profiles.id",
                ondelete="CASCADE",
                name="fk_vc_sessions_voice_profile_id",
            ),
            nullable=False,
            comment="Voice profile yang digunakan (FK ke voice_profiles.id)",
        ),
        sa.Column(
            "started_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            comment="Waktu sesi dimulai",
        ),
        sa.Column(
            "ended_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
            comment="Waktu sesi berakhir (setelah grace period atau close)",
        ),
        sa.Column(
            "avg_latency_ms",
            sa.Float,
            nullable=True,
            comment="Rata-rata latensi konversi sesi dalam ms",
        ),
        sa.Column(
            "settings",
            sa.JSON,
            nullable=False,
            comment="Pengaturan sesi VC (JSON: pitch_shift, sample_rate, chunk_duration_ms)",
        ),
    )

    op.create_index(
        "idx_vc_sessions_user_started",
        "vc_sessions",
        ["user_id", "started_at"],
    )
    op.create_index(
        "idx_vc_sessions_voice_profile_id",
        "vc_sessions",
        ["voice_profile_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_vc_sessions_voice_profile_id", table_name="vc_sessions")
    op.drop_index("idx_vc_sessions_user_started", table_name="vc_sessions")
    op.drop_table("vc_sessions")
