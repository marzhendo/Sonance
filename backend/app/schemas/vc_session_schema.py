"""
Pydantic schemas dan helper validasi audio untuk Real-time Voice Changer (WebSocket).
Wave 2: Pydantic Schemas & Protokol Pesan WebSocket.
"""
import uuid
from datetime import datetime
from enum import Enum
from typing import Annotated, Literal, Optional, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class VCErrorCode(str, Enum):
    """Kode error standar untuk pesan WebSocket server."""
    AUTH_FAILED = "AUTH_FAILED"
    PROFILE_NOT_FOUND = "PROFILE_NOT_FOUND"
    PROFILE_NOT_READY = "PROFILE_NOT_READY"
    GPU_BUSY = "GPU_BUSY"
    INVALID_STATE = "INVALID_STATE"
    INVALID_PAYLOAD = "INVALID_PAYLOAD"
    MODEL_LOAD_FAILED = "MODEL_LOAD_FAILED"
    INFERENCE_FAILED = "INFERENCE_FAILED"
    SESSION_EXPIRED = "SESSION_EXPIRED"


# ---------------------------------------------------------------------------
# Settings Schemas
# ---------------------------------------------------------------------------

class VCSettings(BaseModel):
    """
    Pengaturan parameter konversi suara real-time.
    Semua field memiliki default value sesuai spesifikasi.
    """
    pitch_shift: int = Field(
        default=0,
        ge=-12,
        le=12,
        description="Pergeseran nada dalam semitone [-12, 12]",
    )
    sample_rate: int = Field(
        default=16000,
        description="Frekuensi sampling audio dalam Hz (16000, 24000, 44100, 48000)",
    )
    chunk_duration_ms: int = Field(
        default=30,
        ge=10,
        le=100,
        description="Durasi per chunk audio dalam ms [10, 100]",
    )

    @field_validator("sample_rate")
    @classmethod
    def validate_sample_rate(cls, v: int) -> int:
        if v not in (16000, 24000, 44100, 48000):
            raise ValueError("sample_rate harus salah satu dari: 16000, 24000, 44100, 48000")
        return v


class VCSettingsUpdate(BaseModel):
    """
    Pembaruan parameter pengaturan secara dinamis selama sesi aktif.
    Hanya field yang aman diubah saat streaming (seperti pitch_shift) yang diizinkan.
    """
    model_config = ConfigDict(extra="forbid")

    pitch_shift: Optional[int] = Field(
        default=None,
        ge=-12,
        le=12,
        description="Pergeseran nada baru dalam semitone [-12, 12]",
    )

    @model_validator(mode="after")
    def check_at_least_one_field(self) -> "VCSettingsUpdate":
        if self.pitch_shift is None:
            raise ValueError("Setidaknya satu field pengaturan harus disertakan untuk pembaruan.")
        return self


# ---------------------------------------------------------------------------
# Client -> Server Messages
# ---------------------------------------------------------------------------

class InitSessionMessage(BaseModel):
    """
    Pesan inisialisasi sesi dari klien (membuat sesi baru atau reconnect).
    """
    type: Literal["init_session"] = "init_session"
    voice_profile_id: Optional[uuid.UUID] = Field(
        default=None,
        description="ID voice profile target (wajib jika membuat sesi baru)",
    )
    session_id: Optional[uuid.UUID] = Field(
        default=None,
        description="ID sesi yang sedang berjalan (untuk reconnect saat grace period)",
    )
    settings: Optional[VCSettings] = Field(
        default_factory=VCSettings,
        description="Pengaturan sesi konversi suara",
    )

    @field_validator("settings", mode="before")
    @classmethod
    def default_settings_if_none(cls, v: Optional[VCSettings]) -> VCSettings:
        if v is None:
            return VCSettings()
        return v

    @model_validator(mode="after")
    def check_identifiers(self) -> "InitSessionMessage":
        if self.voice_profile_id is None and self.session_id is None:
            raise ValueError("voice_profile_id atau session_id harus disertakan pada init_session.")
        return self


class UpdateSettingsMessage(BaseModel):
    """
    Pesan pembaruan parameter pengaturan dinamis dari klien saat sesi aktif.
    """
    type: Literal["update_settings"] = "update_settings"
    settings: VCSettingsUpdate = Field(
        ...,
        description="Objek pengaturan yang diperbarui",
    )


class CloseSessionMessage(BaseModel):
    """
    Pesan terminasi bersih sesi voice changer dari klien.
    """
    type: Literal["close_session"] = "close_session"


