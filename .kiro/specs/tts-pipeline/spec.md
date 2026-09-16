# Specification: TTS Pipeline (Offline Voice Cloning)

## Problem Statement

Pengguna yang telah berhasil membuat dan melatih Voice Profile (status `ready`) membutuhkan kemampuan untuk menghasilkan ucapan audio baru dari teks menggunakan karakter suara tersebut (offline voice cloning / speech synthesis). 

Saat ini, pengguna tidak memiliki cara untuk:
1. Mengirim teks input dan memilih profil suara yang sudah dilatih untuk disintesis.
2. Mengonfigurasi parameter generasi audio seperti bahasa, kecepatan bicara, pergeseran nada, dan variasi ekspresi.
3. Memantau progres pemrosesan sintesis audio asinkron yang berjalan di antrian latar belakang.
4. Mengunduh atau mengalirkan (streaming) file audio hasil sintesis dalam format terkompresi berkualitas tinggi (Opus).

Selain itu, karena sistem dirancang untuk berjalan pada komputer lokal dengan GPU tunggal, pemrosesan batch TTS berisiko merebut resource VRAM atau mengganggu performa latensi jika dijalankan bersamaan dengan sesi real-time voice changer. Oleh karena itu, diperlukan sistem koordinasi resource yang mampu menunda eksekusi TTS secara otomatis saat sesi real-time sedang aktif, namun tetap memberikan batas waktu tunggu yang pasti (timeout 30 menit) agar job tidak terkatung-katung tanpa kejelasan.

---

## Solution

Membangun subsistem backend **TTS Pipeline** yang menyediakan REST API asinkron, antrian pemrosesan latar belakang, kontrol alokasi GPU dengan batas waktu tunggu, dan abstraksi model akustik:

1. **Endpoint `POST /api/v1/tts/generate`**:
   - Menerima teks input (maksimum 1000 karakter), ID profil suara target, dan parameter konfigurasi opsional (`settings`).
   - Memvalidasi bahwa Voice Profile berstatus `ready` dan merupakan milik user terautentikasi.
   - Membuat entitas database `tts_jobs` dengan status `queued`.
   - Men-dispatch job ke antrian pesan (`RQQueueAdapter` / `InMemoryQueue`).
   - Mengembalikan HTTP 202 Accepted beserta ID job.

2. **Endpoint `GET /api/v1/tts/jobs/{job_id}`**:
   - Mengambil status terkini dari job TTS (`queued`, `processing`, `completed`, `failed`).
   - Menyertakan metadata waktu pembuatan, waktu mulai, waktu selesai, parameter konfigurasi, dan ringkasan error jika terjadi kegagalan.

3. **Endpoint `GET /api/v1/tts/jobs/{job_id}/audio`**:
   - Mengalirkan (streaming) atau mengunduh file audio hasil sintesis berformat Opus (`audio/ogg`) dengan header `Content-Disposition`.
   - Menolak permintaan dengan HTTP 409 Conflict jika job belum selesai atau mengalami kegagalan.

4. **Resource Lock, Prioritization, dan Wait Timeout**:
   - Menyediakan interface kontrol konkurensi GPU (`GPUResourceManager` / flag lock).
   - Worker TTS memeriksa status lock sebelum dan selama eksekusi; jika sesi real-time voice changer aktif, job TTS otomatis dijeda (pause/wait).
   - Menyimpan `gpu_wait_started_at` saat pertama kali mendeteksi GPU terkunci.
   - Menerapkan batas waktu tunggu maksimum 30 menit (1800 detik). Jika sesi real-time belum berakhir setelah 30 menit, job dibatalkan dan ditandai `failed` dengan pesan penjelasan eksplisit (tanpa auto-retry).

5. **Abstraksi Pipeline Akustik**:
   - Mendefinisikan interface abstrak `TTSPipeline(ABC)` yang seragam dengan `TrainingPipeline`.
   - Menyediakan stub `XTTSPipeline` yang mensimulasikan sintesis audio Opus untuk pengujian tanpa ketergantungan pada runtime GPU/model AI sesungguhnya.

