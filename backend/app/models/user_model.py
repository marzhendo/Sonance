"""
ORM model untuk tabel users.

Schema dari PRD-Sonance.md § 8. Database Schema.
Single-user v1 — auth hanya sebagai guard, bukan multi-tenant.
"""
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, List

from sqlalchemy import VARCHAR, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TIMESTAMP

from backend.app.core.database import Base
from backend.app.core.db_types import UUIDType

if TYPE_CHECKING:
    from backend.app.models.voice_profile_model import VoiceProfile


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    """Pengguna Sonance. V1: single-user, auth sebagai guard."""

    __tablename__ = "users"

    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(),
        primary_key=True,
        default=uuid.uuid4,
    )
    email: Mapped[str] = mapped_column(
        VARCHAR(255),
        nullable=False,
    )
    password_hash: Mapped[str] = mapped_column(
        VARCHAR(255),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=_utcnow,
    )

    voice_profiles: Mapped[List["VoiceProfile"]] = relationship(
        "VoiceProfile",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<User id={self.id!s:.8} email={self.email!r}>"
