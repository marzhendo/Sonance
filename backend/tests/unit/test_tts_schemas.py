"""
Tests untuk Pydantic schemas TTS Pipeline: TTSSettings, TTSGenerateRequest, TTSJobResponse, TTSJobStatusResponse.
Wave 2: Pydantic Schemas & Settings Validation.
"""
import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TestTTSSettings:

    def test_default_values(self):
        """TTSSettings memiliki default yang valid sesuai spesifikasi."""
        from backend.app.schemas.tts_job_schema import TTSSettings

        settings = TTSSettings()
        assert settings.language == "id"
        assert settings.speed == 1.0
        assert settings.pitch_shift == 0
        assert settings.temperature == 0.7
        assert settings.output_format == "opus"

    def test_valid_custom_values(self):
        """TTSSettings menerima nilai dalam rentang valid."""
        from backend.app.schemas.tts_job_schema import TTSSettings

        settings = TTSSettings(
            language="en",
            speed=1.5,
            pitch_shift=6,
            temperature=0.9,
            output_format="opus",
        )
        assert settings.language == "en"
        assert settings.speed == 1.5
        assert settings.pitch_shift == 6
        assert settings.temperature == 0.9
        assert settings.output_format == "opus"

    def test_boundary_values(self):
        """Nilai tepat pada batas min dan max diterima."""
        from backend.app.schemas.tts_job_schema import TTSSettings

        # Batas minimum
        s_min = TTSSettings(speed=0.5, pitch_shift=-12, temperature=0.1)
        assert s_min.speed == 0.5
        assert s_min.pitch_shift == -12
        assert s_min.temperature == 0.1

        # Batas maksimum
        s_max = TTSSettings(speed=2.0, pitch_shift=12, temperature=1.0)
        assert s_max.speed == 2.0
        assert s_max.pitch_shift == 12
        assert s_max.temperature == 1.0

    @pytest.mark.parametrize("invalid_lang", ["jp", "fr", "de", "", "ID", "EN"])
    def test_language_whitelist_rejection(self, invalid_lang):
        """Bahasa di luar whitelist ['id', 'en'] harus ditolak ValidationError."""
        from backend.app.schemas.tts_job_schema import TTSSettings

        with pytest.raises(ValidationError):
            TTSSettings(language=invalid_lang)

    @pytest.mark.parametrize("invalid_speed", [0.49, 2.01, -1.0, 0.0, 5.0])
    def test_speed_out_of_range_rejection(self, invalid_speed):
        """Speed di luar rentang [0.5, 2.0] harus ditolak."""
        from backend.app.schemas.tts_job_schema import TTSSettings

        with pytest.raises(ValidationError):
            TTSSettings(speed=invalid_speed)

    @pytest.mark.parametrize("invalid_pitch", [-13, 13, -24, 24])
    def test_pitch_shift_out_of_range_rejection(self, invalid_pitch):
        """Pitch shift di luar rentang [-12, 12] harus ditolak."""
        from backend.app.schemas.tts_job_schema import TTSSettings

        with pytest.raises(ValidationError):
            TTSSettings(pitch_shift=invalid_pitch)

    @pytest.mark.parametrize("invalid_temp", [0.09, 1.01, 0.0, -0.5, 2.0])
    def test_temperature_out_of_range_rejection(self, invalid_temp):
        """Temperature di luar rentang [0.1, 1.0] harus ditolak."""
        from backend.app.schemas.tts_job_schema import TTSSettings

        with pytest.raises(ValidationError):
            TTSSettings(temperature=invalid_temp)

    @pytest.mark.parametrize("invalid_format", ["mp3", "wav", "flac", "ogg", ""])
    def test_output_format_locked_to_opus(self, invalid_format):
        """Output format selain 'opus' harus ditolak."""
        from backend.app.schemas.tts_job_schema import TTSSettings

        with pytest.raises(ValidationError):
            TTSSettings(output_format=invalid_format)


