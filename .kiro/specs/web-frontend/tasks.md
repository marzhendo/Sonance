# Tasks: Sonance Web Frontend (Next.js)

## Overview

Implementasi antarmuka web Sonance mengikuti metodologi berjenjang (*Wave-based tracer-bullet slices*) dari fondasi infrastruktur, tipe data kontrak API, tata letak global, hingga tiga halaman fitur utama (`/profiles`, `/tts`, `/voice-changer`), diakhiri dengan integrasi Web Audio API, WebSocket streaming real-time, dan verifikasi akhir.

Setiap task didesain agar dapat diuji secara mandiri dengan unit testing dan mocking (*Mock Service Worker* atau mock Web Audio) sebelum dihubungkan ke backend Sonance lokal.

---

## Tasks

### Wave 0: Project Setup & Core Client Infrastructure
- [ ] 1. Inisialisasi Project Next.js dan Konfigurasi Dasar
  - [ ] 1.1 Setup Next.js 14+ (App Router), TypeScript, Tailwind CSS, dan ESLint di folder `frontend/`
    - Konfigurasi `tsconfig.json` dengan path alias `@/*`.
    - Setup Tailwind CSS dengan palette warna profesional, kontras tinggi, dan dark-mode support.
    - Setup dependencies: `@tanstack/react-query`, `lucide-react`, `clsx`, `tailwind-merge`, `sonner`.
    - _Blocked by: None (can start immediately)_
  - [ ] 1.2 Inisialisasi shadcn/ui dan Komponen Dasar
    - Setup CLI shadcn/ui: `button`, `dialog`, `input`, `slider`, `card`, `table`, `badge`, `tabs`, `progress`, `select`, `tooltip`, `alert`.
    - Verifikasi build awal `npm run build` berjalan mulus.
    - _Blocked by: Task 1.1_

### Wave 1: Contracts, Types & API Client Layer
- [ ] 2. TypeScript Interfaces & HTTP Client
  - [ ] 2.1 Buat deklarasi tipe data TypeScript di `frontend/lib/types.ts`
    - Tipe data Voice Profile: `VoiceProfile`, `VoiceProfileCreatePayload`, `VoiceProfileStatusResponse`, `VoiceProfileListResponse`.
    - Tipe data TTS: `TTSJob`, `TTSJobCreatePayload`, `TTSSettings`, `TTSJobResponse`.
    - Tipe data Voice Changer: `VCSettings`, `VCSessionResponse`, `VCClientMessage`, `VCServerMessage`, `VCMetrics`.
    - _Blocked by: Task 1.1_
  - [ ] 2.2 Buat HTTP API client wrapper di `frontend/lib/api-client.ts`
    - Injeksi otomatis header `Authorization: Bearer <token>` dari `localStorage`.
    - Penanganan terpusat respons HTTP `401 Unauthorized` dengan memicu event pembukaan dialog token.
    - Fungsi-fungsi helper: `fetchVoiceProfiles()`, `createVoiceProfile()`, `renameVoiceProfile()`, `deleteVoiceProfile()`, `trainVoiceProfile()`, `getVoiceProfileStatus()`, `generateTTS()`, `getTTSJob()`, `getTTSAudioUrl()`.
    - _Blocked by: Task 2.1_

### Wave 2: Shell Aplikasi, Navigasi & Auth Token Modal
- [ ] 3. Global Layout, Navigasi & Manajemen Token
  - [ ] 3.1 Implementasi context dan hook `useAuth` di `frontend/hooks/useAuth.ts`
    - Membaca dan menyimpan `sonance_api_token` di `localStorage`.
    - Sinkronisasi reaktif ke seluruh komponen saat token berubah.
    - _Blocked by: Task 2.2_
  - [ ] 3.2 Buat komponen navigasi `Navbar.tsx` dan `AuthTokenModal.tsx` di `frontend/components/`
    - Navbar responsif dengan tautan ke `/profiles`, `/tts`, dan `/voice-changer`.
    - Indikator status ketersediaan token (ikon gembok hijau jika terisi, merah jika kosong).
    - Modal konfigurasi token dengan validasi input, simpan ke `localStorage`, dan notifikasi toast sukses via Sonner.
    - _Blocked by: Task 3.1_
  - [ ] 3.3 Konfigurasi `app/layout.tsx` dan Beranda Ringkasan `app/page.tsx`
    - Integrasi `QueryClientProvider` dari TanStack Query dengan default options (`staleTime: 5000`, `retry: 1`).
    - Mount `Toaster` dari Sonner dan komponen `Navbar`.
    - Beranda menampilkan kartu navigasi ringkas ke tiga fitur utama.
    - _Blocked by: Task 3.2_

