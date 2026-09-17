"""
Unit tests untuk service layer VCSessionManager (backend/app/services/vc_session_manager.py).
Wave 5: Session Manager & Service Layer.
"""
import asyncio
import uuid
import pytest

from backend.app.core.gpu_manager import get_gpu_manager
from backend.app.models.vc_session_model import VCSession
from backend.app.schemas.vc_session_schema import (
    VCErrorCode,
    VCSettings,
    VCSettingsUpdate,
    calculate_expected_pcm_bytes,
)
from backend.app.services.vc_session_manager import (
    SessionState,
    VCSessionException,
    VCSessionManager,
)
from backend.ml.rvc import RVCRealtimePipeline


@pytest.fixture(autouse=True)
def clean_gpu():
    """Memastikan GPU resource manager dalam keadaan reset sebelum dan sesudah tiap test."""
    gpu = get_gpu_manager()
    gpu.reset()
    yield
    gpu.reset()


@pytest.fixture
def manager():
    """Instance VCSessionManager dengan timer grace period singkat untuk testing."""
    mgr = VCSessionManager(grace_period_sec=0.05)
    yield mgr
    mgr.reset()


@pytest.mark.asyncio
class TestVCSessionManagerLifecycle:
    """Pengujian siklus hidup state machine sesi voice changer."""

    async def test_init_session_success_creates_session_and_acquires_gpu_lock(
        self, manager, db_session, test_user, ready_voice_profile
    ):
        """Inisialisasi sesi baru berhasil: acquire GPU lock, load model, insert DB, status ACTIVE."""
        gpu = get_gpu_manager()
        assert not gpu.is_locked()

        result = await manager.handle_init_session(
            user_id=test_user.id,
            voice_profile_id=ready_voice_profile.id,
            settings=VCSettings(pitch_shift=3),
            db=db_session,
        )

        assert result.session_id is not None
        assert result.reconnected is False
        assert gpu.is_locked()
        assert gpu.get_holder() == str(result.session_id)

        session_state = manager.get_session(result.session_id)
        assert session_state is not None
        assert session_state.state == SessionState.ACTIVE
        assert session_state.pipeline.is_loaded()
        assert session_state.settings.pitch_shift == 3

        db_rec = db_session.get(VCSession, result.session_id)
        assert db_rec is not None
        assert db_rec.user_id == test_user.id
        assert db_rec.voice_profile_id == ready_voice_profile.id
        assert db_rec.started_at is not None
        assert db_rec.ended_at is None
        assert db_rec.settings["pitch_shift"] == 3

    async def test_disconnect_transitions_to_grace_period_and_keeps_gpu_lock(
        self, manager, db_session, test_user, ready_voice_profile
    ):
        """Saat soket terputus, sesi beralih ke GRACE_PERIOD dan GPU lock tetap dipertahankan."""
        gpu = get_gpu_manager()
        res = await manager.handle_init_session(
            user_id=test_user.id,
            voice_profile_id=ready_voice_profile.id,
            db=db_session,
        )
        session_id = res.session_id

        manager.handle_disconnect(session_id, db=db_session)

        session_state = manager.get_session(session_id)
        assert session_state.state == SessionState.GRACE_PERIOD
        assert session_state.grace_timer_task is not None
        assert not session_state.grace_timer_task.done()

        # GPU lock dan model VRAM TETAP dipertahankan selama grace period
        assert gpu.is_locked()
        assert gpu.get_holder() == str(session_id)
        assert session_state.pipeline.is_loaded()

    async def test_reconnect_during_grace_period_restores_active_state(
        self, manager, db_session, test_user, ready_voice_profile
    ):
        """Reconnect sebelum grace period habis membatalkan countdown timer dan mengembalikan state ACTIVE."""
        gpu = get_gpu_manager()
        res = await manager.handle_init_session(
            user_id=test_user.id,
            voice_profile_id=ready_voice_profile.id,
            db=db_session,
        )
        session_id = res.session_id

        manager.handle_disconnect(session_id, db=db_session)
        session_state = manager.get_session(session_id)
        assert session_state.state == SessionState.GRACE_PERIOD

        recon_result = await manager.handle_init_session(
            user_id=test_user.id,
            reconnect_session_id=session_id,
            db=db_session,
        )

        assert recon_result.session_id == session_id
        assert recon_result.reconnected is True
        assert session_state.state == SessionState.ACTIVE
        assert session_state.grace_timer_task is None
        assert gpu.is_locked()

    async def test_grace_period_expired_releases_resources_and_records_ended_at(
        self, manager, db_session, test_user, ready_voice_profile
    ):
        """Setelah grace period habis, GPU lock dilepas, model dibongkar, dan ended_at tercatat."""
        gpu = get_gpu_manager()
        res = await manager.handle_init_session(
            user_id=test_user.id,
            voice_profile_id=ready_voice_profile.id,
            db=db_session,
        )
        session_id = res.session_id

        manager.handle_disconnect(session_id, db=db_session)
        session_state = manager.get_session(session_id)
        assert session_state.state == SessionState.GRACE_PERIOD

        # Panggil expiry handler langsung
        await manager.handle_grace_period_expired(session_id, db=db_session)

        assert session_state.state == SessionState.ENDED
        assert not gpu.is_locked()
        assert gpu.get_holder() is None
        assert not session_state.pipeline.is_loaded()

        db_rec = db_session.get(VCSession, session_id)
        assert db_rec.ended_at is not None

    async def test_close_session_from_active_state(
        self, manager, db_session, test_user, ready_voice_profile
    ):
        """Penutupan eksplisit oleh klien saat ACTIVE langsung mengubah status ke ENDED dan melepas lock."""
        gpu = get_gpu_manager()
        res = await manager.handle_init_session(
            user_id=test_user.id,
            voice_profile_id=ready_voice_profile.id,
            db=db_session,
        )
        session_id = res.session_id

        await manager.handle_close_session(session_id, db=db_session)

        session_state = manager.get_session(session_id)
        assert session_state.state == SessionState.ENDED
        assert not gpu.is_locked()
        assert not session_state.pipeline.is_loaded()

        db_rec = db_session.get(VCSession, session_id)
        assert db_rec.ended_at is not None

    async def test_close_session_from_grace_period_cancels_timer(
        self, manager, db_session, test_user, ready_voice_profile
    ):
        """Penutupan eksplisit saat GRACE_PERIOD membatalkan timer yang sedang berjalan."""
        gpu = get_gpu_manager()
        res = await manager.handle_init_session(
            user_id=test_user.id,
            voice_profile_id=ready_voice_profile.id,
            db=db_session,
        )
        session_id = res.session_id

        manager.handle_disconnect(session_id, db=db_session)
        session_state = manager.get_session(session_id)
        assert session_state.state == SessionState.GRACE_PERIOD
        assert session_state.grace_timer_task is not None

        await manager.handle_close_session(session_id, db=db_session)

        assert session_state.state == SessionState.ENDED
        assert session_state.grace_timer_task is None
        assert not gpu.is_locked()