class TestTTSGenerateRequest:

    def test_valid_request_with_defaults(self):
        """Request dengan teks valid dan voice_profile_id valid sukses."""
        from backend.app.schemas.tts_job_schema import TTSGenerateRequest

        vp_id = uuid.uuid4()
        req = TTSGenerateRequest(voice_profile_id=vp_id, text="Halo dunia")
        assert req.voice_profile_id == vp_id
        assert req.text == "Halo dunia"
        assert req.settings.language == "id"
        assert req.settings.output_format == "opus"

    def test_text_trimmed_automatically(self):
        """Whitespace di awal dan akhir teks otomatis di-trim."""
        from backend.app.schemas.tts_job_schema import TTSGenerateRequest

        req = TTSGenerateRequest(
            voice_profile_id=uuid.uuid4(),
            text="   Teks dengan spasi di awal dan akhir   ",
        )
        assert req.text == "Teks dengan spasi di awal dan akhir"

    def test_text_boundary_1_char(self):
        """Teks 1 karakter diterima."""
        from backend.app.schemas.tts_job_schema import TTSGenerateRequest

        req = TTSGenerateRequest(voice_profile_id=uuid.uuid4(), text="A")
        assert req.text == "A"

    def test_text_boundary_1000_chars(self):
        """Teks tepat 1000 karakter diterima."""
        from backend.app.schemas.tts_job_schema import TTSGenerateRequest

        text_1000 = "x" * 1000
        req = TTSGenerateRequest(voice_profile_id=uuid.uuid4(), text=text_1000)
        assert len(req.text) == 1000

    def test_text_boundary_1000_chars_after_trim(self):
        """Teks 1000 karakter dengan spasi luar tetap valid setelah trim."""
        from backend.app.schemas.tts_job_schema import TTSGenerateRequest

        padded = "   " + ("y" * 1000) + "   "
        req = TTSGenerateRequest(voice_profile_id=uuid.uuid4(), text=padded)
        assert len(req.text) == 1000

    def test_text_1001_chars_rejected(self):
        """Teks 1001 karakter ditolak ValidationError."""
        from backend.app.schemas.tts_job_schema import TTSGenerateRequest

        text_1001 = "x" * 1001
        with pytest.raises(ValidationError):
            TTSGenerateRequest(voice_profile_id=uuid.uuid4(), text=text_1001)

    @pytest.mark.parametrize("empty_text", ["", "   ", "\t", "\n\r", "   \t\n  "])
    def test_empty_or_whitespace_text_rejected(self, empty_text):
        """Teks kosong atau hanya spasi ditolak ValidationError."""
        from backend.app.schemas.tts_job_schema import TTSGenerateRequest

        with pytest.raises(ValidationError):
            TTSGenerateRequest(voice_profile_id=uuid.uuid4(), text=empty_text)

    def test_missing_voice_profile_id_rejected(self):
        """Request tanpa voice_profile_id ditolak."""
        from backend.app.schemas.tts_job_schema import TTSGenerateRequest

        with pytest.raises(ValidationError):
            TTSGenerateRequest(text="Halo dunia")

    def test_invalid_uuid_rejected(self):
        """voice_profile_id non-UUID ditolak."""
        from backend.app.schemas.tts_job_schema import TTSGenerateRequest

        with pytest.raises(ValidationError):
            TTSGenerateRequest(voice_profile_id="bukan-uuid", text="Halo dunia")

    def test_none_settings_falls_back_to_defaults(self):
        """settings=None otomatis menjadi TTSSettings default."""
        from backend.app.schemas.tts_job_schema import TTSGenerateRequest

        req = TTSGenerateRequest(
            voice_profile_id=uuid.uuid4(),
            text="Halo dunia",
            settings=None,
        )
        assert req.settings is not None
        assert req.settings.language == "id"


