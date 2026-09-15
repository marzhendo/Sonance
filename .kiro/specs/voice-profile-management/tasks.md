# Implementation Plan: Voice Profile Management

## Overview

Implementasi fitur Voice Profile Management dari 0 mengikuti urutan: foundation (DB schema + migration, ORM models, Pydantic schemas, auth guard) → service layer per operasi → router/endpoint → worker + pipeline → property-based tests. Setiap ticket adalah vertical slice yang cukup kecil untuk satu sesi TDD dengan `/implement`.

Requirement 9 (isolasi ownership) bukan ticket terpisah — setiap task yang menyentuh data user sudah menyertakan filter `WHERE user_id = ?` sebagai acceptance criteria bawaan.

---

## Tasks

- [x] 1. Foundation: DB Schema, Migration, dan ORM Models
  - [x] 1.1 Buat migration SQL untuk tabel `voice_profiles` dan `training_jobs`
    - Buat file migration (Alembic atau SQL plain) sesuai skema di design doc
    - Tabel `voice_profiles`: kolom `id`, `user_id` (FK ke `users.id`, index), `name` (VARCHAR 255), `source_type` (CHECK enum), `status` (CHECK enum, default `pending`), `sample_audio_path`, `model_checkpoint_path`, `duration_seconds` (FLOAT NOT NULL), `error_message` (TEXT, CHECK char_length ≤ 500), `created_at`, `updated_at`
    - Tabel `training_jobs`: kolom `id`, `voice_profile_id` (FK CASCADE, UNIQUE), `status` (CHECK enum, default `queued`), `progress_pct` (INTEGER CHECK 0–100, default 0), `started_at`, `completed_at`, `error_log` (TEXT)
    - Buat composite index `idx_voice_profiles_user_created ON voice_profiles(user_id, created_at DESC)`
    - _Requirements: 1.1, 2.1, 2.6, 2.7, 2.8_

  - [x] 1.2 Buat ORM model `VoiceProfile` di `backend/app/models/voice_profile_model.py`
    - Implementasi class `VoiceProfile(Base)` sesuai desain: semua kolom dengan tipe Mapped, relasi `training_job` (1-to-1, `cascade="all, delete-orphan"`)
    - Gunakan SQLAlchemy 2.x `Mapped[]` annotation style
    - _Requirements: 1.1, 2.1_

  - [x] 1.3 Buat ORM model `TrainingJob` di `backend/app/models/training_job_model.py`
    - Implementasi class `TrainingJob(Base)`: semua kolom, `unique=True` pada `voice_profile_id`, relasi back-reference ke `VoiceProfile`
    - _Requirements: 2.1, 2.6_

- [x] 2. Foundation: Pydantic Schemas
  - [x] 2.1 Buat Pydantic schemas di `backend/app/schemas/voice_profile_schema.py`
    - Definisi enum: `SourceType` (`own_voice`, `other_person`, `character`) dan `VoiceProfileStatus` (`pending`, `processing`, `ready`, `failed`)
    - Request schemas: `VoiceProfileCreateRequest` (`name` min 1 max 255, `source_type` enum), `VoiceProfileRenameRequest` (`name` dengan validator `name_must_not_be_empty_after_trim` — trim dulu, validasi panjang ≤ 100 setelah trim, reject jika empty)
    - Response schemas: `VoiceProfileResponse` (semua field wajib: `id`, `name`, `source_type`, `status`, `duration_seconds`, `error_message`, `created_at`, `updated_at`; `Config.from_attributes = True`)
    - Status schemas: `TrainingJobStatusResponse` (`status`, `progress_pct`, `started_at`, `completed_at`) dan `VoiceProfileStatusResponse` (`id`, `status`, `error_message`, `training_job: Optional[TrainingJobStatusResponse]`)
    - _Requirements: 1.2, 1.3, 1.4, 3.1, 6.1, 6.3, 6.4_

