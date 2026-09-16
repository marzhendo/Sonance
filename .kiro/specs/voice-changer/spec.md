# Specification: Real-time Voice Changer (WebSocket)

## Problem Statement

Setelah pengguna berhasil melatih Voice Profile hingga berstatus `ready`, pengguna membutuhkan kemampuan untuk mengubah karakter suara mereka secara langsung saat berbicara (streaming real-time voice conversion) untuk keperluan panggilan suara, live streaming, gaming, atau rekaman interaktif.

Saat ini, sistem Sonance baru mendukung sintesis offline (TTS Pipeline) dan belum memiliki infrastruktur untuk:
1. Menjalankan komunikasi audio dua arah berlatensi rendah (target end-to-end latency < 300ms) melalui protokol WebSocket streaming.
2. Mengirim dan menerima potongan audio mentah (raw PCM chunks) tanpa overhead kompresi atau encoding base64.
3. Mengontrol inisialisasi sesi real-time, konfigurasi dinamis (pitch shift, sample rate, chunk duration), serta penerimaan metrik performa latensi secara real-time.
4. Menangani gangguan jaringan sementara melalui mekanisme pemulihan koneksi (reconnection) dengan grace period 10 detik tanpa memutus model atau melepaskan resource GPU secara prematur.
5. Bertindak sebagai pemilik utama (primary lock holder) dari koordinasi GPU tunggal (`GPUResourceManager`) sehingga proses batch latar belakang (TTS) otomatis mengalah dan dijeda selama sesi real-time berlangsung.
6. Memuat model RVC ke dalam VRAM secara on-demand saat sesi dimulai dan membongkarnya kembali setelah sesi berakhir demi efisiensi memori GPU lokal.
7. Mencatat dan melacak riwayat sesi voice changer di database (`vc_sessions`) untuk audit durasi dan metrik performa latensi rata-rata.

---

## Solution

Membangun subsistem **Real-time Voice Changer** berbasis WebSocket di backend FastAPI yang mencakup:

1. **Endpoint WebSocket `wss://.../ws/voice-changer?token={api_token}`**:
   - Autentikasi koneksi awal via query parameter `?token=...` yang memvalidasi token terhadap `SONANCE_API_TOKEN` (menggunakan constant-time comparison).
   - Penolakan koneksi tidak valid dengan WebSocket close code `1008 Policy Violation`.

2. **Protokol Komunikasi Hibrida (Text & Binary Frames)**:
   - **Binary Frame**: Digunakan khusus untuk transmisi potongan audio raw PCM (16-bit signed integer, mono, default 16000 Hz, durasi 20-40ms). Tidak menggunakan base64 JSON demi memangkas overhead data sebesar ~33% dan mengurangi latensi CPU.
   - **Text Frame (JSON)**: Digunakan untuk kontrol signaling, negosiasi parameter sesi, sinkronisasi state, pelaporan metrik latensi, dan error handling.

3. **Mekanisme Reconnection & Grace Period 10 Detik**:
   - Jika koneksi WebSocket terputus tiba-tiba (network hiccup / browser reload), sistem beralih ke state `GRACE_PERIOD` selama 10 detik (`SONANCE_WS_GRACE_PERIOD_SEC=10`).
   - Selama jendela 10 detik terbuka, GPU lock tetap dipertahankan dan model tetap dimuat di memori GPU.
   - Audio frame yang mungkin dikirim atau tersisa saat disconnect langsung di-drop (tidak di-buffer) untuk menghindari penumpukan audio usang saat klien terhubung kembali.
   - Klien bebas melakukan reconnect tanpa batasan jumlah percobaan selama batas 10 detik belum habis.
   - Jika 10 detik terlewati tanpa reconnect, sesi ditutup permanen, GPU lock dilepas, model di-unload, dan timestamp `vc_sessions.ended_at` dicatat tepat pada saat grace period berakhir.

4. **Integrasi GPU Resource Lock Eksklusif**:
   - Sesi voice changer real-time adalah pemilik sah pertama dari `GPUResourceManager` (`backend/app/core/gpu_manager.py`).
   - Pada saat inisialisasi sesi (`init_session`), sistem memanggil `acquire_lock(session_id)`. Jika GPU sedang terkunci oleh sesi lain, permintaan ditolak.
   - Selama lock dipegang, worker TTS yang berjalan otomatis menunda eksekusi job batch.
   - Ketika sesi ditutup (`close_session`) atau grace period habis, sistem memanggil `release_lock(session_id)`.
   - Tidak ada batas durasi maksimum sesi; pengguna dapat menggunakan voice changer selama yang diinginkan.

