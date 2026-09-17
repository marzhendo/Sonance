# Tasks: Real-time Voice Changer (WebSocket)

## Overview

Implementasi fitur Real-time Voice Changer (WebSocket) mengikuti pola dependency berjenjang (Wave 0 hingga Wave 8) yang konsisten dengan Voice Profile Management dan TTS Pipeline: DB migration -> ORM model -> Pydantic schemas & message protocols -> ML pipeline abstraction & stub -> Partisipasi aktif simetris GPU lock pada TTS worker -> Session manager & service layer -> WebSocket router endpoints -> Property-based testing -> Checkpoint final.

Setiap task didesain sebagai tracer-bullet slice yang dapat diuji secara mandiri dengan TDD tanpa ketergantungan pada hardware GPU nyata.

---

## Tasks

### Wave 0: Database Migration
- [x] 1. Migration SQL untuk tabel `vc_sessions`
  - [x] 1.1 Buat Alembic migration `backend/alembic/versions/0003_create_vc_sessions.py`
    - Kolom: `id` (UUID PK), `user_id` (UUID FK -> `users.id` RESTRICT), `voice_profile_id` (UUID FK -> `voice_profiles.id` CASCADE), `started_at` (TIMESTAMP WITH TIME ZONE NOT NULL), `ended_at` (TIMESTAMP WITH TIME ZONE NULL), `avg_latency_ms` (FLOAT NULL), `settings` (JSON NOT NULL).
    - Indexes: `idx_vc_sessions_user_started ON vc_sessions(user_id, started_at DESC)`, `idx_vc_sessions_voice_profile_id ON vc_sessions(voice_profile_id)`.
    - _Blocked by: None (can start immediately)_

### Wave 1: ORM Model
- [x] 2. ORM Model `VCSession`
  - [x] 2.1 Buat ORM model `VCSession` di `backend/app/models/vc_session_model.py`
    - SQLAlchemy 2.x `Mapped[]` annotation style.
    - Relasi: `user` (Many-to-One ke `User`), `voice_profile` (Many-to-One ke `VoiceProfile`).
    - Relasi balik: `User.vc_sessions` (1-to-N, RESTRICT) dan `VoiceProfile.vc_sessions` (1-to-N, CASCADE).
    - Daftarkan model di `backend/alembic/env.py`.
    - Unit tests model di `backend/tests/unit/test_vc_session_model.py`.
    - _Blocked by: Task 1_

### Wave 2: Pydantic Schemas & Message Protocol
- [x] 3. Pydantic Schemas untuk Protokol WebSocket Voice Changer
  - [x] 3.1 Buat schemas di `backend/app/schemas/vc_session_schema.py`
    - `VCSettings`: `pitch_shift` int [-12, 12] (default 0), `sample_rate` whitelist [16000, 24000, 44100, 48000] (default 16000), `chunk_duration_ms` int [10, 100] (default 30).
    - `VCSettingsUpdate`: schema pembaruan pengaturan parsial (semua field opsional dengan validator yang sama).
    - Client messages: `VCInitSessionMessage`, `VCUpdateSettingsMessage`, `VCCloseSessionMessage`.
    - Server messages: `VCSessionReadyMessage`, `VCMetricsMessage`, `VCErrorMessage`.
    - `VCSessionResponse`: representasi status sesi DB.
    - Unit tests di `backend/tests/unit/test_vc_session_schema.py`.
    - _Blocked by: Task 2_

### Wave 3: ML Pipeline Abstraction & Stub
- [x] 4. Interface Pipeline dan Stub `RVCRealtimePipeline`
  - [x] 4.1 Tambahkan interface `VoiceConversionPipeline(ABC)` di `backend/ml/base.py`
    - Abstract methods: `load_model(checkpoint_path)`, `unload_model()`, `is_loaded() -> bool`, `convert_chunk(pcm_data, settings) -> bytes`.
  - [x] 4.2 Buat stub `RVCRealtimePipeline` di `backend/ml/rvc/__init__.py`
    - Implementasi konkret stub: simulasi delay cold-start on-demand, simulasi inferensi chunk, simulasi error via constructor flag `simulate_failure` dan env var `SONANCE_SIMULATE_VC_FAILURE`.
    - Unit tests di `backend/tests/unit/test_vc_pipeline.py`.
    - _Blocked by: None_

### Wave 4: Partisipasi Aktif Simetris GPU Lock pada TTS Worker
- [x] 5. Integrasi Symmetrical GPU Lock pada `tts_worker.py`
  - [x] 5.1 Perbarui `backend/workers/tts_worker.py` (`execute_tts_job`)
    - Panggil `gpu_manager.acquire_lock(session_id=f"tts-{tts_job_id}")` segera sebelum memanggil `pipeline.synthesize()`.
    - Panggil `gpu_manager.release_lock(session_id=f"tts-{tts_job_id}")` di dalam blok `try/finally` untuk memastikan lock selalu dilepas baik saat sukses maupun gagal.
    - Unit dan integration tests di `backend/tests/integration/test_tts_worker.py` (verifikasi lock aktif saat sintesis dan lock bebas setelah selesai).
    - _Blocked by: None_

