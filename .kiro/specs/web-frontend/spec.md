# Specification: Sonance Web Frontend (Next.js)

## 1. Problem Statement & Executive Summary

Backend Sonance v1 telah selesai dibangun dan teruji 100% (529 automated tests lulus) dengan menyediakan seluruh kemampuan kecerdasan buatan lokal:
1. Manajemen Voice Profile (`/api/v1/voice-profiles`) dengan unggah sample audio dan pelatihan model asinkron.
2. Sintesis offline Text-to-Speech (`/api/v1/tts/generate`) dengan pemilihan karakter suara, konfigurasi intonasi/kecepatan, dan pengunduhan stream audio Opus.
3. Real-time Voice Changer (`/ws/voice-changer`) dengan streaming audio dua arah berlatensi rendah (raw PCM 16-bit), toleransi pemutusan koneksi jaringan sementara (grace period 10 detik), dan koordinasi GPU lock simetris terpusat.

Namun, sistem ini belum memiliki antarmuka pengguna grafis (GUI) yang interaktif, mudah digunakan, dan intuitif. Pengguna saat ini harus mengoperasikan cURL, Postman, atau skrip Python terminal untuk berinteraksi dengan API.

**Tujuan Frontend:**
Membangun aplikasi web modern berbasis **Next.js (App Router)** dan **shadcn/ui** yang bertindak sebagai antarmuka pengguna visual komprehensif untuk seluruh kapabilitas backend Sonance, dengan fokus pada:
- Kesederhanaan alur kerja pembuatan dan pemantauan profil suara.
- Kemudahan komposisi teks menjadi suara dengan pemutar waveform audio instan.
- Pengalaman real-time voice changer berlatensi rendah di peramban (browser) menggunakan **Web Audio API** untuk penangkapan mikrofon, konversi PCM, streaming WebSocket, visualisasi audio level meter, dan pemutaran audio balik bebas *glitch*.

Frontend ini murni berperan sebagai *client consumer* tanpa memerlukan perubahan pada arsitektur backend yang sudah ada.

---

## 2. Tech Stack & Dependencies

| Lapisan / Komponen | Teknologi | Keterangan & Rationale |
|---|---|---|
| **Framework** | Next.js 14+ (App Router) | Server-side rendering untuk shell aplikasi, performa cepat, layout modular. |
| **Bahasa** | TypeScript 5+ | Type safety ketat yang selaras dengan Pydantic schemas backend. |
| **Komponen UI** | shadcn/ui + Radix UI + Tailwind CSS | Komponen beraksesibilitas tinggi (WAI-ARIA), styling konsisten, mudah dikustomisasi tanpa vendor lock-in. |
| **Server State & Polling** | TanStack Query v5 (React Query) | Pengelolaan caching, deduplikasi request, dan polling adaptif (`refetchInterval`) untuk status training dan TTS job. |
| **Audio Processing** | Web Audio API + AudioWorklet | Penangkapan mikrofon, konversi PCM 16-bit Float32-to-Int16, pemutaran audio balik berlatensi rendah, dan visualisasi canvas. |
| **Waveform Visualizer** | wavesurfer.js atau Canvas 2D | Visualisasi waveform audio interaktif untuk pratinjau sample dan hasil sintesis TTS. |
| **Form Management** | react-hook-form + Zod | Validasi skema input di sisi klien yang identik dengan boundary backend. |
| **Icons** | Lucide React | Ikon modern, ringan, dan konsisten. |
| **Toast Notifications** | Sonner | Pemberitahuan real-time untuk error, status koneksi, dan progres operasi. |

---

## 3. Architecture & Project Structure

Struktur direktori frontend mengikuti konvensi Next.js App Router:

