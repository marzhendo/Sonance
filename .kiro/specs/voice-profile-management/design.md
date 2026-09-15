# Design Document — Voice Profile Management

## Overview

Voice Profile Management adalah fitur inti Sonance yang memungkinkan pengguna mengunggah sample audio, membuat Voice Profile, men-trigger training job secara async, dan mengelola profile tersebut sepanjang siklus hidupnya.

Fitur ini melibatkan tiga lapisan utama:
1. **HTTP layer** — FastAPI router yang meng-expose 7 endpoint REST
2. **Service layer** — logika bisnis di `Voice_Profile_Service` dan `Training_Job_Service`
3. **Worker layer** — Celery/RQ task yang mengeksekusi training di background

Lingkup fitur ini **tidak mencakup** TTS pipeline maupun real-time voice changer. Kedua fitur tersebut diatur di spec terpisah dan akan mengonsumsi `model_checkpoint_path` yang dihasilkan di sini.

---

## Architecture

### Diagram Alur Sistem

```
Client
  │
  │  HTTP Request (Bearer token di header)
  ▼
┌─────────────────────────────────────────────────────────────────┐
│  FastAPI App                                                     │
│                                                                 │
│  Auth_Guard (core/auth.py)                                      │
│    │  Validasi SONANCE_API_TOKEN                                │
│    │  Ekstrak user_id dari token                                │
│    ▼                                                            │
│  Voice_Profile_Router (routers/voice_profile_router.py)         │
│    │  Routing HTTP → service calls                              │
│    ▼                                                            │
│  ┌─────────────────────────┐  ┌───────────────────────────────┐ │
│  │ Voice_Profile_Service   │  │ Training_Job_Service          │ │
│  │ (services/voice_profile │  │ (services/training_job_       │ │
│  │  _service.py)           │  │  service.py)                  │ │
│  │                         │  │                               │ │
│  │ - create()              │  │ - dispatch()                  │ │
│  │ - list()                │  │ - get_status()                │ │
│  │ - get()                 │  │ - update_progress()           │ │
│  │ - rename()              │  │ - complete()                  │ │
│  │ - delete()              │  │ - fail()                      │ │
│  │ - get_status()          │  │                               │ │
│  └──────────┬──────────────┘  └───────────────┬───────────────┘ │
│             │                                 │                 │
└─────────────┼─────────────────────────────────┼─────────────────┘
              │                                 │
              ▼                                 ▼
      ┌───────────────┐               ┌─────────────────────┐
      │  Database     │               │  Job Queue          │
      │  (SQL)        │               │  (Celery/RQ+Redis)  │
      │               │               │                     │
      │ voice_profiles│               │  training_worker.py │
      │ training_jobs │               │  (workers/)         │
      └───────────────┘               └──────────┬──────────┘
                                                 │
                                                 ▼
                                      ┌────────────────────┐
                                      │  ML Pipelines      │
                                      │                    │
                                      │  ml/rvc/  ←── own_voice
                                      │           ←── other_person
                                      │  ml/svc/  ←── character
                                      └────────────────────┘
```

### Alur Per Request Utama

**POST /api/v1/voice-profiles (Create)**
```
Request → Auth_Guard → validate fields (Router)
       → validate file format & size (Router/422)
       → extract duration (Service)
       → validate duration range (Service/400)
       → save file to SONANCE_SAMPLE_AUDIO_DIR
       → INSERT voice_profiles (status=pending)
       → HTTP 201
```

**POST /api/v1/voice-profiles/{id}/train (Trigger Training)**
```
Request → Auth_Guard → fetch voice_profile WHERE id AND user_id
       → check status=pending (else 409)
       → INSERT training_jobs (status=queued)
       → dispatch task to Job_Queue
       → (if dispatch fails) DELETE training_jobs record → HTTP 500
       → HTTP 202 {training_job_id, status}
```

**Worker (training_worker.py)**
```
Task received → UPDATE voice_profiles.status=processing
             → UPDATE training_jobs.status=processing, started_at=now
             → Pipeline_Router: select RVC or SVC by source_type
             → Execute pipeline (progress_pct updates)
             → (success) UPDATE voice_profiles.status=ready, model_checkpoint_path
                         UPDATE training_jobs.status=completed, completed_at=now
             → (failure) UPDATE voice_profiles.status=failed, error_message (max 500 char)
                         UPDATE training_jobs.status=failed, error_log (full stack trace)
```