@pytest.mark.asyncio
class TestVCSessionManagerErrors:
    """Pengujian penolakan dan edge case error pada VCSessionManager."""

    async def test_init_session_with_non_existent_profile(self, manager, db_session, test_user):
        """Inisialisasi dengan ID profil yang tidak ada memicu PROFILE_NOT_FOUND."""
        random_id = uuid.uuid4()
        with pytest.raises(VCSessionException) as exc_info:
            await manager.handle_init_session(
                user_id=test_user.id,
                voice_profile_id=random_id,
                db=db_session,
            )
        assert exc_info.value.code == VCErrorCode.PROFILE_NOT_FOUND

    async def test_init_session_with_other_user_profile(
        self, manager, db_session, other_user, ready_voice_profile
    ):
        """Inisialisasi profil milik user lain memicu PROFILE_NOT_FOUND demi isolasi tenant."""
        with pytest.raises(VCSessionException) as exc_info:
            await manager.handle_init_session(
                user_id=other_user.id,
                voice_profile_id=ready_voice_profile.id,
                db=db_session,
            )
        assert exc_info.value.code == VCErrorCode.PROFILE_NOT_FOUND

    async def test_init_session_with_non_ready_profile(
        self, manager, db_session, test_user, pending_voice_profile
    ):
        """Inisialisasi profil berstatus pending memicu PROFILE_NOT_READY."""
        with pytest.raises(VCSessionException) as exc_info:
            await manager.handle_init_session(
                user_id=test_user.id,
                voice_profile_id=pending_voice_profile.id,
                db=db_session,
            )
        assert exc_info.value.code == VCErrorCode.PROFILE_NOT_READY

    async def test_init_session_missing_profile_id_for_new_session(
        self, manager, db_session, test_user
    ):
        """Inisialisasi sesi baru tanpa voice_profile_id memicu INVALID_PAYLOAD."""
        with pytest.raises(VCSessionException) as exc_info:
            await manager.handle_init_session(
                user_id=test_user.id,
                voice_profile_id=None,
                db=db_session,
            )
        assert exc_info.value.code == VCErrorCode.INVALID_PAYLOAD

    async def test_init_session_gpu_busy_rejection_for_other_vc_session(
        self, manager, db_session, test_user, ready_voice_profile
    ):
        """Inisialisasi sesi kedua saat sesi pertama masih aktif ditolak dengan GPU_BUSY."""
        res1 = await manager.handle_init_session(
            user_id=test_user.id,
            voice_profile_id=ready_voice_profile.id,
            db=db_session,
        )
        assert res1.session_id is not None

        with pytest.raises(VCSessionException) as exc_info:
            await manager.handle_init_session(
                user_id=test_user.id,
                voice_profile_id=ready_voice_profile.id,
                db=db_session,
            )
        assert exc_info.value.code == VCErrorCode.GPU_BUSY
        assert "GPU sedang digunakan" in exc_info.value.message

    async def test_init_session_gpu_busy_rejection_for_tts_job(
        self, manager, db_session, test_user, ready_voice_profile
    ):
        """Inisialisasi sesi saat TTS job sedang memegang lock ditolak dengan GPU_BUSY dan pesan spesifik."""
        gpu = get_gpu_manager()
        gpu.acquire_lock("tts-job-999")

        with pytest.raises(VCSessionException) as exc_info:
            await manager.handle_init_session(
                user_id=test_user.id,
                voice_profile_id=ready_voice_profile.id,
                db=db_session,
            )
        assert exc_info.value.code == VCErrorCode.GPU_BUSY
        assert "GPU sedang memproses TTS job" in exc_info.value.message

    async def test_init_session_model_load_failure_releases_gpu_lock(
        self, db_session, test_user, ready_voice_profile
    ):
        """Jika model pipeline gagal dimuat, GPU lock harus segera dilepas."""
        gpu = get_gpu_manager()
        failing_factory = lambda: RVCRealtimePipeline(simulate_failure=True)
        fail_mgr = VCSessionManager(gpu_manager=gpu, pipeline_factory=failing_factory)

        with pytest.raises(VCSessionException) as exc_info:
            await fail_mgr.handle_init_session(
                user_id=test_user.id,
                voice_profile_id=ready_voice_profile.id,
                db=db_session,
            )
        assert exc_info.value.code == VCErrorCode.MODEL_LOAD_FAILED
        assert not gpu.is_locked()

    async def test_reconnect_expired_session_raises_session_expired(
        self, manager, db_session, test_user
    ):
        """Mencoba reconnect ke session_id yang tidak ada atau sudah expired memicu SESSION_EXPIRED."""
        random_id = uuid.uuid4()
        with pytest.raises(VCSessionException) as exc_info:
            await manager.handle_init_session(
                user_id=test_user.id,
                reconnect_session_id=random_id,
                db=db_session,
            )
        assert exc_info.value.code == VCErrorCode.SESSION_EXPIRED

    async def test_reconnect_other_user_session_raises_profile_not_found(
        self, manager, db_session, test_user, other_user, ready_voice_profile
    ):
        """Mencoba reconnect ke session milik user lain memicu PROFILE_NOT_FOUND."""
        res = await manager.handle_init_session(
            user_id=test_user.id,
            voice_profile_id=ready_voice_profile.id,
            db=db_session,
        )
        session_id = res.session_id
        manager.handle_disconnect(session_id, db=db_session)

        with pytest.raises(VCSessionException) as exc_info:
            await manager.handle_init_session(
                user_id=other_user.id,
                reconnect_session_id=session_id,
                db=db_session,
            )
        assert exc_info.value.code == VCErrorCode.PROFILE_NOT_FOUND


