"""
Custom SQLAlchemy type decorators untuk kompatibilitas cross-dialect.

UUIDType:
  - PostgreSQL (production): delegasi ke native UUID dialect type
  - SQLite (testing): simpan sebagai CHAR(36) string, kembalikan sebagai uuid.UUID
    object di level Python — representasi tetap UUID, bukan plain string.
"""
import uuid

from sqlalchemy import CHAR, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.types import TypeDecorator


class UUIDType(TypeDecorator):
    """
    Dialect-aware UUID type.

    Behaviour per dialect:
      postgresql → native UUID (as_uuid=True), disimpan sebagai uuid, bukan string
      lainnya    → CHAR(36), disimpan sebagai lowercase hex-with-dashes,
                   dikembalikan sebagai uuid.UUID object

    Penggunaan di model:
        id: Mapped[uuid.UUID] = mapped_column(UUIDType(), primary_key=True, default=uuid.uuid4)
    """

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            # Pakai native UUID PostgreSQL — lebih efisien, index lebih cepat
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        else:
            # SQLite, MySQL, dan lainnya: simpan sebagai CHAR(36)
            return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        """Python → DB: konversi uuid.UUID ke format yang tepat per dialect."""
        if value is None:
            return None
        if dialect.name == "postgresql":
            # PG_UUID dengan as_uuid=True menerima uuid.UUID langsung
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        # SQLite: simpan sebagai string lowercase dengan dashes
        return str(value) if isinstance(value, uuid.UUID) else str(uuid.UUID(str(value)))

    def process_result_value(self, value, dialect):
        """DB → Python: selalu kembalikan uuid.UUID object, bukan string."""
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))
