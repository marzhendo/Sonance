"""create users table

Migration awal — harus dijalankan sebelum 0001.
Tabel users adalah prerequisite FK untuk voice_profiles.user_id.

Schema dari PRD-Sonance.md § 8. Database Schema:
  users: id, email, password_hash, created_at

Revision ID: 0000
Revises: (none — initial)
Create Date: 2026-09-13
"""
from alembic import op
import sqlalchemy as sa

revision: str = "0000"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column(
            "id",
            sa.VARCHAR(36),
            primary_key=True,
            nullable=False,
            comment="UUID primary key",
        ),
        sa.Column(
            "email",
            sa.VARCHAR(255),
            nullable=False,
            comment="Email unik pengguna",
        ),
        sa.Column(
            "password_hash",
            sa.VARCHAR(255),
            nullable=False,
            comment="Bcrypt password hash",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.create_index("idx_users_email", "users", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index("idx_users_email", table_name="users")
    op.drop_table("users")