---

## User Stories

1. As an authenticated user, I want to submit text and select a ready voice profile via `POST /api/v1/tts/generate`, so that I can synthesize speech in that voice.
2. As an authenticated user, I want to receive HTTP 202 Accepted with a unique `job_id` and initial status `queued`, so that I know my request has entered the background processing queue.
3. As an authenticated user, I want to customize synthesis parameters (language, speed, pitch shift, temperature), so that I can tailor the synthesized voice output to my needs.
4. As an authenticated user, I want default settings applied automatically when I omit the `settings` object, so that I do not need to specify technical parameters for every generation.
5. As an authenticated user, I want to be rejected with HTTP 404 when I reference a non-existent `voice_profile_id`, so that I am informed the target profile does not exist.
6. As an authenticated user, I want to be rejected with HTTP 404 when I reference a voice profile owned by another user, so that my account and other accounts remain strictly isolated.
7. As an authenticated user, I want to be rejected with HTTP 409 Conflict when I reference a voice profile that is still `pending`, `processing`, or `failed`, so that I only attempt synthesis using ready models.
8. As an authenticated user, I want to be rejected with HTTP 422 when I submit empty text or text containing only whitespace, so that empty audio generation jobs are prevented.
9. As an authenticated user, I want to be rejected with HTTP 422 when I submit text longer than 1000 characters, so that processing time stays bounded and GPU memory is protected.
10. As an authenticated user, I want to be rejected with HTTP 422 when I submit an unsupported language code outside `["id", "en"]`, so that the system only attempts supported acoustic models.
11. As an authenticated user, I want to be rejected with HTTP 422 when `speed` is outside the valid range [0.5, 2.0], so that speech output remains intelligible.
12. As an authenticated user, I want to be rejected with HTTP 422 when `pitch_shift` is outside the semitone range [-12, 12], so that unnatural audio distortions are avoided.
13. As an authenticated user, I want to be rejected with HTTP 422 when `temperature` is outside the range [0.1, 1.0], so that sampling randomness remains within stable limits.
14. As an authenticated user, I want to be rejected with HTTP 422 when `output_format` is anything other than `opus`, so that storage and streaming format constraints are strictly enforced in version 1.
15. As an authenticated user, I want to query `GET /api/v1/tts/jobs/{job_id}`, so that I can track whether my generation is queued, processing, completed, or failed.
16. As an authenticated user, I want to be rejected with HTTP 404 when querying a job that does not exist or belongs to another user, so that job ownership is strictly preserved.
17. As an authenticated user, I want to see `completed_at` populated and `error_message` as null when a job succeeds, so that the status response is clean and unambiguous.
18. As an authenticated user, I want to see a clear `error_message` when a job fails, so that I understand why the synthesis process could not be completed.
19. As an authenticated user, I want to download or stream the generated Opus audio via `GET /api/v1/tts/jobs/{job_id}/audio`, so that I can listen to or save the synthesized speech.
20. As an authenticated user, I want to receive HTTP 409 Conflict when requesting the audio of a job whose status is `queued` or `processing`, so that I am notified the audio is not yet available.
21. As an authenticated user, I want to receive HTTP 409 Conflict when requesting the audio of a job whose status is `failed`, so that I am informed no audio was produced.
22. As an unauthenticated client, I want all TTS endpoints to return HTTP 401 Unauthorized when a token is missing, invalid, or malformed, so that the API is fully guarded.
23. As a local developer or desktop user, I want the TTS worker to pause automatically whenever a real-time voice changer session begins, so that real-time voice conversion latency is never degraded by background TTS processing.
24. As a local developer or desktop user, I want the paused TTS worker to resume processing automatically as soon as the real-time voice changer session ends, so that background jobs finish without manual intervention.
25. As an authenticated user, I want a TTS job that has been paused waiting for the GPU lock for more than 30 minutes to transition to failed status with a clear cancellation message, so that jobs do not hang indefinitely when real-time sessions run long.

---

## Implementation Decisions