```text
frontend/
├── app/
│   ├── layout.tsx                    # Root layout: TanStack Provider, Theme, Auth Provider, Navbar
│   ├── page.tsx                      # Beranda / Dashboard ringkasan status sistem
│   ├── profiles/
│   │   ├── page.tsx                  # Halaman Voice Profile Management
│   │   └── _components/              # Komponen internal modul profile
│   │       ├── ProfileCard.tsx
│   │       ├── CreateProfileDialog.tsx
│   │       ├── RenameProfileDialog.tsx
│   │       └── TrainingProgress.tsx
│   ├── tts/
│   │   ├── page.tsx                  # Halaman TTS Pipeline
│   │   └── _components/              # Komponen internal modul TTS
│   │       ├── TTSGenerateForm.tsx
│   │       ├── TTSHistoryTable.tsx
│   │       └── WaveformPlayer.tsx
│   ├── voice-changer/
│   │   ├── page.tsx                  # Halaman Real-time Voice Changer
│   │   └── _components/              # Komponen internal modul Voice Changer
│   │       ├── VCControlPanel.tsx
│   │       ├── VCAudioVisualizer.tsx
│   │       ├── VCMetricsDisplay.tsx
│   │       └── VCReconnectionBanner.tsx
├── components/                       # Shared UI components (shadcn/ui)
│   ├── ui/                           # Button, Dialog, Input, Slider, Table, Badge, dll.
│   ├── Navbar.tsx                    # Navigasi utama + status GPU + tombol Auth Token
│   └── AuthTokenModal.tsx            # Modal konfigurasi SONANCE_API_TOKEN
├── hooks/
│   ├── useAuth.ts                    # Hook state token autentikasi (localStorage)
│   ├── useVoiceProfiles.ts           # React Query hook untuk CRUD & training voice profiles
│   ├── useTTS.ts                     # React Query hook untuk generate, list, dan status TTS
│   ├── useAudioCapture.ts            # Web Audio API hook untuk perekaman mikrofon & PCM framing
│   └── useVoiceChangerSocket.ts      # Hook WebSocket streaming, dual framing, reconnection
├── lib/
│   ├── api-client.ts                 # Wrapper HTTP fetch/axios dengan injeksi header Bearer
│   ├── audio-helpers.ts              # Konverter PCM (Float32Array <-> Int16Array), kalkulasi RMS
│   └── types.ts                      # TypeScript interfaces kontrak backend
```

---

## 4. Auth & Security Design (Single-User Model)

Sesuai dengan keputusan arsitektural backend (ADR-001 dan ADR-002), Sonance v1 beroperasi dalam mode *single-user* lokal:
1. **Penyimpanan Token:**
   - Token autentikasi disimpan di `localStorage` peramban dengan kunci `sonance_api_token`.
   - Default fallback diisi dari environment variable `NEXT_PUBLIC_SONANCE_API_TOKEN` jika tersedia.
2. **Injeksi Token REST:**
   - Setiap permintaan HTTP ke backend secara otomatis menyertakan header:
     `Authorization: Bearer <token>`
   - Jika backend merespons dengan status HTTP `401 Unauthorized`, sistem menampilkan toast peringatan dan membuka dialog konfigurasi token.
3. **Injeksi Token WebSocket:**
   - Koneksi WebSocket `/ws/voice-changer` menginjeksi token melalui query parameter:
     `ws://localhost:8000/ws/voice-changer?token=<token>`
   - Jika koneksi ditolak dengan code `1008 Policy Violation`, frontend menampilkan status error auth.
4. **Indikator Status Auth:**
   - Navbar menampilkan status token (indikator titik hijau/merah).
   - Pengguna dapat memperbarui atau merotasi token kapan saja tanpa memuat ulang aplikasi.

---

## 5. Halaman & Spesifikasi Fungsional

### 5.1 Halaman 1: `/profiles` (Voice Profile Management)

Halaman ini mengelola repositori karakter suara pengguna.

#### Komponen & Fitur
1. **Daftar Profil Suara (Card Grid / Table View):**
   - Menampilkan seluruh profil yang dimiliki pengguna (`GET /api/v1/voice-profiles`).
   - Setiap kartu profil menampilkan:
     - Nama profil dan jenis sumber suara (`own_voice` / `other_person` / `character`).
     - Durasi sample audio awal (contoh: "15.4 detik").
     - Badge status visual yang jelas:
       - `pending`: Abu-abu (belum dilatih).
       - `processing`: Kuning/Biru dengan animasi spinner (sedang dilatih).
       - `ready`: Hijau (siap digunakan untuk TTS dan Voice Changer).
       - `failed`: Merah (pelatihan gagal, dilengkapi tooltip pesan kesalahan).
     - Tombol aksi: **Train Now** (jika `pending`), **Rename**, dan **Delete**.