5. **Abstraksi Pipeline Konversi Suara (ML)**:
   - Menambahkan interface abstrak `VoiceConversionPipeline(ABC)` di `backend/ml/base.py` dengan metode `load_model()`, `unload_model()`, `convert_chunk()`, dan `is_loaded()`.
   - Mengimplementasikan stub `RVCRealtimePipeline` di `backend/ml/rvc/__init__.py` yang mensimulasikan latensi inferensi per chunk, simulasi pitch shift, dan simulasi kegagalan terkontrol untuk pengujian.

6. **Database Persistence & Session Tracking**:
   - Tabel database `vc_sessions` dibuat melalui migrasi Alembic `0003_create_vc_sessions.py`.
   - Model ORM `VCSession` mencatat `id`, `user_id`, `voice_profile_id`, `started_at`, `ended_at`, `avg_latency_ms`, dan `settings`.

---

## User Stories

1. As an authenticated user, I want to connect to `wss://.../ws/voice-changer?token={api_token}`, so that I can establish a secure real-time audio communication channel.
2. As an unauthenticated client, I want connection attempts without a valid token to be rejected with WebSocket close code 1008, so that unauthorized access to GPU resources is prevented.
3. As an authenticated user, I want to send an `init_session` message containing `voice_profile_id` and optional settings, so that the server can load the corresponding voice model and prepare real-time conversion.
4. As an authenticated user, I want to receive a `session_ready` message with my unique `session_id`, so that I know when the voice model has finished loading and the server is ready to process audio.
5. As an authenticated user, I want to receive an `error` message with code `PROFILE_NOT_READY` if I specify a voice profile whose status is not `ready`, so that I only perform conversion with completed models.
6. As an authenticated user, I want to receive an `error` message with code `PROFILE_NOT_FOUND` if I reference a non-existent voice profile or one belonging to another user, so that privacy and data isolation are preserved.
7. As an authenticated user, I want to stream raw binary PCM audio chunks to the server, so that my voice is converted with minimal latency and zero encoding overhead.
8. As an authenticated user, I want to receive converted raw binary PCM audio chunks back from the server in real time, so that I can play them directly through my audio output device.
9. As an authenticated user, I want to receive periodic `metrics` messages containing `latency_ms` and `processing_ms`, so that I can monitor connection health and conversion delay.
10. As an authenticated user, I want to send an `update_settings` message to modify parameters like `pitch_shift` during an active session, so that I can adjust pitch without restarting the session or reloading the model.
11. As an authenticated user, I want to send a `close_session` message when I am done, so that the session finishes cleanly, the GPU lock is released, and the model is unloaded.
12. As an authenticated user, I want a 10-second grace period if my connection drops unexpectedly, so that brief network hiccups do not force me to restart my session or reload the voice model.
13. As an authenticated user, I want any audio sent during a disconnect period to be dropped rather than buffered, so that I do not experience delayed audio playback when reconnecting.
14. As an authenticated user, I want `vc_sessions.ended_at` to reflect the exact timestamp when the 10-second grace period expired, so that session tracking accurately represents GPU reservation duration.
15. As a system operator, I want the real-time voice changer session to acquire the exclusive GPU lock upon initialization and hold it throughout the active session and grace period, so that background TTS batch jobs do not degrade real-time conversion performance.
16. As an authenticated user, I want no artificial maximum time limit on my voice changer session, so that I can keep using the voice changer uninterrupted for extended calls or streaming.
17. As an authenticated user, I want to be rejected with an `error` message code `GPU_BUSY` if another voice changer session is already running, so that concurrent session conflicts on a single GPU are prevented.

---

## Technical Decisions & Protocols

### 1. WebSocket URL & Authentication

- **URL**: `/ws/voice-changer`
- **Protocol**: `ws://` (lokal/development) atau `wss://` (production/TLS).
- **Authentication**:
  - Token dikirim sebagai query parameter: `?token={token}`.
  - Implementasi validasi menggunakan `secrets.compare_digest` dengan `SONANCE_API_TOKEN`.
  - Jika token tidak ada, bernilai kosong, atau tidak cocok: server menolak koneksi dengan menutup WebSocket menggunakan kode `1008` (`WS_1008_POLICY_VIOLATION`) dan pesan `"Token autentikasi tidak valid atau tidak ada."`.
  - Setelah token tervalidasi, user identifier diperoleh melalui fungsi helper `_get_user_id()`.