- [x] 3. Foundation: Auth Guard
  - [x] 3.1 Buat Auth Guard di `backend/app/core/auth.py`
    - Implementasi `async def verify_token(authorization: str = Header(...)) -> str` yang membaca `SONANCE_API_TOKEN` dari environment
    - Validasi: token tidak boleh absent, tidak boleh empty string, harus cocok exact dengan `SONANCE_API_TOKEN`
    - Kembalikan `user_id` yang diekstrak dari token (untuk single-user v1, bisa berupa fixed user identifier dari config)
    - Lempar `HTTPException(status_code=401)` jika validasi gagal — request tidak diteruskan ke router
    - _Requirements: 8.1, 8.2_

- [x] 4. Checkpoint — Foundation selesai
  - Pastikan semua model bisa diimport, migration bisa dijalankan, schemas bisa di-instantiate, dan auth guard bisa dipanggil. Jalankan semua tests yang ada.

- [x] 5. Service Layer: Create Voice Profile
  - [x] 5.1 Implementasi `VoiceProfileService.create()` di `backend/app/services/voice_profile_service.py`
    - Validasi format file: baca magic bytes atau header Opus — jika bukan Opus, raise HTTP 400
    - Ekstrak `duration_seconds` dari file Opus — jika file corrupt/tidak dapat dibaca, raise HTTP 400
    - Validasi durasi: jika < 10 atau > 30 detik, raise HTTP 400 dengan pesan yang menyebutkan rentang valid
    - Simpan file ke `SONANCE_SAMPLE_AUDIO_DIR/{user_id}/{uuid}.opus` — jika I/O error, raise HTTP 500, jangan INSERT ke DB
    - INSERT ke `voice_profiles` dengan `status='pending'`, `user_id` dari token, `duration_seconds` aktual dari file
    - Jika INSERT gagal setelah file tersimpan → hapus file (rollback), raise HTTP 500
    - Kembalikan `VoiceProfileResponse` dengan HTTP 201
    - Ownership: `user_id` dari token selalu dipakai sebagai nilai kolom `user_id` pada INSERT — tidak ada parameter luar yang bisa override
    - _Requirements: 1.1, 1.2, 1.6, 1.8, 1.9, 1.10, 1.11_

  - [x]* 5.2 Tulis property test untuk Property 1 dan Property 2
    - **Property 1: Create Voice Profile — Status Awal dan Kelengkapan Response**
    - **Validates: Requirements 1.1, 1.2**
    - **Property 2: Validasi Name — Rejection Semua Input Invalid**
    - **Validates: Requirements 1.3, 6.3**
    - Gunakan `@given` dengan `st.text()` untuk name, `st.sampled_from(SourceType)` untuk source_type
    - `@settings(max_examples=100)` — tag komentar: `# Feature: voice-profile-management, Property 1 & 2`
    - File: `backend/tests/unit/test_voice_profile_service.py`

  - [x]* 5.3 Tulis property test untuk Property 3
    - **Property 3: Validasi Durasi Sample Audio**
    - **Validates: Requirements 1.8, 1.9**
    - Generate file Opus dummy dengan durasi di bawah 10 detik, 10–30 detik (valid), dan di atas 30 detik
    - Verifikasi rejection dengan HTTP 400 untuk out-of-range, dan `duration_seconds` yang tersimpan = durasi aktual untuk valid
    - `@settings(max_examples=100)` — tag komentar: `# Feature: voice-profile-management, Property 3`
    - File: `backend/tests/unit/test_voice_profile_service.py`