### 1. Database Schema & Migration
- **Migration File**: `backend/alembic/versions/0002_create_tts_jobs.py`
- **Table `tts_jobs`**:
  ```sql
  CREATE TABLE tts_jobs (
      id UUID PRIMARY KEY,
      user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
      voice_profile_id UUID NOT NULL REFERENCES voice_profiles(id) ON DELETE CASCADE,
      input_text TEXT NOT NULL,
      status VARCHAR(20) NOT NULL DEFAULT 'queued'
          CHECK (status IN ('queued', 'processing', 'completed', 'failed')),
      output_audio_path VARCHAR(500) NULL,
      settings JSON NOT NULL,
      error_message TEXT NULL,
      created_at TIMESTAMP WITH TIME ZONE NOT NULL,
      started_at TIMESTAMP WITH TIME ZONE NULL,
      completed_at TIMESTAMP WITH TIME ZONE NULL,
      gpu_wait_started_at TIMESTAMP WITH TIME ZONE NULL
  );

  CREATE INDEX idx_tts_jobs_user_created ON tts_jobs (user_id, created_at DESC);
  CREATE INDEX idx_tts_jobs_status ON tts_jobs (status);
  ```
- **ORM Model**: `backend/app/models/tts_job_model.py` (`TTSJob`) menggunakan SQLAlchemy 2.x `Mapped[]` annotation style dengan relasi ke `User` dan `VoiceProfile`.

### 2. Pydantic Schemas (`backend/app/schemas/tts_job_schema.py`)
- **`TTSSettings`**:
  - `language`: `Literal["id", "en"] = "id"`
  - `speed`: `float = Field(default=1.0, ge=0.5, le=2.0)`
  - `pitch_shift`: `int = Field(default=0, ge=-12, le=12)`
  - `temperature`: `float = Field(default=0.7, ge=0.1, le=1.0)`
  - `output_format`: `Literal["opus"] = "opus"`
- **`TTSGenerateRequest`**:
  - `voice_profile_id`: `uuid.UUID`
  - `text`: `str = Field(..., min_length=1, max_length=1000)` dengan validator trimming whitespace.
  - `settings`: `Optional[TTSSettings] = Field(default_factory=TTSSettings)`
- **`TTSJobResponse`** (untuk HTTP 202):
  - `job_id`: `uuid.UUID`
  - `status`: `Literal["queued"]`
- **`TTSJobStatusResponse`** (untuk HTTP 200 `GET /jobs/{id}`):
  - `id`: `uuid.UUID`
  - `voice_profile_id`: `uuid.UUID`
  - `status`: `Literal["queued", "processing", "completed", "failed"]`
  - `input_text`: `str`
  - `settings`: `TTSSettings`
  - `error_message`: `Optional[str]`
  - `created_at`: `datetime`
  - `started_at`: `Optional[datetime]`
  - `completed_at`: `Optional[datetime]`
  - Field `output_audio_path` sengaja tidak di-expose demi keamanan.

### 3. Service Layer (`backend/app/services/tts_job_service.py`)
- **`dispatch(user_id, request_data, db, queue) -> TTSJobResponse`**:
  1. Validasi Voice Profile: `SELECT * FROM voice_profiles WHERE id = :vp_id AND user_id = :user_id`. Jika tidak ditemukan, raise HTTP 404.
  2. Validasi Status: Jika `vp.status != 'ready'`, raise HTTP 409 Conflict dengan detail: `"Voice profile belum siap digunakan untuk TTS. Status saat ini: {vp.status}."`
  3. Simpan record `tts_jobs` baru (`status='queued'`).
  4. Enqueue task ke worker queue: `queue.enqueue("execute_tts_job", tts_job_id=str(job.id))`.
  5. Rollback guarantee: Jika enqueue gagal, hapus record `tts_jobs` dan raise HTTP 500.
- **`get_status(job_id, user_id, db) -> TTSJobStatusResponse`**:
  1. Ambil record: `SELECT * FROM tts_jobs WHERE id = :job_id AND user_id = :user_id`.
  2. Jika tidak ditemukan, raise HTTP 404.
  3. Jaga invariant: `error_message` bernilai `None` jika status bukan `failed`.