### 2. Message Formats & Locked Schemas

Protokol menggunakan kombinasi frame teks berformat JSON dan frame biner mentah.

#### A. Client -> Server Messages

##### 1. Inisialisasi Sesi (`init_session`)
Dikirim oleh klien segera setelah koneksi WebSocket terbuka untuk memulai sesi baru atau menyambung sesi yang ada.

```json
{
  "type": "init_session",
  "voice_profile_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "settings": {
    "pitch_shift": 0,
    "sample_rate": 16000,
    "chunk_duration_ms": 30
  }
}
```

Field rules:
- `type`: String konstan `"init_session"` (wajib).
- `voice_profile_id`: UUID string (wajib jika membuat sesi baru). Harus merujuk ke record `voice_profiles` milik user dengan status `'ready'`.
- `settings`: Object opsional (jika diabaikan, gunakan default value):
  - `pitch_shift`: Integer semitone, range `[-12, 12]`, default `0`.
  - `sample_rate`: Integer frekuensi sampling, whitelist `[16000, 24000, 44100, 48000]`, default `16000`.
  - `chunk_duration_ms`: Integer durasi frame, range `[10, 100]`, default `30`.

##### 2. Reconnect ke Sesi Grace Period
Jika klien menyambung kembali dalam jendela grace period 10 detik, klien dapat menyertakan `session_id` pada query parameter:
`wss://.../ws/voice-changer?token={token}&session_id={session_id}`
atau mengirimkan pesan:

```json
{
  "type": "init_session",
  "session_id": "e9b21f37-1234-4567-89ab-cdef01234567"
}
```

Jika `session_id` valid dan sedang dalam state `GRACE_PERIOD`, server membatalkan countdown grace period dan mengaktifkan kembali sesi tanpa reload model.

##### 3. Input Audio Chunk (Binary Frame)
- Klien mengirimkan potongan raw PCM audio secara berkala (setiap 20-40ms).
- Format: 16-bit signed integer (int16 little-endian), single channel (mono).
- Ukuran byte yang diharapkan per frame dihitung dengan rumus:
  bytes = sample_rate * (chunk_duration_ms / 1000) * 2
  Contoh: untuk 16000 Hz dan 30ms, ukuran frame adalah 16000 * 0.03 * 2 = 960 bytes.
- Frame biner yang diterima sebelum status sesi menjadi `ACTIVE` atau saat status tidak valid akan diabaikan atau memicu pesan error.

##### 4. Pembaruan Pengaturan (`update_settings`)
Klien dapat memperbarui pengaturan dinamis kapan saja selama sesi aktif tanpa menghentikan pemrosesan audio atau memuat ulang model.

```json
{
  "type": "update_settings",
  "settings": {
    "pitch_shift": 2,
    "chunk_duration_ms": 40
  }
}
```

Field rules:
- `type`: String konstan `"update_settings"` (wajib).
- `settings`: Object berisi subset field pengaturan yang ingin diubah. Nilai divalidasi dengan aturan yang sama seperti `init_session`.

##### 5. Penutupan Sesi Bersih (`close_session`)
Klien memberi sinyal bahwa konversi selesai.

```json
{
  "type": "close_session"
}
```

Server akan melepaskan GPU lock, membongkar model, memperbarui status di database, dan menutup koneksi dengan kode `1000` (`WS_1000_NORMAL_CLOSURE`).

---

#### B. Server -> Client Messages

##### 1. Konfirmasi Kesiapan Sesi (`session_ready`)
Dikirim setelah model RVC berhasil dimuat ke GPU dan lock diperoleh.

```json
{
  "type": "session_ready",
  "session_id": "e9b21f37-1234-4567-89ab-cdef01234567",
  "reconnected": false
}
```

Field:
- `type`: String konstan `"session_ready"`.
- `session_id`: UUID sesi yang baru dibuat atau di-resume.
- `reconnected`: Boolean, bernilai `true` jika pesan ini merupakan konfirmasi penyambungan kembali dari grace period.

##### 2. Output Audio Chunk (Binary Frame)
- Server mengirimkan hasil konversi suara langsung sebagai frame biner PCM (16-bit signed integer, mono, disesuaikan dengan sample rate sesi).
- Dikirim segera setelah proses inferensi chunk selesai.