class TestTTSJobResponse:

    def test_tts_job_response_serialization(self):
        """TTSJobResponse mencakup semua field publik dan menyembunyikan output_audio_path."""
        from backend.app.schemas.tts_job_schema import TTSJobResponse, TTSSettings

        job_id = uuid.uuid4()
        vp_id = uuid.uuid4()
        now = utcnow()

        resp = TTSJobResponse(
            id=job_id,
            status="queued",
            input_text="Halo dunia",
            voice_profile_id=vp_id,
            settings=TTSSettings(),
            error_message=None,
            created_at=now,
            started_at=None,
            completed_at=None,
        )

        data = resp.model_dump()
        assert data["id"] == job_id
        assert data["status"] == "queued"
        assert data["input_text"] == "Halo dunia"
        assert data["voice_profile_id"] == vp_id
        assert data["settings"]["language"] == "id"
        assert "output_audio_path" not in data

        # job_id accessor kompatibel
        assert resp.job_id == job_id

    def test_tts_job_response_from_orm(self, db_session, make_tts_job):
        """TTSJobResponse dapat dibuat langsung dari ORM model TTSJob."""
        from backend.app.schemas.tts_job_schema import TTSJobResponse

        orm_job = make_tts_job(input_text="Halo dari ORM", status="queued")
        resp = TTSJobResponse.model_validate(orm_job)

        assert resp.id == orm_job.id
        assert resp.status == "queued"
        assert resp.input_text == "Halo dari ORM"
        assert resp.settings.language == "id"


class TestTTSJobStatusResponse:

    def test_status_response_invariant_non_failed_error_message_is_null(self):
        """error_message dipaksa null saat status bukan failed."""
        from backend.app.schemas.tts_job_schema import TTSJobStatusResponse, TTSSettings

        job_id = uuid.uuid4()
        vp_id = uuid.uuid4()
        now = utcnow()

        # Input mencoba memberikan error_message saat status=processing
        resp = TTSJobStatusResponse(
            id=job_id,
            status="processing",
            input_text="Teks polling",
            voice_profile_id=vp_id,
            settings=TTSSettings(),
            error_message="Seharusnya tidak ada pesan error",
            created_at=now,
            started_at=now,
            completed_at=None,
        )
        assert resp.error_message is None

    def test_status_response_invariant_failed_retains_error_message(self):
        """error_message dipertahankan saat status=failed."""
        from backend.app.schemas.tts_job_schema import TTSJobStatusResponse, TTSSettings

        job_id = uuid.uuid4()
        vp_id = uuid.uuid4()
        now = utcnow()

        resp = TTSJobStatusResponse(
            id=job_id,
            status="failed",
            input_text="Teks gagal",
            voice_profile_id=vp_id,
            settings=TTSSettings(),
            error_message="GPU out of memory",
            created_at=now,
            started_at=now,
            completed_at=now,
        )
        assert resp.error_message == "GPU out of memory"

    def test_status_response_invariant_completed_at_null_when_not_completed(self):
        """completed_at dipaksa null saat status belum completed (termasuk queued, processing, dan failed)."""
        from backend.app.schemas.tts_job_schema import TTSJobStatusResponse, TTSSettings

        now = utcnow()

        for st in ["queued", "processing", "failed"]:
            resp = TTSJobStatusResponse(
                id=uuid.uuid4(),
                status=st,
                input_text="Teks invariant",
                voice_profile_id=uuid.uuid4(),
                settings=TTSSettings(),
                error_message="Pesan error" if st == "failed" else None,
                created_at=now,
                started_at=now,
                completed_at=now,  # Mencoba mengisi completed_at
            )
            assert resp.completed_at is None, f"completed_at harus None saat status={st}"

    def test_status_response_invariant_completed_at_retained_when_completed(self):
        """completed_at dipertahankan saat status=completed."""
        from backend.app.schemas.tts_job_schema import TTSJobStatusResponse, TTSSettings

        now = utcnow()
        resp = TTSJobStatusResponse(
            id=uuid.uuid4(),
            status="completed",
            input_text="Teks selesai",
            voice_profile_id=uuid.uuid4(),
            settings=TTSSettings(),
            error_message=None,
            created_at=now,
            started_at=now,
            completed_at=now,
        )
        assert resp.completed_at == now

    def test_status_response_does_not_expose_audio_path(self):
        """TTSJobStatusResponse tidak mengekspos output_audio_path."""
        from backend.app.schemas.tts_job_schema import TTSJobStatusResponse, TTSSettings

        resp = TTSJobStatusResponse(
            id=uuid.uuid4(),
            status="completed",
            input_text="Teks selesai",
            voice_profile_id=uuid.uuid4(),
            settings=TTSSettings(),
            created_at=utcnow(),
        )
        data = resp.model_dump()
        assert "output_audio_path" not in data
