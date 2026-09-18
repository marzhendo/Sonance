"""
Property-based tests dengan Hypothesis untuk Real-time Voice Changer.
Wave 7: Property-Based Testing.

Mencakup Property 1 sampai 4:
- Property 1: Validasi Settings (VCSettings: pitch_shift range, sample_rate whitelist, chunk_duration_ms range)
- Property 2: Invariant Byte Size Frame PCM (16-bit alignment formula, validate_pcm_frame exact vs deviation)
- Property 3: Invariant State Machine VCSessionManager (invalid transitions, lock pair symmetry, ended_at timestamp, non-ready profile rejection)
- Property 4: Auth Guard WebSocket (penolakan semua variasi token invalid dengan WS code 1008 sebelum accept)
"""
import asyncio
from datetime import timezone
import urllib.parse
import uuid
import pytest
from hypothesis import HealthCheck, given, settings, strategies as st
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from backend.app.core.gpu_manager import get_gpu_manager
from backend.app.models.vc_session_model import VCSession
from backend.app.schemas.vc_session_schema import (
    VCErrorCode,
    VCSettings,
    VCSettingsUpdate,
    calculate_expected_pcm_bytes,
    validate_pcm_frame,
)
from backend.app.services.vc_session_manager import (
    SessionState,
    VCSessionException,
    VCSessionManager,
    get_vc_session_manager,
)
from backend.ml.rvc import RVCRealtimePipeline
from backend.tests.conftest import TEST_TOKEN, TEST_USER_ID


@pytest.fixture(autouse=True)
def clean_resources():
    """Memastikan resource GPU dan manager selalu bersih."""
    gpu = get_gpu_manager()
    gpu.reset()
    manager = get_vc_session_manager()
    manager.reset()
    yield
    manager.reset()
    gpu.reset()


# ===========================================================================
# Property 1: Validasi Settings (VCSettings)
# ===========================================================================

class TestVCProperty1SettingsValidation:
    """Property-based testing untuk validasi skema VCSettings."""

    @settings(max_examples=30, deadline=None)
    @given(pitch=st.integers(min_value=-12, max_value=12))
    def test_property_1a_pitch_shift_valid_range_accepted(self, pitch):
        """Property 1a: Nilai pitch_shift dalam range [-12, 12] selalu diterima."""
        config = VCSettings(pitch_shift=pitch)
        assert config.pitch_shift == pitch

    @settings(max_examples=30, deadline=None)
    @given(pitch=st.one_of(st.integers(max_value=-13), st.integers(min_value=13)))
    def test_property_1b_pitch_shift_out_of_range_rejected(self, pitch):
        """Property 1b: Nilai pitch_shift di luar range [-12, 12] selalu ditolak ValidationError."""
        with pytest.raises(ValidationError):
            VCSettings(pitch_shift=pitch)

    @settings(max_examples=20, deadline=None)
    @given(sr=st.sampled_from([16000, 24000, 44100, 48000]))
    def test_property_1c_sample_rate_whitelist_accepted(self, sr):
        """Property 1c: Nilai sample_rate dalam whitelist [16000, 24000, 44100, 48000] selalu diterima."""
        config = VCSettings(sample_rate=sr)
        assert config.sample_rate == sr

    @settings(max_examples=30, deadline=None)
    @given(
        sr=st.integers(min_value=-1000, max_value=200000).filter(
            lambda x: x not in (16000, 24000, 44100, 48000)
        )
    )
    def test_property_1d_sample_rate_outside_whitelist_rejected(self, sr):
        """Property 1d: Nilai sample_rate di luar whitelist selalu ditolak ValidationError."""
        with pytest.raises(ValidationError):
            VCSettings(sample_rate=sr)

    @settings(max_examples=30, deadline=None)
    @given(dur=st.integers(min_value=10, max_value=100))
    def test_property_1e_chunk_duration_valid_range_accepted(self, dur):
        """Property 1e: Nilai chunk_duration_ms dalam range [10, 100] selalu diterima."""
        config = VCSettings(chunk_duration_ms=dur)
        assert config.chunk_duration_ms == dur

    @settings(max_examples=30, deadline=None)
    @given(dur=st.one_of(st.integers(max_value=9), st.integers(min_value=101)))
    def test_property_1f_chunk_duration_out_of_range_rejected(self, dur):
        """Property 1f: Nilai chunk_duration_ms di luar range [10, 100] selalu ditolak ValidationError."""
        with pytest.raises(ValidationError):
            VCSettings(chunk_duration_ms=dur)


# ===========================================================================
# Property 2: Invariant Byte Size Frame PCM
# ===========================================================================