- **`get_audio_path(job_id, user_id, db) -> str`**:
  1. Ambil record: `SELECT * FROM tts_jobs WHERE id = :job_id AND user_id = :user_id`.
  2. Jika tidak ditemukan, raise HTTP 404.
  3. Jika `status in ('queued', 'processing')`, raise HTTP 409 Conflict ("Audio belum selesai diproses").
  4. Jika `status == 'failed'`, raise HTTP 409 Conflict ("Job TTS gagal dan tidak menghasilkan file audio").
  5. Jika `status == 'completed'`: verifikasi keberadaan file fisik di storage. Jika file hilang, raise HTTP 500. Kembalikan path file.
- **Callbacks & State Mutators Worker**:
  - `record_gpu_wait_start(job_id, db)`: Jika `gpu_wait_started_at` masih NULL, set `gpu_wait_started_at = now()`.
  - `update_start(job_id, db)`: Validasi status saat ini adalah `queued`, ubah status menjadi `processing`, set `started_at = now()`.
  - `complete(job_id, output_path, db)`: Validasi status `processing`, ubah status menjadi `completed`, set `output_audio_path = output_path`, `completed_at = now()`.
  - `fail(job_id, error_summary, db)`: Ubah status menjadi `failed`, set `error_message = error_summary[:500]`, `completed_at = now()`.
  - `fail_due_to_gpu_timeout(job_id, db)`: Ubah status menjadi `failed`, set `error_message = "Job dibatalkan setelah menunggu GPU selama 30 menit karena sesi real-time voice changer masih aktif. Silakan coba lagi nanti."`, `completed_at = now()`.

### 4. Router Layer (`backend/app/routers/tts_router.py`)
- Semua endpoint dilindungi oleh `Depends(verify_token)`.
- `POST /api/v1/tts/generate`: panggil `tts_job_service.dispatch()`, return status 202 Accepted.
- `GET /api/v1/tts/jobs/{job_id}`: panggil `tts_job_service.get_status()`, return status 200 OK.
- `GET /api/v1/tts/jobs/{job_id}/audio`: panggil `tts_job_service.get_audio_path()`, return `FileResponse(path, media_type="audio/ogg", filename=f"tts_{job_id}.opus")`.

### 5. Worker, GPU Lock Timeout, & Pipeline Stub
- **Queue Name**: Menggunakan antrian `tts` (fallback: `training`).
- **Interface Pipeline**: `backend/ml/base.py` menambahkan class `TTSPipeline(ABC)`:
  ```python
  class TTSPipeline(ABC):
      @abstractmethod
      def synthesize(
          self,
          text: str,
          voice_profile_checkpoint: str,
          settings: dict,
          output_path: str,
      ) -> str:
          pass
  ```
- **Stub `XTTSPipeline` (`backend/ml/xtts/__init__.py`)**:
  - Mensimulasikan delay sintesis (0.1 detik).
  - Menghasilkan file output dummy berformat Opus.
  - Mendukung simulasi error via parameter / environment variable `SONANCE_SIMULATE_TTS_FAILURE`.
- **GPU Resource Coordinator (`backend/app/core/gpu_manager.py`)**:
  - Class sederhana `GPUResourceManager` dengan method:
    - `is_locked() -> bool`
    - `acquire_lock(session_id: str)`
    - `release_lock()`
- **Logika Eksekusi Worker TTS (`backend/workers/tts_worker.py`)**:
  1. Worker mengambil job `tts_job_id`.
  2. Pengecekan GPU Lock Loop:
     - Jika `gpu_manager.is_locked()` bernilai True:
       - Panggil `tts_job_service.record_gpu_wait_start(job_id)`.
       - Hitung durasi tunggu: `elapsed = now() - job.gpu_wait_started_at`.
       - Jika `elapsed >= 1800` (30 menit):
         - Panggil `tts_job_service.fail_due_to_gpu_timeout(job_id)`.
         - Keluar dari eksekusi tanpa auto-retry.
       - Jika `elapsed < 1800`:
         - Tidur sejenak (polling backoff, misal 0.5 - 1 detik) lalu ulangi pengecekan.
  3. Setelah lock bebas (atau tidak terkunci):
     - Panggil `tts_job_service.update_start(job_id)`.
     - Jalankan `pipeline.synthesize(...)`.
     - Jika sukses: panggil `tts_job_service.complete(job_id, output_path)`.
     - Jika exception: panggil `tts_job_service.fail(job_id, error_summary)`.