- [x] 6. Service Layer: List dan Detail Voice Profile
  - [x] 6.1 Implementasi `VoiceProfileService.list()` di `backend/app/services/voice_profile_service.py`
    - Query: `SELECT * FROM voice_profiles WHERE user_id = :user_id ORDER BY created_at DESC`
    - Filter `user_id` wajib selalu ada — tidak ada query tanpa filter ini
    - Jika ada record yang `user_id`-nya tidak cocok dengan token, raise HTTP 403 (Req 4.2 — defense in depth)
    - Return list kosong `[]` jika tidak ada, bukan 404
    - Setiap item dikembalikan sebagai `VoiceProfileResponse` dengan semua field wajib
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 9.1_

  - [x] 6.2 Implementasi `VoiceProfileService.get()` di `backend/app/services/voice_profile_service.py`
    - Query: `SELECT * FROM voice_profiles WHERE id = :id AND user_id = :user_id`
    - Jika tidak ditemukan (termasuk milik user lain) → raise HTTP 404 — jangan bedakan "tidak ada" vs "milik user lain"
    - Return `VoiceProfileResponse`
    - _Requirements: 5.1, 5.2, 5.3, 9.1, 9.2_

  - [x]* 6.3 Tulis property test untuk Property 7 dan Property 8
    - **Property 7: List Voice Profile — Isolasi Kepemilikan dan Urutan**
    - **Validates: Requirements 4.1, 4.2, 4.4**
    - **Property 8: Ownership Isolation — HTTP 404 untuk Resource Milik User Lain**
    - **Validates: Requirements 2.4, 3.3, 5.3, 6.5, 7.2, 9.2**
    - Generate multiple users dan multiple voice profiles, verifikasi list hanya berisi milik sendiri dan sorted DESC
    - Verifikasi semua operasi pada resource milik user lain selalu return 404 (tidak pernah 403 atau data bocor)
    - `@settings(max_examples=100)` — tag komentar: `# Feature: voice-profile-management, Property 7 & 8`
    - File: `backend/tests/unit/test_voice_profile_service.py`

- [x] 7. Service Layer: Rename Voice Profile
  - [x] 7.1 Implementasi `VoiceProfileService.rename()` di `backend/app/services/voice_profile_service.py`
    - Query fetch: `SELECT * FROM voice_profiles WHERE id = :id AND user_id = :user_id` — jika tidak ada, raise HTTP 404
    - Trim `new_name` sebelum disimpan (`.strip()`)
    - UPDATE hanya kolom `name` dan `updated_at` — semua field lain dipertahankan tanpa sentuhan
    - Kembalikan `VoiceProfileResponse` dengan data terbaru
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 9.1, 9.2_

  - [x]* 7.2 Tulis property test untuk Property 10
    - **Property 10: Rename — Field Preservation**
    - **Validates: Requirements 6.1, 6.6**
    - Generate nama sebelum dan sesudah rename, verifikasi semua field non-`name` identik, dan `name` yang tersimpan = `trim(input)`
    - `@settings(max_examples=100)` — tag komentar: `# Feature: voice-profile-management, Property 10`
    - File: `backend/tests/unit/test_voice_profile_service.py`

- [x] 8. Service Layer: Delete Voice Profile
  - [x] 8.1 Implementasi `VoiceProfileService.delete()` di `backend/app/services/voice_profile_service.py`
    - Query fetch: `SELECT * FROM voice_profiles WHERE id = :id AND user_id = :user_id` — jika tidak ada, raise HTTP 404
    - Jika `status == 'processing'`, raise HTTP 409 dengan pesan "tidak dapat dihapus saat training sedang berlangsung"
    - Hapus file `sample_audio_path` dan `model_checkpoint_path`: `FileNotFoundError` → toleransi, lanjutkan; `OSError`/`PermissionError` → raise HTTP 500, batal hapus DB
    - DELETE `training_jobs WHERE voice_profile_id = :id` lalu DELETE `voice_profiles WHERE id = :id AND user_id = :user_id`
    - Return `None` (HTTP 204 di router)
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 9.1, 9.2_

