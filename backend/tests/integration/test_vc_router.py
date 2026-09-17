"""
Integration tests untuk WebSocket Router Real-time Voice Changer (/ws/voice-changer).
Wave 6: WebSocket Router Layer & End-to-End Integration.
"""
import json
import uuid
import pytest
from starlette.websockets import WebSocketDisconnect

from backend.app.core.gpu_manager import get_gpu_manager
from backend.app.models.vc_session_model import VCSession
from backend.app.schemas.vc_session_schema import calculate_expected_pcm_bytes
from backend.app.services.vc_session_manager import (
    SessionState,
    get_vc_session_manager,
)
from backend.tests.conftest import TEST_TOKEN, TEST_USER_ID
from backend.workers.tts_worker import execute_tts_job


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    """Menyetel variabel lingkungan autentikasi untuk pengujian WebSocket."""
    monkeypatch.setenv("SONANCE_API_TOKEN", TEST_TOKEN)
    monkeypatch.setenv("SONANCE_USER_ID", TEST_USER_ID)


@pytest.fixture(autouse=True)
def clean_resources():
    """Memastikan GPU dan session manager dalam kondisi bersih sebelum dan sesudah tiap test."""
    gpu = get_gpu_manager()
    gpu.reset()
    manager = get_vc_session_manager()
    manager.reset()
    yield
    manager.reset()
    gpu.reset()


class TestVoiceChangerWebSocketAuth:
    """Pengujian penjaga autentikasi query param ?token=... pada rute WebSocket."""

    def test_auth_guard_rejects_missing_token_with_1008(self, client):
        """Koneksi tanpa parameter token ditutup sebelum accept dengan code 1008."""
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/ws/voice-changer"):
                pass
        assert exc_info.value.code == 1008

    def test_auth_guard_rejects_empty_token_with_1008(self, client):
        """Koneksi dengan token kosong (?token=) ditutup dengan code 1008."""
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/ws/voice-changer?token="):
                pass
        assert exc_info.value.code == 1008

    def test_auth_guard_rejects_invalid_token_with_1008(self, client):
        """Koneksi dengan token yang tidak cocok ditutup dengan code 1008."""
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/ws/voice-changer?token=wrong-secret-token"):
                pass
        assert exc_info.value.code == 1008