### Wave 3: Feature 1 - `/profiles` Voice Profile Management
- [ ] 4. Halaman Voice Profile Management
  - [ ] 4.1 Buat hook `useVoiceProfiles.ts` di `frontend/hooks/useVoiceProfiles.ts`
    - Query untuk memuat daftar profil suara dengan pagination dan filter pencarian.
    - Mutasi untuk `create`, `rename`, `delete`, dan `train`.
    - Query dinamis dengan `refetchInterval` (2000ms) untuk status training saat profil berstatus `processing`.
    - Invalidation query otomatis saat aksi berhasil.
    - _Blocked by: Task 2.2_
  - [ ] 4.2 Komponen UI Profil: `ProfileCard.tsx`, `CreateProfileDialog.tsx`, `RenameProfileDialog.tsx`
    - Kartu profil menampilkan nama, sumber (`own_voice`/`other_person`/`character`), durasi audio, badge status (`pending`/`processing`/`ready`/`failed`), dan bilah progres pelatihan.
    - Dialog pembuatan profil dengan input nama, dropdown sumber suara, dan file upload dropzone (validasi tipe file audio dan durasi 5-300 detik via elemen audio HTML5).
    - Dialog ubah nama dan dialog konfirmasi hapus permanen.
    - _Blocked by: Task 4.1_
  - [ ] 4.3 Integrasi Halaman `app/profiles/page.tsx`
    - Grid responsif daftar profil, tombol "Tambah Profil Baru", state kosong (*empty state*), dan indikator loading (*skeleton*).
    - Uji alur: upload sample -> klik Latih Sekarang -> lihat progress bar bergerak dari 0% ke 100% -> status berubah menjadi Ready.
    - _Blocked by: Task 4.2_

### Wave 4: Feature 2 - `/tts` Text-to-Speech Pipeline
- [ ] 5. Halaman TTS Pipeline & Riwayat Sintesis
  - [ ] 5.1 Buat hook `useTTS.ts` di `frontend/hooks/useTTS.ts`
    - Query untuk mengambil daftar Voice Profile yang berstatus `ready` sebagai opsi suara.
    - Mutasi untuk mengirim job sintesis `POST /api/v1/tts/generate`.
    - Polling interval (1500ms) untuk memantau job yang berstatus `queued` atau `processing`.
    - _Blocked by: Task 2.2_
  - [ ] 5.2 Komponen Form Sintesis `TTSGenerateForm.tsx`
    - Dropdown profil suara (hanya profil ready).
    - Textarea input teks dengan live character counter (maks 1000 karakter).
    - Slider pengaturan suara: bahasa (`id`/`en`), kecepatan (`0.5x` - `2.0x`), pitch shift (`-12` - `+12`), dan temperature (`0.1` - `1.0`).
    - Tombol Submit dengan indikator loading.
    - _Blocked by: Task 5.1_
  - [ ] 5.3 Komponen Pemutar Audio `WaveformPlayer.tsx` & Tabel Riwayat `TTSHistoryTable.tsx`
    - Tabel riwayat menampilkan cuplikan teks, karakter suara, tanggal, badge status (`queued`/`processing`/`completed`/`failed`).
    - Pemutar audio terintegrasi untuk job `completed` (tombol play/pause, seekbar, waktu durasi, dan tombol download audio Opus).
    - _Blocked by: Task 5.2_
  - [ ] 5.4 Integrasi Halaman `app/tts/page.tsx`
    - Layout split-view atau bertumpuk: Form generator di sisi kiri/atas, riwayat job di sisi kanan/bawah.
    - _Blocked by: Task 5.3_

