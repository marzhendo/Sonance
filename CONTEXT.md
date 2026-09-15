# CONTEXT.md — Sonance Domain Model & Project Conventions

**Status:** Finalized (hasil sesi grill-with-docs)
**Berlaku untuk:** Seluruh spec, ticket, dan implementasi Sonance v1

---

## 1. Glossary — Domain Terms

Kamus istilah resmi project ini. Gunakan nama-nama ini secara konsisten di seluruh codebase, komentar, spec, dan ticket.

| Term | Definisi |
|---|---|
| **Voice Profile** | Entitas utama yang merepresentasikan satu karakter suara yang sudah di-clone. Berisi metadata, path ke sample audio asli, dan path ke model checkpoint hasil training. |
| **Sample Audio** | File audio mentah yang diupload user sebagai bahan training voice profile. Format simpan: Opus. Satu voice profile = satu file sample. |
| **Training Job** | Proses async yang membangun model checkpoint dari sample audio. Relasi 1-to-1 dengan voice profile. |
| **Model Checkpoint** | File `.pth` (PyTorch) hasil training yang menjadi "representasi model" dari satu voice profile. Disimpan di server lokal. |
| **Speaker Embedding** | Vektor numerik yang mengkodekan karakteristik unik sebuah suara, diekstrak dari sample audio selama proses training. |
| **TTS Job** | Proses async untuk menghasilkan audio dari input teks menggunakan voice profile tertentu (Voice Cloning / Offline mode). |
| **VC Session** | Satu sesi real-time voice changer — dimulai saat `init_session`, berakhir saat `close_session` atau grace period expired setelah disconnect. |
| **Grace Period** | Window waktu 10 detik setelah WebSocket disconnect di mana session ID tetap valid dan client bisa reconnect tanpa re-init model. |
| **GPU Lock** | State di mana GPU sedang dipegang oleh satu VC Session aktif. Selama GPU locked, TTS queue di-pause. |
| **Model Manager** | Komponen backend yang bertanggung jawab load/unload model ke/dari GPU memory secara on-demand. |
| **Cold Start** | Delay saat model pertama kali di-load ke GPU (belum ada di memory). UI menampilkan indikator "Menyiapkan model..." saat ini terjadi. |
| **Audio Chunk** | Potongan audio PCM raw yang dikirim/diterima per frame dalam sesi real-time. Durasi target: 20–40ms per chunk. |
| **Pitch Shift** | Pergeseran nada suara dalam satuan semitone. Range: -12 sampai +12. Default: 0. |
| **Source Type** | Klasifikasi asal suara dalam voice profile: `own_voice`, `other_person`, atau `character`. Memengaruhi pipeline/model yang dipakai saat training dan inference. |
| **Voice Profile Lifecycle** | Urutan status: `pending` → `processing` → `ready` / `failed`. `pending` berarti training job sudah di-queue, belum mulai. |

---

## 2. Entity Reference

Ringkasan entitas database dan field penting beserta catatan desain.

### `users`
- Satu akun per instalasi (single-user v1). Auth hanya sebagai guard.
- Token auth: API key/token statis — bukan JWT, tidak ada expiry/refresh.

### `voice_profiles`
| Field | Catatan |
|---|---|
| `source_type` | `own_voice` / `other_person` / `character` — beda nilai = beda pipeline training & inference |
| `status` | `pending` = job sudah di-queue; `processing` = job sedang jalan; `ready` = bisa dipakai; `failed` = gagal |
| `sample_audio_path` | Path ke file Opus. Boleh dihapus setelah training selesai (siklus hidup independen dari checkpoint). |
| `model_checkpoint_path` | Path ke file `.pth`. Disimpan selama voice profile ada. |

### `training_jobs`
- Relasi ke `voice_profiles`: **1-to-1**. Tidak ada riwayat retry atau fine-tune ulang di v1.
- `progress_pct`: 0–100, diupdate oleh worker selama proses berlangsung.

