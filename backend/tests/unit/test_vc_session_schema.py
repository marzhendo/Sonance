"""
Unit tests untuk Pydantic schemas dan protokol WebSocket voice changer.
Wave 2: Pydantic Schemas & Protokol Pesan WebSocket.
"""
import json
import uuid
import pytest
from pydantic import ValidationError


class TestVCSettings:
    """Pengujian untuk schema VCSettings."""

    def test_vc_settings_default_values(self):
        from backend.app.schemas.vc_session_schema import VCSettings

        settings = VCSettings()
        assert settings.pitch_shift == 0
        assert settings.sample_rate == 16000
        assert settings.chunk_duration_ms == 30

    @pytest.mark.parametrize("pitch", [-12, -6, 0, 6, 12])
    def test_vc_settings_valid_pitch_shift(self, pitch):
        from backend.app.schemas.vc_session_schema import VCSettings

        settings = VCSettings(pitch_shift=pitch)
        assert settings.pitch_shift == pitch

    @pytest.mark.parametrize("pitch", [-13, -20, 13, 24])
    def test_vc_settings_invalid_pitch_shift(self, pitch):
        from backend.app.schemas.vc_session_schema import VCSettings

        with pytest.raises(ValidationError):
            VCSettings(pitch_shift=pitch)

    @pytest.mark.parametrize("sr", [16000, 24000, 44100, 48000])
    def test_vc_settings_valid_sample_rate(self, sr):
        from backend.app.schemas.vc_session_schema import VCSettings

        settings = VCSettings(sample_rate=sr)
        assert settings.sample_rate == sr

    @pytest.mark.parametrize("sr", [8000, 11025, 22050, 32000, 96000])
    def test_vc_settings_invalid_sample_rate(self, sr):
        from backend.app.schemas.vc_session_schema import VCSettings

        with pytest.raises(ValidationError):
            VCSettings(sample_rate=sr)

    @pytest.mark.parametrize("duration", [10, 20, 30, 50, 100])
    def test_vc_settings_valid_chunk_duration(self, duration):
        from backend.app.schemas.vc_session_schema import VCSettings

        settings = VCSettings(chunk_duration_ms=duration)
        assert settings.chunk_duration_ms == duration

    @pytest.mark.parametrize("duration", [0, 5, 9, 101, 200])
    def test_vc_settings_invalid_chunk_duration(self, duration):
        from backend.app.schemas.vc_session_schema import VCSettings

        with pytest.raises(ValidationError):
            VCSettings(chunk_duration_ms=duration)


class TestVCSettingsUpdate:
    """Pengujian untuk schema pembaruan pengaturan VCSettingsUpdate."""

    def test_valid_settings_update(self):
        from backend.app.schemas.vc_session_schema import VCSettingsUpdate

        update = VCSettingsUpdate(pitch_shift=4)
        assert update.pitch_shift == 4

    def test_empty_settings_update_fails(self):
        from backend.app.schemas.vc_session_schema import VCSettingsUpdate

        with pytest.raises(ValidationError):
            VCSettingsUpdate()

    def test_extra_fields_forbidden(self):
        from backend.app.schemas.vc_session_schema import VCSettingsUpdate

        with pytest.raises(ValidationError):
            VCSettingsUpdate(pitch_shift=2, sample_rate=24000)  # sample_rate tidak boleh diubah live