2. **Form Buat Profil Baru (Modal Dialog):**
   - Input teks nama profil (1-100 karakter, validasi spasi kosong).
   - Dropdown pilihan `source_type`:
     - Suara Sendiri (`own_voice`)
     - Orang Lain (`other_person`)
     - Karakter Rekaan (`character`)
   - File dropzone untuk mengunggah sample audio:
     - Format yang didukung: WAV, MP3, OGG, FLAC, Opus, AAC, M4A.
     - Batas ukuran file: 50MB.
     - Pratinjau durasi audio langsung sebelum dikirim (memastikan 5.0 - 300.0 detik).
   - Indikator progres unggah berkas multipart form data.
3. **Pemicu Pelatihan (Trigger Training) & Polling:**
   - Tombol **Mulai Latih** memanggil `POST /api/v1/voice-profiles/{id}/train`.
   - Menangani HTTP `409 Conflict` jika profil tidak dalam status `pending` atau job sudah berjalan.
   - Mengaktifkan *smart polling* menggunakan TanStack Query:
     - Polling interval setiap 2000ms (`refetchInterval`) pada endpoint `GET /api/v1/voice-profiles/{id}/status`.
     - Menampilkan bilah progres (`progress_pct` 0-100%) dan estimasi waktu.
     - Polling otomatis berhenti segera setelah status berubah menjadi `ready` atau `failed`.
4. **Rename & Delete:**
   - Rename: Modal ringkas untuk memanggil `PATCH /api/v1/voice-profiles/{id}`.
   - Delete: Dialog konfirmasi bahaya sebelum memanggil `DELETE /api/v1/voice-profiles/{id}` (menghapus profil, checkpoint, dan sample secara permanen).

---

### 5.2 Halaman 2: `/tts` (Text-to-Speech Pipeline)

Halaman ini digunakan untuk menghasilkan sintesis ujaran suara berkualitas tinggi secara asinkron.

#### Komponen & Fitur
1. **Form Generator Sintesis:**
   - **Pemilihan Karakter Suara:** Dropdown yang memuat seluruh Voice Profile yang berstatus `ready`. Profil yang belum ready otomatis dinonaktifkan dengan keterangan informatif.
   - **Area Teks Input:** Textarea dengan penghitung karakter real-time (maksimum 1000 karakter, trim whitespace otomatis).
   - **Panel Konfigurasi Suara (Collapsible / Accordion):**
     - **Bahasa:** Tombol radio / segment control antara Bahasa Indonesia (`id`) dan Bahasa Inggris (`en`). Default: `id`.
     - **Kecepatan (Speed):** Slider rentang `0.5x` hingga `2.0x` (step 0.05). Default: `1.0x`.
     - **Pergeseran Nada (Pitch Shift):** Slider semitone rentang `-12` hingga `+12` (step 1). Default: `0`.
     - **Variasi Ekspresi (Temperature):** Slider rentang `0.1` hingga `1.0` (step 0.05). Default: `0.7`.
     - **Format Audio:** Terkunci pada `opus` sesuai batasan backend v1.
   - **Tombol Submit (Generate Voice):** Memanggil `POST /api/v1/tts/generate`. Tombol dinonaktifkan saat input teks kosong atau sedang memproses.
2. **Tabel Riwayat Job TTS:**
   - Menampilkan daftar job sintesis yang dikirim:
     - ID Job ringkas, teks masukan (dipotong dengan tooltip lengkap).
     - Nama Voice Profile yang digunakan.
     - Timestamp pembuatan.
     - Badge status: `queued` (kuning), `processing` (biru beranimasi), `completed` (hijau), `failed` (merah).
   - **Polling Dinamis:** Job yang berstatus `queued` atau `processing` otomatis di-poll setiap 1500ms via `GET /api/v1/tts/jobs/{job_id}` hingga final.
3. **Pemutar Audio Hasil (Waveform Player):**
   - Untuk job yang berstatus `completed`, tautan audio diarahkan ke `GET /api/v1/tts/jobs/{job_id}/audio`.
   - Menggunakan pemutar audio berbasis waveform (wavesurfer.js atau elemen audio HTML5 berdesain modern):
     - Tombol Play / Pause.
     - Bilah scrubbing durasi dan penunjuk waktu berjalan.
     - Tombol **Unduh Audio** (`.opus`).

---

### 5.3 Halaman 3: `/voice-changer` (Real-time Voice Changer)

