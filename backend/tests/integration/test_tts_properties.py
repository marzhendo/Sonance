"""Property-based tests dengan Hypothesis untuk TTS Pipeline.
Wave 7: Property-Based Testing.
Mencakup Property 1 sampai 5:
- Property 1: Validasi Teks Input (acceptance 1-1000 char, rejection empty/whitespace/exotic whitespace/>1000 char)
- Property 2: Validasi Settings (language whitelist, speed/pitch_shift/temperature boundaries, output_format)
- Property 3: Rejection Profil Non-Ready (status pending/processing/failed ditolak 409 & zero DB leak)
- Property 4: Status Polling Invariants (error_message dan completed_at sesuai status)
- Property 5: Auth Guard HTTP 401 di 3 Endpoint TTS
"""
import uuid
from datetime import datetime, timezone
import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from backend.app.models.tts_job_model import TTSJob
from backend.app.schemas.tts_job_schema import (
    TTSGenerateRequest,
    TTSJobStatus,
    TTSJobStatusResponse,
    TTSSettings,
)
from backend.tests.conftest import TEST_TOKEN


# ===========================================================================
# Property 1: Validasi Teks Input
# ===========================================================================

class TestTTSProperty1TextInput:

    @settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
    @given(
        text=st.text(
            alphabet=st.characters(blacklist_categories=("Cs",)),
            min_size=1,
            max_size=1000,
        ).filter(lambda s: 1 <= len(s.strip()) <= 1000 and s.strip() != "")
    )
    def test_property_1_valid_text_accepted(
        self, text, client, ready_voice_profile, db_session, mock_queue
    ):
        """Property 1: Setiap string 1-1000 karakter non-whitespace selalu diterima dengan status 202."""
        try:
            payload = {
                "voice_profile_id": str(ready_voice_profile.id),
                "text": text,
            }
            resp = client.post("/api/v1/tts/generate", json=payload)
            assert resp.status_code == 202
            data = resp.json()
            assert data["status"] == "queued"
            assert data["input_text"] == text.strip()
            assert db_session.query(TTSJob).count() == 1
        finally:
            db_session.query(TTSJob).delete()
            db_session.commit()
            if hasattr(mock_queue, "enqueued_jobs"):
                mock_queue.enqueued_jobs.clear()

    @settings(max_examples=35, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
    @given(
        empty_text=st.text(
            alphabet=" \t\r\n\u00a0\u2000\u2001\u2002\u2003\u2009\u202f\u3000",
            min_size=0,
            max_size=50,
        )
    )
    def test_property_1_empty_or_whitespace_text_rejected_with_422(
        self, empty_text, client, ready_voice_profile, db_session
    ):
        """Property 1: String kosong atau hanya whitespace (termasuk unicode exotic) selalu ditolak 422."""
        payload = {
            "voice_profile_id": str(ready_voice_profile.id),
            "text": empty_text,
        }
        resp = client.post("/api/v1/tts/generate", json=payload)
        assert resp.status_code == 422
        assert db_session.query(TTSJob).count() == 0

    @settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
    @given(
        long_text=st.text(
            alphabet=st.characters(blacklist_categories=("Cs",)),
            min_size=1001,
            max_size=1300,
        ).filter(lambda s: len(s.strip()) > 1000)
    )
    def test_property_1_overlong_text_rejected_with_422(
        self, long_text, client, ready_voice_profile, db_session
    ):
        """Property 1: Teks lebih dari 1000 karakter setelah di-trim selalu ditolak 422 tanpa kebocoran DB."""
        payload = {
            "voice_profile_id": str(ready_voice_profile.id),
            "text": long_text,
        }
        resp = client.post("/api/v1/tts/generate", json=payload)
        assert resp.status_code == 422
        assert db_session.query(TTSJob).count() == 0


# ===========================================================================
# Property 2: Validasi Settings
# ===========================================================================

class TestTTSProperty2Settings:

    @settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
    @given(
        language=st.sampled_from(["id", "en"]),
        speed=st.floats(min_value=0.5, max_value=2.0, allow_nan=False, allow_infinity=False),
        pitch_shift=st.integers(min_value=-12, max_value=12),
        temperature=st.floats(min_value=0.1, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    def test_property_2_valid_settings_in_range_accepted(
        self, language, speed, pitch_shift, temperature, client, ready_voice_profile, db_session, mock_queue
    ):
        """Property 2: Konfigurasi settings dalam rentang valid selalu diterima 202."""
        try:
            payload = {
                "voice_profile_id": str(ready_voice_profile.id),
                "text": "Sintesis dengan konfigurasi yang valid.",
                "settings": {
                    "language": language,
                    "speed": speed,
                    "pitch_shift": pitch_shift,
                    "temperature": temperature,
                    "output_format": "opus",
                },
            }
            resp = client.post("/api/v1/tts/generate", json=payload)
            assert resp.status_code == 202
            data = resp.json()
            assert data["settings"]["language"] == language
            assert abs(data["settings"]["speed"] - speed) < 1e-4
            assert data["settings"]["pitch_shift"] == pitch_shift
            assert abs(data["settings"]["temperature"] - temperature) < 1e-4
        finally:
            db_session.query(TTSJob).delete()
            db_session.commit()
            if hasattr(mock_queue, "enqueued_jobs"):
                mock_queue.enqueued_jobs.clear()

    @settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
    @given(
        invalid_lang=st.text(
            alphabet=st.characters(min_codepoint=97, max_codepoint=122),
            min_size=1,
            max_size=8,
        ).filter(lambda s: s not in ["id", "en"])
    )
    def test_property_2_language_outside_whitelist_rejected(
        self, invalid_lang, client, ready_voice_profile, db_session
    ):
        """Property 2: Bahasa di luar whitelist ['id', 'en'] selalu ditolak 422."""
        payload = {
            "voice_profile_id": str(ready_voice_profile.id),
            "text": "Teks bahasa tidak valid",
            "settings": {"language": invalid_lang},
        }
        resp = client.post("/api/v1/tts/generate", json=payload)
        assert resp.status_code == 422
        assert db_session.query(TTSJob).count() == 0

    @settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
    @given(
        invalid_speed=st.one_of(
            st.floats(min_value=-10.0, max_value=0.49, allow_nan=False, allow_infinity=False),
            st.floats(min_value=2.01, max_value=50.0, allow_nan=False, allow_infinity=False),
        )
    )
    def test_property_2_speed_outside_range_rejected(
        self, invalid_speed, client, ready_voice_profile, db_session
    ):
        """Property 2: Speed di luar rentang [0.5, 2.0] selalu ditolak 422."""
        payload = {
            "voice_profile_id": str(ready_voice_profile.id),
            "text": "Teks pengujian speed",
            "settings": {"speed": invalid_speed},
        }
        resp = client.post("/api/v1/tts/generate", json=payload)
        assert resp.status_code == 422
        assert db_session.query(TTSJob).count() == 0

    @settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
    @given(
        invalid_pitch=st.one_of(
            st.integers(min_value=-100, max_value=-13),
            st.integers(min_value=13, max_value=100),
        )
    )
    def test_property_2_pitch_shift_outside_range_rejected(
        self, invalid_pitch, client, ready_voice_profile, db_session
    ):
        """Property 2: Pitch shift di luar rentang [-12, 12] selalu ditolak 422."""
        payload = {
            "voice_profile_id": str(ready_voice_profile.id),
            "text": "Teks pengujian pitch",
            "settings": {"pitch_shift": invalid_pitch},
        }
        resp = client.post("/api/v1/tts/generate", json=payload)
        assert resp.status_code == 422
        assert db_session.query(TTSJob).count() == 0

    @settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
    @given(
        invalid_temp=st.one_of(
            st.floats(min_value=-10.0, max_value=0.09, allow_nan=False, allow_infinity=False),
            st.floats(min_value=1.01, max_value=50.0, allow_nan=False, allow_infinity=False),
        )
    )
    def test_property_2_temperature_outside_range_rejected(
        self, invalid_temp, client, ready_voice_profile, db_session
    ):
        """Property 2: Temperature di luar rentang [0.1, 1.0] selalu ditolak 422."""
        payload = {
            "voice_profile_id": str(ready_voice_profile.id),
            "text": "Teks pengujian temperatur",
            "settings": {"temperature": invalid_temp},
        }
        resp = client.post("/api/v1/tts/generate", json=payload)
        assert resp.status_code == 422
        assert db_session.query(TTSJob).count() == 0

    @settings(max_examples=25, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
    @given(
        invalid_fmt=st.text(min_size=1, max_size=10).filter(lambda s: s != "opus")
    )
    def test_property_2_output_format_not_opus_rejected(
        self, invalid_fmt, client, ready_voice_profile, db_session
    ):
        """Property 2: output_format selain 'opus' selalu ditolak 422."""
        payload = {
            "voice_profile_id": str(ready_voice_profile.id),
            "text": "Teks pengujian format",
            "settings": {"output_format": invalid_fmt},
        }
        resp = client.post("/api/v1/tts/generate", json=payload)
        assert resp.status_code == 422
        assert db_session.query(TTSJob).count() == 0


# ===========================================================================
# Property 3: Rejection Voice Profile Non-Ready
# ===========================================================================

class TestTTSProperty3NonReadyProfileRejection:

    @settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
    @given(
        status_name=st.sampled_from(["pending", "processing", "failed"])
    )
    def test_property_3_non_ready_profile_rejected_with_409_and_zero_db_leak(
        self, status_name, client, test_user, make_voice_profile, db_session
    ):
        """Property 3: Voice profile dengan status non-ready selalu ditolak 409 tanpa ada record job dibuat."""
        vp = make_voice_profile(user=test_user, status=status_name)
        payload = {
            "voice_profile_id": str(vp.id),
            "text": "Teks untuk profil non-ready",
        }
        resp = client.post("/api/v1/tts/generate", json=payload)
        assert resp.status_code == 409
        data = resp.json()
        assert status_name in data["detail"]
        assert "belum siap" in data["detail"].lower()
        # Zero DB leak guarantee
        assert db_session.query(TTSJob).count() == 0


# ===========================================================================
# Property 4: Status Polling Invariants
# ===========================================================================

class TestTTSProperty4StatusPollingInvariants:

    @settings(max_examples=40, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
    @given(
        status_name=st.sampled_from(["queued", "processing", "completed", "failed"]),
        error_text=st.text(min_size=1, max_size=80).filter(lambda s: s.strip() != ""),
    )
    def test_property_4_status_polling_invariants(
        self, status_name, error_text, client, test_user, ready_voice_profile, make_tts_job, db_session
    ):
        """Property 4: error_message selalu None kecuali status failed, completed_at selalu None kecuali completed."""
        try:
            now_dt = datetime.now(timezone.utc)
            if status_name == "failed":
                err_msg = error_text
                comp_at = None
            elif status_name == "completed":
                err_msg = None
                comp_at = now_dt
            else:
                err_msg = None
                comp_at = None

            job = make_tts_job(
                user=test_user,
                voice_profile=ready_voice_profile,
                status=status_name,
                error_message=err_msg,
                completed_at=comp_at,
            )

            # 1. Verifikasi lewat endpoint HTTP GET /api/v1/tts/jobs/{job_id}
            resp = client.get(f"/api/v1/tts/jobs/{job.id}")
            assert resp.status_code == 200
            data = resp.json()

            assert data["id"] == str(job.id)
            assert data["status"] == status_name
            assert "output_audio_path" not in data

            if status_name == "failed":
                assert data["error_message"] == err_msg
                assert data["completed_at"] is None
            elif status_name == "completed":
                assert data["error_message"] is None
                assert data["completed_at"] is not None
            else:
                assert data["error_message"] is None
                assert data["completed_at"] is None

            # 2. Verifikasi schema model invariants secara langsung
            schema_obj = TTSJobStatusResponse.model_validate(job)
            if status_name == "failed":
                assert schema_obj.error_message == err_msg
                assert schema_obj.completed_at is None
            elif status_name == "completed":
                assert schema_obj.error_message is None
                assert schema_obj.completed_at is not None
            else:
                assert schema_obj.error_message is None
                assert schema_obj.completed_at is None
        finally:
            db_session.query(TTSJob).delete()
            db_session.commit()


# ===========================================================================
# Property 5: Auth Guard di 3 Endpoint TTS
# ===========================================================================

class TestTTSProperty5AuthGuard:

    @settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
    @given(
        raw_token=st.text(
            alphabet=st.characters(min_codepoint=32, max_codepoint=126),
            min_size=0,
            max_size=60,
        ).filter(lambda s: s.strip() != TEST_TOKEN),
        use_bearer=st.booleans(),
    )
    def test_property_5_all_tts_endpoints_reject_invalid_token_with_401(
        self, raw_token, use_bearer, unauth_client, monkeypatch
    ):
        """Property 5: Semua variasi token invalid selalu menghasilkan HTTP 401 di ketiga endpoint TTS."""
        monkeypatch.setenv("SONANCE_API_TOKEN", TEST_TOKEN)
        header_val = f"Bearer {raw_token}" if use_bearer else raw_token
        headers = {"Authorization": header_val} if raw_token else {}
        dummy_job_id = uuid.uuid4()

        responses = [
            unauth_client.post("/api/v1/tts/generate", json={}, headers=headers),
            unauth_client.get(f"/api/v1/tts/jobs/{dummy_job_id}", headers=headers),
            unauth_client.get(f"/api/v1/tts/jobs/{dummy_job_id}/audio", headers=headers),
        ]

        for r in responses:
            assert r.status_code == 401
            data = r.json()
            assert "detail" in data
