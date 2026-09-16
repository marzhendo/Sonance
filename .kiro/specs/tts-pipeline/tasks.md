# Tasks: TTS Pipeline (Offline Voice Cloning)

## Overview

Implementasi fitur TTS Pipeline (Offline Voice Cloning) mengikuti pola dependency berjenjang (Wave 0 hingga Wave 7) yang konsisten dengan Voice Profile Management: DB migration → ORM model → Pydantic schemas → Service layer → Router endpoints → Worker & ML stubs (termasuk GPU lock timeout 30 menit) → Property-based testing.

Setiap task didesain sebagai tracer-bullet slice yang dapat diuji secara mandiri dengan TDD.

---

## Tasks

### Wave 0: Database Migration
- [x] 1. Migration SQL untuk tabel `tts_jobs`
  - [x] 1.1 Buat Alembic migration `backend/alembic/versions/0002_create_tts_jobs.py`
    - Kolom: `id` (UUID PK), `user_id` (UUID FK -> `users.id` RESTRICT), `voice_profile_id` (UUID FK -> `voice_profiles.id` CASCADE), `input_text` (TEXT NOT NULL), `status` (VARCHAR(20) CHECK enum `queued`, `processing`, `completed`, `failed`), `output_audio_path` (VARCHAR(500) NULL), `settings` (JSON NOT NULL), `error_message` (TEXT NULL), `created_at` (TIMESTAMP WITH TIME ZONE NOT NULL), `started_at` (TIMESTAMP WITH TIME ZONE NULL), `completed_at` (TIMESTAMP WITH TIME ZONE NULL), `gpu_wait_started_at` (TIMESTAMP WITH TIME ZONE NULL).
    - Composite indexes: `idx_tts_jobs_user_created ON tts_jobs(user_id, created_at DESC)`, `idx_tts_jobs_status ON tts_jobs(status)`.
    - _Blocked by: None (can start immediately)_

### Wave 1: ORM Model
- [x] 2. ORM Model `TTSJob`
  - [x] 2.1 Buat ORM model `TTSJob` di `backend/app/models/tts_job_model.py`
    - SQLAlchemy 2.x `Mapped[]` annotation style.
    - Relasi: `user` (Many-to-One ke `User`), `voice_profile` (Many-to-One ke `VoiceProfile`).
    - Unit tests model di `backend/tests/unit/test_tts_models.py`.
    - _Blocked by: Task 1_

### Wave 2: Pydantic Schemas & Settings Validation
- [x] 3. Pydantic Schemas untuk TTS Pipeline
  - [x] 3.1 Buat schemas di `backend/app/schemas/tts_job_schema.py`
    - `TTSSettings`: `language` whitelist `["id", "en"]` (default "id"), `speed` float [0.5, 2.0] (default 1.0), `pitch_shift` int [-12, 12] (default 0), `temperature` float [0.1, 1.0] (default 0.7), `output_format` locked `"opus"` (default "opus").
    - `TTSGenerateRequest`: `voice_profile_id` (UUID), `text` (1-1000 karakter setelah trim), `settings` (opsional, default `TTSSettings()`).
    - `TTSJobResponse`: `job_id` (UUID), `status` ("queued") untuk HTTP 202.
    - `TTSJobStatusResponse`: representasi status publik (exclude `output_audio_path`).
    - Unit tests di `backend/tests/unit/test_tts_schemas.py`.
    - _Blocked by: Task 2_

### Wave 3: Service Layer
- [x] 4. Implementasi `TTSJobService`
  - [x] 4.1 Buat service di `backend/app/services/tts_job_service.py`
    - `dispatch(user_id, request_data, db, queue) -> TTSJobResponse`: Validasi profil milik user (404), validasi status profil `ready` (409 Conflict jika bukan ready), insert `tts_jobs` (`status='queued'`), enqueue ke queue adapter, rollback & 500 jika queue gagal.
    - `get_status(job_id, user_id, db) -> TTSJobStatusResponse`: Validasi kepemilikan (404), pastikan `error_message` adalah None jika status bukan `failed`.
    - `get_audio_path(job_id, user_id, db) -> str`: Validasi kepemilikan (404), tolak dengan 409 jika status `queued`, `processing`, atau `failed`, verifikasi keberadaan fisik file Opus di storage (500 jika hilang), return path.
    - Worker mutators: `record_gpu_wait_start()`, `update_start()`, `complete()`, `fail()`, dan `fail_due_to_gpu_timeout()`.
    - Unit tests di `backend/tests/unit/test_tts_job_service.py`.
    - _Blocked by: Task 3_

