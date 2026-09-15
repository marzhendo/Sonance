# Requirements Document

## Introduction

Fitur ini memungkinkan pengguna membuat dan mengelola Voice Profile — entitas utama yang merepresentasikan satu karakter suara yang sudah di-clone. Alur utamanya adalah: pengguna mengupload satu file Sample Audio (format Opus, 10–30 detik), sistem membuat Voice Profile dengan status `pending`, kemudian pengguna men-trigger Training Job secara async. Training Job berjalan di queue dan bertransisi melalui lifecycle `pending → processing → ready / failed`. Pengguna dapat memantau status, serta melakukan operasi manajemen dasar: list, detail, rename, dan delete.

Fitur ini **tidak mencakup** TTS pipeline maupun real-time voice changer (diatur di spec terpisah).

---

## Glossary

- **Voice_Profile_Service**: Komponen backend yang menangani seluruh logika bisnis pengelolaan Voice Profile (buat, list, detail, rename, delete, cek status).
- **Training_Job_Service**: Komponen backend yang menangani dispatch, eksekusi, dan pembaruan status Training Job.
- **Voice_Profile_Router**: FastAPI router (`voice_profile_router.py`) yang meng-expose endpoint HTTP untuk Voice Profile Management.
- **Job_Queue**: Sistem antrian async (Celery/RQ + Redis) yang mengeksekusi Training Job di background.
- **Voice_Profile**: Entitas database (`voice_profiles`) yang merepresentasikan satu karakter suara. Berisi metadata, `sample_audio_path`, `model_checkpoint_path`, dan `status`.
- **Sample_Audio**: File audio Opus yang diupload user sebagai bahan training. Satu Voice Profile = satu Sample Audio. Durasi 10–30 detik, ukuran maksimum 10 MB.
- **Training_Job**: Entitas database (`training_jobs`) yang merepresentasikan proses async training. Relasi 1-to-1 dengan Voice Profile.
- **Model_Checkpoint**: File `.pth` (PyTorch) hasil Training Job, disimpan di `SONANCE_CHECKPOINT_DIR`.
- **Speaker_Embedding**: Vektor numerik karakteristik suara yang diekstrak selama proses training.
- **source_type**: Enum `own_voice` / `other_person` / `character` — memengaruhi pipeline training dan inference yang dipakai.
- **Pipeline_Router**: Komponen di dalam Training_Job_Service yang memilih pipeline training berdasarkan `source_type`. `own_voice` dan `other_person` → RVC pipeline; `character` → SVC pipeline.
- **Auth_Guard**: Middleware FastAPI yang memvalidasi API token pada setiap request.

---

## Requirements

### Requirement 1: Membuat Voice Profile dengan Upload Sample Audio

**User Story:** Sebagai pengguna, saya ingin mengupload sample audio dan membuat Voice Profile baru, sehingga saya dapat memulai proses voice cloning.

#### Acceptance Criteria

1. WHEN pengguna mengirim request `POST /api/v1/voice-profiles` dengan field `name`, `source_type`, dan file `sample_audio` (Opus, ukuran ≤ 10 MB), THE Voice_Profile_Service SHALL membuat record `voice_profiles` baru dengan `status = 'pending'` dan menyimpan file ke `SONANCE_SAMPLE_AUDIO_DIR`.

2. WHEN pembuatan Voice Profile berhasil, THE Voice_Profile_Service SHALL mengembalikan response HTTP 201 dengan representasi lengkap Voice Profile yang baru dibuat, termasuk `id`, `name`, `source_type`, `status`, `duration_seconds`, `created_at`, dan `updated_at`.

3. IF field `name` tidak disertakan, kosong, atau melebihi 255 karakter, THEN THE Voice_Profile_Router SHALL mengembalikan response HTTP 422 dengan pesan error yang mendeskripsikan constraint yang dilanggar.

4. IF field `source_type` tidak termasuk dalam nilai `own_voice`, `other_person`, atau `character`, THEN THE Voice_Profile_Router SHALL mengembalikan response HTTP 422 dengan pesan error yang menyebutkan nilai-nilai yang valid.

5. IF file `sample_audio` tidak dikirim, THEN THE Voice_Profile_Router SHALL mengembalikan response HTTP 422 dengan pesan error yang menyatakan bahwa file sample audio wajib disertakan.

6. IF file `sample_audio` memiliki format bukan Opus, THEN THE Voice_Profile_Service SHALL mengembalikan response HTTP 400 dengan pesan error yang menyatakan bahwa hanya format Opus yang diterima.

7. IF ukuran file `sample_audio` melebihi 10 MB, THEN THE Voice_Profile_Router SHALL mengembalikan response HTTP 422 dengan pesan error yang menyebutkan batas ukuran maksimum.