class TestClientMessages:
    """Pengujian parsing dan validasi pesan Client -> Server."""

    def test_init_session_with_voice_profile(self):
        from backend.app.schemas.vc_session_schema import InitSessionMessage

        vp_id = uuid.uuid4()
        msg = InitSessionMessage(voice_profile_id=vp_id)
        assert msg.type == "init_session"
        assert msg.voice_profile_id == vp_id
        assert msg.settings.pitch_shift == 0
        assert msg.settings.sample_rate == 16000
        assert msg.settings.chunk_duration_ms == 30

    def test_init_session_with_custom_settings(self):
        from backend.app.schemas.vc_session_schema import InitSessionMessage, VCSettings

        vp_id = uuid.uuid4()
        msg = InitSessionMessage(
            voice_profile_id=vp_id,
            settings=VCSettings(pitch_shift=-3, sample_rate=24000, chunk_duration_ms=20),
        )
        assert msg.settings.pitch_shift == -3
        assert msg.settings.sample_rate == 24000
        assert msg.settings.chunk_duration_ms == 20

    def test_init_session_reconnect_with_session_id(self):
        from backend.app.schemas.vc_session_schema import InitSessionMessage

        sess_id = uuid.uuid4()
        msg = InitSessionMessage(session_id=sess_id)
        assert msg.session_id == sess_id

    def test_init_session_missing_both_identifiers_fails(self):
        from backend.app.schemas.vc_session_schema import InitSessionMessage

        with pytest.raises(ValidationError):
            InitSessionMessage()

    def test_update_settings_message(self):
        from backend.app.schemas.vc_session_schema import UpdateSettingsMessage, VCSettingsUpdate

        msg = UpdateSettingsMessage(settings=VCSettingsUpdate(pitch_shift=2))
        assert msg.type == "update_settings"
        assert msg.settings.pitch_shift == 2

    def test_close_session_message(self):
        from backend.app.schemas.vc_session_schema import CloseSessionMessage

        msg = CloseSessionMessage()
        assert msg.type == "close_session"

    def test_parse_client_message_polymorphism(self):
        from backend.app.schemas.vc_session_schema import (
            parse_client_message,
            InitSessionMessage,
            UpdateSettingsMessage,
            CloseSessionMessage,
        )

        vp_id = str(uuid.uuid4())
        # InitSession JSON string
        init_json = json.dumps({"type": "init_session", "voice_profile_id": vp_id})
        parsed_init = parse_client_message(init_json)
        assert isinstance(parsed_init, InitSessionMessage)
        assert str(parsed_init.voice_profile_id) == vp_id

        # UpdateSettings dict
        update_dict = {"type": "update_settings", "settings": {"pitch_shift": -2}}
        parsed_update = parse_client_message(update_dict)
        assert isinstance(parsed_update, UpdateSettingsMessage)
        assert parsed_update.settings.pitch_shift == -2

        # CloseSession JSON string
        close_json = json.dumps({"type": "close_session"})
        parsed_close = parse_client_message(close_json)
        assert isinstance(parsed_close, CloseSessionMessage)

    def test_parse_client_message_invalid_type_fails(self):
        from backend.app.schemas.vc_session_schema import parse_client_message

        with pytest.raises(ValidationError):
            parse_client_message({"type": "unknown_action"})


class TestServerMessages:
    """Pengujian parsing dan validasi pesan Server -> Client."""

    def test_session_ready_message(self):
        from backend.app.schemas.vc_session_schema import SessionReadyMessage

        s_id = uuid.uuid4()
        msg = SessionReadyMessage(session_id=s_id)
        assert msg.type == "session_ready"
        assert msg.session_id == s_id
        assert msg.reconnected is False

        reconnected_msg = SessionReadyMessage(session_id=s_id, reconnected=True)
        assert reconnected_msg.reconnected is True

    def test_metrics_message(self):
        from backend.app.schemas.vc_session_schema import MetricsMessage

        msg = MetricsMessage(latency_ms=85.4, processing_ms=42.1)
        assert msg.type == "metrics"
        assert msg.latency_ms == 85.4
        assert msg.processing_ms == 42.1

    def test_metrics_negative_value_fails(self):
        from backend.app.schemas.vc_session_schema import MetricsMessage

        with pytest.raises(ValidationError):
            MetricsMessage(latency_ms=-1.0, processing_ms=20.0)

    @pytest.mark.parametrize(
        "code",
        [
            "AUTH_FAILED",
            "PROFILE_NOT_FOUND",
            "PROFILE_NOT_READY",
            "GPU_BUSY",
            "INVALID_STATE",
            "INVALID_PAYLOAD",
            "MODEL_LOAD_FAILED",
            "INFERENCE_FAILED",
            "SESSION_EXPIRED",
        ],
    )
    def test_error_message_valid_codes(self, code):
        from backend.app.schemas.vc_session_schema import ErrorMessage, VCErrorCode

        msg = ErrorMessage(code=code, message=f"Error {code}")
        assert msg.type == "error"
        assert msg.code == VCErrorCode(code)
        assert msg.message == f"Error {code}"

    def test_error_message_invalid_code_fails(self):
        from backend.app.schemas.vc_session_schema import ErrorMessage

        with pytest.raises(ValidationError):
            ErrorMessage(code="UNSUPPORTED_ERROR_CODE", message="test")

    def test_parse_server_message_polymorphism(self):
        from backend.app.schemas.vc_session_schema import (
            parse_server_message,
            SessionReadyMessage,
            MetricsMessage,
            ErrorMessage,
        )

        s_id = str(uuid.uuid4())
        ready_json = json.dumps({"type": "session_ready", "session_id": s_id})
        parsed_ready = parse_server_message(ready_json)
        assert isinstance(parsed_ready, SessionReadyMessage)

        metrics_dict = {"type": "metrics", "latency_ms": 70.0, "processing_ms": 30.0}
        parsed_metrics = parse_server_message(metrics_dict)
        assert isinstance(parsed_metrics, MetricsMessage)

        error_json = json.dumps({"type": "error", "code": "GPU_BUSY", "message": "GPU sedang digunakan"})
        parsed_error = parse_server_message(error_json)
        assert isinstance(parsed_error, ErrorMessage)


