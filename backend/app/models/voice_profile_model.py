"""
ORM model untuk tabel voice_profiles.
Wave 1 — Task 1.2 (updated: native UUID type, FK ke users enforced).

Relasi:
  - users (1) ──< (N) voice_profiles
  - voice_profiles (1) ──< (1) training_jobs  [cascade delete]
"""
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    VARCHAR,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TIMESTAMP

from backend.app.core.database import Base
from backend.app.core.db_types import UUIDType

if TYPE_CHECKING:
    from backend.app.models.training_job_model import TrainingJob
    from backend.app.models.user_model import User


def _utcnow() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(timezone.utc)


class VoiceProfile(Base):
    """
    Merepresentasikan satu karakter suara yang sudah atau sedang di-clone.

    Lifecycle status:
        pending → processing → ready
                             → failed

    source_type menentukan pipeline training (ADR-007):
        own_voice / other_person → RVC pipeline
        character                → SVC pipeline
    """

    __tablename__ = "voice_profiles"

    __table_args__ = (
        CheckConstraint(
            "source_type IN ('own_voice', 'other_person', 'character')",
            name="ck_voice_profiles_source_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'ready', 'failed')",
            name="ck_voice_profiles_status",
        ),
        CheckConstraint(
            "error_message IS NULL OR length(error_message) <= 500",
            name="ck_voice_profiles_error_message_length",
        ),
        Index("idx_voice_profiles_user_created", "user_id", "created_at"),
        Index("idx_voice_profiles_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(),
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_voice_profiles_user_id"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    source_type: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    status: Mapped[str] = mapped_column(
        VARCHAR(20),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    sample_audio_path: Mapped[Optional[str]] = mapped_column(VARCHAR(1024), nullable=True)
    model_checkpoint_path: Mapped[Optional[str]] = mapped_column(VARCHAR(1024), nullable=True)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=_utcnow,
        onupdate=_utcnow,
    )

    # Relasi ke User (N→1)
    user: Mapped["User"] = relationship(
        "User",
        back_populates="voice_profiles",
    )

    # Relasi 1-to-1 ke TrainingJob (cascade delete — ADR-006)
    training_job: Mapped[Optional["TrainingJob"]] = relationship(
        "TrainingJob",
        back_populates="voice_profile",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<VoiceProfile id={self.id!s:.8} name={self.name!r} "
            f"status={self.status!r}>"
        )