### `tts_jobs`
- `settings` JSONB schema (semua field opsional, ada default):
  ```json
  {
    "language": "id",       // whitelist: ["id", "en"] — default "id"
    "speed": 1.0,           // range 0.5–2.0 — default 1.0
    "pitch_shift": 0,       // semitone, range -12..+12 — default 0
    "temperature": 0.7,     // range 0.1–1.0 — default 0.7
    "output_format": "opus" // dikunci "opus" di v1 — default "opus"
  }
  ```
- Output audio diambil via `GET /api/v1/tts/jobs/{job_id}/audio` (streaming/download), bukan path statis publik.

### `vc_sessions`
- `ended_at`: di-set saat `close_session` diterima, **atau** saat grace period 10 detik expired setelah disconnect — bukan saat disconnect awal.
- `settings` JSONB menyimpan parameter sesi: `pitch_shift`, `sample_rate`, `chunk_duration_ms`.

---

## 3. WebSocket State Machine

State resmi sebuah VC Session:

```
DISCONNECTED
    │
    │ connect + auth token
    ▼
CONNECTED (auth validated)
    │
    │ {"type": "init_session"}
    ▼
INITIALIZING (model loading / cold start)
    │
    │ model ready
    ▼
ACTIVE (audio chunks flowing)
    │
    ├─── {"type": "update_settings"} ──▶ ACTIVE (settings updated in-place)
    │
    ├─── {"type": "close_session"} ────▶ ENDED (ended_at = now)
    │
    └─── network disconnect
              │
              ▼
         GRACE_PERIOD (10 detik, session_id masih valid)
              │
              ├─── reconnect dalam 10 detik ──▶ ACTIVE (resume, no re-init)
              │
              └─── 10 detik habis ────────────▶ ENDED (ended_at = grace_period_expired_at)
```

**Behavior saat GRACE_PERIOD:**
- GPU Lock tetap dipegang (model tidak di-unload).
- Audio chunk yang dikirim client selama disconnect: **di-drop**, tidak di-buffer.
- Reconnect bebas, tidak ada limit jumlah percobaan selama window terbuka.

---

## 4. GPU Resource Rules

Aturan ini bersifat invariant — tidak boleh dilanggar oleh implementasi manapun.

1. **Hanya satu VC Session yang boleh aktif dalam satu waktu.** (single-user constraint)
2. **Selama VC Session aktif atau dalam GRACE_PERIOD, GPU Lock dipegang.** TTS queue di-pause.
3. **TTS job melanjutkan eksekusi segera setelah GPU Lock dilepas** (sesi ended).
4. **Tidak ada batas durasi maksimum VC Session.** Sesi bisa berjalan tanpa batas waktu.
5. **Model loading bersifat on-demand.** Tidak ada model yang standby permanen di GPU memory.
6. **Source type memengaruhi model yang di-load.** `own_voice` dan `other_person` pakai RVC pipeline; `character` bisa pakai pipeline berbeda (ditentukan lebih lanjut di spec).

---

## 5. API Quick Reference

Endpoint resmi v1. Gunakan base path `/api/v1` untuk semua.

**Voice Profiles**
```
POST   /voice-profiles                    # Buat profile + upload sample
GET    /voice-profiles                    # List semua profile milik user
GET    /voice-profiles/{id}               # Detail satu profile
DELETE /voice-profiles/{id}               # Hapus profile
PATCH  /voice-profiles/{id}               # Update metadata (name, dll)
POST   /voice-profiles/{id}/train         # Trigger training job (async)
GET    /voice-profiles/{id}/status        # Cek status training
```

**TTS**
```
POST   /tts/generate                      # Buat TTS job baru
GET    /tts/jobs/{job_id}                 # Status + metadata job
GET    /tts/jobs/{job_id}/audio           # Download/stream hasil audio Opus
```

**Auth**
```
POST   /auth/register
POST   /auth/login
GET    /auth/me
```

**System**
```
GET    /gpu-status                        # State GPU saat ini (lihat schema di bawah)
```

**WebSocket**
```
wss://.../ws/voice-changer?token={api_token}
```

**`GET /gpu-status` response schema:**
```json
{
  "gpu": {
    "available": true,
    "vram_used_mb": 4200,
    "vram_total_mb": 8192,
    "utilization_pct": 67
  },
  "active_session": {
    "session_id": "uuid | null",
    "voice_profile_id": "uuid | null",
    "started_at": "ISO8601 | null"
  },
  "loaded_model": {
    "type": "rvc | xtts | none",
    "voice_profile_id": "uuid | null"
  },
  "tts_queue": {
    "depth": 2,
    "paused": true
  }
}
```