Halaman paling interaktif dan krusial, menghubungkan mikrofon pengguna langsung ke pipa inferensi GPU real-time melalui WebSocket.

#### Komponen & Fitur
1. **Panel Kontrol Sesi:**
   - **Pemilihan Karakter Suara:** Dropdown Voice Profile berstatus `ready`.
   - **Tombol Utama (Mulai / Hentikan Sesi):**
     - State awal: Tombol hijau **Mulai Mengubah Suara**.
     - State memuat: Tombol dinonaktifkan dengan label **Menyiapkan Model...** (menutupi cold-start delay backend).
     - State aktif: Tombol merah **Hentikan Sesi**.
   - **Badge Status Koneksi:**
     - `Terputus`: Abu-abu.
     - `Menghubungkan`: Kuning berkedip.
     - `Aktif (Streaming)`: Hijau menyala.
     - `Reconnecting`: Oranye berkedip dengan timer mundur grace period 10 detik.
2. **Kontrol Parameter Real-time:**
   - **Live Pitch Shift Slider:** Slider rentang `-12` hingga `+12` semitone. Saat sesi aktif, pergeseran slider langsung mengirim pesan kontrol `update_settings` ke WebSocket tanpa memulai ulang sesi atau memuat ulang model.
   - **Pengaturan Buffer (Hanya saat sesi belum mulai):**
     - Sample rate whitelist dropdown: `16000`, `24000`, `44100`, `48000` Hz (default: `16000`).
     - Chunk duration slider: `10ms` hingga `100ms` (default: `30ms`).
3. **Penanganan Reconnection Otomatis (Grace Period 10 Detik):**
   - Jika koneksi WebSocket terputus tidak sengaja (event `close` bukan kode 1000):
     - Muncul banner peringatan mencolok: **"Koneksi jaringan terputus. Menyambung kembali... (X detik tersisa)"**.
     - Sistem mencoba melakukan `reconnect` secara agresif.
     - Mengirimkan pesan `init_session` dengan menyertakan `session_id` lama.
     - Jika berhasil (`session_ready` dengan `reconnected: true`), streaming audio langsung dilanjutkan tanpa reload model.
     - Jika 10 detik habis (menerima error `SESSION_EXPIRED` atau timeout), sistem merilis mikrofon dan mengembalikan antarmuka ke state idle.
4. **Penanganan Error Khusus & GPU Contention:**
   - Menampilkan modal peringatan informatif saat menerima kode error:
     - `GPU_BUSY`: "GPU sedang digunakan untuk memproses sintesis TTS atau sesi lain. Silakan tunggu sesaat."
     - `PROFILE_NOT_READY`: "Karakter suara belum siap digunakan."
     - `MODEL_LOAD_FAILED`: "Gagal memuat checkpoint model suara ke GPU."
5. **Visualisasi Audio Real-time:**
   - Visualisasi grafis level meter stereo/dual-bar:
     - Bar 1: **Input Mic Level** (RMS input audio pengguna dari mikrofon).
     - Bar 2: **Output Converted Level** (RMS output audio yang diterima dari backend).
   - Membantu pengguna memverifikasi bahwa mikrofon menangkap suara dan backend merespons balik audio konversi.
6. **Live Latency & Processing Metrics Display:**
   - Menampilkan metrik performa real-time dari pesan kontrol server `metrics`:
     - **Latency Total:** `latency_ms` (target: < 100ms).
     - **Durasi Komputasi GPU:** `processing_ms`.
     - Indikator kualitas sinyal (Hijau jika < 150ms, Kuning jika 150-300ms, Merah jika > 300ms).

---

## 6. Web Audio API & Streaming Pipeline Architecture

Alur pemrosesan audio di peramban dirancang dengan overhead komputasi minimal:

```text
[Mikrofon] 
    │ (Web Audio API MediaStream)
    ▼
[AudioContext @ 16kHz] ──▶ [AnalyserNode Input] ──▶ Level Meter Canvas
    │
    ▼ (AudioWorkletNode / ScriptProcessor)
[Float32 to Int16 PCM Chunk Converter]
    │ (ArrayBuffer biner, ~960 bytes per 30ms)
    ▼
[WebSocket wss://.../ws/voice-changer]
    │
    ▼ (Inference RVC pada GPU Server)
    │
    ▼ (ArrayBuffer biner balik)
[WebSocket onmessage (binary)]
    │
    ▼
[Int16 to Float32 Converter] ──▶ [Jitter Buffer Queue]
    │
    ▼
[AudioContext Destination (Speakers)] ──▶ [AnalyserNode Output] ──▶ Level Meter Canvas
```

