"""
ORM model untuk tabel training_jobs.
Wave 1: Task 1.3.

Relasi:
  - voice_profiles (1) ──< (1) training_jobs  [UNIQUE FK, CASCADE on delete]

Constraint penting:
  - voice_profile_id UNIQUE  → menegakkan relasi 1-to-1 (ADR-006)
  - ON DELETE CASCADE        → terhapus otomatis saat VoiceProfile dihapus
  - progress_pct CHECK 0-100 → invariant untuk status polling
"""
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    VARCHAR,
    CheckConstraint,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TIMESTAMP

from backend.app.core.database import Base
from backend.app.core.db_types import UUIDType

if TYPE_CHECKING:
    from backend.app.models.voice_profile_model import VoiceProfile


class TrainingJob(Base):
    """
    Merepresentasikan satu proses training async untuk sebuah VoiceProfile.

    Relasi 1-to-1 dengan VoiceProfile: satu VoiceProfile hanya boleh punya
    satu TrainingJob (ADR-006). Tidak ada retry yang membuat job baru; jika
    training gagal, user harus membuat VoiceProfile baru.

    State transitions:
        queued → processing → completed
                            → failed
    """

    __tablename__ = "training_jobs"

    __table_args__ = (
        UniqueConstraint("voice_profile_id", name="uq_training_jobs_voice_profile_id"),
        CheckConstraint(
            "status IN ('queued', 'processing', 'completed', 'failed')",
            name="ck_training_jobs_status",
        ),
        CheckConstraint(
            "progress_pct >= 0 AND progress_pct <= 100",
            name="ck_training_jobs_progress_pct",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(),
        primary_key=True,
        default=uuid.uuid4,
    )
    voice_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(),
        ForeignKey("voice_profiles.id", ondelete="CASCADE"),
        nullable=False,
        # Unique constraint ditangani lewat __table_args__ di atas
        # agar nama constraint bisa dikontrol secara eksplisit.
        index=True,
    )
    status: Mapped[str] = mapped_column(
        VARCHAR(20),
        nullable=False,
        default="queued",
        server_default="queued",
    )
    progress_pct: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    error_log: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )

    # Back-reference ke VoiceProfile
    voice_profile: Mapped["VoiceProfile"] = relationship(
        "VoiceProfile",
        back_populates="training_job",
    )

    def __repr__(self) -> str:
        return (
            f"<TrainingJob id={self.id!s:.8} "
            f"voice_profile_id={self.voice_profile_id!s:.8} "
            f"status={self.status!r} progress={self.progress_pct}%>"
        )