class TestVCProperty2PCMFrameByteSize:
    """Property-based testing untuk formula ukuran byte frame dan validasi PCM."""

    @settings(max_examples=35, deadline=None)
    @given(
        sample_rate=st.sampled_from([16000, 24000, 44100, 48000]),
        chunk_duration_ms=st.integers(min_value=10, max_value=100),
    )
    def test_property_2a_expected_pcm_bytes_formula_and_16bit_alignment(
        self, sample_rate, chunk_duration_ms
    ):
        """
        Property 2a: Untuk semua kombinasi valid sample_rate dan chunk_duration_ms:
        - Hasil calculate_expected_pcm_bytes() selalu bernilai genap (% 2 == 0, 16-bit alignment).
        - Nilai sama persis dengan int(sample_rate * (chunk_duration_ms / 1000.0)) * 2.
        - Nilai selalu > 0.
        """
        expected = calculate_expected_pcm_bytes(sample_rate, chunk_duration_ms)
        assert expected > 0
        assert expected % 2 == 0
        assert expected == int(sample_rate * (chunk_duration_ms / 1000.0)) * 2

    @settings(max_examples=35, deadline=None)
    @given(
        sample_rate=st.sampled_from([16000, 24000, 44100, 48000]),
        chunk_duration_ms=st.integers(min_value=10, max_value=100),
    )
    def test_property_2b_validate_pcm_frame_exact_size_accepted(
        self, sample_rate, chunk_duration_ms
    ):
        """Property 2b: Frame audio PCM biner dengan ukuran persis sesuai formula selalu diterima."""
        expected_bytes = calculate_expected_pcm_bytes(sample_rate, chunk_duration_ms)
        frame = b"\x00" * expected_bytes
        assert validate_pcm_frame(frame, sample_rate, chunk_duration_ms) is True

    @settings(max_examples=35, deadline=None)
    @given(
        sample_rate=st.sampled_from([16000, 24000, 44100, 48000]),
        chunk_duration_ms=st.integers(min_value=10, max_value=100),
        offset=st.integers(min_value=-40, max_value=40).filter(lambda x: x != 0),
    )
    def test_property_2c_validate_pcm_frame_deviating_size_rejected(
        self, sample_rate, chunk_duration_ms, offset
    ):
        """Property 2c: Frame audio PCM dengan ukuran menyimpang dari expected selalu ditolak."""
        expected_bytes = calculate_expected_pcm_bytes(sample_rate, chunk_duration_ms)
        actual_len = max(0, expected_bytes + offset)
        frame = b"\x00" * actual_len
        assert validate_pcm_frame(frame, sample_rate, chunk_duration_ms, tolerance_bytes=0) is False

    @settings(max_examples=30, deadline=None)
    @given(
        sample_rate=st.sampled_from([16000, 24000, 44100, 48000]),
        chunk_duration_ms=st.integers(min_value=10, max_value=100),
        odd_len=st.integers(min_value=1, max_value=1000).filter(lambda x: x % 2 != 0),
    )
    def test_property_2d_validate_pcm_frame_odd_length_always_rejected(
        self, sample_rate, chunk_duration_ms, odd_len
    ):
        """Property 2d: Frame dengan panjang ganjil (melanggar 16-bit PCM alignment) selalu ditolak."""
        frame = b"\x00" * odd_len
        assert validate_pcm_frame(frame, sample_rate, chunk_duration_ms) is False


# ===========================================================================
# Property 3: Invariant State Machine VCSessionManager
# ===========================================================================

