# Sonance

Voice cloning and real-time voice changer platform.

## Local Development Setup

### 1. Redis Broker (Docker)

Untuk menjalankan worker asynchronous di lingkungan lokal, gunakan Redis container via Docker:

```bash
docker run -d --name sonance-redis -p 6379:6379 redis:alpine
```

Pastikan Redis container berjalan dengan mengecek:
```bash
docker ps
```

### 2. Menjalankan Training Worker Daemon

Worker mendengarkan antrian job pelatihan model menggunakan RQ (Redis Queue).

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

Opsi CLI tambahan:
- `--burst`: Memproses semua job yang ada di antrian saat ini lalu keluar otomatis.
- `--queue <nama>`: Menentukan antrian spesifik yang diproses (default: `training`).

### 3. Menjalankan API Server (FastAPI)

Jalankan FastAPI server dengan broker Redis yang sama agar job training di-enqueue ke worker:

**PowerShell (Windows):**
```powershell
$env:SONANCE_REDIS_URL = "redis://localhost:6379/0"
$env:SONANCE_API_TOKEN = "your-dev-secret-token"
$env:PYTHONPATH = "."
python -m uvicorn backend.app.main:app --reload
```

**Bash (Linux / macOS):**
```bash
export SONANCE_REDIS_URL="redis://localhost:6379/0"
export SONANCE_API_TOKEN="your-dev-secret-token"
export PYTHONPATH="."
python -m uvicorn backend.app.main:app --reload
```

Jika `SONANCE_REDIS_URL` tidak diset, API server otomatis fallback ke mode in-memory queue.

### 4. Menjalankan Test Suite

Test suite berjalan sepenuhnya terisolasi dan cepat tanpa memerlukan instance Redis:

```powershell
$env:PYTHONPATH = "."
python -m pytest backend/tests/ -v
```