- [x] 9. Service Layer: Training Job — Dispatch
  - [x] 9.1 Implementasi `TrainingJobService.dispatch()` di `backend/app/services/training_job_service.py`
    - Fetch voice profile: `SELECT * FROM voice_profiles WHERE id = :id AND user_id = :user_id` — jika tidak ada, raise HTTP 404
    - Jika `status != 'pending'`, raise HTTP 409 ("training hanya bisa di-trigger pada Voice Profile dengan status pending")
    - INSERT ke `training_jobs` dengan `status='queued'`, `progress_pct=0`
    - Dispatch task ke Job Queue (Celery/RQ) dengan `voice_profile_id` dan `source_type`
    - Jika dispatch gagal: DELETE record `training_jobs` yang baru dibuat, `voice_profiles.status` tetap `pending`, raise HTTP 500
    - Return `TrainingJobResponse` (`training_job_id`, `status='queued'`) untuk HTTP 202
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.9, 9.1, 9.2_

- [x] 10. Service Layer: Status Polling
  - [x] 10.1 Implementasi `VoiceProfileService.get_status()` di `backend/app/services/voice_profile_service.py`
    - Query: `SELECT vp.*, tj.* FROM voice_profiles vp LEFT JOIN training_jobs tj ON tj.voice_profile_id = vp.id WHERE vp.id = :id AND vp.user_id = :user_id`
    - Jika tidak ada, raise HTTP 404
    - Susun `VoiceProfileStatusResponse`: `id`, `status`, `error_message`, dan nested `training_job` (jika ada)
    - Invariant yang harus dipenuhi di layer service (bukan hanya di response):
      - Jika `status='processing'`: pastikan `training_job.progress_pct` ada dan dalam range [0, 100]
      - Jika `status='failed'`: `error_message` tidak null, `training_job.completed_at` null
      - Jika `status='ready'`: `training_job.completed_at` tidak null
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 9.1, 9.2_

- [x] 11. Checkpoint — Service layer selesai
  - Pastikan semua service methods bisa dipanggil dari unit tests tanpa router. Jalankan semua tests yang ada.

- [x] 12. Router Layer: Semua Endpoint Voice Profile
  - [x] 12.1 Buat router `backend/app/routers/voice_profile_router.py` dengan semua 7 endpoint
    - Semua endpoint wajib menggunakan `Depends(verify_token)` — tidak ada endpoint yang bisa diakses tanpa auth
    - `POST /api/v1/voice-profiles`: terima `name` (Form), `source_type` (Form), `sample_audio` (UploadFile); validasi 422 via Pydantic untuk `name` (max 255), `source_type` (enum), file tidak dikirim, ukuran file > 10 MB; panggil `voice_profile_service.create()`; return HTTP 201
    - `GET /api/v1/voice-profiles`: panggil `voice_profile_service.list()`; return HTTP 200
    - `GET /api/v1/voice-profiles/{id}`: panggil `voice_profile_service.get()`; return HTTP 200
    - `PATCH /api/v1/voice-profiles/{id}`: terima `VoiceProfileRenameRequest`; validasi 422 via Pydantic untuk `name` (required, max 100, non-whitespace); panggil `voice_profile_service.rename()`; return HTTP 200
    - `DELETE /api/v1/voice-profiles/{id}`: panggil `voice_profile_service.delete()`; return HTTP 204
    - `POST /api/v1/voice-profiles/{id}/train`: panggil `training_job_service.dispatch()`; return HTTP 202
    - `GET /api/v1/voice-profiles/{id}/status`: panggil `voice_profile_service.get_status()`; return HTTP 200
    - Daftarkan router ke `backend/app/main.py` dengan prefix `/api/v1`
    - _Requirements: 1.3, 1.4, 1.5, 1.7, 2.2, 2.3, 5.2, 6.2, 6.3, 6.4, 7.2, 8.1, 8.2_

  - [x]* 12.2 Tulis property test untuk Property 9
    - **Property 9: Auth Guard — HTTP 401 untuk Semua Endpoint**
    - **Validates: Requirements 8.1, 8.2**
    - Generate berbagai kombinasi token tidak valid: absent, empty string, string random, string yang hampir cocok
    - Verifikasi semua 7 endpoint selalu return 401 untuk token invalid — tidak ada yang lolos
    - `@settings(max_examples=100)` — tag komentar: `# Feature: voice-profile-management, Property 9`
    - File: `backend/tests/integration/test_voice_profile_router.py`