8. IF durasi file `sample_audio` kurang dari 10 detik atau lebih dari 30 detik, THEN THE Voice_Profile_Service SHALL mengembalikan response HTTP 400 dengan pesan error yang menyebutkan rentang durasi yang valid (10–30 detik).

9. WHEN file `sample_audio` berhasil divalidasi, THE Voice_Profile_Service SHALL mengekstrak dan menyimpan `duration_seconds` dari file tersebut ke record `voice_profiles`.

10. IF ekstraksi `duration_seconds` gagal karena file tidak dapat dibaca atau corrupt, THEN THE Voice_Profile_Service SHALL mengembalikan response HTTP 400 dengan pesan error yang menyatakan bahwa file tidak dapat diproses.

11. IF penyimpanan file ke `SONANCE_SAMPLE_AUDIO_DIR` gagal karena error I/O atau izin akses, THEN THE Voice_Profile_Service SHALL mengembalikan response HTTP 500 dan memastikan tidak ada record `voice_profiles` yang tersimpan di database (rollback).

---

### Requirement 2: Trigger Training Job

**User Story:** Sebagai pengguna, saya ingin men-trigger training untuk Voice Profile yang sudah dibuat, sehingga sistem dapat membangun Model Checkpoint dari Sample Audio saya.

#### Acceptance Criteria

1. WHEN pengguna mengirim request `POST /api/v1/voice-profiles/{id}/train` untuk Voice Profile dengan `status = 'pending'`, THE Training_Job_Service SHALL membuat record `training_jobs` baru dengan `status = 'queued'` dan men-dispatch job ke Job_Queue.

2. WHEN job berhasil di-dispatch ke Job_Queue, THE Voice_Profile_Router SHALL mengembalikan response HTTP 202 dengan `training_job_id` dan `status = 'queued'`.

3. IF Voice Profile dengan `{id}` tidak ditemukan, THEN THE Voice_Profile_Router SHALL mengembalikan response HTTP 404.

4. IF Voice Profile dengan `{id}` dimiliki oleh user lain, THEN THE Voice_Profile_Router SHALL mengembalikan response HTTP 404 (bukan 403, untuk menghindari enumerasi resource).

5. IF Voice Profile memiliki `status` selain `pending` saat request `POST /api/v1/voice-profiles/{id}/train` diterima, THEN THE Voice_Profile_Router SHALL mengembalikan response HTTP 409 dengan pesan error yang menyatakan bahwa training hanya bisa di-trigger pada Voice Profile dengan status `pending`.

6. WHEN Training Job dimulai oleh worker, THE Training_Job_Service SHALL mengupdate `voice_profiles.status` menjadi `processing` dan `training_jobs.status` menjadi `processing`, serta mencatat `training_jobs.started_at`.

7. WHEN Training Job selesai berhasil, THE Training_Job_Service SHALL mengupdate `voice_profiles.status` menjadi `ready`, menyimpan `model_checkpoint_path` ke record `voice_profiles`, mengupdate `training_jobs.status` menjadi `completed`, dan mencatat `training_jobs.completed_at`.

8. IF Training Job gagal di tengah eksekusi, THEN THE Training_Job_Service SHALL mengupdate `voice_profiles.status` menjadi `failed`, mengisi `voice_profiles.error_message` dengan ringkasan error (maksimum 500 karakter), mengupdate `training_jobs.status` menjadi `failed`, dan menyimpan stack trace lengkap ke `training_jobs.error_log`.

9. IF dispatch ke Job_Queue gagal setelah record `training_jobs` dibuat, THEN THE Training_Job_Service SHALL menghapus record `training_jobs` yang baru dibuat dan mengembalikan response HTTP 500 — `voice_profiles.status` tetap `pending`.

10. IF `source_type` adalah `own_voice` atau `other_person`, THEN THE Pipeline_Router SHALL menggunakan pipeline RVC untuk training. IF `source_type` adalah `character`, THEN THE Pipeline_Router SHALL menggunakan pipeline SVC untuk training.

---

### Requirement 3: Polling Status Voice Profile

**User Story:** Sebagai pengguna, saya ingin memantau status training Voice Profile saya, sehingga saya tahu kapan voice profile siap digunakan atau apakah training gagal.

#### Acceptance Criteria

1. WHEN pengguna mengirim request `GET /api/v1/voice-profiles/{id}/status`, THE Voice_Profile_Service SHALL mengembalikan response HTTP 200 dengan `id`, `status`, `error_message` (null jika tidak ada error), `training_job.status`, `training_job.progress_pct`, `training_job.started_at`, dan `training_job.completed_at`.

