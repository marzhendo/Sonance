"""
Pydantic schemas untuk Voice Profile Management.
Wave 2 — Task 2.1.

Prinsip field exposure:
  - sample_audio_path dan model_checkpoint_path adalah path internal server —
    tidak di-expose ke client di response schema apapun.
  - error_message: None saat tidak ada error, string saat status=failed.
  - Semua field name di-trim (strip) sebelum disimpan.
"""
import uuid
from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SourceType(str, Enum):
    """
    Asal suara dalam voice profile.
    Nilai ini menentukan pipeline training dan inference (ADR-007):
      own_voice / other_person → RVC pipeline
      character                → SVC pipeline
    """
    own_voice = "own_voice"
    other_person = "other_person"
    character = "character"


class VoiceProfileStatus(str, Enum):
    """
    Lifecycle status voice profile.
    Transitions: pending → processing → ready | failed
    """
    pending = "pending"
    processing = "processing"
    ready = "ready"
    failed = "failed"


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class VoiceProfileCreateRequest(BaseModel):
    """
    Body untuk POST /api/v1/voice-profiles.
    File sample_audio diterima sebagai UploadFile terpisah di router (Form + File).
    """
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Nama tampilan voice profile (1–255 karakter, di-trim)",
    )
    source_type: SourceType = Field(
        ...,
        description="Asal suara: own_voice | other_person | character",
    )

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, v: str) -> str:
        """Trim whitespace sebelum validasi panjang."""
        if isinstance(v, str):
            v = v.strip()
        return v

    @field_validator("name")
    @classmethod
    def name_not_empty_after_trim(cls, v: str) -> str:
        if not v:
            raise ValueError("name tidak boleh kosong atau hanya berisi whitespace")
        return v

    model_config = {"str_strip_whitespace": False}  # trim manual di validator


class VoiceProfileRenameRequest(BaseModel):
    """
    Body untuk PATCH /api/v1/voice-profiles/{id}.
    Hanya field name yang bisa diubah lewat endpoint ini.
    """
    name: str = Field(
        ...,
        description="Nama baru (1–100 karakter non-whitespace setelah di-trim)",
    )

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, v: str) -> str:
        if isinstance(v, str):
            v = v.strip()
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v:
            raise ValueError("name tidak boleh kosong atau hanya berisi whitespace")
        if len(v) > 100:
            raise ValueError("name tidak boleh melebihi 100 karakter setelah di-trim")
        return v


# ---------------------------------------------------------------------------
# Nested response schema (dipakai di status endpoint)
# ---------------------------------------------------------------------------

class TrainingJobStatusResponse(BaseModel):
    """
    Status training job — embedded di VoiceProfileStatusResponse.
    Tidak di-expose sebagai endpoint mandiri.
    """
    status: str
    progress_pct: int = Field(ge=0, le=100)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class VoiceProfileResponse(BaseModel):
    """
    Response untuk create, get, list, rename.

    Field yang sengaja TIDAK di-expose ke client:
      - sample_audio_path  (path internal server)
      - model_checkpoint_path  (path internal server)

    Alasan: client tidak perlu tahu lokasi file di filesystem server.
    Akses ke file dilakukan lewat endpoint khusus, bukan path langsung.
    """
    id: uuid.UUID
    name: str
    source_type: SourceType
    status: VoiceProfileStatus
    duration_seconds: float
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class VoiceProfileListResponse(BaseModel):
    """Response untuk GET /api/v1/voice-profiles."""
    items: List[VoiceProfileResponse]


class VoiceProfileStatusResponse(BaseModel):
    """
    Response untuk GET /api/v1/voice-profiles/{id}/status.

    Invariant yang dijaga di layer service (sebelum schema ini dibuat):
      - processing: training_job.progress_pct ada dan 0–100
      - failed: error_message != None, training_job.completed_at = None
      - ready: training_job.completed_at != None
    """
    id: uuid.UUID
    status: VoiceProfileStatus
    error_message: Optional[str] = None
    training_job: Optional[TrainingJobStatusResponse] = None

    model_config = {"from_attributes": True}
