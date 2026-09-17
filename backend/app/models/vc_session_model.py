"""
ORM model untuk tabel vc_sessions.
Wave 1: ORM Model.
Spec: Real-time Voice Changer (WebSocket).

Relasi:
  - users (1) < (N) vc_sessions (ON DELETE RESTRICT)
  - voice_profiles (1) < (N) vc_sessions (ON DELETE CASCADE)
"""
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    JSON,
    Float,
    ForeignKey,
    Index,
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


class VCSession(Base):
    """
    Merepresentasikan satu sesi aktif atau riwayat real-time voice changer.
    """

    __tablename__ = "vc_sessions"

    __table_args__ = (
        Index("idx_vc_sessions_user_started", "user_id", "started_at"),
        Index("idx_vc_sessions_voice_profile_id", "voice_profile_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(),
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_vc_sessions_user_id"),
        nullable=False,
    )
    voice_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(),
        ForeignKey("voice_profiles.id", ondelete="CASCADE", name="fk_vc_sessions_voice_profile_id"),
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=_utcnow,
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    avg_latency_ms: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )
    settings: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    # Relasi ke User (N-to-1)
    user: Mapped["User"] = relationship(
        "User",
        back_populates="vc_sessions",
    )

    # Relasi ke VoiceProfile (N-to-1)
    voice_profile: Mapped["VoiceProfile"] = relationship(
        "VoiceProfile",
        back_populates="vc_sessions",
    )

    def __repr__(self) -> str:
        return (
            f"<VCSession id={self.id!s:.8} "
            f"user_id={self.user_id!s:.8} "
            f"voice_profile_id={self.voice_profile_id!s:.8}>"
        )