**DELETE /api/v1/voice-profiles/{id}**
```
Request → Auth_Guard → fetch voice_profile WHERE id AND user_id
       → check status != processing (else 409)
       → try delete sample_audio_path file
           FileNotFoundError → tolerated, continue
           OSError/PermissionError → HTTP 500, stop (no DB changes)
       → try delete model_checkpoint_path file
           FileNotFoundError → tolerated, continue
           OSError/PermissionError → HTTP 500, stop (no DB changes)
       → DELETE training_jobs WHERE voice_profile_id
       → DELETE voice_profiles WHERE id AND user_id
       → HTTP 204
```

---

## Components and Interfaces

### Auth_Guard (`core/auth.py`)

```python
async def verify_token(
    authorization: str = Header(...)
) -> str:
    """
    Memvalidasi SONANCE_API_TOKEN dari header Authorization.
    Mengembalikan user_id yang diekstrak dari token.
    Melempar HTTP 401 jika token tidak valid.
    
    Catatan: Token dikirim via header (bukan query param).
    Query param hanya digunakan untuk WebSocket (ADR-002).
    """
```

### Voice_Profile_Router (`routers/voice_profile_router.py`)

| Method | Path | Handler | Auth |
|--------|------|---------|------|
| POST | `/api/v1/voice-profiles` | `create_voice_profile` | ✓ |
| GET | `/api/v1/voice-profiles` | `list_voice_profiles` | ✓ |
| GET | `/api/v1/voice-profiles/{id}` | `get_voice_profile` | ✓ |
| PATCH | `/api/v1/voice-profiles/{id}` | `rename_voice_profile` | ✓ |
| DELETE | `/api/v1/voice-profiles/{id}` | `delete_voice_profile` | ✓ |
| POST | `/api/v1/voice-profiles/{id}/train` | `trigger_training` | ✓ |
| GET | `/api/v1/voice-profiles/{id}/status` | `get_training_status` | ✓ |

**Validasi yang ditangani di layer Router (FastAPI/Pydantic — HTTP 422):**
- Field `name` tidak ada, kosong, atau melebihi batas karakter
- Field `source_type` bukan nilai enum valid
- File `sample_audio` tidak dikirim
- Ukuran file `sample_audio` melebihi 10 MB

**Validasi yang ditangani di layer Service (HTTP 400/409/500):**
- Format file bukan Opus
- Durasi file di luar rentang 10–30 detik
- File corrupt/tidak dapat dibaca
- Status conflict (training saat non-pending, delete saat processing)
- I/O error saat file write/delete

### Voice_Profile_Service (`services/voice_profile_service.py`)

```python
async def create(
    user_id: str,
    name: str,
    source_type: SourceType,
    sample_audio: UploadFile,
    db: AsyncSession,
) -> VoiceProfileResponse:
    """Membuat voice profile baru. Melempar HTTP 400 untuk format/durasi invalid."""

async def list(
    user_id: str,
    db: AsyncSession,
) -> list[VoiceProfileResponse]:
    """Mengembalikan semua VP milik user, diurutkan created_at DESC."""

async def get(
    voice_profile_id: UUID,
    user_id: str,
    db: AsyncSession,
) -> VoiceProfileResponse:
    """Mengambil satu VP. Melempar HTTP 404 jika tidak ada atau milik user lain."""

async def rename(
    voice_profile_id: UUID,
    user_id: str,
    new_name: str,
    db: AsyncSession,
) -> VoiceProfileResponse:
    """Rename VP. Trim name sebelum validasi dan simpan."""

async def delete(
    voice_profile_id: UUID,
    user_id: str,
    db: AsyncSession,
) -> None:
    """Delete VP + file. HTTP 409 jika status=processing."""

async def get_status(
    voice_profile_id: UUID,
    user_id: str,
    db: AsyncSession,
) -> VoiceProfileStatusResponse:
    """Mengembalikan status VP beserta info training_job terkait."""
```

### Training_Job_Service (`services/training_job_service.py`)