### Wave 5: Session Manager & Service Layer
- [x] 6. Implementasi `VCSessionManager`
  - [x] 6.1 Buat service di `backend/app/services/vc_session_manager.py`
    - In-memory session tracking (`ActiveSessionState`) dengan state machine: `IDLE`, `LOADING`, `ACTIVE`, `GRACE_PERIOD`, `ENDED`.
    - `create_session(user_id, voice_profile_id, settings, websocket, db)`: validasi profil (ada, milik user, status ready), acquire GPU lock via `gpu_manager.acquire_lock(session_id)`. Jika gagal, lemparkan error `GPU_BUSY` ("GPU sedang memproses TTS job, coba lagi sesaat lagi") tanpa retry server-side. Load model on-demand, simpan record `vc_sessions`.
    - `process_audio_chunk(session_id, chunk_bytes) -> tuple[bytes, dict]`: jalankan `convert_chunk`, hitung processing dan total latency, kumpulkan sampel untuk `avg_latency_ms`.
    - `update_settings(session_id, new_settings, db)`: update settings aktif di memori dan kolom `settings` di DB.
    - `handle_disconnect(session_id, db)`: transisi ke `GRACE_PERIOD`, jalankan timer 10 detik. Audio masuk saat terputus langsung di-drop. Jika timeout 10 detik tercapai tanpa reconnect: panggil terminasi dengan `ended_at = now()`, release GPU lock, unload model.
    - `reconnect_session(session_id, user_id, websocket) -> bool`: jika dalam grace period, batalkan timer, pasangkan websocket baru, ubah state ke `ACTIVE`.
    - `close_session(session_id, db)`: terminasi bersih, release GPU lock, unload model, update `ended_at` dan `avg_latency_ms` di DB.
    - Unit tests di `backend/tests/unit/test_vc_session_manager.py`.
    - _Blocked by: Task 1, Task 2, Task 3, Task 4, Task 5_

### Wave 6: WebSocket Router Layer & End-to-End Integration
- [x] 7. WebSocket Endpoint `/ws/voice-changer`
  - [x] 7.1 Buat router `backend/app/routers/vc_router.py` dan daftarkan di `backend/app/main.py`
    - Autentikasi query param `?token=...`: validasi constant-time dengan `SONANCE_API_TOKEN`. Jika invalid/missing, tutup soket dengan WS code 1008.
    - Handler message loop: dispatch frame JSON (`init_session`, `update_settings`, `close_session`) dan frame biner PCM.
    - Kirim kembali binary PCM hasil konversi diikuti pesan teks `metrics`.
    - Tangani `WebSocketDisconnect` dengan memicu grace period di session manager.
  - [x] 7.2 Integration tests di `backend/tests/integration/test_vc_router.py`
    - Handshake valid, `init_session`, penerimaan `session_ready`, transmisi streaming binary PCM, penerimaan metrics, `close_session` bersih.
    - Auth guard: penolakan token invalid/missing dengan WS code 1008.
    - Rejection profil suara tidak ready (error `PROFILE_NOT_READY`) atau profil tidak ditemukan (error `PROFILE_NOT_FOUND`).
    - **Symmetric GPU Lock Contention**:
      - TTS job sedang berjalan (`processing`, lock ter-acquire) menyebabkan `init_session` real-time GAGAL dengan `GPU_BUSY` ("GPU sedang memproses TTS job, coba lagi sesaat lagi").
      - Begitu TTS job selesai (lock ter-release), percobaan `init_session` berikutnya BERHASIL.
      - Sesi real-time aktif menyebabkan inisialisasi sesi real-time kedua ditolak dengan `GPU_BUSY`.
    - **Grace Period & Reconnect**:
      - Soket putus -> grace period 10 detik aktif, GPU lock tetap dipegang.
      - Reconnect < 10 detik berhasil (`session_ready` dengan `reconnected: true`) tanpa reload model.
      - Audio dikirim saat putus di-drop (tidak di-buffer).
      - Grace period expired (> 10s) melepaskan GPU lock, model di-unload, dan `ended_at` terisi waktu expired.
    - _Blocked by: Task 6_

### Wave 7: Property-Based Testing
- [x] 8. Property-Based Testing dengan Hypothesis untuk Voice Changer
  - [x] 8.1 Buat property tests di `backend/tests/integration/test_vc_properties.py`
    - **Property 1**: Validasi Settings (pitch shift [-12, 12] valid vs invalid, sample rate whitelist valid vs invalid, chunk duration [10, 100]).
    - **Property 2**: Invariant Ukuran Frame Audio PCM (untuk semua kombinasi valid `sample_rate` dan `chunk_duration_ms`, ukuran byte frame sama persis dengan `sample_rate * (chunk_duration_ms / 1000) * 2`).
    - **Property 3**: Rejection Voice Profile Not Ready (profil status non-ready selalu memicu error `PROFILE_NOT_READY`).
    - **Property 4**: Auth Rejection Invariant (semua string token acak/invalid selalu menghasilkan penutupan WS 1008).
    - **Property 5**: State Machine Invariants (frame biner sebelum `init_session` ditolak/diabaikan; update settings sebelum inisialisasi ditolak).
    - _Blocked by: Task 7_

### Wave 8: Checkpoint Final
- [x] 9. Checkpoint Final Real-time Voice Changer
  - [x] 9.1 Jalankan full test suite (`pytest backend/tests/ -v`) dan pastikan 100% lulus (Voice Profile + TTS Pipeline + Real-time Voice Changer) tanpa regresi.
  - [x] 9.2 Verifikasi rantai migrasi Alembic (0000 -> 0001 -> 0002 -> 0003) berjalan lancar pada upgrade dan downgrade.
  - [x] 9.3 Verifikasi kepatuhan terhadap aturan antislop, tidak ada em dash, dan konvensi penamaan seragam.
  - _Blocked by: Task 8_

---

## Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["3.1"] },
    { "id": 3, "tasks": ["4.1", "4.2"] },
    { "id": 4, "tasks": ["5.1"] },
    { "id": 5, "tasks": ["6.1"] },
    { "id": 6, "tasks": ["7.1", "7.2"] },
    { "id": 7, "tasks": ["8.1"] },
    { "id": 8, "tasks": ["9.1", "9.2", "9.3"] }
  ]
}
```