2. IF Voice Profile dengan `{id}` tidak ditemukan, THEN THE Voice_Profile_Router SHALL mengembalikan response HTTP 404.

3. IF Voice Profile dengan `{id}` dimiliki oleh user lain, THEN THE Voice_Profile_Router SHALL mengembalikan response HTTP 404 (bukan 403).

4. WHEN `voice_profiles.status` adalah `processing`, THE Voice_Profile_Service SHALL menyertakan nilai `training_jobs.progress_pct` terkini (0–100) dalam response.

5. WHEN `voice_profiles.status` adalah `failed`, THE Voice_Profile_Service SHALL menyertakan `error_message` yang tidak null dan `training_job.completed_at` yang null dalam response.

6. WHEN `voice_profiles.status` adalah `ready`, THE Voice_Profile_Service SHALL menyertakan `training_job.completed_at` yang tidak null dalam response.

---

### Requirement 4: List Voice Profile

**User Story:** Sebagai pengguna, saya ingin melihat daftar semua Voice Profile milik saya, sehingga saya dapat memilih profile yang ingin digunakan atau dikelola.

#### Acceptance Criteria

1. WHEN pengguna mengirim request `GET /api/v1/voice-profiles`, THE Voice_Profile_Service SHALL mengembalikan response HTTP 200 dengan array semua Voice Profile milik user yang terautentikasi, diurutkan berdasarkan `created_at` descending.

2. IF query database untuk list menghasilkan Voice Profile dari `user_id` yang berbeda dengan user yang terautentikasi, THEN THE Voice_Profile_Service SHALL mengembalikan response HTTP 403 — ownership isolation dianggap gagal.

3. WHEN tidak ada Voice Profile yang dimiliki user, THE Voice_Profile_Service SHALL mengembalikan response HTTP 200 dengan array kosong `[]`.

4. WHEN request `GET /api/v1/voice-profiles` berhasil, THE Voice_Profile_Service SHALL menyertakan setidaknya field `id`, `name`, `source_type`, `status`, `duration_seconds`, `created_at`, dan `updated_at` pada setiap item dalam array response. Field tambahan diperbolehkan.

---

### Requirement 5: Detail Voice Profile

**User Story:** Sebagai pengguna, saya ingin melihat detail lengkap satu Voice Profile, sehingga saya dapat mengetahui semua informasi dan status terkini dari profile tersebut.

#### Acceptance Criteria

1. WHEN pengguna mengirim request `GET /api/v1/voice-profiles/{id}`, THE Voice_Profile_Service SHALL mengembalikan response HTTP 200 dengan representasi lengkap Voice Profile yang mencakup `id`, `name`, `source_type`, `status`, `duration_seconds`, `error_message` (null jika tidak ada error), `created_at`, dan `updated_at`.

2. IF Voice Profile dengan `{id}` tidak ditemukan, THEN THE Voice_Profile_Router SHALL mengembalikan response HTTP 404 dengan pesan error yang menyatakan resource tidak ditemukan.

3. IF Voice Profile dengan `{id}` ditemukan tetapi dimiliki oleh user lain, THEN THE Voice_Profile_Router SHALL mengembalikan response HTTP 404 (bukan 403, untuk menghindari enumerasi resource).

4. IF request tidak menyertakan API token yang valid, THEN THE Auth_Guard SHALL mengembalikan response HTTP 401 sebelum pengecekan ownership dilakukan.

---

### Requirement 6: Rename Voice Profile

**User Story:** Sebagai pengguna, saya ingin mengganti nama Voice Profile saya, sehingga saya dapat mengorganisir profile dengan nama yang lebih deskriptif.

#### Acceptance Criteria

1. WHEN pengguna mengirim request `PATCH /api/v1/voice-profiles/{id}` dengan field `name` yang valid (1–100 karakter non-whitespace setelah di-trim), THE Voice_Profile_Service SHALL menyimpan `name` yang sudah di-trim, mengupdate `voice_profiles.updated_at`, lalu mengembalikan response HTTP 200 dengan representasi Voice Profile yang sudah diupdate.

2. IF field `name` tidak disertakan dalam request body, THEN THE Voice_Profile_Router SHALL mengembalikan response HTTP 422 dengan pesan error yang menyatakan bahwa field `name` wajib ada.

3. IF field `name` kosong, hanya berisi whitespace, atau kosong setelah di-trim, THEN THE Voice_Profile_Router SHALL mengembalikan response HTTP 422 dengan pesan error yang menyatakan bahwa nama tidak boleh kosong.

4. IF field `name` melebihi 100 karakter setelah di-trim, THEN THE Voice_Profile_Router SHALL mengembalikan response HTTP 422 dengan pesan error yang menyebutkan batas maksimum 100 karakter.

