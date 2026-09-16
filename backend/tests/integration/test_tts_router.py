"""
Integration tests untuk TTS Router (/api/v1/tts/generate, /api/v1/tts/jobs/{job_id}, /api/v1/tts/jobs/{job_id}/audio).
Wave 4: Router Layer.
"""
import uuid
from datetime import datetime, timezone

import pytest

from backend.app.schemas.tts_job_schema import TTSJobStatus


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TestTTSGenerateEndpoint:

    def test_generate_success_returns_202(self, client, ready_voice_profile):
        """POST /api/v1/tts/generate berhasil mengembalikan 202 Accepted dan TTSJobResponse."""
        payload = {
            "voice_profile_id": str(ready_voice_profile.id),
            "text": "Halo dunia, ini adalah pengujian sintesis TTS endpoint.",
            "settings": {
                "language": "id",
                "speed": 1.1,
                "pitch_shift": 2,
                "temperature": 0.8,
            },
        }

        resp = client.post("/api/v1/tts/generate", json=payload)
        assert resp.status_code == 202

        data = resp.json()
        assert "id" in data
        assert data["status"] == "queued"
        assert data["input_text"] == "Halo dunia, ini adalah pengujian sintesis TTS endpoint."
        assert data["voice_profile_id"] == str(ready_voice_profile.id)
        assert data["settings"]["speed"] == 1.1
        assert "output_audio_path" not in data

    def test_generate_unauthorized_returns_401(self, unauth_client, ready_voice_profile):
        """POST /api/v1/tts/generate tanpa token autentikasi melempar 401 Unauthorized."""
        payload = {
            "voice_profile_id": str(ready_voice_profile.id),
            "text": "Teks tanpa auth",
        }
        resp = unauth_client.post("/api/v1/tts/generate", json=payload)
        assert resp.status_code == 401

    def test_generate_voice_profile_not_found_returns_404(self, client):
        """POST /api/v1/tts/generate dengan voice_profile_id fiktif melempar 404."""
        payload = {
            "voice_profile_id": str(uuid.uuid4()),
            "text": "Teks profile not found",
        }
        resp = client.post("/api/v1/tts/generate", json=payload)
        assert resp.status_code == 404

    def test_generate_other_user_voice_profile_returns_404(
        self, client, make_user, make_voice_profile
    ):
        """POST /api/v1/tts/generate dengan voice profile milik user lain melempar 404."""
        other = make_user()
        other_vp = make_voice_profile(user=other, status="ready")

        payload = {
            "voice_profile_id": str(other_vp.id),
            "text": "Teks isolasi kepemilikan",
        }
        resp = client.post("/api/v1/tts/generate", json=payload)
        assert resp.status_code == 404

    @pytest.mark.parametrize("invalid_status", ["pending", "processing", "failed"])
    def test_generate_voice_profile_not_ready_returns_409(
        self, client, make_voice_profile, test_user, invalid_status
    ):
        """POST /api/v1/tts/generate saat profil belum ready melempar 409 Conflict."""
        vp = make_voice_profile(user=test_user, status=invalid_status)

        payload = {
            "voice_profile_id": str(vp.id),
            "text": "Teks status non-ready",
        }
        resp = client.post("/api/v1/tts/generate", json=payload)
        assert resp.status_code == 409
        assert invalid_status in resp.json()["detail"]

    @pytest.mark.parametrize("empty_text", ["", "   ", "\t\n"])
    def test_generate_empty_text_returns_422(self, client, ready_voice_profile, empty_text):
        """POST /api/v1/tts/generate dengan teks kosong melempar 422 Unprocessable Content."""
        payload = {
            "voice_profile_id": str(ready_voice_profile.id),
            "text": empty_text,
        }
        resp = client.post("/api/v1/tts/generate", json=payload)
        assert resp.status_code == 422

    def test_generate_text_too_long_returns_422(self, client, ready_voice_profile):
        """POST /api/v1/tts/generate dengan teks > 1000 karakter melempar 422."""
        payload = {
            "voice_profile_id": str(ready_voice_profile.id),
            "text": "A" * 1001,
        }
        resp = client.post("/api/v1/tts/generate", json=payload)
        assert resp.status_code == 422

    def test_generate_invalid_settings_returns_422(self, client, ready_voice_profile):
        """POST /api/v1/tts/generate dengan settings di luar batas melempar 422."""
        payload = {
            "voice_profile_id": str(ready_voice_profile.id),
            "text": "Teks dengan setting invalid",
            "settings": {
                "speed": 5.0,  # Max 2.0
            },
        }
        resp = client.post("/api/v1/tts/generate", json=payload)
        assert resp.status_code == 422

    def test_generate_invalid_uuid_voice_profile_id_returns_422(self, client):
        """POST /api/v1/tts/generate dengan voice_profile_id bukan UUID melempar 422."""
        payload = {
            "voice_profile_id": "bukan-uuid-valid",
            "text": "Teks pengujian",
        }
        resp = client.post("/api/v1/tts/generate", json=payload)
        assert resp.status_code == 422