```python
async def dispatch(
    voice_profile_id: UUID,
    source_type: SourceType,
    db: AsyncSession,
) -> TrainingJobResponse:
    """
    Membuat record training_job, dispatch ke Job_Queue.
    Rollback training_job record jika dispatch gagal.
    """

async def update_progress(
    training_job_id: UUID,
    progress_pct: int,
    db: AsyncSession,
) -> None:
    """Dipanggil oleh worker untuk update progress (0-100)."""

async def complete(
    training_job_id: UUID,
    voice_profile_id: UUID,
    checkpoint_path: str,
    db: AsyncSession,
) -> None:
    """Dipanggil oleh worker saat training berhasil."""

async def fail(
    training_job_id: UUID,
    voice_profile_id: UUID,
    error_summary: str,
    error_log: str,
    db: AsyncSession,
) -> None:
    """Dipanggil oleh worker saat training gagal."""
```

### Pipeline_Router (di dalam `training_worker.py`)

```python
def select_pipeline(source_type: SourceType) -> TrainingPipeline:
    """
    Routing logic berdasarkan ADR-007:
    - own_voice    → RVC pipeline (backend/ml/rvc/)
    - other_person → RVC pipeline (backend/ml/rvc/)
    - character    → SVC pipeline (backend/ml/svc/)
    """
    if source_type in (SourceType.own_voice, SourceType.other_person):
        return RVCPipeline()
    elif source_type == SourceType.character:
        return SVCPipeline()
    else:
        raise ValueError(f"Unknown source_type: {source_type}")
```

---

## Data Models

### Pydantic Schemas (`schemas/voice_profile_schema.py`)

```python
class SourceType(str, Enum):
    own_voice = "own_voice"
    other_person = "other_person"
    character = "character"

class VoiceProfileStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    ready = "ready"
    failed = "failed"

# Request schemas
class VoiceProfileCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    source_type: SourceType
    # sample_audio: diterima sebagai UploadFile di router (Form + File)

class VoiceProfileRenameRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    
    @validator("name")
    def name_must_not_be_empty_after_trim(cls, v):
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("name tidak boleh hanya berisi whitespace")
        if len(trimmed) > 100:
            raise ValueError("name tidak boleh melebihi 100 karakter setelah di-trim")
        return trimmed

# Response schemas
class VoiceProfileResponse(BaseModel):
    id: UUID
    name: str
    source_type: SourceType
    status: VoiceProfileStatus
    duration_seconds: float
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class TrainingJobStatusResponse(BaseModel):
    status: str
    progress_pct: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]

class VoiceProfileStatusResponse(BaseModel):
    id: UUID
    status: VoiceProfileStatus
    error_message: Optional[str]
    training_job: Optional[TrainingJobStatusResponse]
```

### ORM Models

**`models/voice_profile_model.py`**
```python
class VoiceProfile(Base):
    __tablename__ = "voice_profiles"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    source_type: Mapped[str] = mapped_column(
        Enum("own_voice", "other_person", "character", name="source_type_enum"),
        nullable=False
    )
    status: Mapped[str] = mapped_column(
        Enum("pending", "processing", "ready", "failed", name="voice_profile_status_enum"),
        nullable=False,
        default="pending"
    )
    sample_audio_path: Mapped[Optional[str]] = mapped_column(VARCHAR(1024))
    model_checkpoint_path: Mapped[Optional[str]] = mapped_column(VARCHAR(1024))
    duration_seconds: Mapped[float] = mapped_column(FLOAT, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(TEXT)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    training_job: Mapped[Optional["TrainingJob"]] = relationship(
        "TrainingJob", back_populates="voice_profile", uselist=False,
        cascade="all, delete-orphan"
    )
```

**`models/training_job_model.py`**
```python
class TrainingJob(Base):
    __tablename__ = "training_jobs"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    voice_profile_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("voice_profiles.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # 1-to-1 constraint (ADR-006)
        index=True
    )
    status: Mapped[str] = mapped_column(
        Enum("queued", "processing", "completed", "failed", name="training_job_status_enum"),
        nullable=False,
        default="queued"
    )
    progress_pct: Mapped[int] = mapped_column(INTEGER, nullable=False, default=0)
    started_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    error_log: Mapped[Optional[str]] = mapped_column(TEXT)

    voice_profile: Mapped["VoiceProfile"] = relationship(
        "VoiceProfile", back_populates="training_job"
    )
```

### Database Schema SQL