- [x] 13. Worker Layer: Training Worker dan Pipeline Router
  - [x] 13.1 Buat training worker di `backend/workers/training_worker.py`
    - Definisi Celery/RQ task `execute_training_job(voice_profile_id: str, source_type: str)`
    - Saat task dimulai: panggil `training_job_service.update_start()` → UPDATE `voice_profiles.status='processing'`, `training_jobs.status='processing'`, `training_jobs.started_at=now()`
    - Implementasi `select_pipeline(source_type: SourceType) -> TrainingPipeline`: `own_voice`/`other_person` → `RVCPipeline()`, `character` → `SVCPipeline()`; raise `ValueError` untuk source_type tidak dikenal
    - Eksekusi pipeline dengan progress callback yang memanggil `training_job_service.update_progress()`
    - Saat sukses: panggil `training_job_service.complete()` → UPDATE `voice_profiles.status='ready'`, `model_checkpoint_path`, `training_jobs.status='completed'`, `completed_at=now()`
    - Saat gagal: panggil `training_job_service.fail()` → UPDATE `voice_profiles.status='failed'`, `error_message` (max 500 char, ring kasan), `training_jobs.status='failed'`, `error_log` (full stack trace)
    - _Requirements: 2.6, 2.7, 2.8, 2.10_

  - [x] 13.2 Buat stub pipeline di `backend/ml/rvc/` dan `backend/ml/svc/`
    - Buat `backend/ml/rvc/__init__.py` dengan class `RVCPipeline` yang mengekspos method `train(sample_audio_path: str, checkpoint_dir: str, progress_cb: Callable) -> str` (return checkpoint path)
    - Buat `backend/ml/svc/__init__.py` dengan class `SVCPipeline` dengan interface yang sama
    - Stub cukup melempar `NotImplementedError` — implementasi ML sebenarnya ada di spec terpisah
    - _Requirements: 2.10_

  - [x] 13.3 Implementasi service methods untuk worker callbacks di `backend/app/services/training_job_service.py`
    - `update_start(training_job_id, voice_profile_id, db)`: UPDATE kedua tabel ke status `processing`, set `started_at`
    - `update_progress(training_job_id, progress_pct, db)`: UPDATE `training_jobs.progress_pct` — validasi 0 ≤ pct ≤ 100
    - `complete(training_job_id, voice_profile_id, checkpoint_path, db)`: UPDATE status `ready`/`completed`, set `model_checkpoint_path`, `completed_at`
    - `fail(training_job_id, voice_profile_id, error_summary, error_log, db)`: UPDATE status `failed`, set `error_message` (truncate ke 500 char), `error_log`
    - _Requirements: 2.6, 2.7, 2.8_

  - [x]* 13.4 Tulis property test untuk Property 4 dan Property 5
    - **Property 4: Pipeline Routing Berdasarkan source_type**
    - **Validates: Requirements 2.10**
    - **Property 5: Training Job Lifecycle — State Transitions**
    - **Validates: Requirements 2.6, 2.7, 2.8**
    - Property 4: generate semua nilai `source_type` valid, verifikasi pipeline yang dipilih selalu konsisten — RVC untuk `own_voice`/`other_person`, SVC untuk `character`
    - Property 5: mock pipeline, verifikasi semua state transitions terjadi berurutan dan konsisten: `processing` → `ready`/`failed` dengan field yang benar
    - `@settings(max_examples=100)` — tag komentar: `# Feature: voice-profile-management, Property 4 & 5`
    - File: `backend/tests/unit/test_pipeline_router.py` (P4) dan `backend/tests/integration/test_training_worker.py` (P5)

