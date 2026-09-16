"""
ORM model untuk tabel tts_jobs.
Wave 1: ORM Model.
Spec: TTS Pipeline (Offline Voice Cloning).

Relasi:
  - users (1) < (N) tts_jobs (ON DELETE RESTRICT)
  - voice_profiles (1) < (N) tts_jobs (ON DELETE CASCADE)
"""
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    JSON,
    VARCHAR,
    CheckConstraint,
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
    from backend.app.models.user_model import User
    from backend.app.models.voice_profile_model import VoiceProfile


def _utcnow() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(timezone.utc)


class TTSJob(Base):
    """
    Merepresentasikan satu proses offline voice cloning / text-to-speech.

    Lifecycle status:
        queued -> processing -> completed
                             -> failed
    """

    __tablename__ = "tts_jobs"

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'processing', 'completed', 'failed')",
            name="ck_tts_jobs_status",
        ),
        Index("idx_tts_jobs_user_created", "user_id", "created_at"),
        Index("idx_tts_jobs_status", "status"),
        Index("idx_tts_jobs_user_status", "user_id", "status"),
        Index("idx_tts_jobs_voice_profile_id", "voice_profile_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(),
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_tts_jobs_user_id"),
        nullable=False,
    )
    voice_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(),
        ForeignKey("voice_profiles.id", ondelete="CASCADE", name="fk_tts_jobs_voice_profile_id"),
        nullable=False,
    )
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        VARCHAR(20),
        nullable=False,
        default="queued",
        server_default="queued",
    )
    output_audio_path: Mapped[Optional[str]] = mapped_column(
        VARCHAR(500),
        nullable=True,
    )
    settings: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    gpu_wait_started_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=_utcnow,
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )

    # Relasi ke User (N-to-1)
    user: Mapped["User"] = relationship(
        "User",
        back_populates="tts_jobs",
    )

    # Relasi ke VoiceProfile (N-to-1)
    voice_profile: Mapped["VoiceProfile"] = relationship(
        "VoiceProfile",
        back_populates="tts_jobs",
    )

    def __repr__(self) -> str:
        return (
            f"<TTSJob id={self.id!s:.8} "
            f"user_id={self.user_id!s:.8} "
            f"voice_profile_id={self.voice_profile_id!s:.8} "
            f"status={self.status!r}>"
        )
