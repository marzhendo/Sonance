"""
Pydantic schemas untuk TTS Pipeline (Offline Voice Cloning).
Wave 2: Pydantic Schemas & Settings Validation.

Prinsip field exposure:
  - output_audio_path adalah internal storage path, tidak di-expose di level schema.
  - Invariants pada status response:
    - error_message: null saat status bukan failed.
    - completed_at: null saat status bukan completed (queued, processing, failed).
"""
import uuid
from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TTSJobStatus(str, Enum):
    """Lifecycle status TTS job."""
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"


# ---------------------------------------------------------------------------
# Settings Schema
# ---------------------------------------------------------------------------

class TTSSettings(BaseModel):
    """
    Pengaturan parameter sintesis suara TTS.
    Semua field memiliki nilai default sesuai spesifikasi.
    """
    language: Literal["id", "en"] = Field(
        default="id",
        description="Bahasa sintesis suara (whitelist: 'id', 'en')",
    )
    speed: float = Field(
        default=1.0,
        ge=0.5,
        le=2.0,
        description="Kecepatan sintesis suara [0.5, 2.0]",
    )
    pitch_shift: int = Field(
        default=0,
        ge=-12,
        le=12,
        description="Pergeseran nada dalam semitone [-12, 12]",
    )
    temperature: float = Field(
        default=0.7,
        ge=0.1,
        le=1.0,
        description="Variasi ekspresi sintesis suara [0.1, 1.0]",
    )
    output_format: Literal["opus"] = Field(
        default="opus",
        description="Format audio output, dikunci ke 'opus' sesuai ADR-007",
    )


# ---------------------------------------------------------------------------
# Request Schema
# ---------------------------------------------------------------------------

class TTSGenerateRequest(BaseModel):
    """
    Payload request untuk dispatch TTS job (POST /api/v1/tts/generate).
    """
    voice_profile_id: uuid.UUID = Field(
        ...,
        description="ID voice profile berstatus ready yang akan digunakan",
    )
    text: str = Field(
        ...,
        description="Teks yang akan disintesis menjadi audio (1-1000 karakter setelah trim)",
    )
    settings: Optional[TTSSettings] = Field(
        default_factory=TTSSettings,
        description="Pengaturan TTS opsional, default ke TTSSettings standar jika tidak disertakan",
    )

    @field_validator("text", mode="before")
    @classmethod
    def trim_text(cls, v: str) -> str:
        """Trim whitespace sebelum validasi panjang teks."""
        if isinstance(v, str):
            v = v.strip()
        return v

    @field_validator("text")
    @classmethod
    def validate_text(cls, v: str) -> str:
        if not v:
            raise ValueError("text tidak boleh kosong atau hanya berisi whitespace")
        if len(v) > 1000:
            raise ValueError("text tidak boleh melebihi 1000 karakter setelah di-trim")
        return v

    @field_validator("settings", mode="before")
    @classmethod
    def default_settings_if_none(cls, v: Optional[TTSSettings]) -> TTSSettings:
        if v is None:
            return TTSSettings()
        return v

    model_config = ConfigDict(str_strip_whitespace=False)


# ---------------------------------------------------------------------------
# Response Schemas
# ---------------------------------------------------------------------------

class TTSJobResponse(BaseModel):
    """
    Response saat TTS job berhasil dibuat atau di-dispatch (HTTP 202).
    output_audio_path sengaja tidak di-expose ke client.
    """
    id: uuid.UUID
    status: TTSJobStatus
    input_text: str
    voice_profile_id: uuid.UUID
    settings: TTSSettings
    error_message: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @property
    def job_id(self) -> uuid.UUID:
        """Kompatibilitas alias untuk job_id."""
        return self.id

    @field_validator("settings", mode="before")
    @classmethod
    def parse_settings(cls, v):
        if v is None or v == {}:
            return TTSSettings()
        if isinstance(v, dict):
            return TTSSettings(**v)
        return v

    model_config = ConfigDict(from_attributes=True)


class TTSJobStatusResponse(BaseModel):
    """
    Response polling status TTS job (GET /api/v1/tts/jobs/{id}).
    Menegakkan invariant spesifikasi:
      - error_message selalu null jika status bukan failed.
      - completed_at selalu null jika status bukan completed.
    """
    id: uuid.UUID
    status: TTSJobStatus
    input_text: str
    voice_profile_id: uuid.UUID
    settings: TTSSettings
    error_message: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @field_validator("settings", mode="before")
    @classmethod
    def parse_settings(cls, v):
        if v is None or v == {}:
            return TTSSettings()
        if isinstance(v, dict):
            return TTSSettings(**v)
        return v

    @model_validator(mode="after")
    def enforce_invariants(self) -> "TTSJobStatusResponse":
        """Menegakkan invariant respons polling status."""
        if self.status != TTSJobStatus.failed:
            self.error_message = None
        if self.status != TTSJobStatus.completed:
            self.completed_at = None
        return self

    model_config = ConfigDict(from_attributes=True)