class TestPCMFrameValidation:
    """Pengujian helper validasi byte frame audio PCM."""

    def test_calculate_expected_pcm_bytes(self):
        from backend.app.schemas.vc_session_schema import calculate_expected_pcm_bytes

        # 16000 Hz, 30 ms -> 16000 * 0.03 * 2 = 960 bytes
        assert calculate_expected_pcm_bytes(16000, 30) == 960
        # 24000 Hz, 20 ms -> 24000 * 0.02 * 2 = 960 bytes
        assert calculate_expected_pcm_bytes(24000, 20) == 960
        # 44100 Hz, 30 ms -> 44100 * 0.03 * 2 = 2646 bytes
        assert calculate_expected_pcm_bytes(44100, 30) == 2646
        # 48000 Hz, 40 ms -> 48000 * 0.04 * 2 = 3840 bytes
        assert calculate_expected_pcm_bytes(48000, 40) == 3840

    def test_validate_pcm_frame_success(self):
        from backend.app.schemas.vc_session_schema import validate_pcm_frame

        frame = b"\x00" * 960
        assert validate_pcm_frame(frame, sample_rate=16000, chunk_duration_ms=30) is True

    def test_validate_pcm_frame_invalid_length(self):
        from backend.app.schemas.vc_session_schema import validate_pcm_frame

        wrong_frame = b"\x00" * 900
        assert validate_pcm_frame(wrong_frame, sample_rate=16000, chunk_duration_ms=30) is False

    def test_validate_pcm_frame_odd_byte_length_rejected(self):
        from backend.app.schemas.vc_session_schema import validate_pcm_frame

        odd_frame = b"\x00" * 961
        assert validate_pcm_frame(odd_frame, sample_rate=16000, chunk_duration_ms=30) is False

    def test_validate_pcm_frame_empty_bytes_rejected(self):
        from backend.app.schemas.vc_session_schema import validate_pcm_frame

        assert validate_pcm_frame(b"", sample_rate=16000, chunk_duration_ms=30) is False

    def test_validate_pcm_frame_with_tolerance(self):
        from backend.app.schemas.vc_session_schema import validate_pcm_frame

        # Expected 960, actual 962 (difference 2 <= tolerance 4, even bytes)
        frame_962 = b"\x00" * 962
        assert validate_pcm_frame(frame_962, sample_rate=16000, chunk_duration_ms=30, tolerance_bytes=4) is True

        # Expected 960, actual 970 (difference 10 > tolerance 4)
        frame_970 = b"\x00" * 970
        assert validate_pcm_frame(frame_970, sample_rate=16000, chunk_duration_ms=30, tolerance_bytes=4) is False


class TestVCSessionResponse:
    """Pengujian untuk schema VCSessionResponse."""

    def test_vc_session_response_serialization(self):
        from datetime import datetime, timezone
        from backend.app.schemas.vc_session_schema import VCSessionResponse, VCSettings

        now = datetime.now(timezone.utc)
        s_id = uuid.uuid4()
        u_id = uuid.uuid4()
        vp_id = uuid.uuid4()

        resp = VCSessionResponse(
            id=s_id,
            user_id=u_id,
            voice_profile_id=vp_id,
            started_at=now,
            ended_at=None,
            avg_latency_ms=78.2,
            settings=VCSettings(pitch_shift=1),
        )
        assert resp.id == s_id
        assert resp.user_id == u_id
        assert resp.voice_profile_id == vp_id
        assert resp.avg_latency_ms == 78.2
        assert resp.settings.pitch_shift == 1
        assert resp.ended_at is None