---

## 6. Architecture Decision Records (ADR)

### ADR-001: Auth menggunakan API Key, bukan JWT
**Konteks:** Single-user local app, tidak ada multi-tenant.  
**Keputusan:** Token statis (API key). Tidak ada expiry, tidak ada refresh token.  
**Alasan:** JWT complexity (expiry, refresh flow) tidak memberikan nilai tambah di konteks single-user lokal.  
**Konsekuensi:** Token disimpan di config lokal. Jika bocor, user perlu regenerate manual.

### ADR-002: WebSocket auth via query parameter
**Konteks:** Browser WebSocket API tidak mendukung custom header saat handshake.  
**Keputusan:** Token dikirim sebagai query parameter: `?token=...`  
**Alasan:** Keterbatasan teknis browser, bukan pilihan preferensi.  
**Konsekuensi:** Token terekspos di server log URL. Mitigasi: gunakan HTTPS/WSS, dan log URL di server harus di-sanitize.

### ADR-003: VC Session reconnect menggunakan grace period 10 detik
**Konteks:** Koneksi bisa putus karena network hiccup sementara.  
**Keputusan:** Session ID valid selama 10 detik setelah disconnect. Reconnect bebas tanpa limit attempt. Audio selama disconnect di-drop.  
**Alasan:** 10 detik cukup untuk handle network hiccup tanpa menahan GPU terlalu lama untuk sesi yang sudah abandoned.  
**Konsekuensi:** `vc_sessions.ended_at` mencerminkan waktu grace period expired, bukan waktu disconnect awal.

### ADR-004: Model loading on-demand, bukan standby
**Konteks:** GPU memory terbatas (lokal).  
**Keputusan:** Model di-load ke GPU hanya saat dibutuhkan, di-unload setelah sesi/job selesai.  
**Alasan:** Mencegah VRAM exhaustion jika ada multiple model type (RVC + XTTS).  
**Konsekuensi:** Ada cold-start delay. UI wajib menampilkan indikator "Menyiapkan model...".

### ADR-005: TTS queue di-pause saat VC Session aktif
**Konteks:** GPU tunggal tidak bisa melayani real-time inference dan batch job bersamaan tanpa degradasi latency.  
**Keputusan:** TTS job worker di-pause selama GPU Lock dipegang oleh VC Session. Resume otomatis saat GPU Lock dilepas.  
**Alasan:** Latency real-time voice changer adalah prioritas utama (target < 300ms).  
**Konsekuensi:** TTS job bisa mengalami delay tak terduga jika user menjalankan VC Session panjang.

### ADR-006: Voice Profile 1-to-1 dengan Training Job
**Konteks:** Scope v1.  
**Keputusan:** Satu voice profile hanya punya satu training job. Tidak ada fine-tune ulang atau retry yang menciptakan job baru.  
**Alasan:** Menyederhanakan state machine dan UI di v1.  
**Konsekuensi:** Jika training gagal dan user ingin retry, harus membuat voice profile baru. (Bisa direvisi di v2.)

### ADR-007: source_type memengaruhi pipeline
**Konteks:** Berbeda asal suara bisa butuh pendekatan model berbeda.  
**Keputusan:** `source_type` bukan sekadar label — ia menentukan pipeline training dan inference yang dipakai.  
**Alasan:** `own_voice` dan `other_person` cocok untuk RVC pipeline standar; `character` mungkin butuh pendekatan berbeda.  
**Konsekuensi:** Backend perlu routing logic berdasarkan `source_type` saat dispatch training job dan saat load model untuk inference.

---

## 7. Project Structure