##### 3. Laporan Metrik Latensi (`metrics`)
Dikirim secara periodik (setiap frame audio atau interval pelaporan) untuk memberikan telemetri latensi ke antarmuka pengguna.

```json
{
  "type": "metrics",
  "latency_ms": 85.4,
  "processing_ms": 42.1
}
```

Field:
- `type`: String konstan `"metrics"`.
- `latency_ms`: Float, perkiraan total latensi transit bolak-balik ditambah pemrosesan.
- `processing_ms`: Float, waktu eksekusi yang dihabiskan oleh model pipeline untuk mengubah chunk audio tersebut.

##### 4. Pesan Kesalahan (`error`)
Dikirim jika terjadi kegagalan validasi, kendala resource, atau kegagalan inferensi internal.

```json
{
  "type": "error",
  "code": "PROFILE_NOT_READY",
  "message": "Voice profile belum siap digunakan untuk konversi suara."
}
```

Standard Error Codes:
- `AUTH_FAILED`: Autentikasi token gagal.
- `PROFILE_NOT_FOUND`: Profil suara tidak ditemukan atau bukan milik pengguna terautentikasi.
- `PROFILE_NOT_READY`: Profil suara belum berstatus `ready`.
- `GPU_BUSY`: GPU sedang terkunci oleh sesi voice changer lain atau sedang digunakan oleh proses sintesis TTS. Jika terkunci oleh TTS, pesan: "GPU sedang memproses TTS job, coba lagi sesaat lagi". Server tidak melakukan retry otomatis; keputusan retry diserahkan sepenuhnya kepada klien.
- `INVALID_STATE`: Menerima audio chunk atau update settings sebelum `init_session` berhasil.
- `INVALID_PAYLOAD`: Format JSON atau nilai parameter tidak memenuhi batas validasi schema.
- `MODEL_LOAD_FAILED`: Gagal memuat bobot model checkpoint ke VRAM GPU.
- `INFERENCE_FAILED`: Error yang tidak terduga saat memproses konversi chunk audio.
- `SESSION_EXPIRED`: Grace period 10 detik berakhir tanpa ada reconnection.

---

### 3. Session Lifecycle & Reconnection State Machine

Sesi voice changer dikelola melalui siklus hidup state machine sebagai berikut:

```
                  ┌──────────────┐
                  │  CONNECTING  │ (WebSocket TCP handshake)
                  └──────┬───────┘
                         │ auth valid
                         ▼
                  ┌──────────────┐
                  │  CONNECTED   │ (Menunggu init_session)
                  └──────┬───────┘
                         │ init_session diterima & valid
                         │ acquire GPU lock & load model
                         ▼
                  ┌──────────────┐
                  │    ACTIVE    │◀─────────────────────────────┐
                  └──────┬───────┘                              │
                         │                                      │
           socket putus  │             klien reconnect < 10s    │
          tanpa close_msg│             batal countdown timer    │
                         ▼                                      │
                  ┌──────────────┐                              │
                  │ GRACE_PERIOD ├──────────────────────────────┘
                  └──────┬───────┘
                         │
                         │ 10 detik habis tanpa reconnect
                         │ ATAU close_session dari klien
                         ▼
                  ┌──────────────┐
                  │    ENDED     │ (release GPU lock, unload model,
                  └──────────────┘  set ended_at = now, close 1000)
```

Aturan Perilaku State Machine:
1. **Perilaku saat `GRACE_PERIOD`**:
   - Countdown timer 10 detik diinisialisasi menggunakan background task (`asyncio.create_task`).
   - GPU lock **tetap dipegang** oleh sesi tersebut. Model RVC **tetap dipertahankan** di GPU memory agar tidak terjadi penundaan cold-start saat klien tersambung kembali.
   - Semua potongan audio yang masuk saat soket putus **di-drop secara langsung** (tidak diantrekan dalam buffer memori) untuk mencegah audio stale diputar saat klien reconnect.
   - Klien bebas melakukan percobaan reconnect berkali-kali tanpa batas kuota selama jendela 10 detik belum habis.