@pytest.mark.asyncio
class TestVCSessionManagerAudioAndSettings:
    """Pengujian transmisi audio chunk, validasi PCM frame, dan pembaruan pengaturan."""

    async def test_handle_audio_chunk_successful_conversion_and_metrics(
        self, manager, db_session, test_user, ready_voice_profile
    ):
        """Audio chunk PCM valid berhasil dikonversi dan metrik latensi tercatat."""
        res = await manager.handle_init_session(
            user_id=test_user.id,
            voice_profile_id=ready_voice_profile.id,
            db=db_session,
        )
        session_id = res.session_id

        expected_bytes = calculate_expected_pcm_bytes(16000, 30)
        pcm_frame = b"\x00" * expected_bytes

        out_pcm, metrics = await manager.handle_audio_chunk(
            session_id=session_id,
            pcm_bytes=pcm_frame,
            return_metrics=True,
        )

        assert out_pcm is not None
        assert len(out_pcm) == expected_bytes
        assert metrics is not None
        assert "latency_ms" in metrics
        assert "processing_ms" in metrics
        assert metrics["processing_ms"] >= 0.0

        latest = manager.get_latest_metrics(session_id)
        assert latest is not None
        assert latest["processing_ms"] == metrics["processing_ms"]

    async def test_handle_audio_chunk_dropped_during_grace_period(
        self, manager, db_session, test_user, ready_voice_profile
    ):
        """Audio chunk yang masuk saat GRACE_PERIOD di-drop secara diam-diam (return None)."""
        res = await manager.handle_init_session(
            user_id=test_user.id,
            voice_profile_id=ready_voice_profile.id,
            db=db_session,
        )
        session_id = res.session_id

        manager.handle_disconnect(session_id, db=db_session)

        expected_bytes = calculate_expected_pcm_bytes(16000, 30)
        pcm_frame = b"\x00" * expected_bytes

        result = await manager.handle_audio_chunk(session_id, pcm_frame)
        assert result is None

    async def test_handle_audio_chunk_invalid_state_rejection(
        self, manager, db_session, test_user, ready_voice_profile
    ):
        """Audio chunk yang dikirim ke sesi yang sudah ENDED ditolak dengan INVALID_STATE."""
        res = await manager.handle_init_session(
            user_id=test_user.id,
            voice_profile_id=ready_voice_profile.id,
            db=db_session,
        )
        session_id = res.session_id
        await manager.handle_close_session(session_id, db=db_session)

        expected_bytes = calculate_expected_pcm_bytes(16000, 30)
        pcm_frame = b"\x00" * expected_bytes

        with pytest.raises(VCSessionException) as exc_info:
            await manager.handle_audio_chunk(session_id, pcm_frame)
        assert exc_info.value.code == VCErrorCode.INVALID_STATE

    async def test_handle_audio_chunk_invalid_pcm_payload_rejection(
        self, manager, db_session, test_user, ready_voice_profile
    ):
        """Frame PCM dengan ukuran yang tidak sesuai ditolak dengan INVALID_PAYLOAD."""
        res = await manager.handle_init_session(
            user_id=test_user.id,
            voice_profile_id=ready_voice_profile.id,
            db=db_session,
        )
        session_id = res.session_id

        bad_frame = b"\x00\x01\x02"  # Ganjil (3 bytes), bukan 960 bytes

        with pytest.raises(VCSessionException) as exc_info:
            await manager.handle_audio_chunk(session_id, bad_frame)
        assert exc_info.value.code == VCErrorCode.INVALID_PAYLOAD

    async def test_handle_audio_chunk_pipeline_failure_raises_inference_failed(
        self, db_session, test_user, ready_voice_profile
    ):
        """Kegagalan pipeline saat convert_chunk memicu error INFERENCE_FAILED."""
        class FailingConvertPipeline(RVCRealtimePipeline):
            def convert_chunk(self, pcm_bytes, settings=None):
                raise RuntimeError("Simulated inference failure")

        mgr = VCSessionManager(pipeline_factory=lambda: FailingConvertPipeline())
        try:
            res = await mgr.handle_init_session(
                user_id=test_user.id,
                voice_profile_id=ready_voice_profile.id,
                db=db_session,
            )
            session_id = res.session_id

            expected_bytes = calculate_expected_pcm_bytes(16000, 30)
            pcm_frame = b"\x00" * expected_bytes

            with pytest.raises(VCSessionException) as exc_info:
                await mgr.handle_audio_chunk(session_id, pcm_frame)
            assert exc_info.value.code == VCErrorCode.INFERENCE_FAILED
        finally:
            mgr.reset()

    async def test_handle_update_settings_success(
        self, manager, db_session, test_user, ready_voice_profile
    ):
        """Pembaruan pengaturan pitch_shift saat sesi aktif berhasil diperbarui di memory dan DB."""
        res = await manager.handle_init_session(
            user_id=test_user.id,
            voice_profile_id=ready_voice_profile.id,
            db=db_session,
        )
        session_id = res.session_id

        updated = await manager.handle_update_settings(
            session_id=session_id,
            settings_update=VCSettingsUpdate(pitch_shift=5),
            db=db_session,
        )

        assert updated.pitch_shift == 5

        session_state = manager.get_session(session_id)
        assert session_state.settings.pitch_shift == 5

        db_rec = db_session.get(VCSession, session_id)
        assert db_rec.settings["pitch_shift"] == 5

    async def test_handle_update_settings_in_invalid_state(
        self, manager, db_session, test_user, ready_voice_profile
    ):
        """Update settings saat sesi GRACE_PERIOD atau ENDED ditolak dengan INVALID_STATE."""
        res = await manager.handle_init_session(
            user_id=test_user.id,
            voice_profile_id=ready_voice_profile.id,
            db=db_session,
        )
        session_id = res.session_id
        manager.handle_disconnect(session_id, db=db_session)

        with pytest.raises(VCSessionException) as exc_info:
            await manager.handle_update_settings(
                session_id=session_id,
                settings_update={"pitch_shift": 2},
                db=db_session,
            )
        assert exc_info.value.code == VCErrorCode.INVALID_STATE

    async def test_average_latency_computed_on_session_termination(
        self, manager, db_session, test_user, ready_voice_profile
    ):
        """Rata-rata latensi tercatat secara akurat di DB saat sesi berakhir."""
        res = await manager.handle_init_session(
            user_id=test_user.id,
            voice_profile_id=ready_voice_profile.id,
            db=db_session,
        )
        session_id = res.session_id

        expected_bytes = calculate_expected_pcm_bytes(16000, 30)
        pcm_frame = b"\x00" * expected_bytes

        # Proses 3 chunk audio
        await manager.handle_audio_chunk(session_id, pcm_frame)
        await manager.handle_audio_chunk(session_id, pcm_frame)
        await manager.handle_audio_chunk(session_id, pcm_frame)

        session_state = manager.get_session(session_id)
        assert len(session_state.latencies) == 3

        await manager.handle_close_session(session_id, db=db_session)

        db_rec = db_session.get(VCSession, session_id)
        assert db_rec.avg_latency_ms is not None
        assert db_rec.avg_latency_ms >= 0.0


