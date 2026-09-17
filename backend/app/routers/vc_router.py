"""
Router WebSocket untuk Real-time Voice Changer (/ws/voice-changer).
Wave 6: WebSocket Router Layer & End-to-End Integration.

Menangani koneksi WebSocket streaming dua arah:
- Autentikasi token via query parameter ?token=...
- Dispatch frame kontrol JSON (init_session, update_settings, close_session)
- Dispatch frame audio biner raw PCM dan pengiriman balik hasil konversi + metrics
- Penanganan disconnect dan aktivasi grace period 10 detik
"""
import logging
import os
import secrets
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.models.user_model import User
from backend.app.schemas.vc_session_schema import (
    CloseSessionMessage,
    ErrorMessage,
    InitSessionMessage,
    MetricsMessage,
    SessionReadyMessage,
    UpdateSettingsMessage,
    VCErrorCode,
    parse_client_message,
)
from backend.app.services.vc_session_manager import (
    VCSessionException,
    VCSessionManager,
    get_vc_session_manager,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["voice-changer"])


def get_current_user_ws(db: Session = Depends(get_db)) -> uuid.UUID:
    """
    Mengambil user identifier yang terautentikasi untuk sesi WebSocket.
    Mendukung konfigurasi SONANCE_USER_ID dan fallback ke user pertama di DB.
    """
    raw = os.environ.get("SONANCE_USER_ID", "")
    if raw:
        try:
            return uuid.UUID(raw)
        except ValueError:
            pass

    stmt = select(User)
    user = db.scalar(stmt)
    if user:
        return user.id
    return uuid.UUID("00000000-0000-0000-0000-000000000001")


@router.websocket("/ws/voice-changer")
async def voice_changer_ws(
    websocket: WebSocket,
    token: Optional[str] = Query(default=None),
    session_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    manager: VCSessionManager = Depends(get_vc_session_manager),
    user_id: uuid.UUID = Depends(get_current_user_ws),
):
    """
    Endpoint WebSocket streaming dua arah untuk real-time voice changer.
    """
    # 1. Autentikasi token via query parameter (?token=...)
    expected_token = os.environ.get("SONANCE_API_TOKEN", "")
    token_valid = False
    if token and expected_token:
        try:
            token_valid = secrets.compare_digest(
                token.encode("utf-8"),
                expected_token.encode("utf-8"),
            )
        except Exception:
            token_valid = False

    if not token_valid:
        logger.warning("Koneksi WebSocket ditolak: token autentikasi tidak valid atau tidak ada.")
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Token autentikasi tidak valid atau tidak ada.",
        )
        return

    # 2. Terima koneksi setelah lolos auth
    await websocket.accept()
    current_session_id: Optional[uuid.UUID] = None

    try:
        while True:
            msg = await websocket.receive()
            if msg.get("type") == "websocket.disconnect":
                if current_session_id is not None:
                    manager.handle_disconnect(current_session_id, db=db)
                break

            # Tangani pesan teks (JSON control frame)
            if "text" in msg and msg["text"] is not None:
                text_content = msg["text"]
                try:
                    client_msg = parse_client_message(text_content)
                except Exception as err:
                    logger.warning("Format payload WebSocket tidak valid: %s", err)
                    err_msg = ErrorMessage(
                        code=VCErrorCode.INVALID_PAYLOAD,
                        message=f"Payload tidak valid: {err}",
                    )
                    await websocket.send_text(err_msg.model_dump_json())
                    continue

                if isinstance(client_msg, InitSessionMessage):
                    recon_id = client_msg.session_id
                    if recon_id is None and session_id is not None:
                        try:
                            recon_id = uuid.UUID(session_id)
                        except ValueError:
                            recon_id = None

                    try:
                        result = await manager.handle_init_session(
                            user_id=user_id,
                            voice_profile_id=client_msg.voice_profile_id,
                            settings=client_msg.settings,
                            reconnect_session_id=recon_id,
                            db=db,
                            websocket=websocket,
                        )
                        current_session_id = result.session_id
                        ready_msg = SessionReadyMessage(
                            session_id=result.session_id,
                            reconnected=result.reconnected,
                        )
                        await websocket.send_text(ready_msg.model_dump_json())
                    except VCSessionException as ve:
                        logger.warning("Gagal inisialisasi sesi: %s (%s)", ve.message, ve.code)
                        err_msg = ErrorMessage(
                            code=ve.code,
                            message=ve.message,
                        )
                        await websocket.send_text(err_msg.model_dump_json())

                elif isinstance(client_msg, UpdateSettingsMessage):
                    if current_session_id is None:
                        err_msg = ErrorMessage(
                            code=VCErrorCode.INVALID_STATE,
                            message="Sesi belum diinisialisasi. Kirim init_session terlebih dahulu.",
                        )
                        await websocket.send_text(err_msg.model_dump_json())
                        continue

                    try:
                        await manager.handle_update_settings(
                            session_id=current_session_id,
                            settings_update=client_msg.settings,
                            db=db,
                        )
                    except VCSessionException as ve:
                        logger.warning("Gagal update settings: %s (%s)", ve.message, ve.code)
                        err_msg = ErrorMessage(
                            code=ve.code,
                            message=ve.message,
                        )
                        await websocket.send_text(err_msg.model_dump_json())

                elif isinstance(client_msg, CloseSessionMessage):
                    if current_session_id is not None:
                        await manager.handle_close_session(current_session_id, db=db)
                        current_session_id = None
                    await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)
                    break

            # Tangani pesan biner (PCM audio frame)
            elif "bytes" in msg and msg["bytes"] is not None:
                pcm_data = msg["bytes"]
                if current_session_id is None:
                    err_msg = ErrorMessage(
                        code=VCErrorCode.INVALID_STATE,
                        message="Sesi belum diinisialisasi. Kirim init_session terlebih dahulu.",
                    )
                    await websocket.send_text(err_msg.model_dump_json())
                    continue

                try:
                    chunk_res = await manager.handle_audio_chunk(
                        session_id=current_session_id,
                        pcm_bytes=pcm_data,
                        return_metrics=True,
                    )
                    if chunk_res is not None and chunk_res[0] is not None:
                        out_pcm, metrics = chunk_res
                        await websocket.send_bytes(out_pcm)
                        if metrics:
                            metrics_msg = MetricsMessage(
                                latency_ms=metrics["latency_ms"],
                                processing_ms=metrics["processing_ms"],
                            )
                            await websocket.send_text(metrics_msg.model_dump_json())
                except VCSessionException as ve:
                    logger.warning("Gagal memproses audio chunk: %s (%s)", ve.message, ve.code)
                    err_msg = ErrorMessage(
                        code=ve.code,
                        message=ve.message,
                    )
                    await websocket.send_text(err_msg.model_dump_json())

    except WebSocketDisconnect:
        logger.info("Koneksi WebSocket terputus untuk session_id=%s", current_session_id)
        if current_session_id is not None:
            manager.handle_disconnect(current_session_id, db=db)