class TestTTSGetJobStatusEndpoint:

    def test_get_job_status_success_returns_200(self, client, test_user, make_tts_job):
        """GET /api/v1/tts/jobs/{job_id} mengembalikan 200 OK dan status job."""
        job = make_tts_job(user=test_user, status="processing")

        resp = client.get(f"/api/v1/tts/jobs/{job.id}")
        assert resp.status_code == 200

        data = resp.json()
        assert data["id"] == str(job.id)
        assert data["status"] == "processing"
        assert data["error_message"] is None
        assert "output_audio_path" not in data

    def test_get_job_status_unauthorized_returns_401(self, unauth_client, test_user, make_tts_job):
        """GET /api/v1/tts/jobs/{job_id} tanpa auth melempar 401."""
        job = make_tts_job(user=test_user)
        resp = unauth_client.get(f"/api/v1/tts/jobs/{job.id}")
        assert resp.status_code == 401

    def test_get_job_status_not_found_returns_404(self, client):
        """GET /api/v1/tts/jobs/{job_id} dengan id fiktif melempar 404."""
        resp = client.get(f"/api/v1/tts/jobs/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_get_job_status_other_user_returns_404(self, client, make_user, make_tts_job):
        """GET /api/v1/tts/jobs/{job_id} milik user lain melempar 404."""
        other = make_user()
        other_job = make_tts_job(user=other)

        resp = client.get(f"/api/v1/tts/jobs/{other_job.id}")
        assert resp.status_code == 404

    def test_get_job_status_failed_invariants(self, client, test_user, make_tts_job):
        """GET /api/v1/tts/jobs/{job_id} status failed menampilkan pesan error."""
        job = make_tts_job(
            user=test_user,
            status="failed",
            error_message="Gagal memproses model sintesis",
        )

        resp = client.get(f"/api/v1/tts/jobs/{job.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "failed"
        assert data["error_message"] == "Gagal memproses model sintesis"
        assert data["completed_at"] is None


class TestTTSGetAudioEndpoint:

    def test_get_audio_success_returns_200_stream(
        self, client, test_user, make_tts_job, tmp_path
    ):
        """GET /api/v1/tts/jobs/{job_id}/audio mengembalikan 200 dan binary audio/ogg."""
        audio_file = tmp_path / "result.opus"
        audio_content = b"OggS dummy binary opus stream content"
        audio_file.write_bytes(audio_content)

        job = make_tts_job(
            user=test_user,
            status="completed",
            output_audio_path=str(audio_file),
            completed_at=utcnow(),
        )

        resp = client.get(f"/api/v1/tts/jobs/{job.id}/audio")
        assert resp.status_code == 200
        assert "audio/ogg" in resp.headers["content-type"]
        assert f"tts_{job.id}.opus" in resp.headers.get("content-disposition", "")
        assert resp.content == audio_content

    def test_get_audio_unauthorized_returns_401(self, unauth_client, test_user, make_tts_job):
        """GET /api/v1/tts/jobs/{job_id}/audio tanpa auth melempar 401."""
        job = make_tts_job(user=test_user, status="completed")
        resp = unauth_client.get(f"/api/v1/tts/jobs/{job.id}/audio")
        assert resp.status_code == 401

    def test_get_audio_not_found_returns_404(self, client):
        """GET /api/v1/tts/jobs/{job_id}/audio id fiktif melempar 404."""
        resp = client.get(f"/api/v1/tts/jobs/{uuid.uuid4()}/audio")
        assert resp.status_code == 404

    def test_get_audio_other_user_returns_404(self, client, make_user, make_tts_job):
        """GET /api/v1/tts/jobs/{job_id}/audio milik user lain melempar 404."""
        other = make_user()
        other_job = make_tts_job(user=other, status="completed")

        resp = client.get(f"/api/v1/tts/jobs/{other_job.id}/audio")
        assert resp.status_code == 404

    @pytest.mark.parametrize("pending_status", ["queued", "processing"])
    def test_get_audio_in_progress_returns_409(
        self, client, test_user, make_tts_job, pending_status
    ):
        """GET /api/v1/tts/jobs/{job_id}/audio saat status belum selesai melempar 409."""
        job = make_tts_job(user=test_user, status=pending_status)

        resp = client.get(f"/api/v1/tts/jobs/{job.id}/audio")
        assert resp.status_code == 409
        assert "belum selesai" in resp.json()["detail"]

    def test_get_audio_failed_returns_409(self, client, test_user, make_tts_job):
        """GET /api/v1/tts/jobs/{job_id}/audio saat job gagal melempar 409."""
        job = make_tts_job(user=test_user, status="failed", error_message="Failure")

        resp = client.get(f"/api/v1/tts/jobs/{job.id}/audio")
        assert resp.status_code == 409
        assert "gagal" in resp.json()["detail"]

    def test_get_audio_missing_file_returns_500(self, client, test_user, make_tts_job):
        """GET /api/v1/tts/jobs/{job_id}/audio saat file fisik hilang melempar 500."""
        job = make_tts_job(
            user=test_user,
            status="completed",
            output_audio_path="/tmp/non_existent_audio_path.opus",
            completed_at=utcnow(),
        )

        resp = client.get(f"/api/v1/tts/jobs/{job.id}/audio")
        assert resp.status_code == 500
