# Sonance

Platform voice cloning dan real-time voice changer berbasis GPU lokal (single-user v1).

## Fitur Utama

1. **Voice Profile Management**:
   - Pembuatan dan pengelolaan profil suara (`own_voice`, `other_person`, `character`).
   - Validasi format dan durasi sample audio mentah (Opus/WAV).
   - Penjadwalan proses pelatihan model suara secara asinkron (RQ).
   - Validasi siklus hidup profil (`pending` -> `processing` -> `ready` / `failed`).

2. **Text-to-Speech (TTS) Pipeline**:
   - Sintesis audio offline berkualitas tinggi berbasis XTTS-v2.
   - Pilihan pengaturan bahasa (`id`, `en`), kecepatan (`speed`), nada (`pitch_shift`), dan `temperature`.
   - Penyimpanan audio hasil sintesis berformat Opus dengan endpoint streaming langsung.
   - Pelaksanaan job melalui antrian `tts_worker` terlindungi GPU lock.

3. **Real-time Voice Changer**:
   - Streaming audio dua arah berlatensi rendah melalui endpoint WebSocket `/ws/voice-changer`.
   - Konversi chunk audio raw PCM biner 16-bit mono menggunakan model RVC.
   - Mekanisme rekoneksi otomatis dengan toleransi jaringan (grace period 10 detik).
   - Pembaruan pengaturan nada (*live pitch shift*) saat sesi berjalan tanpa memuat ulang model.

4. **Symmetric GPU Lock Coordination**:
   - Koordinasi terpusat pemakaian VRAM GPU melalui `GPUResourceManager`.
   - Mencegah contention antara sesi streaming real-time berlatensi rendah dan batch TTS job.
   - TTS worker otomatis menunggu dengan backoff saat sesi real-time aktif.
   - Sesi real-time baru ditolak dengan `GPU_BUSY` saat GPU sedang digunakan job TTS.

---

## Local Development Setup

### 1. Redis Broker (Docker)

Untuk menjalankan antrian job asynchronous (training dan TTS), jalankan instance Redis lokal:

```bash
docker run -d --name sonance-redis -p 6379:6379 redis:alpine
```

Verifikasi container berjalan:
```bash
docker ps
```

### 2. Database Migration (Alembic)

Jalankan migrasi database SQLite atau PostgreSQL hingga revisi terakhir (`0003`):

```bash
# Upgrade ke revisi terbaru
python -m alembic upgrade head

# Downgrade jika diperlukan pengujian rollback
python -m alembic downgrade base
```

### 3. Menjalankan Training Worker Daemon

Worker memproses antrian pelatihan model suara (`training` queue):

**PowerShell (Windows):**
```powershell
$env:SONANCE_REDIS_URL = "redis://localhost:6379/0"
$env:PYTHONPATH = "."
python -m backend.workers.training_worker
```

**Bash (Linux / macOS):**
```bash
export SONANCE_REDIS_URL="redis://localhost:6379/0"
export PYTHONPATH="."
python -m backend.workers.training_worker
```

### 4. Menjalankan TTS Worker Daemon

Worker memproses antrian sintesis teks ke suara (`tts` queue) dengan penguncian GPU simetris:

**PowerShell (Windows):**
```powershell
$env:SONANCE_REDIS_URL = "redis://localhost:6379/0"
$env:PYTHONPATH = "."
python -m backend.workers.tts_worker
```

**Bash (Linux / macOS):**
```bash
export SONANCE_REDIS_URL="redis://localhost:6379/0"
export PYTHONPATH="."
python -m backend.workers.tts_worker
```

### 5. Menjalankan API Server (FastAPI)

Jalankan server REST dan WebSocket:

**PowerShell (Windows):**
```powershell
$env:SONANCE_REDIS_URL = "redis://localhost:6379/0"
$env:SONANCE_API_TOKEN = "your-dev-secret-token"
$env:PYTHONPATH = "."
python -m uvicorn backend.app.main:app --reload --port 8000
```

**Bash (Linux / macOS):**
```bash
export SONANCE_REDIS_URL="redis://localhost:6379/0"
export SONANCE_API_TOKEN="your-dev-secret-token"
export PYTHONPATH="."
python -m uvicorn backend.app.main:app --reload --port 8000
```

Dokumentasi interaktif OpenAPI tersedia di:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

Endpoint WebSocket Real-time Voice Changer:
- `ws://localhost:8000/ws/voice-changer?token=your-dev-secret-token`

### 6. Menjalankan Test Suite

Seluruh test suite (Unit, Integration, dan Property-Based Testing) dapat dijalankan tanpa dependensi Redis eksternal:

```powershell
$env:PYTHONPATH = "."
python -m pytest backend/tests/ -v
```