### Spesifikasi Teknis Konversi PCM
- **Input Mic:** `channelCount: 1`, `sampleRate: 16000` (atau sesuai konfigurasi sesi), `echoCancellation: true`, `noiseSuppression: false`, `autoGainControl: false`.
- **Framing Biner:**
  Sampel audio Float32 dikuantisasi ke 16-bit integer bertanda (`Int16Array`, nilai -32768 hingga 32767).
  Formula ukuran byte per frame:
  $$\text{bytes} = \text{sample\_rate} \times \left(\frac{\text{chunk\_duration\_ms}}{1000}\right) \times 2$$
  Untuk setting default (16000 Hz, 30ms):
  $$\text{bytes} = 16000 \times 0.030 \times 2 = 960 \text{ bytes}$$
- **Anti-Glitch Playback:**
  Potongan audio yang kembali dijadwalkan secara presisi pada linimasa `AudioContext.currentTime` dengan buffer peredam jitter 1-2 frame untuk mencegah distorsi atau suara *choppy*.

---

## 7. UX & Antislop Compliance Guidelines

Sesuai dengan standar kualitas proyek yang didefinisikan dalam `AGENTS.md` dan panduan antislop:

1. **Gaya Penulisan & Copywriting:**
   - Tidak menggunakan kata-kata hampa AI (*AI slop*) seperti: "revolusioner", "seamless", "cutting-edge", "game-changer", "dive in".
   - Menggunakan bahasa yang lugas, komunikatif, dan berorientasi pada aksi nyata pengguna.
   - **Aturan Absolut:** Dilarang keras menggunakan karakter tanda em dash (`—`) di seluruh antarmuka, tooltip, pesan kesalahan, komentar kode, dan dokumentasi. Gunakan tanda titik dua (`:`), tanda hubung biasa (`-`), atau tanda kurung.
2. **Tata Letak & Aksesibilitas (Human First):**
   - Kontras warna teks memenuhi standar WCAG AA (rasio minimal 4.5:1 untuk teks normal).
   - Setiap elemen interaktif (tombol, slider, form) memiliki indikator fokus keyboard yang terlihat jelas (*focus-visible ring*).
   - Desain responsif dari ukuran layar desktop studio (1440px+) hingga laptop (1024px) dan tablet.
   - Status visual tidak hanya mengandalkan warna, tetapi didampingi label teks dan ikon deskriptif.

---

## 8. Kontrak Komunikasi WebSocket Detail

### Client ke Server
1. **`init_session` (Text JSON):**
   ```json
   {
     "type": "init_session",
     "voice_profile_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
     "session_id": "optional-uuid-for-reconnect",
     "settings": {
       "pitch_shift": 0,
       "sample_rate": 16000,
       "chunk_duration_ms": 30
     }
   }
   ```
2. **`audio_chunk` (Binary ArrayBuffer):**
   Kumpulan byte mentah PCM 16-bit mono berukuran genap.
3. **`update_settings` (Text JSON):**
   ```json
   {
     "type": "update_settings",
     "settings": {
       "pitch_shift": 2
     }
   }
   ```
4. **`close_session` (Text JSON):**
   ```json
   {
     "type": "close_session"
   }
   ```

### Server ke Client
1. **`session_ready` (Text JSON):**
   ```json
   {
     "type": "session_ready",
     "session_id": "40209df3-00d9-4d69-873b-eb8cfadbc67d",
     "reconnected": false
   }
   ```
2. **`audio_chunk` (Binary ArrayBuffer):**
   Audio PCM 16-bit mono hasil konversi RVC.
3. **`metrics` (Text JSON):**
   ```json
   {
     "type": "metrics",
     "latency_ms": 42.5,
     "processing_ms": 18.2
   }
   ```
4. **`error` (Text JSON):**
   ```json
   {
     "type": "error",
     "code": "GPU_BUSY",
     "message": "GPU sedang digunakan oleh sesi lain, coba lagi nanti."
   }
   ```
