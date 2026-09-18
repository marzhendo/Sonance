"""
Service layer VCSessionManager untuk Real-time Voice Changer (WebSocket).
Wave 5: Session Manager & Service Layer.

Mengelola siklus hidup state machine sesi konversi suara real-time:
CONNECTED -> INITIALIZING -> ACTIVE -> [DISCONNECTED] -> GRACE_PERIOD -> ACTIVE / ENDED
"""
import asyncio
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, NamedTuple, Optional, Tuple, Union

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.database import get_session_factory
from backend.app.core.gpu_manager import GPUResourceManager, get_gpu_manager
from backend.app.models.vc_session_model import VCSession
from backend.app.models.voice_profile_model import VoiceProfile
from backend.app.schemas.vc_session_schema import (
    VCErrorCode,
    VCSettings,
    VCSettingsUpdate,
    validate_pcm_frame,
)
from backend.app.schemas.voice_profile_schema import VoiceProfileStatus
from backend.ml.base import VoiceConversionPipeline
from backend.ml.rvc import RVCRealtimePipeline

logger = logging.getLogger(__name__)

DEFAULT_GRACE_PERIOD_SEC = 10.0


class SessionState(str, Enum):
    """Status siklus hidup sesi real-time voice changer."""
    CONNECTED = "CONNECTED"
    INITIALIZING = "INITIALIZING"
    ACTIVE = "ACTIVE"
    GRACE_PERIOD = "GRACE_PERIOD"
    ENDED = "ENDED"