2. **Penyelesaian Grace Period**:
   - Jika klien berhasil reconnect sebelum 10 detik habis: task timer dibatalkan, soket baru dipasangkan ke sesi aktif, dan server mengirimkan `session_ready` dengan flag `reconnected: true`.
   - Jika waktu 10 detik terlewati: timer memicu proses pembatalan, memanggil `release_lock(session_id)`, memanggil `unload_model()`, mencatat `vc_sessions.ended_at` dengan timestamp saat batas 10 detik terlampaui (sesuai ADR-003), dan mengubah state menjadi `ENDED`.
3. **Penutupan Bersih (`close_session`)**:
   - Jika klien mengirim `close_session` secara eksplisit saat state `ACTIVE`, tidak ada grace period yang diaktifkan. Sesi langsung bertransisi ke `ENDED`, melepaskan GPU lock, membongkar model, menetapkan `ended_at = now()`, dan menutup soket dengan kode `1000`.

---

### 4. GPU Resource Lock Coordination (Simetri GPU Lock)

- Menggunakan singleton `GPUResourceManager` dari `backend/app/core/gpu_manager.py`.
- **Prinsip Prioritas Simetris:** Siapa pun yang duluan memanggil `acquire_lock()` berhak menggunakan GPU; pihak lain menunggu atau gagal secara gracefully:
  - Jika sesi voice changer aktif atau dalam `GRACE_PERIOD`: worker TTS menunggu dalam backoff polling loop (timeout 30 menit).
  - Jika TTS job sedang memegang lock: inisialisasi sesi voice changer (`init_session`) ditolak dengan kode `GPU_BUSY` dan pesan: `"GPU sedang memproses TTS job, coba lagi sesaat lagi"`. Server **tidak** melakukan retry otomatis; keputusan coba ulang diserahkan kepada klien.
- **Partisipasi Aktif TTS Worker (`backend/workers/tts_worker.py`):**
  - Pada `execute_tts_job()`, worker **HARUS** memanggil `gpu_manager.acquire_lock(session_id=f"tts-{job_id}")` segera sebelum memanggil `pipeline.synthesize()`.
  - Worker **HARUS** memanggil `gpu_manager.release_lock(session_id=f"tts-{job_id}")` di dalam blok `try/finally`, memastikan lock selalu dilepas baik saat job berhasil maupun gagal karena exception.
  - Ini konsisten dengan pengecekan `is_locked()` yang sudah ada sebelumnya, namun sekarang TTS menjadi partisipan aktif penuh dalam protokol lock, bukan hanya pengamat pasif.
- **WebSocket Real-time Voice Changer Handler:**
  - Saat menerima pesan `init_session`, server memanggil `gpu_resource_manager.acquire_lock(str(session_id))`.
  - Jika `acquire_lock` mengembalikan `False` (karena TTS job sedang memegang lock `tts-{job_id}` atau ada sesi VC lain):
    - Server segera merespons dengan pesan `error` berkode `GPU_BUSY` dan pesan `"GPU sedang memproses TTS job, coba lagi sesaat lagi"`.
    - Server **JANGAN** melakukan retry otomatis di background; biarkan klien yang memutuskan kapan mencoba lagi.
  - Jika `acquire_lock` berhasil:
    - Server melanjutkan pemuatan model dan transisi ke state `ACTIVE`.
- **Selama sesi dalam status `ACTIVE` atau `GRACE_PERIOD`:**
  - `gpu_resource_manager.is_locked()` bernilai `True` dan dipegang oleh `session_id`.
  - Worker TTS yang mendeteksi lock ini akan mencatat `gpu_wait_started_at` dan menunda eksekusinya (backoff loop).
- **Pelepasan Lock Real-time Session:**
  - Saat sesi berakhir (melalui `close_session` atau timeout grace period 10 detik):
    - Server memanggil `gpu_resource_manager.release_lock(str(session_id))`.
    - Worker TTS yang sedang menunggu dapat segera melanjutkan proses sintesis.
- **Batas Durasi:** Tidak ada batas durasi maksimum untuk sesi voice changer; lock dipertahankan selama sesi aktif.

---

### 5. ML Pipeline Abstraction & Stub

#### A. Interface `VoiceConversionPipeline` (`backend/ml/base.py`)
Menambahkan class abstract baru ke dalam `backend/ml/base.py` untuk menerapkan prinsip dependency inversion:

