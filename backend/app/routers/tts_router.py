"""Router endpoints untuk TTS Pipeline (Offline Voice Cloning)."""
import uuid
from fastapi import APIRouter, Depends, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.app.core.auth import verify_token
from backend.app.core.database import get_db
from backend.app.schemas.tts_job_schema import (
    TTSGenerateRequest,
    TTSJobResponse,
    TTSJobStatusResponse,
)
from backend.app.services.tts_job_service import TTSJobService

router = APIRouter(tags=["TTS"])
tts_job_service = TTSJobService()


@router.post(
    "/generate",
    response_model=TTSJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Kirim job sintesis suara (TTS)",
)
def generate_tts(
    request: TTSGenerateRequest,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Menerima request sintesis teks dan mendaftarkan job ke antrian."""
    return tts_job_service.dispatch(user_id=user_id, request=request, db=db)


@router.get(
    "/jobs/{job_id}",
    response_model=TTSJobStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Cek status TTS job",
)
def get_tts_job_status(
    job_id: uuid.UUID,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Mengambil status pemrosesan TTS job."""
    return tts_job_service.get_status(user_id=user_id, job_id=job_id, db=db)


@router.get(
    "/jobs/{job_id}/audio",
    status_code=status.HTTP_200_OK,
    summary="Download hasil audio TTS",
)
def get_tts_audio(
    job_id: uuid.UUID,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Mengunduh atau streaming file audio hasil sintesis TTS."""
    audio_path = tts_job_service.get_audio_path(user_id=user_id, job_id=job_id, db=db)
    filename = f"tts_{job_id}.opus"
    return FileResponse(
        path=audio_path,
        media_type="audio/ogg",
        filename=filename,
    )