### Wave 5: Web Audio API & Audio Helpers Infrastructure
- [ ] 6. Utilitas Audio & Penangkapan Mikrofon
  - [ ] 6.1 Buat library utilitas `frontend/lib/audio-helpers.ts`
    - Konversi Float32Array (-1.0 s/d 1.0) menjadi Int16Array PCM mentah (-32768 s/d 32767).
    - Konversi Int16Array PCM mentah kembali ke Float32Array untuk playback audio.
    - Kalkulasi level volume Root Mean Square (RMS) dan nilai desibel (dB) untuk indikator visualizer.
    - Kalkulasi ukuran byte frame: `sample_rate * (chunk_duration_ms / 1000) * 2`.
    - Unit tests untuk seluruh fungsi konversi audio di `frontend/lib/audio-helpers.test.ts`.
    - _Blocked by: Task 1.1_
  - [ ] 6.2 Buat custom hook `useAudioCapture.ts` di `frontend/hooks/useAudioCapture.ts`
    - Akses mikrofon peramban via `navigator.mediaDevices.getUserMedia`.
    - Setup `AudioContext` dengan sample rate yang dipilih (default 16000 Hz).
    - Perekaman chunk per durasi (default 30ms) dan pengiriman callback frame biner `ArrayBuffer`.
    - Ekstraksi data audio input untuk visualizer level meter.
    - _Blocked by: Task 6.1_

### Wave 6: WebSocket Client & Reconnection Hook
- [ ] 7. Real-time Voice Changer WebSocket Client
  - [ ] 7.1 Buat hook `useVoiceChangerSocket.ts` di `frontend/hooks/useVoiceChangerSocket.ts`
    - Pengelolaan koneksi WebSocket ke `/ws/voice-changer?token={token}`.
    - State Machine: `DISCONNECTED`, `CONNECTING`, `CONNECTED`, `INITIALIZING`, `ACTIVE`, `GRACE_PERIOD`, `ENDED`.
    - Protokol dual-framing:
      - Pengiriman kontrol JSON: `init_session`, `update_settings`, `close_session`.
      - Pengiriman audio biner `ArrayBuffer` (raw PCM 16-bit).
      - Penerimaan respon JSON: `session_ready`, `metrics`, `error`.
      - Penerimaan audio biner hasil konversi untuk diteruskan ke playback buffer.
    - _Blocked by: Task 6.2_
  - [ ] 7.2 Implementasi Grace Period 10 Detik & Logika Rekoneksi Otomatis
    - Mendeteksi koneksi terputus tidak sengaja (kode penutupan selain 1000).
    - Transisi ke state `GRACE_PERIOD` dengan timer hitung mundur 10 detik.
    - Upaya koneksi ulang otomatis dan pengiriman `init_session` dengan `session_id` yang sedang aktif.
    - Melanjutkan sesi secara mulus saat menerima `session_ready` (`reconnected: true`).
    - Menghentikan upaya dan merilis resource jika grace period habis atau server mengirim `SESSION_EXPIRED`.
    - _Blocked by: Task 7.1_
  - [ ] 7.3 Pemutar Audio Balik Rendah Latensi (*Playback Queue*)
    - Menjadwalkan chunk audio Float32 yang diterima pada linimasa `AudioContext.currentTime`.
    - Buffer adaptif mini (1-2 frame) untuk meredam jitter jaringan tanpa menambah latency yang terasa.
    - Ekstraksi data audio output untuk visualizer level meter.
    - _Blocked by: Task 7.2_