class TestVoiceChangerWebSocketLifecycle:
    """Pengujian alur happy path, streaming audio chunk, dan terminasi sesi."""

    def test_happy_path_streaming_and_normal_closure(
        self, client, db_session, ready_voice_profile, tmp_path
    ):
        """
        Alur normal: connect -> init_session -> session_ready -> streaming PCM ->
        terima PCM + metrics -> close_session -> closed 1000 & DB record updated.
        """
        gpu = get_gpu_manager()
        assert not gpu.is_locked()

        url = f"/ws/voice-changer?token={TEST_TOKEN}"
        with client.websocket_connect(url) as ws:
            # 1. Kirim init_session
            init_payload = {
                "type": "init_session",
                "voice_profile_id": str(ready_voice_profile.id),
                "settings": {
                    "pitch_shift": 2,
                    "sample_rate": 16000,
                    "chunk_duration_ms": 30,
                },
            }
            ws.send_text(json.dumps(init_payload))

            # 2. Terima session_ready
            ready_raw = ws.receive_text()
            ready_data = json.loads(ready_raw)
            assert ready_data["type"] == "session_ready"
            assert ready_data["reconnected"] is False
            session_id = ready_data["session_id"]
            assert session_id is not None

            # Verifikasi GPU terkunci oleh sesi ini
            assert gpu.is_locked()
            assert gpu.get_holder() == session_id

            # 3. Kirim 2 chunk audio raw PCM
            frame_size = calculate_expected_pcm_bytes(16000, 30)
            pcm_chunk = b"\x01\x02" * (frame_size // 2)

            for _ in range(2):
                ws.send_bytes(pcm_chunk)
                # Terima audio output biner
                out_pcm = ws.receive_bytes()
                assert len(out_pcm) == frame_size

                # Terima metrics JSON
                metrics_raw = ws.receive_text()
                metrics_data = json.loads(metrics_raw)
                assert metrics_data["type"] == "metrics"
                assert "latency_ms" in metrics_data
                assert "processing_ms" in metrics_data

            # 4. Kirim close_session
            ws.send_text(json.dumps({"type": "close_session"}))
            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_text()
            assert exc_info.value.code == 1000

        # Verifikasi cleanup resource
        assert not gpu.is_locked()
        db_rec = db_session.get(VCSession, uuid.UUID(session_id))
        assert db_rec is not None
        assert db_rec.ended_at is not None
        assert db_rec.avg_latency_ms is not None

    def test_validation_profile_not_found(self, client):
        """Inisialisasi dengan voice_profile_id yang tidak ada mengembalikan PROFILE_NOT_FOUND."""
        url = f"/ws/voice-changer?token={TEST_TOKEN}"
        with client.websocket_connect(url) as ws:
            ws.send_text(
                json.dumps({
                    "type": "init_session",
                    "voice_profile_id": str(uuid.uuid4()),
                })
            )
            err_raw = ws.receive_text()
            err_data = json.loads(err_raw)
            assert err_data["type"] == "error"
            assert err_data["code"] == "PROFILE_NOT_FOUND"

    def test_validation_profile_not_ready(self, client, pending_voice_profile):
        """Inisialisasi profil suara berstatus pending mengembalikan PROFILE_NOT_READY."""
        url = f"/ws/voice-changer?token={TEST_TOKEN}"
        with client.websocket_connect(url) as ws:
            ws.send_text(
                json.dumps({
                    "type": "init_session",
                    "voice_profile_id": str(pending_voice_profile.id),
                })
            )
            err_raw = ws.receive_text()
            err_data = json.loads(err_raw)
            assert err_data["type"] == "error"
            assert err_data["code"] == "PROFILE_NOT_READY"


class TestVoiceChangerGPUContention:
    """Pengujian simetri GPU lock contention antara TTS job dan WebSocket voice changer."""

    def test_gpu_busy_rejection_when_tts_job_holds_lock(self, client, ready_voice_profile):
        """Saat TTS job memegang lock GPU, init_session ditolak dengan GPU_BUSY lalu sukses saat retry."""
        gpu = get_gpu_manager()
        tts_lock_id = "tts-active-job-777"
        gpu.acquire_lock(tts_lock_id)

        url = f"/ws/voice-changer?token={TEST_TOKEN}"
        with client.websocket_connect(url) as ws:
            init_payload = {
                "type": "init_session",
                "voice_profile_id": str(ready_voice_profile.id),
            }
            ws.send_text(json.dumps(init_payload))

            err_raw = ws.receive_text()
            err_data = json.loads(err_raw)
            assert err_data["type"] == "error"
            assert err_data["code"] == "GPU_BUSY"
            assert "GPU sedang memproses TTS job" in err_data["message"]

            # Simulasi TTS job selesai dan melepas lock
            gpu.release_lock(tts_lock_id)

            # Klien retry pada koneksi yang sama
            ws.send_text(json.dumps(init_payload))
            ready_raw = ws.receive_text()
            ready_data = json.loads(ready_raw)
            assert ready_data["type"] == "session_ready"
            assert ready_data["reconnected"] is False

            # Cleanup
            ws.send_text(json.dumps({"type": "close_session"}))

    def test_tts_worker_paused_while_voice_changer_active(
        self, client, db_session, test_user, ready_voice_profile, make_tts_job, tmp_path
    ):
        """Saat sesi voice changer aktif, eksekusi TTS worker dijeda (waiting_for_gpu)."""
        url = f"/ws/voice-changer?token={TEST_TOKEN}"
        with client.websocket_connect(url) as ws:
            ws.send_text(
                json.dumps({
                    "type": "init_session",
                    "voice_profile_id": str(ready_voice_profile.id),
                })
            )
            ready_raw = ws.receive_text()
            ready_data = json.loads(ready_raw)
            assert ready_data["type"] == "session_ready"

            # Buat TTS job dan coba eksekusi saat VC aktif
            tts_job = make_tts_job(
                user=test_user,
                voice_profile=ready_voice_profile,
                input_text="Coba sintesis suara saat VC aktif.",
            )

            result = execute_tts_job(
                tts_job_id=tts_job.id,
                db=db_session,
                output_dir=str(tmp_path),
                poll_interval=0.0,
                max_poll_iterations=1,
            )

            assert result["status"] == "waiting_for_gpu"
            db_session.refresh(tts_job)
            assert tts_job.status == "queued"
            assert tts_job.started_at is None

            # Tutup sesi VC
            ws.send_text(json.dumps({"type": "close_session"}))


class TestVoiceChangerReconnectionFlow:
    """Pengujian mekanisme grace period dan pemulihan koneksi (reconnection)."""

    def test_reconnection_within_grace_period_succeeds(
        self, client, ready_voice_profile
    ):
        """Klien terputus mendadak dan berhasil reconnect dalam grace period dengan session_id sama."""
        url = f"/ws/voice-changer?token={TEST_TOKEN}"
        session_id = None

        # 1. Klien pertama terhubung dan init sesi
        with client.websocket_connect(url) as ws1:
            ws1.send_text(
                json.dumps({
                    "type": "init_session",
                    "voice_profile_id": str(ready_voice_profile.id),
                })
            )
            ready_data = json.loads(ws1.receive_text())
            assert ready_data["type"] == "session_ready"
            session_id = ready_data["session_id"]
            # Keluar blok tanpa close_session (simulasi disconnect tidak terduga)

        manager = get_vc_session_manager()
        session_state = manager.get_session(session_id)
        assert session_state.state == SessionState.GRACE_PERIOD
        assert get_gpu_manager().is_locked()

        # 2. Klien kedua reconnect dengan session_id yang sama
        with client.websocket_connect(url) as ws2:
            ws2.send_text(
                json.dumps({
                    "type": "init_session",
                    "session_id": session_id,
                })
            )
            recon_data = json.loads(ws2.receive_text())
            assert recon_data["type"] == "session_ready"
            assert recon_data["session_id"] == session_id
            assert recon_data["reconnected"] is True

            # State kembali ACTIVE
            assert session_state.state == SessionState.ACTIVE

            # Audio streaming tetap berfungsi
            frame_size = calculate_expected_pcm_bytes(16000, 30)
            ws2.send_bytes(b"\x00" * frame_size)
            out = ws2.receive_bytes()
            assert len(out) == frame_size
            ws2.receive_text()  # metrics

            ws2.send_text(json.dumps({"type": "close_session"}))

    def test_reconnect_failed_after_grace_period_expired(
        self, client, db_session, ready_voice_profile
    ):
        """Mencoba reconnect setelah grace period expired menghasilkan error SESSION_EXPIRED."""
        url = f"/ws/voice-changer?token={TEST_TOKEN}"
        session_id = None

        with client.websocket_connect(url) as ws1:
            ws1.send_text(
                json.dumps({
                    "type": "init_session",
                    "voice_profile_id": str(ready_voice_profile.id),
                })
            )
            ready_data = json.loads(ws1.receive_text())
            session_id = ready_data["session_id"]

        manager = get_vc_session_manager()
        # Paksa grace period expired
        import asyncio
        asyncio.run(manager.handle_grace_period_expired(session_id, db=db_session))

        # Reconnect ke sesi yang sudah expired
        with client.websocket_connect(url) as ws2:
            ws2.send_text(
                json.dumps({
                    "type": "init_session",
                    "session_id": session_id,
                })
            )
            err_data = json.loads(ws2.receive_text())
            assert err_data["type"] == "error"
            assert err_data["code"] == "SESSION_EXPIRED"

            # Klien dapat memulai sesi baru secara bersih
            ws2.send_text(
                json.dumps({
                    "type": "init_session",
                    "voice_profile_id": str(ready_voice_profile.id),
                })
            )
            new_ready = json.loads(ws2.receive_text())
            assert new_ready["type"] == "session_ready"
            assert new_ready["session_id"] != session_id
            ws2.send_text(json.dumps({"type": "close_session"}))


class TestVoiceChangerPayloadAndStateHandling:
    """Pengujian penolakan payload tidak valid dan state guard saat koneksi WebSocket berjalan."""

    def test_invalid_payload_returns_error_and_keeps_connection_alive(
        self, client, ready_voice_profile
    ):
        """Kirim JSON yang tidak sesuai schema memicu INVALID_PAYLOAD tanpa memutus koneksi."""
        url = f"/ws/voice-changer?token={TEST_TOKEN}"
        with client.websocket_connect(url) as ws:
            # Kirim payload aneh / tidak valid
            ws.send_text(json.dumps({"type": "unknown_action", "payload": 123}))

            err_data = json.loads(ws.receive_text())
            assert err_data["type"] == "error"
            assert err_data["code"] == "INVALID_PAYLOAD"

            # Koneksi tetap hidup, kirim init_session valid
            ws.send_text(
                json.dumps({
                    "type": "init_session",
                    "voice_profile_id": str(ready_voice_profile.id),
                })
            )
            ready_data = json.loads(ws.receive_text())
            assert ready_data["type"] == "session_ready"

            ws.send_text(json.dumps({"type": "close_session"}))

    def test_binary_audio_chunk_before_init_session_rejected(self, client):
        """Kirim audio frame biner sebelum init_session ditolak dengan INVALID_STATE."""
        url = f"/ws/voice-changer?token={TEST_TOKEN}"
        with client.websocket_connect(url) as ws:
            ws.send_bytes(b"\x00" * 960)
            err_data = json.loads(ws.receive_text())
            assert err_data["type"] == "error"
            assert err_data["code"] == "INVALID_STATE"

    def test_update_settings_during_active_session(
        self, client, ready_voice_profile
    ):
        """Klien dapat mengirim update_settings saat sesi aktif."""
        url = f"/ws/voice-changer?token={TEST_TOKEN}"
        with client.websocket_connect(url) as ws:
            ws.send_text(
                json.dumps({
                    "type": "init_session",
                    "voice_profile_id": str(ready_voice_profile.id),
                })
            )
            ready_data = json.loads(ws.receive_text())
            session_id = ready_data["session_id"]

            # Kirim pembaruan pengaturan
            ws.send_text(
                json.dumps({
                    "type": "update_settings",
                    "settings": {"pitch_shift": 6},
                })
            )

            # Kirim audio chunk untuk memastikan pembaruan pengaturan selesai diproses di event loop
            frame_size = calculate_expected_pcm_bytes(16000, 30)
            ws.send_bytes(b"\x00" * frame_size)
            ws.receive_bytes()
            ws.receive_text()  # metrics

            manager = get_vc_session_manager()
            session_state = manager.get_session(session_id)
            assert session_state.settings.pitch_shift == 6

            ws.send_text(json.dumps({"type": "close_session"}))