class VCSessionException(Exception):
    """Exception khusus untuk error protokol voice changer."""

    def __init__(self, code: VCErrorCode, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class InitSessionResult(NamedTuple):
    """Hasil pemanggilan handle_init_session."""
    session_id: uuid.UUID
    reconnected: bool


class ActiveSessionState:
    """State sesi real-time yang disimpan di memory runtime."""

    def __init__(
        self,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        voice_profile_id: uuid.UUID,
        settings: VCSettings,
        state: SessionState,
        pipeline: VoiceConversionPipeline,
        started_at: datetime,
        websocket: Optional[Any] = None,
    ):
        self.session_id = session_id
        self.user_id = user_id
        self.voice_profile_id = voice_profile_id
        self.settings = settings
        self.state = state
        self.pipeline = pipeline
        self.started_at = started_at
        self.websocket = websocket
        self.ended_at: Optional[datetime] = None
        self.grace_timer_task: Optional[asyncio.Task] = None
        self.latencies: List[float] = []


class VCSessionManager:
    """
    Manager sesi terkoordinasi untuk streaming WebSocket voice changer.
    Mengatur state machine, alokasi GPU lock simetris, pemuatan model on-demand,
    perhitungan latensi, dan mekanisme grace period 10 detik.
    """

    def __init__(
        self,
        gpu_manager: Optional[GPUResourceManager] = None,
        pipeline_factory: Optional[Callable[[], VoiceConversionPipeline]] = None,
        grace_period_sec: Optional[float] = None,
        sleep_fn: Optional[Callable[[float], Coroutine]] = None,
    ):
        self.gpu_manager = gpu_manager or get_gpu_manager()
        self.pipeline_factory = pipeline_factory or (lambda: RVCRealtimePipeline())
        if grace_period_sec is not None:
            self.grace_period_sec = float(grace_period_sec)
        else:
            env_sec = os.environ.get("SONANCE_WS_GRACE_PERIOD_SEC", str(DEFAULT_GRACE_PERIOD_SEC))
            try:
                self.grace_period_sec = float(env_sec)
            except ValueError:
                self.grace_period_sec = DEFAULT_GRACE_PERIOD_SEC

        self._sleep_fn = sleep_fn or asyncio.sleep
        self._active_sessions: Dict[uuid.UUID, ActiveSessionState] = {}

    def get_session(self, session_id: Union[uuid.UUID, str]) -> Optional[ActiveSessionState]:
        """Mengambil data sesi aktif di memory."""
        s_uuid = session_id if isinstance(session_id, uuid.UUID) else uuid.UUID(str(session_id))
        return self._active_sessions.get(s_uuid)

    def get_active_sessions_count(self) -> int:
        """Mengembalikan jumlah sesi yang sedang aktif atau dalam grace period."""
        return sum(
            1
            for s in self._active_sessions.values()
            if s.state in (SessionState.ACTIVE, SessionState.GRACE_PERIOD)
        )

    def get_latest_metrics(self, session_id: Union[uuid.UUID, str]) -> Optional[Dict[str, float]]:
        """Mengembalikan metrik latensi chunk terakhir dari sesi."""
        s = self.get_session(session_id)
        if not s or not s.latencies:
            return None
        last_ms = s.latencies[-1]
        return {
            "latency_ms": last_ms,
            "processing_ms": last_ms,
        }

    async def handle_init_session(
        self,
        user_id: Union[uuid.UUID, str],
        voice_profile_id: Optional[Union[uuid.UUID, str]] = None,
        settings: Optional[Union[VCSettings, dict]] = None,
        reconnect_session_id: Optional[Union[uuid.UUID, str]] = None,
        db: Optional[Session] = None,
        websocket: Optional[Any] = None,
    ) -> InitSessionResult:
        """
        Menginisialisasi sesi voice changer baru atau melanjutkan sesi dalam grace period.
        """
        user_uuid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))

        # 1. Alur Reconnect
        if reconnect_session_id is not None:
            r_uuid = (
                reconnect_session_id
                if isinstance(reconnect_session_id, uuid.UUID)
                else uuid.UUID(str(reconnect_session_id))
            )
            existing = self._active_sessions.get(r_uuid)
            if not existing or existing.state == SessionState.ENDED:
                raise VCSessionException(
                    code=VCErrorCode.SESSION_EXPIRED,
                    message="Sesi sudah kedaluwarsa atau tidak ditemukan.",
                )

            if existing.user_id != user_uuid:
                raise VCSessionException(
                    code=VCErrorCode.PROFILE_NOT_FOUND,
                    message="Sesi bukan milik pengguna terautentikasi.",
                )

            if existing.state == SessionState.GRACE_PERIOD:
                if existing.grace_timer_task and not existing.grace_timer_task.done():
                    existing.grace_timer_task.cancel()
                    existing.grace_timer_task = None
                existing.state = SessionState.ACTIVE
                existing.websocket = websocket
                return InitSessionResult(session_id=existing.session_id, reconnected=True)

            if existing.state == SessionState.ACTIVE:
                existing.websocket = websocket
                return InitSessionResult(session_id=existing.session_id, reconnected=True)

            raise VCSessionException(
                code=VCErrorCode.INVALID_STATE,
                message=f"Status sesi tidak dapat disambung kembali: {existing.state.value}.",
            )

        # 2. Alur Inisialisasi Sesi Baru
        if voice_profile_id is None:
            raise VCSessionException(
                code=VCErrorCode.INVALID_PAYLOAD,
                message="voice_profile_id harus disertakan untuk inisialisasi sesi baru.",
            )

        vp_uuid = (
            voice_profile_id
            if isinstance(voice_profile_id, uuid.UUID)
            else uuid.UUID(str(voice_profile_id))
        )

        owns_session = False
        db_sess = db
        if db_sess is None:
            factory = get_session_factory()
            db_sess = factory()
            owns_session = True

        try:
            # Validasi Voice Profile
            stmt = select(VoiceProfile).where(
                VoiceProfile.id == vp_uuid,
                VoiceProfile.user_id == user_uuid,
            )
            vp = db_sess.scalar(stmt)
            if not vp:
                raise VCSessionException(
                    code=VCErrorCode.PROFILE_NOT_FOUND,
                    message="Voice profile tidak ditemukan.",
                )

            if vp.status != VoiceProfileStatus.ready.value:
                raise VCSessionException(
                    code=VCErrorCode.PROFILE_NOT_READY,
                    message="Voice profile belum siap digunakan untuk konversi suara.",
                )

            # Validasi Settings
            if settings is None:
                vc_settings = VCSettings()
            elif isinstance(settings, VCSettings):
                vc_settings = settings
            else:
                vc_settings = VCSettings(**settings)

            new_session_id = uuid.uuid4()
            lock_id = str(new_session_id)

            # Simetris GPU Lock Acquisition
            if not self.gpu_manager.acquire_lock(session_id=lock_id):
                holder = self.gpu_manager.get_holder()
                if holder and holder.startswith("tts-"):
                    msg = "GPU sedang memproses TTS job, coba lagi sesaat lagi"
                else:
                    msg = "GPU sedang digunakan oleh sesi lain, coba lagi nanti."
                raise VCSessionException(
                    code=VCErrorCode.GPU_BUSY,
                    message=msg,
                )

            # Pemuatan Model Pipeline on-demand
            pipeline = self.pipeline_factory()
            checkpoint_path = vp.model_checkpoint_path or vp.sample_audio_path or ""
            try:
                pipeline.load_model(checkpoint_path)
            except Exception as err:
                self.gpu_manager.release_lock(session_id=lock_id)
                logger.exception("Gagal memuat model RVC untuk VoiceProfile %s: %s", vp.id, err)
                raise VCSessionException(
                    code=VCErrorCode.MODEL_LOAD_FAILED,
                    message=f"Gagal memuat model voice profile: {err}",
                )

            # Persistensi Sesi ke Database
            now = datetime.now(timezone.utc)
            vc_record = VCSession(
                id=new_session_id,
                user_id=user_uuid,
                voice_profile_id=vp_uuid,
                started_at=now,
                settings=vc_settings.model_dump(),
            )
            db_sess.add(vc_record)
            db_sess.commit()
            db_sess.refresh(vc_record)

            # Daftarkan state ke runtime in-memory map
            session_start = vc_record.started_at or now
            if session_start.tzinfo is None:
                session_start = session_start.replace(tzinfo=timezone.utc)

            active_state = ActiveSessionState(
                session_id=new_session_id,
                user_id=user_uuid,
                voice_profile_id=vp_uuid,
                settings=vc_settings,
                state=SessionState.ACTIVE,
                pipeline=pipeline,
                started_at=session_start,
                websocket=websocket,
            )
            self._active_sessions[new_session_id] = active_state

            return InitSessionResult(session_id=new_session_id, reconnected=False)

        finally:
            if owns_session:
                db_sess.close()

    def handle_disconnect(
        self,
        session_id: Union[uuid.UUID, str],
        db: Optional[Session] = None,
    ) -> None:
        """
        Menangani pemutusan koneksi WebSocket sementara.
        Memasuki state GRACE_PERIOD dan memulai timer countdown 10 detik.
        """
        s_uuid = session_id if isinstance(session_id, uuid.UUID) else uuid.UUID(str(session_id))
        session = self._active_sessions.get(s_uuid)
        if not session or session.state != SessionState.ACTIVE:
            return

        session.state = SessionState.GRACE_PERIOD
        session.websocket = None

        async def _grace_period_countdown():
            try:
                await self._sleep_fn(self.grace_period_sec)
                await self.handle_grace_period_expired(s_uuid, db=db)
            except asyncio.CancelledError:
                pass

        session.grace_timer_task = asyncio.create_task(_grace_period_countdown())

    async def handle_grace_period_expired(
        self,
        session_id: Union[uuid.UUID, str],
        db: Optional[Session] = None,
    ) -> None:
        """
        Menangani kedaluwarsa grace period 10 detik tanpa ada reconnection.
        Transisi ke ENDED, melepaskan GPU lock, membongkar model, dan mencatat ended_at.
        """
        s_uuid = session_id if isinstance(session_id, uuid.UUID) else uuid.UUID(str(session_id))
        session = self._active_sessions.get(s_uuid)
        if not session or session.state != SessionState.GRACE_PERIOD:
            return

        session.state = SessionState.ENDED
        session.grace_timer_task = None

        # Lepaskan GPU lock dan unload model
        self.gpu_manager.release_lock(session_id=str(s_uuid))
        try:
            session.pipeline.unload_model()
        except Exception as err:
            logger.warning("Error saat membongkar model sesi %s: %s", s_uuid, err)

        # Update database: ended_at dicatat saat expired (sesuai ADR-003)
        expired_at = datetime.now(timezone.utc)
        session.ended_at = expired_at

        avg_lat = (
            round(sum(session.latencies) / len(session.latencies), 2)
            if session.latencies
            else None
        )

        owns_session = False
        db_sess = db
        if db_sess is None:
            factory = get_session_factory()
            db_sess = factory()
            owns_session = True

        try:
            vc_record = db_sess.get(VCSession, s_uuid)
            if vc_record:
                vc_record.ended_at = expired_at
                vc_record.avg_latency_ms = avg_lat
                db_sess.commit()
        finally:
            if owns_session:
                db_sess.close()

    async def handle_close_session(
        self,
        session_id: Union[uuid.UUID, str],
        db: Optional[Session] = None,
    ) -> None:
        """
        Menangani penutupan sesi secara eksplisit oleh klien.
        Langsung bertransisi ke ENDED tanpa melalui grace period.
        """
        s_uuid = session_id if isinstance(session_id, uuid.UUID) else uuid.UUID(str(session_id))
        session = self._active_sessions.get(s_uuid)
        if not session or session.state == SessionState.ENDED:
            return

        if session.grace_timer_task and not session.grace_timer_task.done():
            session.grace_timer_task.cancel()
            session.grace_timer_task = None

        session.state = SessionState.ENDED

        # Lepaskan GPU lock dan unload model
        self.gpu_manager.release_lock(session_id=str(s_uuid))
        try:
            session.pipeline.unload_model()
        except Exception as err:
            logger.warning("Error saat membongkar model sesi %s: %s", s_uuid, err)

        close_time = datetime.now(timezone.utc)
        session.ended_at = close_time

        avg_lat = (
            round(sum(session.latencies) / len(session.latencies), 2)
            if session.latencies
            else None
        )

        owns_session = False
        db_sess = db
        if db_sess is None:
            factory = get_session_factory()
            db_sess = factory()
            owns_session = True

        try:
            vc_record = db_sess.get(VCSession, s_uuid)
            if vc_record:
                vc_record.ended_at = close_time
                vc_record.avg_latency_ms = avg_lat
                db_sess.commit()
        finally:
            if owns_session:
                db_sess.close()

    async def handle_audio_chunk(
        self,
        session_id: Union[uuid.UUID, str],
        pcm_bytes: bytes,
        return_metrics: bool = False,
    ) -> Union[Optional[bytes], Tuple[Optional[bytes], Optional[Dict[str, float]]]]:
        """
        Memproses satu frame audio raw PCM:
        - Jika state GRACE_PERIOD: audio di-drop diam-diam (return None).
        - Jika state bukan ACTIVE: raises VCSessionException(INVALID_STATE).
        - Validasi ukuran frame PCM.
        - Inferensi via pipeline dan pencatatan metrik latensi.
        """
        s_uuid = session_id if isinstance(session_id, uuid.UUID) else uuid.UUID(str(session_id))
        session = self._active_sessions.get(s_uuid)
        if not session:
            raise VCSessionException(
                code=VCErrorCode.INVALID_STATE,
                message="Sesi tidak ditemukan.",
            )

        if session.state == SessionState.GRACE_PERIOD:
            # Drop audio chunk saat terputus
            return (None, None) if return_metrics else None

        if session.state != SessionState.ACTIVE:
            raise VCSessionException(
                code=VCErrorCode.INVALID_STATE,
                message=f"Sesi dalam status '{session.state.value}', bukan ACTIVE.",
            )

        # Validasi ukuran frame PCM
        is_valid = validate_pcm_frame(
            pcm_bytes,
            sample_rate=session.settings.sample_rate,
            chunk_duration_ms=session.settings.chunk_duration_ms,
        )
        if not is_valid:
            raise VCSessionException(
                code=VCErrorCode.INVALID_PAYLOAD,
                message="Ukuran frame audio PCM tidak valid.",
            )

        # Inferensi pemrosesan audio
        t0 = time.perf_counter()
        try:
            converted = session.pipeline.convert_chunk(pcm_bytes, session.settings)
        except Exception as err:
            logger.exception("Gagal inferensi konversi audio sesi %s: %s", s_uuid, err)
            raise VCSessionException(
                code=VCErrorCode.INFERENCE_FAILED,
                message=f"Inferensi konversi suara gagal: {err}",
            )
        t1 = time.perf_counter()

        proc_ms = round((t1 - t0) * 1000.0, 2)
        lat_ms = proc_ms
        session.latencies.append(proc_ms)
        metrics = {"latency_ms": lat_ms, "processing_ms": proc_ms}

        if return_metrics:
            return converted, metrics
        return converted

    async def process_audio_chunk(
        self,
        session_id: Union[uuid.UUID, str],
        pcm_bytes: bytes,
    ) -> Tuple[Optional[bytes], Optional[Dict[str, float]]]:
        """Alias untuk handle_audio_chunk dengan output tuple (converted_pcm, metrics)."""
        res = await self.handle_audio_chunk(session_id, pcm_bytes, return_metrics=True)
        return res  # type: ignore

    async def handle_update_settings(
        self,
        session_id: Union[uuid.UUID, str],
        settings_update: Union[VCSettingsUpdate, dict],
        db: Optional[Session] = None,
    ) -> VCSettings:
        """
        Memperbarui parameter pengaturan dinamis saat sesi aktif.
        """
        s_uuid = session_id if isinstance(session_id, uuid.UUID) else uuid.UUID(str(session_id))
        session = self._active_sessions.get(s_uuid)
        if not session:
            raise VCSessionException(
                code=VCErrorCode.INVALID_STATE,
                message="Sesi tidak ditemukan.",
            )

        if session.state != SessionState.ACTIVE:
            raise VCSessionException(
                code=VCErrorCode.INVALID_STATE,
                message=f"Sesi dalam status '{session.state.value}', bukan ACTIVE.",
            )

        upd = (
            settings_update
            if isinstance(settings_update, VCSettingsUpdate)
            else VCSettingsUpdate(**settings_update)
        )

        if upd.pitch_shift is not None:
            session.settings.pitch_shift = upd.pitch_shift

        owns_session = False
        db_sess = db
        if db_sess is None:
            factory = get_session_factory()
            db_sess = factory()
            owns_session = True

        try:
            vc_record = db_sess.get(VCSession, s_uuid)
            if vc_record:
                vc_record.settings = session.settings.model_dump()
                db_sess.commit()
        finally:
            if owns_session:
                db_sess.close()

        return session.settings

    # Helper method aliases
    async def create_session(
        self,
        user_id: Union[uuid.UUID, str],
        voice_profile_id: Union[uuid.UUID, str],
        settings: Optional[Union[VCSettings, dict]] = None,
        websocket: Optional[Any] = None,
        db: Optional[Session] = None,
    ) -> InitSessionResult:
        """Alias untuk handle_init_session pembuatan sesi baru."""
        return await self.handle_init_session(
            user_id=user_id,
            voice_profile_id=voice_profile_id,
            settings=settings,
            websocket=websocket,
            db=db,
        )

    async def reconnect_session(
        self,
        session_id: Union[uuid.UUID, str],
        user_id: Union[uuid.UUID, str],
        websocket: Optional[Any] = None,
        db: Optional[Session] = None,
    ) -> bool:
        """Alias untuk handle_init_session reconnect."""
        res = await self.handle_init_session(
            user_id=user_id,
            reconnect_session_id=session_id,
            websocket=websocket,
            db=db,
        )
        return res.reconnected

    async def close_session(
        self,
        session_id: Union[uuid.UUID, str],
        db: Optional[Session] = None,
    ) -> None:
        """Alias untuk handle_close_session."""
        await self.handle_close_session(session_id=session_id, db=db)

    async def update_settings(
        self,
        session_id: Union[uuid.UUID, str],
        settings_update: Union[VCSettingsUpdate, dict],
        db: Optional[Session] = None,
    ) -> VCSettings:
        """Alias untuk handle_update_settings."""
        return await self.handle_update_settings(
            session_id=session_id,
            settings_update=settings_update,
            db=db,
        )

    def reset(self) -> None:
        """Membersihkan seluruh state runtime dan membatalkan timer yang sedang berjalan."""
        for s in self._active_sessions.values():
            if s.grace_timer_task and not s.grace_timer_task.done():
                s.grace_timer_task.cancel()
        self._active_sessions.clear()


_global_vc_session_manager: Optional[VCSessionManager] = None


def get_vc_session_manager() -> VCSessionManager:
    """Mengembalikan singleton instance default VCSessionManager."""
    global _global_vc_session_manager
    if _global_vc_session_manager is None:
        _global_vc_session_manager = VCSessionManager()
    return _global_vc_session_manager