### Wave 7: Feature 3 - `/voice-changer` Real-time UI
- [ ] 8. Halaman Real-time Voice Changer
  - [ ] 8.1 Komponen Kontrol `VCControlPanel.tsx` dan `VCMetricsDisplay.tsx`
    - Dropdown pemilihan Voice Profile (hanya yang berstatus ready).
    - Pengaturan awal: dropdown `sample_rate` (16k, 24k, 44.1k, 48k) dan slider `chunk_duration_ms` (10-100ms).
    - Slider Live Pitch Shift (-12 s/d +12 semitone) yang mengirim `update_settings` secara live saat digeser.
    - Tombol utama Mulai / Berhenti dengan indikator "Menyiapkan model..." saat cold-start.
    - Panel metrik live: `latency_ms` dan `processing_ms` dengan indikator warna kualitas sinyal.
    - _Blocked by: Task 7.3_
  - [ ] 8.2 Komponen Visualizer `VCAudioVisualizer.tsx` dan Banner `VCReconnectionBanner.tsx`
    - Komponen Canvas level meter audio dual-bar (Input Mic Level vs Output Converted Level).
    - Banner peringatan rekoneksi dengan animasi dan timer mundur 10 detik saat terputus.
    - Modal dialog informatif untuk error `GPU_BUSY`, `PROFILE_NOT_READY`, atau `MODEL_LOAD_FAILED`.
    - _Blocked by: Task 8.1_
  - [ ] 8.3 Integrasi Halaman `app/voice-changer/page.tsx`
    - Menggabungkan kontrol sesi, visualizer, pemutar playback, dan penanganan error.
    - Uji alur end-to-end: pilih profil -> klik Mulai -> izinkan mic -> bicara -> dengarkan audio terkonversi -> geser pitch shift live -> simulasi putus jaringan -> verifikasi rekoneksi sukses.
    - _Blocked by: Task 8.2_

### Wave 8: Checkpoint Final & Verifikasi Komprehensif
- [ ] 9. Checkpoint Final Web Frontend
  - [ ] 9.1 Verifikasi fungsional end-to-end lintas 3 halaman terhadap backend lokal aktif
    - `/profiles`: Buat profil, unggah audio, latih sampai ready, ganti nama, hapus.
    - `/tts`: Sintesis teks ke audio, polling status, putar audio di pemutar waveform, unduh berkas Opus.
    - `/voice-changer`: Streaming suara mic, pemutaran suara hasil konversi real-time, pergeseran nada live, verifikasi penolakan `GPU_BUSY` saat TTS job berjalan.
  - [ ] 9.2 Audit Kepatuhan Antislop & Aksesibilitas
    - Verifikasi tidak ada karakter em dash (`—`) di seluruh file kode, UI copy, dan komentar.
    - Verifikasi kontras warna WCAG AA dan navigasi keyboard di seluruh komponen form/dialog.
  - [ ] 9.3 Build & Production Optimization
    - Jalankan `npm run build` dan pastikan zero build errors, zero type errors.
    - Periksa bundle size dan pastikan code splitting halaman berjalan optimal.
  - [ ] 9.4 Dokumentasi Penggunaan di `README.md`
    - Tambahkan instruksi instalasi frontend (`cd frontend && npm install && npm run dev`).
    - Konfigurasi environment variables frontend (`NEXT_PUBLIC_SONANCE_API_URL`, `NEXT_PUBLIC_SONANCE_WS_URL`).
    - _Blocked by: Task 9.1, 9.2, 9.3_

---

## Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["2.1", "2.2"] },
    { "id": 2, "tasks": ["3.1", "3.2", "3.3"] },
    { "id": 3, "tasks": ["4.1", "4.2", "4.3"] },
    { "id": 4, "tasks": ["5.1", "5.2", "5.3", "5.4"] },
    { "id": 5, "tasks": ["6.1", "6.2"] },
    { "id": 6, "tasks": ["7.1", "7.2", "7.3"] },
    { "id": 7, "tasks": ["8.1", "8.2", "8.3"] },
    { "id": 8, "tasks": ["9.1", "9.2", "9.3", "9.4"] }
  ]
}
```