```sql
-- Tabel voice_profiles
CREATE TABLE voice_profiles (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id               UUID NOT NULL REFERENCES users(id),
    name                  VARCHAR(255) NOT NULL,
    source_type           VARCHAR(20) NOT NULL
                            CHECK (source_type IN ('own_voice', 'other_person', 'character')),
    status                VARCHAR(20) NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending', 'processing', 'ready', 'failed')),
    sample_audio_path     VARCHAR(1024),
    model_checkpoint_path VARCHAR(1024),
    duration_seconds      FLOAT NOT NULL,
    error_message         TEXT CHECK (char_length(error_message) <= 500),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_voice_profiles_user_id ON voice_profiles(user_id);
CREATE INDEX idx_voice_profiles_user_created ON voice_profiles(user_id, created_at DESC);

-- Tabel training_jobs
CREATE TABLE training_jobs (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    voice_profile_id  UUID NOT NULL UNIQUE REFERENCES voice_profiles(id) ON DELETE CASCADE,
    status            VARCHAR(20) NOT NULL DEFAULT 'queued'
                        CHECK (status IN ('queued', 'processing', 'completed', 'failed')),
    progress_pct      INTEGER NOT NULL DEFAULT 0
                        CHECK (progress_pct >= 0 AND progress_pct <= 100),
    started_at        TIMESTAMPTZ,
    completed_at      TIMESTAMPTZ,
    error_log         TEXT
);

CREATE INDEX idx_training_jobs_voice_profile_id ON training_jobs(voice_profile_id);
```

### Voice Profile Lifecycle

```
[POST /voice-profiles]
        │
        ▼
    status: pending
        │
        │ POST /voice-profiles/{id}/train
        ▼
    training_jobs.status: queued
        │
        │ worker picks up job
        ▼
    voice_profiles.status: processing
    training_jobs.status: processing
    training_jobs.started_at = now()
        │
        ├─────────────────────┐
        ▼                     ▼
  (success)              (failure)
voice_profiles.status: ready   voice_profiles.status: failed
training_jobs.status: completed  training_jobs.status: failed
training_jobs.completed_at = now()  voice_profiles.error_message (max 500 char)
voice_profiles.model_checkpoint_path  training_jobs.error_log (full stack trace)
```

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Create Voice Profile — Status Awal dan Kelengkapan Response

*For any* kombinasi `name` valid (1–255 karakter non-whitespace) dan `source_type` valid (`own_voice`, `other_person`, `character`) yang dikirim bersama file Opus berformat valid dengan durasi dalam rentang [10, 30] detik, sistem SHALL selalu membuat Voice Profile baru dengan `status = 'pending'` dan mengembalikan HTTP 201 yang mengandung semua field wajib (`id`, `name`, `source_type`, `status`, `duration_seconds`, `created_at`, `updated_at`).

**Validates: Requirements 1.1, 1.2**

---

### Property 2: Validasi Name — Rejection Semua Input Invalid

*For any* string yang merupakan input `name`, jika string tersebut kosong, terdiri seluruhnya dari karakter whitespace, atau memiliki panjang lebih dari 255 karakter, sistem SHALL selalu menolak request tersebut dengan HTTP 422 dan tidak membuat record baru di database.

**Validates: Requirements 1.3, 6.3**

---

### Property 3: Validasi Durasi Sample Audio

*For any* file Opus yang valid, jika durasi file tersebut kurang dari 10 detik atau lebih dari 30 detik, sistem SHALL selalu menolak request dengan HTTP 400. Sebaliknya, *for any* file Opus valid dengan durasi dalam rentang [10, 30] detik, `duration_seconds` yang tersimpan di database SHALL selalu sesuai dengan durasi aktual file tersebut.

**Validates: Requirements 1.8, 1.9**

---

### Property 4: Pipeline Routing Berdasarkan source_type

*For any* Voice Profile yang di-trigger training-nya, sistem SHALL selalu menggunakan pipeline yang tepat: jika `source_type` adalah `own_voice` atau `other_person`, pipeline RVC SHALL digunakan; jika `source_type` adalah `character`, pipeline SVC SHALL digunakan — tanpa pengecualian.

**Validates: Requirements 2.10**

---

### Property 5: Training Job Lifecycle — State Transitions