class TestVCProperty3StateMachineInvariants:
    """Property-based testing untuk siklus hidup state machine dan manajemen GPU lock."""

    @settings(max_examples=25, deadline=None)
    @given(random_id=st.uuids())
    def test_property_3a_invalid_state_audio_and_settings_rejected(self, random_id):
        """Property 3a: Pemrosesan audio chunk atau update settings pada sesi tak dikenal selalu ditolak INVALID_STATE."""
        manager = VCSessionManager()

        async def _run():
            with pytest.raises(VCSessionException) as exc_info1:
                await manager.handle_audio_chunk(random_id, b"\x00" * 960)
            assert exc_info1.value.code == VCErrorCode.INVALID_STATE

            with pytest.raises(VCSessionException) as exc_info2:
                await manager.handle_update_settings(random_id, {"pitch_shift": 2})
            assert exc_info2.value.code == VCErrorCode.INVALID_STATE

        asyncio.run(_run())

    @settings(max_examples=25, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
    @given(
        pitch=st.integers(min_value=-12, max_value=12),
        sample_rate=st.sampled_from([16000, 24000, 44100, 48000]),
    )
    def test_property_3b_lock_pair_symmetry_and_zero_leak(
        self, pitch, sample_rate, db_session, test_user, ready_voice_profile
    ):
        """
        Property 3b: GPU lock selalu ter-acquire saat inisialisasi dan selalu ter-release saat sesi berakhir.
        Tidak pernah terjadi kebocoran lock (lock leak) di akhir siklus hidup.
        """
        gpu = get_gpu_manager()
        manager = VCSessionManager(gpu_manager=gpu)

        async def _run():
            try:
                assert not gpu.is_locked()

                res = await manager.handle_init_session(
                    user_id=test_user.id,
                    voice_profile_id=ready_voice_profile.id,
                    settings=VCSettings(pitch_shift=pitch, sample_rate=sample_rate),
                    db=db_session,
                )
                session_id = res.session_id

                # Lock ter-acquire
                assert gpu.is_locked()
                assert gpu.get_holder() == str(session_id)

                # Tutup sesi
                await manager.handle_close_session(session_id, db=db_session)

                # Lock ter-release secara simetris
                assert not gpu.is_locked()
                assert gpu.get_holder() is None
            finally:
                db_session.query(VCSession).delete()
                db_session.commit()
                manager.reset()
                gpu.reset()

        asyncio.run(_run())

    @settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
    @given(normal_close=st.booleans())
    def test_property_3c_ended_at_timestamp_invariant(
        self, normal_close, db_session, test_user, ready_voice_profile
    ):
        """
        Property 3c: ended_at selalu None saat sesi aktif / grace period,
        dan selalu terisi timestamp valid setelah state bertransisi ke ENDED.
        """
        gpu = get_gpu_manager()
        manager = VCSessionManager(gpu_manager=gpu)

        async def _run():
            try:
                res = await manager.handle_init_session(
                    user_id=test_user.id,
                    voice_profile_id=ready_voice_profile.id,
                    db=db_session,
                )
                session_id = res.session_id
                state = manager.get_session(session_id)

                # Saat ACTIVE: ended_at harus None
                assert state.ended_at is None

                if normal_close:
                    await manager.handle_close_session(session_id, db=db_session)
                else:
                    manager.handle_disconnect(session_id, db=db_session)
                    assert state.state == SessionState.GRACE_PERIOD
                    assert state.ended_at is None
                    await manager.handle_grace_period_expired(session_id, db=db_session)

                # Saat ENDED: ended_at harus terisi timestamp valid
                assert state.state == SessionState.ENDED
                assert state.ended_at is not None
                s_end = state.ended_at if state.ended_at.tzinfo else state.ended_at.replace(tzinfo=timezone.utc)
                s_start = state.started_at if state.started_at.tzinfo else state.started_at.replace(tzinfo=timezone.utc)
                assert s_end >= s_start

                db_rec = db_session.get(VCSession, session_id)
                assert db_rec.ended_at is not None
                db_end = db_rec.ended_at if db_rec.ended_at.tzinfo else db_rec.ended_at.replace(tzinfo=timezone.utc)
                db_start = db_rec.started_at if db_rec.started_at.tzinfo else db_rec.started_at.replace(tzinfo=timezone.utc)
                assert db_end >= db_start
            finally:
                db_session.query(VCSession).delete()
                db_session.commit()
                manager.reset()
                gpu.reset()

        asyncio.run(_run())

    @settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
    @given(status_val=st.sampled_from(["pending", "failed"]))
    def test_property_3d_non_ready_profile_rejection_invariant(
        self, status_val, db_session, test_user, make_voice_profile
    ):
        """Property 3d: Profil suara non-ready selalu ditolak PROFILE_NOT_READY tanpa lock bocor."""
        gpu = get_gpu_manager()
        manager = VCSessionManager(gpu_manager=gpu)

        async def _run():
            vp = make_voice_profile(user=test_user, status=status_val, name=f"VP-{status_val}")
            try:
                with pytest.raises(VCSessionException) as exc_info:
                    await manager.handle_init_session(
                        user_id=test_user.id,
                        voice_profile_id=vp.id,
                        db=db_session,
                    )

                assert exc_info.value.code == VCErrorCode.PROFILE_NOT_READY
                assert not gpu.is_locked()
            finally:
                db_session.query(VCSession).delete()
                db_session.delete(vp)
                db_session.commit()
                manager.reset()
                gpu.reset()

        asyncio.run(_run())


# ===========================================================================
# Property 4: Auth Guard WebSocket
# ===========================================================================

class TestVCProperty4AuthGuard:
    """Property-based testing untuk auth guard rute WebSocket /ws/voice-changer."""

    @settings(max_examples=35, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
    @given(
        invalid_token=st.text(
            alphabet=st.characters(blacklist_categories=("Cs",)),
            max_size=60,
        ).filter(lambda t: t != TEST_TOKEN)
    )
    def test_property_4a_arbitrary_invalid_token_rejected_with_1008(
        self, invalid_token, client, monkeypatch
    ):
        """
        Property 4a: Untuk semua string token invalid acak yang di-generate Hypothesis,
        endpoint /ws/voice-changer selalu close dengan code 1008 sebelum accept().
        """
        monkeypatch.setenv("SONANCE_API_TOKEN", TEST_TOKEN)
        encoded_token = urllib.parse.quote(invalid_token, safe="")
        url = f"/ws/voice-changer?token={encoded_token}"

        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(url):
                pass

        assert exc_info.value.code == 1008