- [x] 14. Property-Based Tests: Status Polling Invariants
  - [x]* 14.1 Tulis property test untuk Property 6
    - **Property 6: Status Polling — Invariant Field Berdasarkan Status**
    - **Validates: Requirements 3.1, 3.4, 3.5, 3.6**
    - Generate voice profiles dalam berbagai state (`processing`, `failed`, `ready`), panggil `GET /status`, verifikasi invariant field setiap state terpenuhi
    - Untuk `processing`: `progress_pct` ada dan 0–100; untuk `failed`: `error_message` != null, `completed_at` null; untuk `ready`: `completed_at` != null
    - `@settings(max_examples=100)` — tag komentar: `# Feature: voice-profile-management, Property 6`
    - File: `backend/tests/integration/test_voice_profile_router.py`

- [x] 15. Test Infrastructure: conftest.py
  - [x] 15.1 Buat `backend/tests/conftest.py` dengan fixtures utama
    - `test_db`: in-memory SQLite atau test PostgreSQL database dengan schema lengkap
    - `mock_storage`: mock untuk `SONANCE_SAMPLE_AUDIO_DIR` dan `SONANCE_CHECKPOINT_DIR` menggunakan `tmp_path`
    - `mock_queue`: mock untuk Celery/RQ dispatch — capture task yang di-enqueue tanpa eksekusi
    - `test_client`: FastAPI `TestClient` dengan dependency override untuk `verify_token` (valid token) dan `get_db`
    - `other_user_client`: `TestClient` dengan `user_id` berbeda untuk test isolasi ownership
    - `sample_opus_factory`: factory function yang menghasilkan bytes Opus valid dengan durasi yang bisa dikontrol
    - _Requirements: semua requirements (fixture dasar untuk seluruh test suite)_

- [x] 16. Checkpoint Final — Semua tests pass
  - Jalankan `pytest backend/tests/ -v` dan pastikan semua tests lulus
  - Pastikan tidak ada orphan file di mock storage setelah test selesai
  - Tanyakan kepada user jika ada pertanyaan sebelum lanjut ke langkah selanjutnya.

---

## Notes

- Task bertanda `*` adalah opsional dan bisa di-skip untuk MVP yang lebih cepat
- Setiap task yang menyentuh data user sudah menyertakan filter `WHERE user_id = :user_id` sebagai acceptance criteria bawaan — Requirement 9 (isolasi ownership) adalah cross-cutting concern, bukan ticket terpisah
- Auth guard (`verify_token` via `Depends()`) adalah hard dependency untuk semua router task (Task 12.1) — implementasinya ada di Task 3.1
- 10 Correctness Properties dikelompokkan menjadi 5 property test tasks berdasarkan kedekatan concern:
  - P1+P2 → Task 5.2 (create + name validation)
  - P3 → Task 5.3 (duration validation)
  - P4+P5 → Task 13.4 (pipeline routing + lifecycle)
  - P6 → Task 14.1 (status polling invariants)
  - P7+P8 → Task 6.3 (list isolation + ownership 404)
  - P9 → Task 12.2 (auth guard semua endpoint)
  - P10 → Task 7.2 (rename field preservation)
- Bahasa implementasi: **Python** (sesuai stack FastAPI di `backend/`)
- Library property-based testing: **Hypothesis** (`@given`, `@settings`, `st.*`)

---

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3"] },
    { "id": 2, "tasks": ["2.1", "3.1"] },
    { "id": 3, "tasks": ["15.1"] },
    { "id": 4, "tasks": ["5.1", "6.1", "6.2", "7.1", "8.1", "9.1", "10.1"] },
    { "id": 5, "tasks": ["5.2", "5.3", "6.3", "7.2"] },
    { "id": 6, "tasks": ["12.1", "13.3"] },
    { "id": 7, "tasks": ["13.1", "13.2"] },
    { "id": 8, "tasks": ["12.2", "13.4", "14.1"] }
  ]
}
```