*For any* Training Job yang di-dispatch, state transitions berikut SHALL selalu terjadi secara berurutan dan konsisten:
- Saat worker memulai: `voice_profiles.status = 'processing'`, `training_jobs.status = 'processing'`, `training_jobs.started_at != NULL`
- Jika selesai berhasil: `voice_profiles.status = 'ready'`, `training_jobs.status = 'completed'`, `training_jobs.completed_at != NULL`, `voice_profiles.model_checkpoint_path != NULL`
- Jika gagal: `voice_profiles.status = 'failed'`, `training_jobs.status = 'failed'`, `voice_profiles.error_message != NULL` (panjang ≤ 500 karakter), `training_jobs.error_log != NULL`

**Validates: Requirements 2.6, 2.7, 2.8**

---

### Property 6: Status Polling — Invariant Field Berdasarkan Status

*For any* Voice Profile, respons dari `GET /api/v1/voice-profiles/{id}/status` SHALL selalu memenuhi invariant berikut:
- Ketika `status = 'processing'`: field `training_job.progress_pct` SHALL ada dan nilainya dalam rentang [0, 100]
- Ketika `status = 'failed'`: field `error_message` SHALL tidak null, dan `training_job.completed_at` SHALL null
- Ketika `status = 'ready'`: field `training_job.completed_at` SHALL tidak null

**Validates: Requirements 3.1, 3.4, 3.5, 3.6**

---

### Property 7: List Voice Profile — Isolasi Kepemilikan dan Urutan

*For any* request `GET /api/v1/voice-profiles` yang terautentikasi, respons SHALL hanya berisi Voice Profile milik user yang terautentikasi (tidak ada profile milik user lain), diurutkan `created_at` DESC, dan setiap item SHALL mengandung semua field wajib (`id`, `name`, `source_type`, `status`, `duration_seconds`, `created_at`, `updated_at`).

**Validates: Requirements 4.1, 4.2, 4.4**

---

### Property 8: Ownership Isolation — HTTP 404 untuk Resource Milik User Lain

*For any* Voice Profile yang dimiliki user A, semua operasi yang dilakukan oleh user B (GET detail, PATCH rename, DELETE, POST train, GET status) SHALL selalu mengembalikan HTTP 404 — tidak pernah 403, tidak pernah mengekspos data milik user A.

**Validates: Requirements 2.4, 3.3, 5.3, 6.5, 7.2, 9.2**

---

### Property 9: Auth Guard — HTTP 401 untuk Semua Endpoint

*For any* request ke salah satu dari 7 endpoint Voice Profile Management (`POST /voice-profiles`, `GET /voice-profiles`, `GET /voice-profiles/{id}`, `PATCH /voice-profiles/{id}`, `DELETE /voice-profiles/{id}`, `POST /voice-profiles/{id}/train`, `GET /voice-profiles/{id}/status`) yang tidak menyertakan API token, menyertakan token kosong, atau menyertakan token yang tidak cocok dengan `SONANCE_API_TOKEN`, sistem SHALL selalu mengembalikan HTTP 401 dan tidak meneruskan request ke router.

**Validates: Requirements 8.1, 8.2**

---

### Property 10: Rename — Field Preservation

*For any* operasi rename yang berhasil, semua field Voice Profile selain `name` dan `updated_at` (`id`, `source_type`, `status`, `sample_audio_path`, `model_checkpoint_path`, `duration_seconds`, `error_message`, `created_at`) SHALL tetap identik dengan nilai sebelum rename. Selain itu, `name` yang tersimpan SHALL selalu merupakan hasil `trim()` dari `name` yang dikirim.

**Validates: Requirements 6.1, 6.6**

---

## Error Handling

### Hierarki Error dan HTTP Status Code

| Kondisi | Status Code | Layer | Catatan |
|---------|------------|-------|---------|
| Token tidak ada / kosong / salah | 401 | Auth_Guard | Request tidak diteruskan ke router |
| Field wajib tidak ada / format invalid | 422 | Router (Pydantic) | Validasi otomatis Pydantic |
| `name` kosong / whitespace / terlalu panjang | 422 | Router (Pydantic) | Validasi sebelum I/O |
| `source_type` tidak valid | 422 | Router (Pydantic) | Enum validation |
| File tidak dikirim | 422 | Router (Pydantic) | File required |
| File > 10 MB | 422 | Router (Pydantic) | Size check |
| Format file bukan Opus | 400 | Service | Setelah file diterima |
| Durasi di luar rentang [10,30] detik | 400 | Service | Setelah durasi diekstrak |
| File corrupt / tidak dapat dibaca | 400 | Service | saat ekstraksi durasi |
| Resource tidak ditemukan | 404 | Service | Termasuk resource milik user lain |
| Conflict status (training non-pending, delete saat processing) | 409 | Service | State guard |
| I/O error saat file write | 500 | Service | Dengan DB rollback |
| I/O error saat file delete | 500 | Service | DB tidak dihapus |
| Queue dispatch gagal | 500 | Service | training_job record dihapus (rollback) |