### Repo Structure (Monorepo)
```
sonance/
├── backend/                    # Python FastAPI
│   ├── app/
│   │   ├── routers/            # _router.py files
│   │   ├── services/           # _service.py files
│   │   ├── schemas/            # _schema.py files (Pydantic)
│   │   ├── models/             # _model.py files (ORM/DB)
│   │   ├── core/               # config, dependencies, auth
│   │   └── main.py
│   ├── workers/                # Celery/RQ task workers
│   ├── ml/                     # Model loading, inference pipelines
│   │   ├── rvc/
│   │   └── xtts/
│   └── tests/
├── frontend/                   # Next.js / React
│   ├── components/             # PascalCase komponen
│   ├── pages/ (atau app/)
│   ├── utils/                  # camelCase utilities
│   └── hooks/
├── desktop/                    # Electron/Tauri wrapper
├── docs/
│   ├── prd-sonance
│   └── specs/                  # Output dari /to-spec
└── CONTEXT.md
```

### Naming Conventions

| Layer | Convention | Contoh |
|---|---|---|
| Python router | `{domain}_router.py` | `voice_profile_router.py` |
| Python service | `{domain}_service.py` | `training_job_service.py` |
| Python schema | `{domain}_schema.py` | `tts_job_schema.py` |
| Python model | `{domain}_model.py` | `voice_profile_model.py` |
| React component | `PascalCase.tsx` | `VoiceProfileCard.tsx` |
| React hook | `use{Name}.ts` | `useVcSession.ts` |
| React util | `camelCase.ts` | `formatDuration.ts` |
| DB table | `snake_case` plural | `voice_profiles`, `tts_jobs` |
| DB column | `snake_case` | `model_checkpoint_path` |
| Env variable | `SONANCE_` prefix | `SONANCE_DATABASE_URL` |

### Environment Variables (Canonical List)

```env
# Database
SONANCE_DATABASE_URL=

# Redis (job queue)
SONANCE_REDIS_URL=

# Auth
SONANCE_API_TOKEN=

# Storage paths
SONANCE_SAMPLE_AUDIO_DIR=
SONANCE_CHECKPOINT_DIR=
SONANCE_OUTPUT_AUDIO_DIR=

# Model config
SONANCE_GPU_DEVICE=cuda:0
SONANCE_RVC_MODEL_DIR=
SONANCE_XTTS_MODEL_DIR=

# App
SONANCE_HOST=0.0.0.0
SONANCE_PORT=8000
SONANCE_WS_GRACE_PERIOD_SEC=10
```

---

## 8. TTS Settings — Whitelist & Defaults

Field `settings` JSONB pada `tts_jobs` dan `POST /api/v1/tts/generate`:

| Field | Type | Default | Valid Values |
|---|---|---|---|
| `language` | string | `"id"` | `"id"`, `"en"` (whitelist ketat) |
| `speed` | float | `1.0` | `0.5` – `2.0` |
| `pitch_shift` | int | `0` | `-12` – `+12` |
| `temperature` | float | `0.7` | `0.1` – `1.0` |
| `output_format` | string | `"opus"` | `"opus"` (dikunci v1) |

Semua field opsional. Jika tidak dikirim, gunakan default.

---

## 9. Audio Pipeline — Format & Flow

```
Mic input (raw PCM)
    │
    ▼ [20–40ms chunk]
WebSocket binary frame (PCM) ──▶ Backend
    │
    ▼
RVC inference (voice conversion)
    │
    ▼
HiFi-GAN vocoder (PCM/WAV output)
    │
    ├──▶ WebSocket binary frame (PCM) ──▶ Client (real-time playback)
    │
    └──▶ [Opsional: encode Opus] ──▶ Storage (jika sesi direkam)

TTS flow:
Text input ──▶ XTTS-v2 acoustic model ──▶ mel-spectrogram
    │
    ▼ [dikondisikan pada speaker embedding]
HiFi-GAN vocoder ──▶ PCM/WAV ──▶ encode Opus ──▶ storage
```

**Format summary:**
- Transport real-time: **PCM binary** (tanpa encoding overhead)
- Storage: **Opus** (lossy, hemat disk)
- Checkpoint model: **`.pth`** (PyTorch native)
- Sample audio input: **Opus** (saat disimpan ke disk)

---

*Dokumen ini adalah sumber kebenaran tunggal untuk konvensi dan domain model Sonance v1.*
*Update dokumen ini jika ada keputusan arsitektur baru yang dibuat selama development.*