```python
class VoiceConversionPipeline(ABC):
    """
    Interface abstrak untuk semua pipeline real-time voice conversion.
    Menerapkan pemrosesan audio berbasis chunk secara real-time.
    """

    @abstractmethod
    def load_model(self, checkpoint_path: str) -> None:
        """
        Memuat bobot model checkpoint ke dalam memori atau perangkat GPU.
        
        Args:
            checkpoint_path: Path absolut ke file model checkpoint (.pth).
        """
        pass

    @abstractmethod
    def unload_model(self) -> None:
        """Membongkar model dari memori GPU untuk menghemat VRAM."""
        pass

    @abstractmethod
    def is_loaded(self) -> bool:
        """Mengecek apakah model saat ini sedang termuat di memori."""
        pass

    @abstractmethod
    def convert_chunk(
        self,
        pcm_data: bytes,
        settings: dict,
    ) -> bytes:
        """
        Mengubah satu potongan audio raw PCM menjadi suara target.
        
        Args:
            pcm_data: Raw bytes data audio PCM input (16-bit mono).
            settings: Konfigurasi konversi (pitch_shift, sample_rate, dsb).
            
        Returns:
            bytes: Raw bytes data audio PCM hasil konversi.
        """
        pass
```

#### B. Stub `RVCRealtimePipeline` (`backend/ml/rvc/__init__.py`)
Implementasi stub konkret untuk pengujian unit dan integrasi tanpa hardware GPU riil:
- Memiliki parameter constructor `simulate_failure: bool = False` dan `inference_delay: float = 0.01` (10ms simulasi latensi).
- Mendukung variabel lingkungan `SONANCE_SIMULATE_VC_FAILURE=1`.
- `load_model`: Memverifikasi keberadaan checkpoint file, mengatur flag internal `_is_loaded = True`, dan mensimulasikan jeda cold-start singkat (misal 50ms).
- `unload_model`: Mengatur flag internal `_is_loaded = False`.
- `convert_chunk`:
  - Memastikan model sudah termuat (`_is_loaded is True`), jika belum memicu `RuntimeError("Model belum dimuat.")`.
  - Jika mode kegagalan aktif, memicu `RuntimeError("Simulated RVC inference error")`.
  - Mensimulasikan latensi inferensi dengan sleep singkat sesuai `inference_delay`.
  - Mengembalikan bytes audio output PCM berukuran sama dengan input.

---

### 6. Database Schema & ORM Model

#### A. Migrasi Alembic (`backend/alembic/versions/0003_create_vc_sessions.py`)
- Revisi: `0003`
- Down Revision: `0002` (table `tts_jobs`)

```sql
CREATE TABLE vc_sessions (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    voice_profile_id UUID NOT NULL REFERENCES voice_profiles(id) ON DELETE CASCADE,
    started_at TIMESTAMP WITH TIME ZONE NOT NULL,
    ended_at TIMESTAMP WITH TIME ZONE NULL,
    avg_latency_ms FLOAT NULL,
    settings JSON NOT NULL
);

CREATE INDEX idx_vc_sessions_user_started ON vc_sessions (user_id, started_at DESC);
CREATE INDEX idx_vc_sessions_voice_profile_id ON vc_sessions (voice_profile_id);
```

#### B. Model SQLAlchemy (`backend/app/models/vc_session_model.py`)
- Class `VCSession(Base)` menggunakan SQLAlchemy 2.x `Mapped[]` annotation style.
- Relasi:
  - `VCSession.user` (N-to-1 ke `User`, `ondelete="RESTRICT"`).
  - `VCSession.voice_profile` (N-to-1 ke `VoiceProfile`, `ondelete="CASCADE"`).
  - Relasi balik: `User.vc_sessions` dan `VoiceProfile.vc_sessions`.

---

### 7. Session Manager Layer (`backend/app/services/vc_session_manager.py`)

Untuk mengelola state in-memory, websocket connections, asynchronous timers, dan integrasi database:

1. **Class `ActiveSessionState`**:
   - Menyimpan `session_id`, `user_id`, `voice_profile_id`, `settings`, `pipeline`, `websocket`, `state`, `grace_timer_task`, `latencies` (list float untuk menghitung average), dan `started_at`.