### Strategi Rollback

**Pembuatan Voice Profile (POST /voice-profiles):**
- Jika file berhasil disimpan tapi INSERT DB gagal → hapus file dari disk
- Jika INSERT DB berhasil tapi terjadi error di langkah lain → hapus record dan file
- Prinsip: tidak ada "orphan file" di disk tanpa record DB yang valid

**Trigger Training (POST /voice-profiles/{id}/train):**
- Jika INSERT training_jobs berhasil tapi dispatch queue gagal → DELETE training_jobs record
- `voice_profiles.status` tetap `pending` — user bisa retry

**Delete Voice Profile (DELETE /voice-profiles/{id}):**
- Urutan eksekusi: delete file dulu, baru delete DB records
- `FileNotFoundError` → lanjutkan (file sudah tidak ada, tujuan tercapai)
- `OSError` / `PermissionError` → hentikan, return HTTP 500, jangan hapus DB records

### Format Error Response

```json
{
  "detail": "Pesan error yang deskriptif dalam Bahasa Indonesia"
}
```

Untuk validasi Pydantic (HTTP 422), FastAPI menggunakan format bawaan:
```json
{
  "detail": [
    {
      "loc": ["body", "name"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

---

## Testing Strategy

### Pendekatan Dual Testing

Fitur ini menggunakan dua lapisan testing yang saling melengkapi:

1. **Unit tests** — memverifikasi contoh spesifik, edge case, dan kondisi error
2. **Property-based tests** — memverifikasi correctness properties di atas menggunakan input yang di-generate secara acak

Library property-based testing yang digunakan: **[Hypothesis](https://hypothesis.readthedocs.io/)** (Python).

### Konfigurasi Property-Based Tests

Setiap property test dikonfigurasi dengan:
- Minimum **100 iterasi** per test (melalui `@settings(max_examples=100)`)
- Tag komentar yang mereferensikan property di design doc ini
- Format tag: `# Feature: voice-profile-management, Property {N}: {ringkasan property}`

Contoh:
```python
# Feature: voice-profile-management, Property 2: Validasi Name — Rejection Semua Input Invalid
@given(name=st.one_of(
    st.just(""),
    st.text(alphabet=string.whitespace, min_size=1),
    st.text(min_size=256)
))
@settings(max_examples=100)
def test_invalid_name_always_rejected(name: str):
    response = client.post("/api/v1/voice-profiles", data={"name": name, ...})
    assert response.status_code == 422
```

### Unit Tests (Example-Based)

Kasus yang ditangani unit test (satu-dua contoh spesifik):

- `source_type` invalid (mis. `"robot"`, `""`) → 422
- File tidak dikirim → 422
- File corrupt → 400
- I/O error saat file write → 500 + DB rollback (dengan mock `open()`)
- Dispatch queue gagal → 500 + training_job rollback (dengan mock queue)
- Voice profile tidak ditemukan (UUID random) → 404
- Status conflict: trigger train untuk VP status=`ready` → 409
- Status conflict: delete VP status=`processing` → 409
- File tidak ada di disk saat delete → 204 tetap berhasil
- I/O error saat file delete → 500 + DB tidak dihapus

### Struktur Test Files

```
backend/tests/
├── unit/
│   ├── test_voice_profile_service.py     # Unit tests + property tests service layer
│   ├── test_training_job_service.py      # Unit tests training job logic
│   └── test_pipeline_router.py           # Property test routing (Property 4)
├── integration/
│   ├── test_voice_profile_router.py      # Integration tests endpoint-to-DB
│   └── test_training_worker.py           # Worker integration tests
└── conftest.py                           # Fixtures: test DB, mock storage, mock queue
```

### Coverage Target

- Service layer: **90%+** (unit + property tests)
- Router layer: **80%+** (integration tests)
- Worker layer: **75%+** (integration tests dengan mock ML pipeline)
- Property tests wajib mencakup semua 10 Correctness Properties di atas
