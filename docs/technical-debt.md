# Technical Debt & Arsitektur Lanjutan Sonance

Dokumen ini mendokumentasikan seluruh technical debt dan penyederhanaan arsitektural yang sengaja diambil pada implementasi Sonance v1 (single-user, local GPU). Dokumen ini berfungsi sebagai referensi utama untuk fase pengembangan berikutnya (integrasi model AI asli, multi-proses, dan cloud scaling).

---

## 1. Ringkasan Technical Debt Berdasarkan Area

| Area | Status Saat Ini (v1) | Keterbatasan | Rekomendasi Solusi Fase Lanjutan |
|---|---|---|---|
| **GPU Lock Coordination** | In-memory singleton (`GPUResourceManager`) | Hanya berlaku dalam satu proses runtime Python. Tidak sinkron jika Uvicorn dijalankan dengan multiple workers (`--workers > 1`). | Distributed lock menggunakan Redis (`SET resource_name my_random_value NX PX 30000` atau Redlock). |
| **ML Training Pipeline** | Stub (`RVCPipeline`, `SVCPipeline`) | Mensimulasikan progres pelatihan (0-100%) dan menulis file checkpoint tiruan tanpa beban komputasi GPU sesungguhnya. | Integrasi library RVC asli berbasis PyTorch, ekstraksi fitur HuBERT/ContentVec, dan fine-tuning generator VITS. |
| **ML TTS Pipeline** | Stub (`XTTSPipeline`) | Menghasilkan file audio tiruan menggunakan format Opus tanpa pemrosesan teks akustik dan vocoder HiFi-GAN asli. | Integrasi model Coqui XTTS-v2 asli, conditioning speaker embedding dari sample audio, dan sintesis mel-spectrogram ke waveform. |
| **ML Real-time Voice Changer** | Stub (`RVCRealtimePipeline`) | Mensimulasikan latensi inferensi dan mengembalikan raw PCM chunk dengan modifikasi sederhana. | Integrasi model inferensi RVC v2 berbasis ONNX Runtime / TensorRT untuk latensi inferensi sub-30ms pada GPU. |
| **Storage Audio & Checkpoint** | Filesystem lokal (`Path`) | File disimpan pada direktori lokal server. Rentan terhadap skalabilitas horizontal dan keterbatasan disk lokal. | Integrasi S3 / Google Cloud Storage / MinIO dengan pre-signed URL untuk upload sample audio dan unduhan TTS. |
| **Autentikasi & Otorisasi** | Static Token Auth (ADR-001) | Menggunakan single static token (`SONANCE_API_TOKEN`) dan pemetaan user tunggal (`SONANCE_USER_ID`). | Multi-user JWT authentication, refresh token rotation, dan per-user resource isolation. |
| **Notifikasi Pelepasan GPU** | Polling backoff loop (30 menit) | Worker TTS melakukan polling berkala untuk mengecek ketersediaan GPU lock. | Event-driven notification menggunakan Redis Pub/Sub saat GPU lock dilepas oleh sesi voice changer. |

---

## 2. Rincian Teknis & Panduan Migrasi

### 2.1 Koordinasi GPU Lock Terdistribusi
- **Kondisi saat ini**:
  Implementasi di `backend/app/core/gpu_manager.py` menggunakan instance in-memory singleton.
- **Kebutuhan refactoring**:
  Ketika API server dijalankan dengan multi-worker cluster (misal: Gunicorn/Uvicorn dengan 4 workers) atau worker terpisah mesin:
  1. Ganti implementasi `acquire_lock()` dan `release_lock()` menggunakan Redis distributed lock dengan kepemilikan token unik.
  2. Implementasikan mekanisme heartbeat renewal background task agar lock tidak kedaluwarsa selama streaming voice changer aktif.

### 2.2 Integrasi Model Machine Learning Asli
- **Interface yang sudah siap**:
  Arsitektur backend telah mengunci abstraksi antarmuka pada `backend/ml/base.py`:
  - `TrainingPipeline`: `start_training(dataset_path, output_checkpoint_path, progress_callback)`
  - `TTSPipeline`: `load_model()`, `synthesize(text, voice_profile_path, output_path, settings)`
  - `VoiceConversionPipeline`: `load_model(checkpoint_path)`, `unload_model()`, `convert_chunk(pcm_bytes, settings)`
- **Langkah implementasi AI**:
  1. Buat implementasi konkret di sub-paket `backend/ml/rvc/` dan `backend/ml/xtts/` tanpa perlu mengubah service layer maupun router.
  2. Tambahkan pemeriksaan dependensi CUDA dan alokasi VRAM PyTorch (`torch.cuda.is_available()`, `torch.cuda.empty_cache()`).
  3. Konfigurasi path bobot model dasar pre-trained via environment variable (`SONANCE_RVC_MODEL_DIR`, `SONANCE_XTTS_MODEL_DIR`).

### 2.3 Abstraksi Penyimpanan File Storage
- **Kondisi saat ini**:
  Modul `backend/app/services/storage_audit.py` dan penyimpanan sample mengandalkan filesystem lokal.
- **Kebutuhan refactoring**:
  1. Buat abstraction layer `StorageBackend` (`LocalStorageBackend`, `S3StorageBackend`).
  2. Pertahankan utilitas konsistensi storage (`audit_storage_consistency`) untuk memverifikasi bucket cloud storage terhadap metadata database.

### 2.4 WebSocket Real-time Buffer Tuning
- **Kondisi saat ini**:
  Frame audio raw PCM diproses per chunk individual tanpa jitter buffer.
- **Kebutuhan pada jaringan publik**:
  1. Menambahkan ring buffer adaptif atau jitter buffer berukuran kecil (10-20ms) di sisi server untuk meredam network jitter saat klien streaming melalui koneksi internet nirkabel.