---

## Testing Decisions

### 1. Seams Pengujian
- **Primary Seam (HTTP Integration)**: FastAPI `TestClient` memanggil endpoint `/api/v1/tts/generate`, `/api/v1/tts/jobs/{job_id}`, dan `/api/v1/tts/jobs/{job_id}/audio` dengan header auth token valid dan database in-memory.
- **Service Layer Seam (Unit)**: Pemanggilan langsung `TTSJobService` untuk menguji edge case bisnis, rollback guarantee saat queue gagal, dan ownership isolation.
- **Worker & Timeout Seam (Lifecycle Integration)**: Pemanggilan `execute_tts_job` bersama stub `XTTSPipeline` dan mock `GPUResourceManager` untuk memverifikasi:
  - Transisi state sukses dan gagal.
  - Penundaan job saat GPU terkunci dan kelanjutan proses saat lock dilepas.
  - **GPU Lock Timeout Verification**: Verifikasi bahwa job yang mendeteksi lock aktif selama > 30 menit (disimulasikan melalui mock clock atau manipulasi `gpu_wait_started_at`) otomatis dibatalkan menjadi `failed` dengan pesan yang persis sesuai spesifikasi, dan tidak menunggu tanpa batas.
- **Property-Based Testing (Hypothesis)**:
  - Validasi variasi teks (panjang 0-1000 karakter, whitespace, unicode).
  - Validasi variasi settings numerik (speed di dalam vs di luar range, pitch shift, temperature).
  - Invariant status response polling (error_message null saat non-failed, dsb).
  - Auth Guard 401 pada ketiga endpoint TTS.

### 2. Kriteria Pengujian Berkualitas
- Pengujian menguji perilaku eksternal (status code, payload JSON, header, integritas file audio) dan bukan implementasi internal.
- Menggunakan fixture isolasi database dengan transaksi rollback otomatis (SAVEPOINT) agar tidak ada state yang bocor antar test.
- Berjalan sangat cepat (< 3 detik untuk seluruh test suite TTS) tanpa membutuhkan live Redis broker atau GPU hardware.

---

## Out of Scope

1. **Implementasi Model AI Sesungguhnya**: Pengunduhan bobot XTTS-v2, mel-spectrogram vocoder HiFi-GAN, dan inferensi GPU riil berada di luar cakupan spec ini (diwakili oleh stub `XTTSPipeline`).
2. **WebSocket Real-time Voice Changer**: Penanganan audio streaming dua arah lewat WebSocket akan diatur dalam spesifikasi terpisah setelah TTS Pipeline selesai.
3. **Format Audio Selain Opus**: Konversi WAV, MP3, atau FLAC tidak didukung pada v1 (dikunci ke Opus sesuai ADR-007 / PRD).
4. **Multi-User Permission & Sharing**: Fitur berbagi Voice Profile atau TTS job antar pengguna tidak didukung (single-user / isolated ownership).
5. **Pagination Riwayat Job TTS**: Endpoint list semua riwayat job TTS belum dibutuhkan di v1; hanya pengambilan detail status per `job_id`.

---

## Further Notes

- Konvensi penamaan mengikuti `CONTEXT.md`: snake_case untuk tabel (`tts_jobs`), snake_case untuk file router (`tts_router.py`), Pydantic schema (`tts_job_schema.py`), service (`tts_job_service.py`).
- Penyimpanan audio hasil sintesis menggunakan direktori konfigurasi `SONANCE_OUTPUT_AUDIO_DIR` yang aman dan terisolasi per folder user ID.
