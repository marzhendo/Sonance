<!-- antislop:start -->
## antislop
For UI, copy, people, mobile layout, or code comments work, load the antislop skill for the task:
- Core filter, always on: `antislop`
- Copy & text: `antislop-copywriting`
- People: `antislop-human`
- Mobile / responsive: `antislop-layoutmobile`
- Code comments: `antislop-code`
Before starting, ask the user when antislop applies: during the work, or after it is done.
<!-- antislop:end -->

## Development and Services

### Background Worker and Queue
- Broker: Redis Queue (RQ) configured via `SONANCE_REDIS_URL`.
- Default queue names: `training` (model training), `tts` (offline speech synthesis).
- Run worker daemon:
  - Training worker: `python -m backend.workers.training_worker` (requires `SONANCE_REDIS_URL`).
  - TTS worker: `python -m backend.workers.tts_worker` (requires `SONANCE_REDIS_URL`).
- Tests: Test suite uses in-memory queue fallback (`InMemoryQueue`) by default without requiring an active Redis server.

### Real-time Voice Changer
- Endpoint WebSocket: `/ws/voice-changer?token={token}`.
- Protokol: Dual control & data framing (JSON text control message + binary 16-bit mono raw PCM chunk).
- State Machine: `CONNECTED` -> `INITIALIZING` -> `ACTIVE` -> `GRACE_PERIOD` (10s) -> `ENDED`.

### Symmetric GPU Lock Coordination
- Pengelola tunggal: `backend.app.core.gpu_manager.GPUResourceManager`.
- Partisipasi simetris: Voice changer session dan TTS worker bersaing secara setara.
- TTS worker acquire lock `tts-{job_id}` via `try/finally`. Jika locked oleh voice changer, TTS worker menunggu backoff (timeout 30m).
- Jika TTS worker sedang memegang lock, inisialisasi voice changer ditolak dengan `GPU_BUSY`.

### Database and Migrations
- Migration chain: `0000_create_users` -> `0001_create_voice_profiles_and_training_jobs` -> `0002_create_tts_jobs` -> `0003_create_vc_sessions`.
- Dialect support: Dialect-aware type decorators (`UUIDType`) for cross-compatibility between PostgreSQL (native UUID) and SQLite (`CHAR(36)`).