2. **Class `VCSessionManager` (Singleton / Service)**:
   - `create_session(user_id, voice_profile_id, settings, websocket, db) -> VCSession`:
     - Memvalidasi profil suara (eksis, milik user, status `ready`).
     - Mencoba memperoleh GPU lock (`gpu_resource_manager.acquire_lock(session_id)`). Jika gagal, lemparkan exception `GPU_BUSY`.
     - Menyimpan record `vc_sessions` di DB dengan status awal.
     - Memuat model pipeline via `pipeline.load_model(...)`.
     - Mendaftarkan state ke in-memory map `_active_sessions`.
   - `reconnect_session(session_id, user_id, websocket) -> bool`:
     - Memeriksa apakah `session_id` ada dalam `_active_sessions` dan berstatus `GRACE_PERIOD`.
     - Membatalkan timer task grace period.
     - Memperbarui objek `websocket` yang aktif dan mengembalikan status ke `ACTIVE`.
   - `handle_disconnect(session_id, db)`:
     - Jika sesi sedang `ACTIVE`, ubah status ke `GRACE_PERIOD`.
     - Buat `asyncio.create_task` yang menunggu selama `SONANCE_WS_GRACE_PERIOD_SEC` (10 detik).
     - Jika timer kedaluwarsa tanpa reconnect: panggil `terminate_session(session_id, db, expired_at=now)`.
   - `process_audio_chunk(session_id, pcm_bytes) -> bytes`:
     - Menghitung waktu pemrosesan (`processing_ms`).
     - Memanggil `pipeline.convert_chunk(pcm_bytes, settings)`.
     - Mencatat durasi latensi ke daftar metrik sesi.
   - `update_settings(session_id, new_settings, db)`:
     - Memvalidasi dan memperbarui pengaturan aktif di memori dan kolom `settings` di DB.
   - `terminate_session(session_id, db, normal_close=True)`:
     - Memanggil `pipeline.unload_model()`.
     - Memanggil `gpu_resource_manager.release_lock(session_id)`.
     - Menghitung `avg_latency_ms` dari data latensi yang terkumpul.
     - Memperbarui `vc_sessions.ended_at` dan `vc_sessions.avg_latency_ms` di DB.
     - Menghapus sesi dari daftar `_active_sessions`.

---

### 8. Router Layer (`backend/app/routers/voice_changer_router.py`)

- Endpoint WebSocket didaftarkan di `backend/app/main.py`:
  `app.include_router(voice_changer_router)` dengan rute `@router.websocket("/ws/voice-changer")`.
- Alur handler:
  1. Ambil query parameter `token` dan opsional `session_id`.
  2. Validasi token. Jika tidak valid: panggil `await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="...")` dan return.
  3. Lakukan `await websocket.accept()`.
  4. Loop penerimaan pesan WebSocket:
     - Menerima pesan teks (JSON) untuk dispatch ke handler: `init_session`, `update_settings`, `close_session`.
     - Menerima frame biner (`bytes`) untuk diteruskan ke `process_audio_chunk()`. Hasil konversi dikirim kembali sebagai binary frame, diikuti pesan teks `metrics`.
  5. Menangani event `WebSocketDisconnect`: memicu `handle_disconnect()` pada session manager.
  6. Menangani exception tak terduga dengan mengirim pesan `error` dan menutup soket secara bersih.

---

## Testing Decisions

### 1. Seams & Levels Pengujian

- **Unit Testing**:
  - `test_vc_session_schema.py`: Validasi schema JSON Pydantic (`init_session`, `update_settings`, rentang angka `pitch_shift`, whitelist `sample_rate`, durasi chunk).
  - `test_rvc_realtime_pipeline.py`: Pengujian interface stub `RVCRealtimePipeline` (metode `load_model`, `unload_model`, `convert_chunk`, simulasi kegagalan).
  - `test_vc_session_model.py`: Pengujian ORM model `VCSession`, foreign key constraint (RESTRICT pada user, CASCADE pada voice profile), dan indeks query.