5. IF Voice Profile dengan `{id}` tidak ditemukan atau dimiliki oleh user lain, THEN THE Voice_Profile_Router SHALL mengembalikan response HTTP 404.

6. THE Voice_Profile_Service SHALL mempertahankan semua field lain (`source_type`, `status`, `sample_audio_path`, `model_checkpoint_path`, `duration_seconds`, `error_message`) tanpa perubahan saat melakukan rename.

---

### Requirement 7: Delete Voice Profile

**User Story:** Sebagai pengguna, saya ingin menghapus Voice Profile yang tidak lagi saya butuhkan, sehingga saya dapat mengelola storage dan mengurangi clutter.

#### Acceptance Criteria

1. WHEN pengguna mengirim request `DELETE /api/v1/voice-profiles/{id}` untuk Voice Profile yang ada dan dimilikinya, THE Voice_Profile_Service SHALL menghapus record `voice_profiles`, record `training_jobs` yang berelasi, file `sample_audio_path` (jika masih ada), dan file `model_checkpoint_path` (jika ada), lalu mengembalikan response HTTP 204.

2. IF Voice Profile dengan `{id}` tidak ditemukan atau dimiliki oleh user lain, THEN THE Voice_Profile_Router SHALL mengembalikan response HTTP 404.

3. IF Voice Profile memiliki `status = 'processing'` pada saat request DELETE diterima, THEN THE Voice_Profile_Service SHALL mengembalikan response HTTP 409 dengan pesan error yang menyatakan bahwa Voice Profile tidak dapat dihapus saat training sedang berlangsung.

4. IF file `sample_audio_path` atau `model_checkpoint_path` tidak ditemukan di filesystem saat proses delete, THEN THE Voice_Profile_Service SHALL tetap menghapus record database dan mengembalikan HTTP 204 tanpa error. IF terjadi error filesystem lain (permission denied, I/O error), THEN THE Voice_Profile_Service SHALL mengembalikan response HTTP 500 dan tidak menghapus record database.

5. IF request tidak menyertakan API token yang valid, THEN THE Auth_Guard SHALL mengembalikan response HTTP 401 sebelum pengecekan ownership atau status dilakukan.

---

### Requirement 8: Autentikasi pada Seluruh Endpoint

**User Story:** Sebagai pengguna, saya ingin semua endpoint Voice Profile Management dilindungi oleh autentikasi, sehingga hanya saya yang bisa mengakses dan mengelola profile saya.

#### Acceptance Criteria

1. WHEN request masuk ke salah satu dari endpoint `POST /api/v1/voice-profiles`, `GET /api/v1/voice-profiles`, `GET /api/v1/voice-profiles/{id}`, `PATCH /api/v1/voice-profiles/{id}`, `DELETE /api/v1/voice-profiles/{id}`, `POST /api/v1/voice-profiles/{id}/train`, atau `GET /api/v1/voice-profiles/{id}/status`, THE Auth_Guard SHALL memvalidasi bahwa API token hadir, bukan string kosong, dan sesuai dengan token yang dikonfigurasi di `SONANCE_API_TOKEN`.

2. IF request tidak menyertakan API token, menyertakan token kosong, atau menyertakan token yang tidak cocok dengan `SONANCE_API_TOKEN`, THEN THE Auth_Guard SHALL mengembalikan response HTTP 401 dengan pesan error yang menyatakan autentikasi gagal — request tidak diteruskan ke Voice_Profile_Router.

---

### Requirement 9: Isolasi Data Antar User

**User Story:** Sebagai pengguna, saya ingin data Voice Profile saya terisolasi dari pengguna lain, sehingga privasi dan keamanan data saya terjaga.

#### Acceptance Criteria

1. WHILE memproses request yang terautentikasi untuk operasi list, detail, rename, delete, training trigger, atau cek status, THE Voice_Profile_Service SHALL menyertakan filter `WHERE user_id = <user_id dari token>` pada seluruh query database yang mengakses tabel `voice_profiles` dan `training_jobs`.

2. IF `user_id` pada record Voice Profile yang ditemukan tidak sama dengan `user_id` yang diekstrak dari token autentikasi, THEN THE Voice_Profile_Service SHALL mengembalikan response HTTP 404 untuk operasi detail, rename, delete, training trigger, dan cek status — tidak mengekspos informasi bahwa resource tersebut ada.

3. WHEN operasi list dijalankan dan tidak ada Voice Profile dengan `user_id` yang cocok dengan token, THE Voice_Profile_Service SHALL mengembalikan response HTTP 200 dengan array kosong `[]` — bukan HTTP 404.