### Wave 4: Router Layer
- [x] 5. Router Endpoints TTS (`POST /generate`, `GET /jobs/{id}`, `GET /jobs/{id}/audio`)
  - [x] 5.1 Buat router `backend/app/routers/tts_router.py` dan daftarkan ke `backend/app/main.py`
    - Semua endpoint menggunakan `Depends(verify_token)`.
    - `POST /api/v1/tts/generate`: panggil `dispatch()`, return HTTP 202.
    - `GET /api/v1/tts/jobs/{job_id}`: panggil `get_status()`, return HTTP 200.
    - `GET /api/v1/tts/jobs/{job_id}/audio`: panggil `get_audio_path()`, return `FileResponse(media_type="audio/ogg")`.
    - Integration tests di `backend/tests/integration/test_tts_router.py`.
    - _Blocked by: Task 4_

### Wave 5: ML Pipeline Stub & GPU Resource Manager
- [x] 6. Pipeline Interface, Stub `XTTSPipeline`, dan `GPUResourceManager`
  - [x] 6.1 Tambahkan interface `TTSPipeline(ABC)` di `backend/ml/base.py`
  - [x] 6.2 Buat stub `XTTSPipeline` di `backend/ml/xtts/__init__.py`
    - Mensimulasikan sintesis teks ke file dummy `.opus`, mendukung simulasi failure via `SONANCE_SIMULATE_TTS_FAILURE`.
  - [x] 6.3 Buat `GPUResourceManager` di `backend/app/core/gpu_manager.py`
    - Interface: `is_locked() -> bool`, `acquire_lock(session_id: str)`, `release_lock()`.
    - Unit tests di `backend/tests/unit/test_tts_pipeline.py`.
    - _Blocked by: Task 4_

### Wave 6: Worker Layer & GPU Lock Timeout
- [x] 7. TTS Worker dengan Penanganan GPU Lock dan Timeout 30 Menit
  - [x] 7.1 Buat worker di `backend/workers/tts_worker.py`
    - Fungsi task `execute_tts_job(tts_job_id, db=None, pipeline=None, gpu_manager=None)`.
    - Cek GPU lock: jika terkunci, catat `gpu_wait_started_at`.
    - Periksa selisih waktu tunggu (`now() - gpu_wait_started_at`). Jika >= 1800 detik (30 menit): batalkan job menjadi `failed` dengan pesan `"Job dibatalkan setelah menunggu GPU selama 30 menit karena sesi real-time voice changer masih aktif. Silakan coba lagi nanti."` (tanpa auto-retry).
    - Jika lock bebas: ubah status ke `processing`, jalankan sintesis, panggil `complete()` atau `fail()`.
    - CLI runner: `python -m backend.workers.tts_worker`.
    - Integration tests di `backend/tests/integration/test_tts_worker.py` (verifikasi eksekusi sukses, jeda saat terkunci, dan pembatalan saat timeout > 30 menit).
    - _Blocked by: Task 5, Task 6_

### Wave 7: Property-Based Testing
- [x] 8. Property-Based Testing dengan Hypothesis untuk TTS Pipeline
  - [x] 8.1 Buat property tests di `backend/tests/integration/test_tts_properties.py`
    - **Property 1**: Validasi Teks (rejection teks kosong/whitespace, teks > 1000 karakter).
    - **Property 2**: Validasi Settings (rejection bahasa di luar `id`/`en`, speed < 0.5 atau > 2.0, pitch shift < -12 atau > 12, temperature < 0.1 atau > 1.0, output_format != `opus`).
    - **Property 3**: Rejection Voice Profile Not Ready (profil status `pending`, `processing`, atau `failed` selalu ditolak dengan HTTP 409).
    - **Property 4**: Status Polling Invariants (`error_message` selalu None pada status non-failed; `completed_at` selalu None pada status non-completed).
    - **Property 5**: Auth Guard 401 across all 3 TTS endpoints untuk semua token invalid.
    - _Blocked by: Task 7_

### Wave 8: Checkpoint Final
- [x] 9. Checkpoint Final TTS Pipeline
  - [x] 9.1 Jalankan `pytest backend/tests/ -v` dan pastikan seluruh test suite (Voice Profile + TTS) lulus 100% tanpa regresi.
  - _Blocked by: Task 8_

---

## Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["3.1"] },
    { "id": 3, "tasks": ["4.1"] },
    { "id": 4, "tasks": ["5.1"] },
    { "id": 5, "tasks": ["6.1", "6.2", "6.3"] },
    { "id": 6, "tasks": ["7.1"] },
    { "id": 7, "tasks": ["8.1"] },
    { "id": 8, "tasks": ["9.1"] }
  ]
}
```