- **WebSocket Integration Testing (`test_voice_changer_ws.py`)**:
  - Menggunakan FastAPI `TestClient.websocket_connect` untuk memverifikasi alur end-to-end secara asinkron/sinkron:
    - **Happy Path**: Handshake dengan token valid -> `init_session` -> menerima `session_ready` -> mengirim binary PCM chunks -> menerima binary PCM chunks hasil konversi & frame `metrics` -> mengirim `close_session` -> verifikasi soket ditutup bersih dan GPU lock dilepas.
    - **Auth Guard (401 / WS 1008)**: Memverifikasi koneksi tanpa token atau dengan token salah langsung ditolak dengan kode 1008.
    - **Validasi Profil Suara**: Memverifikasi penolakan dengan error `PROFILE_NOT_READY` jika profil belum `ready`, dan `PROFILE_NOT_FOUND` jika profil tidak ada atau milik user lain.
    - **GPU Lock Contention (Real-time vs Real-time)**: Memverifikasi penolakan dengan error `GPU_BUSY` saat ada sesi real-time lain yang masih aktif.
    - **GPU Lock Contention Simetris (TTS vs Real-time)**:
      - Memverifikasi bahwa TTS job yang sedang berjalan (status `processing`, lock ter-acquire dengan `tts-{job_id}`) menyebabkan percobaan `init_session` real-time session GAGAL dengan error `GPU_BUSY` dan pesan `"GPU sedang memproses TTS job, coba lagi sesaat lagi"`.
      - Memverifikasi begitu TTS job selesai (lock ter-release lewat `finally`), percobaan `init_session` berikutnya pada WebSocket BERHASIL menerima `session_ready`.
    - **Grace Period & Reconnection (10 Detik)**:
      - Memverifikasi saat koneksi soket terputus, state beralih ke grace period dan GPU lock tetap aktif.
      - Memverifikasi koneksi ulang dalam jendela < 10 detik berhasil menyambung kembali (`reconnected: true`) tanpa reload model.
      - Memverifikasi audio yang dikirim selama putus koneksi di-drop (tidak di-buffer).
      - Memverifikasi jika waktu 10 detik habis tanpa reconnect, sesi ditandai berakhir, `ended_at` terisi dengan waktu expired, dan GPU lock dilepas secara otomatis.
    - **Dynamic Settings Update**: Memverifikasi bahwa pengiriman `update_settings` berhasil mengubah pitch shift tanpa mengganggu konversi stream audio.
- **Property-Based Testing (Hypothesis)**:
  - Validasi parameter numerik: pengujian kombinasi pitch shift [-12, 12] dan di luar batas, sample rate valid vs invalid, serta durasi chunk.
  - Invariant ukuran frame audio: memverifikasi bahwa untuk setiap pasangan integer `sample_rate` dan `chunk_duration_ms` yang valid, ukuran frame PCM bytes selalu tepat bernilai sample_rate * (chunk_duration_ms / 1000) * 2.

### 2. Kriteria Kualitas & Kecepatan

- Seluruh pengujian berjalan cepat secara lokal menggunakan database test in-memory SQLite / test DB transaction rollback.
- Stub ML pipeline digunakan secara eksklusif dalam test suite untuk menjamin 0 dependensi pada GPU hardware nyata atau file model biner berukuran gigabyte.
- 0 regresi pada 394 test yang sudah ada untuk Voice Profile Management dan TTS Pipeline.

---

## Out of Scope

1. **Hardware GPU Inference Riil**: Pengunduhan checkpoint bobot model RVC v2, algoritma pemisahan fungsional pitch/F0 riil (Harvest/Crepe), dan inferensi TensorRT/CUDA riil berada di luar scope v1 (diwakili oleh stub `RVCRealtimePipeline`).
2. **Audio Compression pada WebSocket**: Real-time Opus streaming dua arah via WebRTC atau WebSocket Opus tidak didukung pada v1 (dikunci ke raw binary PCM sesuai PRD dan ADR-007).
3. **Multi-User Real-time Concurrency**: Sistem dikunci untuk single GPU lokal dengan aturan 1 sesi voice changer aktif pada satu waktu.
4. **Rekaman Sesi ke Storage**: Penyimpanan otomatis seluruh rekaman audio sesi real-time ke file disk Opus belum diaktifkan pada v1.

---

## Invariants & Rules

1. **Single Session Rule**: Hanya ada maksimal satu VC session yang berstatus `ACTIVE` atau `GRACE_PERIOD` dalam satu waktu.
2. **GPU Lock Retention**: Selama sesi berstatus `ACTIVE` atau `GRACE_PERIOD`, GPU lock **harus** tetap dipegang (`is_locked() == True`).
3. **No Audio Buffering During Disconnect**: Audio chunk yang dikirim atau diterima saat klien terputus tidak boleh disimpan di buffer memori; harus di-drop segera.
4. **Accurate `ended_at`**: Nilai kolom `ended_at` pada `vc_sessions` harus mencatat waktu grace period berakhir (jika terputus karena timeout) atau waktu pesan `close_session` diterima (jika ditutup bersih).
5. **On-Demand Loading**: Model hanya dimuat ke memori saat `init_session` berhasil dieksekusi, dan harus dibongkar (`unload_model()`) saat sesi berakhir.