ClientMessage = Annotated[
    Union[InitSessionMessage, UpdateSettingsMessage, CloseSessionMessage],
    Field(discriminator="type"),
]
_client_message_adapter = TypeAdapter(ClientMessage)


def parse_client_message(data: Union[str, dict]) -> ClientMessage:
    """Parse raw JSON string atau dictionary menjadi ClientMessage konkret."""
    if isinstance(data, str):
        return _client_message_adapter.validate_json(data)
    elif isinstance(data, dict):
        return _client_message_adapter.validate_python(data)
    raise ValueError("Data harus berupa string JSON atau dictionary.")


# ---------------------------------------------------------------------------
# Server -> Client Messages
# ---------------------------------------------------------------------------

class SessionReadyMessage(BaseModel):
    """
    Pesan konfirmasi kesiapan sesi dari server setelah model selesai dimuat.
    """
    type: Literal["session_ready"] = "session_ready"
    session_id: uuid.UUID = Field(
        ...,
        description="ID unik sesi voice changer yang aktif",
    )
    reconnected: bool = Field(
        default=False,
        description="Bernilai true jika pesan ini mengonfirmasi penyambungan kembali dari grace period",
    )


class MetricsMessage(BaseModel):
    """
    Laporan metrik latensi streaming dari server ke klien.
    """
    type: Literal["metrics"] = "metrics"
    latency_ms: float = Field(
        ...,
        ge=0.0,
        description="Total latensi transit bolak-balik ditambah inferensi (ms)",
    )
    processing_ms: float = Field(
        ...,
        ge=0.0,
        description="Waktu eksekusi inferensi pemrosesan chunk audio (ms)",
    )


class ErrorMessage(BaseModel):
    """
    Pesan kesalahan dari server ke klien.
    """
    type: Literal["error"] = "error"
    code: VCErrorCode = Field(
        ...,
        description="Kode error standar",
    )
    message: str = Field(
        ...,
        description="Pesan kesalahan deskriptif",
    )


ServerMessage = Annotated[
    Union[SessionReadyMessage, MetricsMessage, ErrorMessage],
    Field(discriminator="type"),
]
_server_message_adapter = TypeAdapter(ServerMessage)


def parse_server_message(data: Union[str, dict]) -> ServerMessage:
    """Parse raw JSON string atau dictionary menjadi ServerMessage konkret."""
    if isinstance(data, str):
        return _server_message_adapter.validate_json(data)
    elif isinstance(data, dict):
        return _server_message_adapter.validate_python(data)
    raise ValueError("Data harus berupa string JSON atau dictionary.")


# ---------------------------------------------------------------------------
# Helper Validasi Audio PCM (Binary)
# ---------------------------------------------------------------------------

def calculate_expected_pcm_bytes(sample_rate: int, chunk_duration_ms: int) -> int:
    """
    Menghitung ukuran byte yang diharapkan untuk frame audio raw PCM (16-bit signed integer, mono).
    Rumus: sample_rate * (chunk_duration_ms / 1000) * 2 bytes.
    """
    return int(sample_rate * (chunk_duration_ms / 1000.0) * 2)


def validate_pcm_frame(
    frame: bytes,
    sample_rate: int,
    chunk_duration_ms: int,
    tolerance_bytes: int = 0,
) -> bool:
    """
    Memvalidasi integritas frame audio raw PCM biner:
    - Harus berupa bytes/bytearray tidak kosong
    - Ukuran harus kelipatan 2 (16-bit sample alignment)
    - Ukuran harus sesuai dengan expected bytes (dengan toleransi opsional)
    """
    if not isinstance(frame, (bytes, bytearray)):
        return False
    actual_len = len(frame)
    if actual_len == 0 or actual_len % 2 != 0:
        return False

    expected_len = calculate_expected_pcm_bytes(sample_rate, chunk_duration_ms)
    if tolerance_bytes <= 0:
        return actual_len == expected_len
    return abs(actual_len - expected_len) <= tolerance_bytes


# ---------------------------------------------------------------------------
# Session Database Serialization
# ---------------------------------------------------------------------------

class VCSessionResponse(BaseModel):
    """
    Representasi publik data sesi vc_sessions dari database.
    """
    id: uuid.UUID
    user_id: uuid.UUID
    voice_profile_id: uuid.UUID
    started_at: datetime
    ended_at: Optional[datetime] = None
    avg_latency_ms: Optional[float] = None
    settings: VCSettings

    model_config = ConfigDict(from_attributes=True)