@pytest.mark.asyncio
class TestVCSessionManagerFastGraceTimer:
    """Pengujian simulasi grace period expiry otomatis via asynchronous task."""

    async def test_simulated_grace_period_auto_expires_with_fast_timer(
        self, db_session, test_user, ready_voice_profile
    ):
        """Grace period timer singkat (20ms) otomatis bertransisi ke ENDED tanpa blocking 10 detik."""
        gpu = get_gpu_manager()
        # Set grace period ke 20ms
        fast_mgr = VCSessionManager(grace_period_sec=0.02)
        try:
            res = await fast_mgr.handle_init_session(
                user_id=test_user.id,
                voice_profile_id=ready_voice_profile.id,
                db=db_session,
            )
            session_id = res.session_id

            fast_mgr.handle_disconnect(session_id, db=db_session)
            session_state = fast_mgr.get_session(session_id)
            assert session_state.state == SessionState.GRACE_PERIOD
            assert gpu.is_locked()

            # Tunggu timer 20ms selesai
            await asyncio.sleep(0.06)

            assert session_state.state == SessionState.ENDED
            assert not gpu.is_locked()
            assert gpu.get_holder() is None

            db_rec = db_session.get(VCSession, session_id)
            assert db_rec.ended_at is not None
        finally:
            fast_mgr.reset()
